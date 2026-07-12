"""题材成分股 source + chain (背景 · Phase 2) · 替代 boards.get_theme_constituents
内的 try-THS-except-EM 硬编码 fallback。

跟 KlineSourceChain 同模式 (priority sort + race + fallback · 复用 _run_chain)。

内置 2 源:
- ThsConstituentSource    (priority=10): 同花顺公开页面
                                          · THS 主源 · 稳 · 不参与熔断 (THS 失败往往是
                                          单次网络抖动 · 5min cooldown 太重)
- EmConstituentSource     (priority=20): AkShare 东财题材成分接口
                                          · EM datacenter · 走 push2 反爬 · em_push2_concept
                                          5min 熔断保护下游

cache 编排在 boards.py 层 · 此模块只负责 source adapter + chain (DDD 分层)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from kan.data.provider_contracts import ProviderCapabilities
from kan.data.source_chain import _run_chain
from kan.infra.log import debug_log

if TYPE_CHECKING:
    from kan.core.models import Theme


# ══════════════════════════════════════════════════════════════════
# Protocol · 适配器契约
# ══════════════════════════════════════════════════════════════════


@runtime_checkable
class ThemeConstituentSource(Protocol):
    """题材成分股数据源 (adapter) · ThemeConstituentSourceChain 中的一档。

    实现者契约:
    - is_available(): 软依赖 + 熔断器检查 · False 时 chain skip
    - fetch(theme): 返 list[(code, name)] · 失败返 None · chain fallback 下一档
    - 异常不外泄 · 内部 try/except + debug_log

    cache 不在 source 做 (boards.py get_theme_constituents 统一 24h cache)。
    """

    name: str
    """数据源唯一标识 · 熔断器 key + debug_log prefix。"""

    priority: int
    """优先级 · 数字小优先 · 同值多源 race (跟 KlineSource 同约定)。"""

    def is_available(self) -> bool: ...

    def fetch(self, theme: Theme) -> list[tuple[str, str]] | None: ...


# ══════════════════════════════════════════════════════════════════
# Chain · 责任链编排
# ══════════════════════════════════════════════════════════════════


class ThemeConstituentSourceChain:
    """题材成分股源链 · fetch(theme) -> (pairs, source_name) | None。

    pairs = list[(stock_code, short_name)] · 与 boards.get_theme_constituents 旧返回格式一致。

    复用 source_chain._run_chain 通用算法 (与 KlineSourceChain 同形)。
    """

    def __init__(self, sources: list[ThemeConstituentSource]) -> None:
        self._sources: list[ThemeConstituentSource] = sorted(
            sources, key=lambda s: s.priority,
        )

    @property
    def sources(self) -> list[ThemeConstituentSource]:
        return list(self._sources)

    def fetch(
        self, theme: Theme,
    ) -> tuple[list[tuple[str, str]], str] | None:
        """按 priority 依次试 · 全失败返 None · 调用方 (boards) 决定文案。"""
        return _run_chain(self._sources, lambda src: src.fetch(theme))


# ══════════════════════════════════════════════════════════════════
# 内置 2 源 (THS / EM)
# ══════════════════════════════════════════════════════════════════


class ThsConstituentSource:
    """THS (同花顺)题材成分股 · priority=10 · 兼容旧 THS catalog。

    不参与熔断 · THS 失败往往是单次网络抖动 · 5min cooldown 对单题材太重。
    """

    name = "ths_constituent"
    priority = 10
    capabilities = ProviderCapabilities(
        max_concurrency=8,
        initial_concurrency=4,
        max_attempts=1,
        timeout_seconds=10.0,
    )

    def is_available(self) -> bool:
        return True

    def fetch(self, theme: Theme) -> list[tuple[str, str]] | None:
        from kan.data.concepts import fetch_ths_constituents

        try:
            df = fetch_ths_constituents(theme)
        except Exception as e:
            debug_log(__name__, f"THS concept_constituent_ths({theme.code})", e)
            return None
        if df is None or df.empty:
            return None
        return [
            (str(row["stock_code"]).strip(), str(row["short_name"]).strip())
            for _, row in df.iterrows()
        ]


class EmConstituentSource:
    """EM (东方财富)题材成分股 · priority=20 · 走 push2 · 反爬触发 5min 熔断。

    name='em_push2_concept' 沿用旧熔断 key · 保持现有 circuit_breaker 统计兼容。
    is_available 看熔断 · 熔断中 chain skip 不调 fetch。
    """

    name = "em_push2_concept"
    priority = 20
    capabilities = ProviderCapabilities(
        max_concurrency=6,
        initial_concurrency=2,
        max_attempts=1,
        timeout_seconds=15.0,
    )

    def is_available(self) -> bool:
        from kan.infra.circuit_breaker import get_breaker
        return not get_breaker().is_down(self.name)

    def fetch(self, theme: Theme) -> list[tuple[str, str]] | None:
        from kan.data.concepts import fetch_em_constituents
        from kan.infra.circuit_breaker import get_breaker

        breaker = get_breaker()
        try:
            df = fetch_em_constituents(theme)
        except LookupError as e:
            debug_log(__name__, f"EM concept_constituent_east({theme.code}) 未匹配", e)
            return None
        except Exception as e:
            breaker.record(self.name, ok=False)
            debug_log(__name__, f"EM concept_constituent_east({theme.code})", e)
            return None
        if df is None or df.empty:
            breaker.record(self.name, ok=False)
            return None
        breaker.record(self.name, ok=True)
        return [
            (str(row["stock_code"]).strip(), str(row["short_name"]).strip())
            for _, row in df.iterrows()
        ]


# ══════════════════════════════════════════════════════════════════
# default chain (lazy singleton · 注册新源后失效)
# ══════════════════════════════════════════════════════════════════


_default_constituent_chain: ThemeConstituentSourceChain | None = None
_user_constituent_sources: list[ThemeConstituentSource] = []


def default_theme_constituent_chain() -> ThemeConstituentSourceChain:
    """内置题材成分股源链 · 2 内置 (THS / EM) + 用户注册源。

    用户通过 kan.api.register_theme_constituent_source 加自定义源。
    """
    global _default_constituent_chain
    if _default_constituent_chain is None:
        _default_constituent_chain = ThemeConstituentSourceChain(
            [
                ThsConstituentSource(),
                EmConstituentSource(),
                *_user_constituent_sources,
            ],
        )
    return _default_constituent_chain


def reset_default_theme_constituent_chain() -> None:
    """清 default chain singleton · 让下次 default_*_chain() 重建。"""
    global _default_constituent_chain
    _default_constituent_chain = None


def register_theme_constituent_source(source: ThemeConstituentSource) -> None:
    """注册用户自定义题材成分股源 · 自动 reset default chain。

    建议 priority ∈ [50, 89] 避免与内置 (10-20) / 兜底 (90-99) 冲突。
    name 建议加 prefix (例 user_xxx) 避免与内置 ths_constituent / em_push2_concept 撞名。
    """
    _user_constituent_sources.append(source)
    reset_default_theme_constituent_chain()


def clear_user_theme_constituent_sources() -> None:
    """清空所有用户注册的题材成分股源 · 自动 reset default chain。"""
    _user_constituent_sources.clear()
    reset_default_theme_constituent_chain()
