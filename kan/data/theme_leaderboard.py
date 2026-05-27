"""题材榜数据编排层 · v0.0.5.7 引入 · `kan theme trend` 后端。

把"所有题材指数"当一组 first-class 标的批量拉 K 线 + 算 streak。
跟 watchlist trend 在算法上 100% 复用 `calc_trend` · 数据源换成题材 K 线。

两条数据源路径(运行时选择):
- TuShare Pro 路径(优先 · 配 token 时启用):走 ths_daily batch 接口 ·
  60 次 HTTP 拿所有题材 60 天历史 · 服务端聚合 · 客户端 group by code
- adata EM 路径(fallback · 默认):走 get_market_concept_east 单题材 ·
  ThreadPoolExecutor 默认 16 worker · `KAN_THEME_TOP_PARALLEL` env 覆盖(1-32)

为啥两路:adata EM datacenter 不稳定(2026-05-25 实测整体 RemoteDisconnected)·
没 stale cache 兜底时第一次跑 kan theme trend 直接全挂。TuShare 是有 token 用户
的稳定回避路径(自部署代理 / 官方 endpoint 都支持)。

设计要点:
- cache 复用:adata 路径用 `fetch_theme_kline` 已有 24h parquet · TuShare 路径
  用 `tushare_load_theme_klines` 独立 12h batch parquet
- 失败容忍:单题材失败不阻塞整榜 · 收集到 errors 列表 · caller 决定如何提示
- 进度条:caller 传 `progress_console` 显示 rich.Progress · None 时静默(测试 / pipe 用)

为什么不走 OOP `ThemeIndexSet` + `run_data_pipeline`:
- `trend_batch` 现有契约是 `get_cached(symbol)` 个股缓存 · 改它兼容多源会破坏简单性
- 题材榜 UX 跟 watchlist trend 差异大(进度条 / 全量 391 / 排名列)· 独立命令更干净
- 拒绝过度工程(docs/roadmap.md "当前痛点没出现就不引入抽象")
"""
from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kan.core.scanner import TrendResult, calc_trend
from kan.data.boards import (
    ThemeDataUnavailableError,
    fetch_theme_kline,
    load_theme_catalog,
)

if TYPE_CHECKING:
    from rich.console import Console

    from kan.core.models import Theme


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
      em_attempted:       走 EM 路径 → True (token 未配 或 TuShare 失败 fallback)
      em_total:           EM catalog 拿到的题材数(分母)
      em_failed_count:    EM 并行 fetch 失败的题材数(分子)
    """

    tushare_attempted: bool = False
    tushare_failed_at: str | None = None
    tushare_endpoint: str | None = None
    tushare_token_masked: str | None = None
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


def load_theme_leaderboard(
    *,
    candle: bool = False,
    force: bool = False,
    parallel: int | None = None,
    progress_console: Console | None = None,
) -> tuple[
    list[TrendResult],
    list[tuple[Theme, Exception]],
    str,
    LeaderboardDiagnosis,
]:
    """拉所有题材 K 线 + 算 streak · 返回 (results, errors, source, diagnosis)。

    数据源选择(运行时):
    - TuShare token 配置 + ths_daily batch 通 → 走 TuShare 路径(快 · 稳定 · source='tushare')
    - 否则 → 走 adata EM 路径(原 v0.0.5.7 并行实现 · source='em')

    Args:
        candle: True=阳线阴线口径 / False=收盘价口径 · 透传 calc_trend。
        force: True 时忽略 cache 强刷(adata EM 路径)· TuShare 路径目前忽略 force
               (TuShare cache 12h · 当日强刷可手动删 boards/klines_tushare_*.parquet)。
        parallel: adata EM 路径 worker 数 · None 时走 _resolve_parallel(env / 默认 16)。
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

        ts_catalog = tushare_load_theme_catalog()
        if ts_catalog:
            ts_results = _load_via_tushare(
                ts_catalog, candle=candle, progress_console=progress_console,
                tushare_load_klines=tushare_load_theme_klines,
            )
            if ts_results is not None:
                results, errors = ts_results
                return results, errors, "tushare", diagnosis
            # TuShare klines 接口失败 · 标记后落 EM 路径(双重保险)
            diagnosis.tushare_failed_at = "klines"
        else:
            # TuShare catalog 接口失败(token 无效 / 代理坏 / 网络)· 落 EM 路径
            diagnosis.tushare_failed_at = "catalog"

    catalog = load_theme_catalog(force=False)  # catalog 单独走 24h cache · 不并行
    if not catalog:
        raise ThemeDataUnavailableError("题材清单为空 · 无法生成榜单")

    diagnosis.em_attempted = True
    diagnosis.em_total = len(catalog)

    workers = _resolve_parallel(parallel)
    results: list[TrendResult] = []
    errors: list[tuple[Theme, Exception]] = []

    if progress_console is not None:
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

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(fetch_theme_kline, theme, force): theme
                for theme in catalog
            }
            for fut in concurrent.futures.as_completed(futures):
                theme = futures[fut]
                try:
                    df = fut.result()
                    if df is None or df.empty:
                        errors.append((theme, ThemeDataUnavailableError("K 线为空")))
                    else:
                        results.append(calc_trend(df, theme.code, theme.name, candle=candle))
                except Exception as e:
                    # 单题材失败必须降级 · 不阻塞整榜(391 题材任何一个挂都不应让全榜失败)
                    errors.append((theme, e))
                finally:
                    if progress is not None and task_id is not None:
                        progress.update(task_id, advance=1, errs=len(errors))
    finally:
        if progress is not None:
            progress.stop()

    diagnosis.em_failed_count = len(errors)
    return results, errors, "em", diagnosis


def sort_leaderboard(
    results: list[TrendResult],
    *,
    up_filter: int | None = None,
    down_filter: int | None = None,
) -> list[TrendResult]:
    """按 streak 绝对值降序 + streak_pct 绝对值降序 · 跟 trend_batch 排序口径一致。

    Args:
        up_filter: 只保留 streak >= up_filter(连涨过滤)· None 时不过滤。
        down_filter: 只保留 streak <= -down_filter(连跌过滤)· None 时不过滤。

    Returns: 过滤 + 排序后的 list[TrendResult] · 原 list 不变。
    """
    filtered = results
    if up_filter is not None:
        filtered = [r for r in filtered if r.streak >= up_filter]
    elif down_filter is not None:
        filtered = [r for r in filtered if r.streak <= -down_filter]

    return sorted(filtered, key=lambda r: (-abs(r.streak), -abs(r.streak_pct)))


def _load_via_tushare(
    catalog: list[Theme],
    *,
    candle: bool,
    progress_console: Console | None,
    tushare_load_klines,
) -> tuple[list[TrendResult], list[tuple[Theme, Exception]]] | None:
    """TuShare 路径编排 · 1 次 batch 拿所有题材 60 天 K 线 + 逐题材 calc_trend。

    Returns:
        (results, errors) 同 load_theme_leaderboard 主签名
        None 表示 TuShare 不可用(batch 失败 / 0 结果)· caller fallback EM 路径

    progress_console 在 TuShare 路径下表现为单 task bar(N 个交易日 HTTP loop) ·
    比 EM 路径(391 题材并行)语义不同 · 但同样能让用户看到进度。
    """
    if progress_console is not None:
        from rich.progress import Progress, SpinnerColumn, TextColumn

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]TuShare 批量拉题材 K 线[/]"),
            TextColumn("· {task.description}"),
            console=progress_console,
            transient=True,
        )
        progress.add_task("正在拉取 (~60 个交易日 batch)...", total=None)
        progress.start()
    else:
        progress = None

    try:
        klines_by_code = tushare_load_klines(catalog)
    finally:
        if progress is not None:
            progress.stop()

    if not klines_by_code:
        return None

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

    return results, errors
