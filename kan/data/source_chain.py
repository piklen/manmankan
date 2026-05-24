"""数据源责任链编排器 · v0.0.6 引入 · 替代 fetcher.py 硬编码 if-chain。

KlineSourceChain 统一接管 4 件事:
1. 按 priority 排序 + 同 priority 并发 race
2. is_available() 检查 · 跳过不可用源 (token 没配 / 软依赖缺失 / 熔断中)
3. fetch 超时硬上限 · 慢源不拖累 (沿用 _fetch_via_akshare timeout=15 语义)
4. _source 标注由 chain.fetch 返回 (name) · 真正落 DataFrame 在 fetcher._normalize_kline

source 责任 (Adapter pattern · 防腐层):
- 拉数据 + 字段 rename 到标准 schema
- 异常吞 + debug_log + 熔断器 record · 不外泄

chain 责任 (Chain of Responsibility):
- 按 priority 依次试 · 同 priority race · 失败 fallback
- 不读 DataFrame 内容 · 不归一化 (那是 fetcher._normalize_kline 的活)

公开 API:
- KlineSourceChain(sources): 显式注册
- default_kline_chain(): 内置 5 源 + 用户 register_kline_source 添加的源
- reset_default_chain(): 注册新源后清 cache (api 内部用 · 用户极少需要)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import TYPE_CHECKING

from kan.infra.log import debug_log

if TYPE_CHECKING:
    import pandas as pd

    from kan.data.protocols import KlineSource


_RACE_TIMEOUT_SECONDS = 15
"""同 priority 多源并发 race 硬超时 · 沿用 _fetch_via_akshare 语义。

单源 fetch 内部已有各自超时 (akshare timeout=5 / tushare 30s / baostock 进程内) ·
chain 层 race timeout 是 "所有同档源都没及时返回时降级下一档" 的兜底。
"""


class KlineSourceChain:
    """K 线源责任链 · fetch(symbol, start) -> (df, source_name) | None。

    使用:
        chain = KlineSourceChain([TushareKlineSource(), BaostockKlineSource(), ...])
        result = chain.fetch("600519", "20240101")
        if result is None:
            raise ValueError("全源失败")
        df, source_name = result

    设计要点:
    - 构造时按 priority 排序 · runtime fetch 直接走排好的序列
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

        异常:
        - source.fetch 内部异常被 chain 捕获 · debug_log · 不外泄
        - source.is_available 异常视同 False (防御性 · 不让脏实现破整链)
        """
        for group in self._group_by_priority():
            available = [s for s in group if self._safe_is_available(s)]
            if not available:
                continue
            if len(available) == 1:
                result = self._single_fetch(available[0], symbol, start)
                if result is not None:
                    return result
                continue
            # 同 priority 多源并发 race
            result = self._race_fetch(available, symbol, start)
            if result is not None:
                return result
        return None

    def _group_by_priority(self) -> list[list[KlineSource]]:
        """按 priority 分组 · 同 priority 一组 (用于 race) · 不同 priority 严格 fallback。"""
        groups: list[list[KlineSource]] = []
        current: list[KlineSource] = []
        last_priority: int | None = None
        for src in self._sources:
            if last_priority is None or src.priority == last_priority:
                current.append(src)
            else:
                groups.append(current)
                current = [src]
            last_priority = src.priority
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def _safe_is_available(src: KlineSource) -> bool:
        """is_available 异常视同 False · 防御性 · 一个脏实现不破整链。"""
        try:
            return src.is_available()
        except Exception as e:
            debug_log(__name__, f"is_available {src.name}", e)
            return False

    @staticmethod
    def _single_fetch(
        src: KlineSource, symbol: str, start: str,
    ) -> tuple[pd.DataFrame, str] | None:
        """单源 fetch · 异常吞掉视同失败 · 返 (df, name) 或 None。"""
        try:
            df = src.fetch(symbol, start)
        except Exception as e:
            debug_log(__name__, f"single fetch {src.name}", e)
            return None
        if df is None:
            return None
        return df, src.name

    @staticmethod
    def _race_fetch(
        sources: list[KlineSource], symbol: str, start: str,
    ) -> tuple[pd.DataFrame, str] | None:
        """同 priority 多源并发 race · 第一个非 None 中标 · 慢源后台自生自灭。

        不用 `with ThreadPoolExecutor`: __exit__ 的 shutdown(wait=True) 会阻塞
        等所有线程 · 某源 hang 时整个调用挂死。改 shutdown(wait=False, cancel_futures=True) ·
        拿到结果即返回 · 慢/hang 的线程后台自生自灭 · 不阻塞调用方。
        (沿用 v0.0.5.0 _fetch_via_akshare 教训)
        """
        executor = ThreadPoolExecutor(max_workers=len(sources))
        try:
            future_to_source = {
                executor.submit(src.fetch, symbol, start): src
                for src in sources
            }
            try:
                for future in as_completed(future_to_source, timeout=_RACE_TIMEOUT_SECONDS):
                    src = future_to_source[future]
                    try:
                        df = future.result()
                    except Exception as e:
                        debug_log(__name__, f"race fetch {src.name}", e)
                        continue
                    if df is not None:
                        return df, src.name
            except FuturesTimeout:
                # 所有同 priority 源都没及时返回 · 降级下一 priority
                pass
            return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


# ── default chain (lazy singleton · 注册新源后失效) ───────────────────

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
