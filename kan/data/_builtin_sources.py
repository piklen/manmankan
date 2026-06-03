"""K 线源注册表 · 内置 5 源 + 运行时用户注册源 · default_kline_chain 构造时取此列表。

公开 API (用户 facing) 在 `kan.api`:
- `register_kline_source(src)`: 加自定义源
- `clear_user_kline_sources()`: 清空 (主要测试 / 切换源场景用)

此模块是 internal · 用户不应直接 import (走 `kan.api` 入口)。
设计上 chain 不感知 user-vs-builtin · 都是 KlineSource 实例同等对待。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.data.protocols import KlineSource, MetricsSource


_user_kline_sources: list[KlineSource] = []
"""运行时用户注册的 K 线源 · 模块级 list · register_kline_source append · 进程内有效。"""


def builtin_kline_sources() -> list[KlineSource]:
    """内置 5 源 + 用户注册源 · 给 default_kline_chain 构造用。

    内置实例化是 cheap (无 __init__ 参数 · 无网络) · 每次构造 chain 都新建实例无所谓。
    chain 按 priority 排序 · 用户源可 priority=15 插队到 baostock 之前 ·
    可 priority=50 兜底在 tencent 之后。
    """
    from kan.data.sources import (
        BaostockKlineSource,
        EastmoneyKlineSource,
        SinaKlineSource,
        TencentKlineSource,
    )
    from kan.data.tushare import TushareKlineSource

    return [
        TushareKlineSource(),
        BaostockKlineSource(),
        EastmoneyKlineSource(),
        SinaKlineSource(),
        TencentKlineSource(),
        *_user_kline_sources,
    ]


def register_kline_source(source: KlineSource) -> None:
    """注册用户自定义 K 线源 · 自动 reset default chain · 下次调 fetch_kline 含新源。

    Args:
        source: 实现 KlineSource Protocol 的对象 (有 name / priority / is_available / fetch)。
                建议 priority ∈ [50, 89] 避免与内置 (10-49) / 兜底 (90-99) 冲突。
                name 建议加 prefix (例 user_wind / user_tdx) 避免与内置撞名 (熔断器 key 共享)。

    幂等性: 同一对象多次注册会重复出现在 chain 中 (调用方负责去重)。
    """
    from kan.data.source_chain import reset_default_chain

    _user_kline_sources.append(source)
    reset_default_chain()


def clear_user_kline_sources() -> None:
    """清空所有用户注册的 K 线源 · 自动 reset default chain。

    用途:
    - 测试: 进入测试前清空避免污染
    - 切换源场景: 用户运行时换一组源
    """
    from kan.data.source_chain import reset_default_chain

    _user_kline_sources.clear()
    reset_default_chain()


# ══════════════════════════════════════════════════════════════════
# 截面指标领域注册表 (截面指标层) · 同形 K 线三件套 · default_metrics_chain 取此列表
# ══════════════════════════════════════════════════════════════════

_user_metrics_sources: list[MetricsSource] = []
"""运行时用户注册的截面指标源 · 模块级 list · register_metrics_source append。"""


def builtin_metrics_sources() -> list[MetricsSource]:
    """内置截面指标源 + 用户注册源 · 给 default_metrics_chain 构造用。

    截面指标层 只含 TushareMetricsSource (daily_basic · priority 10) ·
    PublicMetricsSource 降级源 (akshare / 东财公开接口) 留后续阶段。
    """
    from kan.data.metrics import TushareMetricsSource

    return [
        TushareMetricsSource(),
        *_user_metrics_sources,
    ]


def register_metrics_source(source: MetricsSource) -> None:
    """注册用户自定义截面指标源 · 自动 reset metrics default chain。

    Args:
        source: 实现 MetricsSource Protocol 的对象 (name / priority / is_available / fetch)。
                建议 priority ∈ [50, 89] 避开内置 (10-49) / 兜底 (90-99)。
                name 建议加 prefix (例 user_wind_metrics) 避免与内置撞名 (熔断器 key 共享)。

    internal: 截面指标层 暂不 export 到 kan.api (AI 入口契约 = AI JSON 层) · 测试 / 内部用。
    """
    from kan.data.source_chain import reset_default_metrics_chain

    _user_metrics_sources.append(source)
    reset_default_metrics_chain()


def clear_user_metrics_sources() -> None:
    """清空所有用户注册的截面指标源 · 自动 reset metrics default chain。

    用途: 测试进入前清空避免污染 / 运行时换一组源。
    """
    from kan.data.source_chain import reset_default_metrics_chain

    _user_metrics_sources.clear()
    reset_default_metrics_chain()
