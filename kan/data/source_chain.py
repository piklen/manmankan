"""数据源责任链编排器 · 背景 · 替代 fetcher.py 硬编码 if-chain。

核心算法 `_run_chain` 是通用的 (K 线 / 题材成分股 / 未来其他领域复用):
1. 按 priority 排序 (caller 已 sort · 此处直接用)
2. is_available() 检查 · 跳过不可用源
3. 同 priority 多源并发 race · 第一个非 None 中标
4. 慢源后台自生自灭 (shutdown wait=False) · 不阻塞调用方
5. 异常吞 + debug_log · 不外泄给 chain caller
6. 全失败返 None · chain caller 决定文案

每个领域的 chain class (KlineSourceChain / ThemeConstituentSourceChain / ...)
负责:
- 持有 sources 列表 · 类型化 fetch 签名 (symbol+start / theme / ...)
- 调 _run_chain 传入领域特定 invoke 闭包
- 提供 default_*_chain() singleton 工厂

source 责任 (Adapter pattern · 防腐层):
- 拉数据 + 字段 rename 到该领域标准 schema
- 异常吞 + debug_log + 熔断器 record · 不外泄

公开 API:
- KlineSourceChain(sources): K 线领域 chain · 显式注册
- default_kline_chain(): K 线 + 用户注册源
- reset_default_kline_chain(): chain 单例失效
- ThemeConstituentSourceChain (kan/data/theme_constituents.py): 题材成分股领域
"""
from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from kan.infra.log import debug_log

if TYPE_CHECKING:
    import pandas as pd

    from kan.data.protocols import KlineSource, MetricsSource


_RACE_TIMEOUT_SECONDS = 15
"""同 priority 多源并发 race 硬超时 · 沿用 _fetch_via_akshare 语义。

单源 fetch 内部已有各自超时 (akshare timeout=5 / tushare 30s / baostock 进程内) ·
chain 层 race timeout 是 "所有同档源都没及时返回时降级下一档" 的兜底。
"""


T = TypeVar("T")


def _run_chain(
    sources_sorted: list[Any],
    invoke: Callable[[Any], T | None],
    *,
    timeout: float = _RACE_TIMEOUT_SECONDS,
) -> tuple[T, str] | None:
    """通用 chain 编排算法 · K 线 / 题材成分股 / 其他领域 chain 共用。

    Args:
        sources_sorted: 已按 priority 升序排序的 source 列表 (caller 负责 sort)
        invoke: 调单源 fetch 的闭包 `(src) -> result | None`
                领域 chain class 用闭包 capture 领域参数 (例 lambda src: src.fetch(symbol, start))
        timeout: 同 priority race 硬超时

    Returns:
        (result, source_name) · 第一个非 None 结果
        None · 所有源 unavailable 或全失败

    异常:
        - source.fetch 内异常 → debug_log + 视同 None (不外泄)
        - source.is_available 异常 → debug_log + 视同 False (防御性 · 不破整链)
    """
    for group in _group_by_priority(sources_sorted):
        available = [s for s in group if _safe_is_available(s)]
        if not available:
            continue
        if len(available) == 1:
            src = available[0]
            try:
                result = invoke(src)
            except Exception as e:
                debug_log(__name__, f"single fetch {src.name}", e)
                continue
            if result is not None:
                return result, src.name
            continue
        # 同 priority 多源并发 race
        race_result = _race(available, invoke, timeout)
        if race_result is not None:
            return race_result
    return None


def _group_by_priority(sources_sorted: list[Any]) -> list[list[Any]]:
    """按 priority 分组 · 同 priority 一组 (race 候选) · 不同 priority 严格 fallback。"""
    groups: list[list[Any]] = []
    current: list[Any] = []
    last_priority: int | None = None
    for src in sources_sorted:
        if last_priority is None or src.priority == last_priority:
            current.append(src)
        else:
            groups.append(current)
            current = [src]
        last_priority = src.priority
    if current:
        groups.append(current)
    return groups


def _safe_is_available(src: Any) -> bool:
    """is_available 异常视同 False · 防御性 · 一个脏实现不破整链。"""
    try:
        return src.is_available()
    except Exception as e:
        debug_log(__name__, f"is_available {src.name}", e)
        return False


def _race(
    sources: list[Any],
    invoke: Callable[[Any], T | None],
    timeout: float,
) -> tuple[T, str] | None:
    """同 priority 多源并发 race · 第一个非 None 中标 · 慢源后台自生自灭。

    不用 ThreadPoolExecutor: executor worker 是非 daemon 线程,即使 wait=False,
    Python 进程退出时仍会等慢源结束。这里显式使用 daemon thread,保证
    已降级/已中标后的 CLI 进程不会被不可取消 SDK 调用拖住。
    """
    results: queue.Queue[tuple[Any, T | None, Exception | None]] = queue.Queue()

    def _worker(src: Any) -> None:
        try:
            results.put((src, invoke(src), None))
        except Exception as e:
            results.put((src, None, e))

    for src in sources:
        threading.Thread(
            target=_worker,
            args=(src,),
            name=f"kan-source-race-{getattr(src, 'name', 'unknown')}",
            daemon=True,
        ).start()

    deadline = time.monotonic() + timeout
    remaining = len(sources)
    while remaining > 0:
        wait = deadline - time.monotonic()
        if wait <= 0:
            return None
        try:
            src, result, err = results.get(timeout=wait)
        except queue.Empty:
            return None
        remaining -= 1
        if err is not None:
            debug_log(__name__, f"race fetch {src.name}", err)
            continue
        if result is not None:
            return result, src.name
    return None


class KlineSourceChain:
    """K 线源责任链 · fetch(symbol, start) -> (df, source_name) | None。

    使用:
        chain = KlineSourceChain([TushareKlineSource(), BaostockKlineSource(), ...])
        result = chain.fetch("600519", "20240101")
        if result is None:
            raise ValueError("全源失败")
        df, source_name = result

    设计要点:
    - 构造时按 priority 排序 · runtime fetch 走 _run_chain 通用算法
    - 同 priority 自动 race (复刻 sina+eastmoney race · 不需要 source 显式知道)
    - is_available() 失败的源完全跳过 (不计入 fallback 链 · 不浪费一次 fetch 调用)
    - 全失败返 None · 不抛 · 调用方决定文案
    """

    def __init__(self, sources: list[KlineSource]) -> None:
        """注册 sources · 按 priority 升序排序 · 同 priority 保持注册顺序 (用作 race 候选)。"""
        self._sources: list[KlineSource] = sorted(sources, key=lambda s: s.priority)

    @property
    def sources(self) -> list[KlineSource]:
        """已注册 sources 的 snapshot (priority 排序后) · 调试 / 检查用。"""
        return list(self._sources)

    def fetch(
        self, symbol: str, start: str,
    ) -> tuple[pd.DataFrame, str] | None:
        """按 priority 依次试 · 同 priority 多源并发 race · 全失败返 None。

        Returns:
            (raw_df, source_name) · raw_df 列名已 rename 但未 _normalize (chain 不做)
            None · 所有源都失败 / 不可用
        """
        return _run_chain(self._sources, lambda src: src.fetch(symbol, start))


# ── K 线 default chain (lazy singleton · 注册新源后失效) ───────────────

_default_chain: KlineSourceChain | None = None


def default_kline_chain() -> KlineSourceChain:
    """内置 K 线源链 · 5 内置源 + 用户通过 kan.api.register_kline_source 注册的源。

    内置源 priority:
    - TushareKlineSource (10): 配 token 时顶档 · 数据精度高 / 数值统一
    - BaostockKlineSource (20): 独立服务器 / 无限流 / 精度高
    - EastmoneyKlineSource (30) + SinaKlineSource (30): akshare 双源 race
    - TencentKlineSource (40): 兜底 · 价格可信但 volume 字段不可信

    lazy singleton · 用户 register_kline_source 后 reset_default_chain 失效重建。
    """
    global _default_chain
    if _default_chain is None:
        from kan.data._builtin_sources import builtin_kline_sources
        _default_chain = KlineSourceChain(builtin_kline_sources())
    return _default_chain


def reset_default_chain() -> None:
    """清 default chain 单例 · 让下次 default_kline_chain() 重建 (含新注册的用户源)。

    public API: kan.api.register_kline_source 内部调此 · 用户通常不需直接调。
    测试也可用此重置 (虽然内置 sources 无状态 · 一般不必)。
    """
    global _default_chain
    _default_chain = None


# ══════════════════════════════════════════════════════════════════
# 截面指标领域 MetricsSourceChain (截面指标层) · 同形 KlineSourceChain · 复用 _run_chain
# ══════════════════════════════════════════════════════════════════


class MetricsSourceChain:
    """截面指标源责任链 · fetch(trade_date, symbols) -> (df, source_name) | None。

    与 KlineSourceChain 同形 (复用通用 _run_chain) · 区别仅 fetch 签名
    (截面 trade_date+symbols vs 单只 symbol+start)。

    使用:
        chain = MetricsSourceChain([TushareMetricsSource()])
        result = chain.fetch("20260529")
        if result is None:
            ...  # 全源失败 / 不可用
        df, source_name = result

    设计要点 (同 KlineSourceChain):
    - 构造时按 priority 排序 · runtime fetch 走 _run_chain 通用算法
    - 同 priority 自动 race · is_available()=False 的源完全跳过 (不浪费 fetch)
    - 全失败返 None · 不抛 · 调用方决定文案
    """

    def __init__(self, sources: list[MetricsSource]) -> None:
        """注册 sources · 按 priority 升序排序 · 同 priority 保持注册顺序 (race 候选)。"""
        self._sources: list[MetricsSource] = sorted(sources, key=lambda s: s.priority)

    @property
    def sources(self) -> list[MetricsSource]:
        """已注册 sources 的 snapshot (priority 排序后) · 调试 / 检查用。"""
        return list(self._sources)

    def fetch(
        self, trade_date: str, symbols: list[str] | None = None,
    ) -> tuple[pd.DataFrame, str] | None:
        """按 priority 依次试 · 同 priority 多源并发 race · 全失败返 None。

        Returns:
            (raw_df, source_name) · raw_df 列名已 rename 但未 normalize (chain 不做)
            None · 所有源都失败 / 不可用
        """
        return _run_chain(self._sources, lambda src: src.fetch(trade_date, symbols))


# ── metrics default chain (lazy singleton · 注册新源后失效) ─────────────

_default_metrics_chain: MetricsSourceChain | None = None


def default_metrics_chain() -> MetricsSourceChain:
    """内置截面指标源链 · TushareMetricsSource (priority 10) + 用户注册源。

    截面指标层 只有 tushare 一个源 (PublicMetricsSource 降级源留 §5 后续) ·
    lazy singleton · register_metrics_source 后 reset 失效重建。
    """
    global _default_metrics_chain
    if _default_metrics_chain is None:
        from kan.data._builtin_sources import builtin_metrics_sources
        _default_metrics_chain = MetricsSourceChain(builtin_metrics_sources())
    return _default_metrics_chain


def reset_default_metrics_chain() -> None:
    """清 metrics default chain 单例 · 让下次 default_metrics_chain() 重建 (含新注册源)。

    register_metrics_source 内部调此 · 测试也可用此重置。
    """
    global _default_metrics_chain
    _default_metrics_chain = None
