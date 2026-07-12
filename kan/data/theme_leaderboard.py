"""题材榜数据编排层 · 背景 · `kan theme trend` 后端。

把"所有题材指数"当一组 first-class 标的批量拉 K 线 + 算 streak。
跟 watchlist trend 在算法上 100% 复用 `calc_trend` · 数据源换成题材 K 线。

两条数据源路径(运行时选择):
- TuShare Pro 路径(优先 · 配 token 时启用):走 ths_daily batch 接口 ·
  60 次 HTTP 拿所有题材 60 天历史 · 服务端聚合 · 客户端 group by code
- AkShare EM 路径(fallback · 默认):走东财单题材行情 ·
  ThreadPoolExecutor 默认 16 worker · `KAN_THEME_TOP_PARALLEL` env 覆盖(1-32)

为啥两路:EM datacenter 可能波动(2026-05-25 实测整体 RemoteDisconnected)·
没 stale cache 兜底时第一次跑 kan theme trend 直接全挂。TuShare 是有 token 用户
的稳定回避路径(自部署代理 / 官方 endpoint 都支持)。

设计要点:
- cache 复用:EM 路径用 `fetch_theme_kline` 已有 24h parquet · TuShare 路径
  用 `tushare_load_theme_klines` 独立 12h batch parquet
- 失败容忍:单题材失败不阻塞整榜 · 收集到 errors 列表 · caller 决定如何提示
- 进度条:caller 传 `progress_console` 显示 rich.Progress · None 时静默(测试 / pipe 用)

为什么不走 OOP `ThemeIndexSet` + `run_data_pipeline`:
- `trend_batch` 现有契约是 `get_cached(symbol)` 个股缓存 · 改它兼容多源会破坏简单性
- 题材榜 UX 跟 watchlist trend 差异大(进度条 / 全量 391 / 排名列)· 独立命令更干净
- 不引入额外抽象 · 当前没有第二个多源题材榜需求
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from kan.core.scanner import TrendResult, calc_trend
from kan.data.boards import (
    ThemeDataUnavailableError,
    fetch_theme_kline,
    load_theme_catalog,
)
from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)

if TYPE_CHECKING:
    import pandas as pd
    from rich.console import Console

    from kan.core.models import Theme
    from kan.infra.lifecycle import OperationLifecycle


@dataclass
class LeaderboardDiagnosis:
    """题材榜数据源链路诊断 · 失败时驱动可解释错误消息。

    每条 fallback 路径都填一个状态字段 · caller 渲染多行错误消息时按需展开。
    成功路径下 caller 通常忽略(source 字符串已够)· 失败路径下用字段值组装诊断。

    Fields:
      tushare_attempted:  token 配了 → True · 没配 → False
      tushare_failed_at:  'catalog'=ths_index 失败 · 'klines'=ths_daily 失败 ·
                          None=没尝试 / 成功
      tushare_endpoint:   实际用的端点(env > config > DEFAULT)· 仅 attempted 时填
      tushare_token_masked: ***xxxx 形式 · 永不存原 token
      tushare_error_code: TuShare server 业务码 (40101/40203/40004) 或客户端码 (-1/-2/-3)·
                          None=没失败 / 没拿到 error · 背景 · 用于精准建议
      tushare_error_msg:  TuShare server 原文 msg (已 redact 防 token 泄漏)·
                          直接给用户看是安全的 · 比我们脑补文案更权威
      em_attempted:       走 EM 路径 → True (token 未配 或 TuShare 失败 fallback)
      em_total:           EM catalog 拿到的题材数(分母)
      em_failed_count:    EM 并行 fetch 失败的题材数(分子)
    """

    tushare_attempted: bool = False
    tushare_failed_at: str | None = None
    tushare_endpoint: str | None = None
    tushare_token_masked: str | None = None
    tushare_error_code: int | str | None = None
    tushare_error_msg: str | None = None
    em_attempted: bool = False
    em_total: int = 0
    em_failed_count: int = 0


def _resolve_parallel(parallel: int | None) -> int:
    """决定 worker 数 · CLI 参数 > env > 默认 16 · clamp 到 [1, 32]。"""
    if parallel is None:
        env = os.environ.get("KAN_THEME_TOP_PARALLEL")
        if env:
            try:
                parallel = int(env)
            except ValueError:
                parallel = 16
        else:
            parallel = 16
    return max(1, min(32, parallel))


_EM_THEME_KLINE_CAPABILITIES = ProviderCapabilities(
    max_concurrency=16,
    initial_concurrency=4,
    max_attempts=2,
    timeout_seconds=30.0,
    backoff_base_seconds=0.5,
    backoff_cap_seconds=2.0,
)


def _fetch_theme_kline_job(
    theme: Theme,
    force: bool,
) -> ProviderFetchResult[pd.DataFrame]:
    """把旧题材 K 线异常契约转换为 provider-aware result。"""
    try:
        frame = fetch_theme_kline(theme, force=force)
    except ThemeDataUnavailableError as exc:
        message = str(exc)
        if "为空" in message:
            return ProviderFetchResult.failed(FetchFailure(
                FetchFailureKind.EMPTY,
                message=message,
            ))
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.TRANSPORT,
            message=message,
            retryable=True,
            affects_circuit=True,
        ))
    except Exception as exc:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.TRANSPORT,
            message=type(exc).__name__,
            retryable=True,
            affects_circuit=True,
        ))
    if frame is None or frame.empty:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.EMPTY,
            message="K 线为空",
        ))
    return ProviderFetchResult.succeeded(frame)


def load_theme_leaderboard(
    *,
    candle: bool = False,
    force: bool = False,
    parallel: int | None = None,
    progress_console: Console | None = None,
    lifecycle: OperationLifecycle | None = None,
) -> tuple[
    list[TrendResult],
    list[tuple[Theme, Exception]],
    str,
    LeaderboardDiagnosis,
]:
    """拉所有题材 K 线 + 算 streak · 返回 (results, errors, source, diagnosis)。

    数据源选择(运行时):
    - TuShare token 配置 + ths_daily batch 通 → 走 TuShare 路径(快 · 稳定 · source='tushare')
    - 否则 → 走 AkShare EM 路径(EM 并行实现 · source='em')

    Args:
        candle: True=阳线阴线口径 / False=收盘价口径 · 透传 calc_trend。
        force: True 时忽略 cache 强刷(EM 路径)· TuShare 路径目前忽略 force
               (TuShare cache 12h · 当日强刷可手动删 boards/klines_tushare_*.parquet)。
        parallel: EM 路径 worker 数 · None 时走 _resolve_parallel(env / 默认 16)。
        progress_console: rich.Console · 不为 None 时显示 rich.Progress 进度条 ·
                          None 时静默(测试 / `--format json` pipe 场景)。

    Returns:
        (results, errors, source, diagnosis)
        - results: TrendResult 列表 · 未排序(caller 决定 sort key)
        - errors: [(Theme, Exception), ...] · 单题材失败不阻塞 · 不抛
        - source: 'tushare' 或 'em' · 给 caller 的 disclaimer / 标题用
        - diagnosis: LeaderboardDiagnosis · 数据源链路状态 · 失败时驱动可解释错误消息

    Raises:
        ThemeDataUnavailableError: catalog 拉取失败(题材清单都没拿到 · 无法继续)。
    """
    from kan.data.tushare import _resolve_config
    from kan.data.tushare_themes import (
        tushare_load_theme_catalog,
        tushare_load_theme_klines,
        tushare_token_configured,
    )
    from kan.storage.config import mask_token

    diagnosis = LeaderboardDiagnosis()

    # 优先尝试 TuShare 路径(配 token 时)
    if tushare_token_configured():
        diagnosis.tushare_attempted = True
        token, endpoint = _resolve_config()
        diagnosis.tushare_endpoint = endpoint
        diagnosis.tushare_token_masked = mask_token(token)

        ts_catalog, catalog_err = tushare_load_theme_catalog()
        if ts_catalog:
            ts_results, ts_errors, klines_err = _load_via_tushare(
                ts_catalog, candle=candle,
                progress_console=progress_console if lifecycle is None else None,
                tushare_load_klines=tushare_load_theme_klines,
                lifecycle=lifecycle,
            )
            if ts_results:
                return ts_results, ts_errors, "tushare", diagnosis
            # TuShare klines 接口失败 · 透传 server error 给 diagnosis · 落 EM
            diagnosis.tushare_failed_at = "klines"
            if klines_err is not None:
                diagnosis.tushare_error_code = klines_err.code
                diagnosis.tushare_error_msg = klines_err.msg
        else:
            # TuShare catalog 接口失败 · 透传 server error · 落 EM 路径
            diagnosis.tushare_failed_at = "catalog"
            if catalog_err is not None:
                diagnosis.tushare_error_code = catalog_err.code
                diagnosis.tushare_error_msg = catalog_err.msg

    catalog = load_theme_catalog(force=False)  # catalog 单独走 24h cache · 不并行
    if not catalog:
        raise ThemeDataUnavailableError("题材清单为空 · 无法生成榜单")

    diagnosis.em_attempted = True
    diagnosis.em_total = len(catalog)

    from kan.data.provider_batch import ProviderJob, run_provider_jobs

    workers = _resolve_parallel(parallel)
    results: list[TrendResult] = []
    errors: list[tuple[Theme, Exception]] = []
    themes_by_code = {theme.code: theme for theme in catalog}

    if lifecycle is not None:
        lifecycle.phase("拉取题材指数 K 线", total=len(catalog), provider="em_concept_hist")

    if progress_console is not None and lifecycle is None:
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            TextColumn,
            TimeRemainingColumn,
        )

        progress = Progress(
            TextColumn("[bold cyan]拉题材 K 线[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("·"),
            TimeRemainingColumn(),
            TextColumn("· 失败 {task.fields[errs]}"),
            console=progress_console,
            transient=True,
        )
        task_id = progress.add_task("themes", total=len(catalog), errs=0)
        progress.start()
    else:
        progress = None
        task_id = None

    def on_result(job_result, completed: int, total: int) -> None:
        theme = themes_by_code[job_result.key]
        frame = job_result.result.data
        failure = job_result.result.failure
        if frame is None:
            message = failure.message if failure is not None else "K 线为空"
            errors.append((theme, ThemeDataUnavailableError(message)))
        else:
            try:
                results.append(calc_trend(
                    frame,
                    theme.code,
                    theme.name,
                    candle=candle,
                ))
            except Exception as exc:
                errors.append((theme, exc))
        if progress is not None and task_id is not None:
            progress.update(task_id, advance=1, errs=len(errors))
        if lifecycle is not None:
            lifecycle.progress(
                completed,
                total,
                "拉取并计算题材趋势",
                provider=job_result.provider,
                failure_count=len(errors),
            )

    def on_wait(provider: str, failure: FetchFailure, attempt: int) -> None:
        if lifecycle is not None:
            lifecycle.wait(
                "题材指数 provider 退避重试",
                provider=provider,
                reason=failure.kind.value,
                attempt=attempt,
                retry_after=failure.retry_after or 0.0,
            )

    def report_heartbeat(active: int, queued: int) -> None:
        if lifecycle is not None:
            lifecycle.heartbeat(active_calls=active, queued=queued)

    jobs = [
        ProviderJob(
            key=theme.code,
            provider="em_concept_hist",
            call=partial(_fetch_theme_kline_job, theme, force),
            capabilities=_EM_THEME_KLINE_CAPABILITIES,
        )
        for theme in catalog
    ]
    try:
        run_provider_jobs(
            jobs,
            max_workers=workers,
            on_result=on_result,
            on_wait=on_wait,
            heartbeat=report_heartbeat if lifecycle is not None else None,
        )
    finally:
        if progress is not None:
            progress.stop()

    diagnosis.em_failed_count = len(errors)
    if errors and lifecycle is not None:
        lifecycle.degraded(
            "部分题材指数 K 线不可用",
            failure_count=len(errors),
            total=len(catalog),
        )
    return results, errors, "em", diagnosis


def sort_leaderboard(
    results: list[TrendResult],
    *,
    up_filter: int | None = None,
    down_filter: int | None = None,
    min_streak: int | None = None,
    sort_by: str = "streak",
    moneyflow: dict[str, float] | None = None,
) -> list[TrendResult]:
    """过滤 + 排序题材榜。

    Args:
        up_filter: 只保留 streak >= up_filter(连涨过滤)· None 时不过滤。
        down_filter: 只保留 streak <= -down_filter(连跌过滤)· None 时不过滤。
        min_streak: 只保留 abs(streak) >= min_streak · None 时不过滤。
        sort_by: "streak" / "latest" / "moneyflow"。
        moneyflow: sort_by="moneyflow" 时的 {theme_code: net_amount}。

    Returns: 过滤 + 排序后的 list[TrendResult] · 原 list 不变。
    """
    filtered = results
    if up_filter is not None:
        filtered = [r for r in filtered if r.streak >= up_filter]
    elif down_filter is not None:
        filtered = [r for r in filtered if r.streak <= -down_filter]
    if min_streak is not None:
        filtered = [r for r in filtered if abs(r.streak) >= min_streak]

    if sort_by == "latest":
        return sorted(
            filtered,
            key=lambda r: (-(r.daily_changes[0][1] if r.daily_changes else 0.0), -abs(r.streak)),
        )
    if sort_by == "moneyflow":
        moneyflow = moneyflow or {}
        for r in filtered:
            r.moneyflow_net = moneyflow.get(r.symbol)
        return sorted(
            filtered,
            key=lambda r: (
                r.moneyflow_net is None,
                -(r.moneyflow_net or 0.0),
                -abs(r.streak),
            ),
        )
    return sorted(filtered, key=lambda r: (-abs(r.streak), -abs(r.streak_pct)))


def _load_via_tushare(
    catalog: list[Theme],
    *,
    candle: bool,
    progress_console: Console | None,
    tushare_load_klines,
    lifecycle: OperationLifecycle | None = None,
):
    """TuShare 路径编排 · 1 次 batch 拿所有题材 35 天 K 线 + 逐题材 calc_trend。

    Returns:
        (results, errors, klines_error):
          - 成功:  (list[TrendResult], list[(Theme, Exception)], None)
          - 失败:  ([], [], TushareApiError) · klines_error 透传给 caller diagnosis

    progress_console 在 TuShare 路径下表现为单 task bar(N 个交易日 HTTP loop) ·
    比 EM 路径(391 题材并行)语义不同 · 但同样能让用户看到进度。
    lifecycle 传入时优先走 lifecycle 反馈，不再创建独立的 Rich Progress。
    """
    if lifecycle is not None:
        lifecycle.phase("TuShare 批量拉取题材 K 线", total=len(catalog))
        progress = None
    elif progress_console is not None:
        from rich.progress import Progress, SpinnerColumn, TextColumn

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]TuShare 批量拉题材 K 线[/]"),
            TextColumn("· {task.description}"),
            console=progress_console,
            transient=True,
        )
        progress.add_task("正在拉取 (~35 个交易日 batch)...", total=None)
        progress.start()
    else:
        progress = None

    try:
        klines_by_code, klines_err = tushare_load_klines(catalog)
    finally:
        if progress is not None:
            progress.stop()

    if not klines_by_code:
        # ths_daily 全 N 天失败 · 透传 first error 给 caller (frequency/credit/token 区分)
        return [], [], klines_err

    results: list[TrendResult] = []
    errors: list[tuple[Theme, Exception]] = []
    for theme in catalog:
        df = klines_by_code.get(theme.code)
        if df is None or df.empty:
            errors.append((theme, RuntimeError("TuShare 未返回此题材数据")))
            continue
        try:
            results.append(calc_trend(df, theme.code, theme.name, candle=candle))
        except Exception as e:
            errors.append((theme, e))

    return results, errors, None
