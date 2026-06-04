"""数据源 Protocol 定义 · 历史背景「适配器 + 责任链」架构。

设计原则:
- 每个领域独立 Protocol (KlineSource / 后续 ThemeKlineSource / HotListSource ...) ·
  签名各异但模式相同 · 拒绝 god type
- 实现者负责 "网络 I/O + source-specific 字段 rename 到标准 schema"
  (Anti-Corruption Layer · 防腐层 · domain model 永不感知数据源差异)
- 链式编排由 source_chain.KlineSourceChain 统一接管 ·
  熔断器 / 并发 race / debug_log / _source 标注全在 chain 内做

priority 约定:
- 数字小优先 · 同 priority 多源并发 race
- 0-9   保留给极顶档 (未来 ToB 付费 + 自部署)
- 10-19 内置付费 (tushare)
- 20-29 内置免费稳定 (baostock 独立服务器)
- 30-39 内置免费 race (eastmoney / sina 双源并发)
- 40-49 内置免费兜底 (tencent · 部分字段不可信)
- 50-89 留给用户自定义源
- 90-99 保留给极兜底 fallback

参考: kan/core/stock_set.py (StockSet Protocol · 同形上游抽象)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd


@runtime_checkable
class KlineSource(Protocol):
    """单只股票日 K 数据源 (适配器) · 责任链中的一档。

    实现者契约:
    - is_available(): token / 软依赖 / 熔断器三重检查 · False 则 chain 直接跳过
      (不计入 fallback · 不调 fetch · 不打扰用户)
    - fetch(symbol, start): 拉数据 + 列名 rename 到标准 schema · 异常吞掉返 None
      (chain 负责 fallback · source 不抛)
    - source 不在内部填 _source / NaN · 由 chain + fetcher._normalize_kline 接管

    标准 schema (fetch 返回 DataFrame 必含 KLINE_REQUIRED · 其余 chain 补 NaN):
    - 必含: date / open / high / low / close
    - 推荐: volume / amount (能拿就拿 · 拿不到 chain 填 NaN)
    - 不填: _source (chain 加)
    """

    name: str
    """数据源唯一标识 · 熔断器 key + _source 标注 + debug_log prefix。

    内置 source 用小写英文 (tushare / baostock / eastmoney / sina / tencent) ·
    用户自定义建议加 prefix 避免冲突 (例 user_wind / user_tdx)。
    """

    priority: int
    """优先级 · 数字小优先 · 同值多源并发 race (复刻早期 sina+eastmoney race 语义)。

    chain 按 priority sort · 不同 priority 严格 fallback 链 ·
    同 priority 时 ThreadPoolExecutor 并发 · 第一个非 None 中标。
    """

    def is_available(self) -> bool:
        """运行时可用性 · False 时 chain 跳过此档 · 不计入 fallback 链。

        典型实现:
        - TushareKlineSource: bool(token) + not breaker.is_down(name)
        - BaostockKlineSource: try import + not breaker.is_down(name)
        - EastmoneyKlineSource: try import akshare + not breaker.is_down(name)

        is_available 必须 cheap (不做网络调用) · chain 在 fetch 前对所有源依次查。
        """
        ...

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        """拉单只股票 K 线 · 失败返 None · 列名已 rename 到标准 schema。

        Args:
            symbol: 6 位股票代码 (chain 已校验 · source 可信任)
            start: YYYYMMDD 起始日期

        Returns:
            DataFrame · 必含 date/open/high/low/close · 缺失列由 chain 填 NaN
            None 表示本源失败 · chain 自动 fallback 下一档

        实现注意:
        - broad except Exception → debug_log + 熔断器 record(ok=False) + return None
        - 不让异常外泄到 chain
        - 不抛 ValueError 等业务异常 · 只用 None 表达失败
        """
        ...


@runtime_checkable
class MetricsSource(Protocol):
    """截面式市场指标数据源 (适配器) · 按 trade_date 拉一批/全市场 · 责任链中的一档。

    与 KlineSource 的本质区别 (签名各异 · 模式相同 · 各领域独立 Protocol 拒绝 god type):
    - KlineSource.fetch(symbol, start):    单只股票时间序列 · 逐只历史 · 全市场代价高
    - MetricsSource.fetch(trade_date, …):  单日截面多只 · 一次拉一批 · 全市场代价低

    截面接口 (daily_basic / moneyflow / ...) 按交易日一次返回全市场 · 这是全市场筛
    廉价的根本原因 (截面 vs K 线代价不对称)。

    实现者契约 (同 KlineSource · 防腐层 ACL · domain model 永不感知数据源差异):
    - is_available(): token / 软依赖 / 熔断器检查 · False 则 chain 跳过 (不计 fallback)
    - fetch(trade_date, symbols): 拉数据 + 列名 rename 到标准 schema · 异常吞掉返 None
    - source 不在内部填 _source / NaN · 由 chain + metrics._normalize_metrics 接管

    截面源约定: fetch 接收 symbols 但实现上可总拉全市场 (截面接口一次全市场最划算 ·
    利于缓存复用) · symbols 过滤交给编排层 metrics.fetch_metrics。

    标准 schema (fetch 返回 DataFrame 必含 METRICS_REQUIRED · 其余编排层补):
    - 必含: symbol (6 位代码 · ts_code 已 strip 交易所后缀)
    - 推荐: trade_date / 各指标列 (pe_ttm / pb / dv_ttm / turnover_rate / ...)
    - 不填: _source (chain 加)
    """

    name: str
    """数据源唯一标识 · 熔断器 key + _source 标注 + debug_log prefix。

    截面源与同数据商的 K 线源应用独立 name (例 tushare_metrics ≠ tushare) ·
    避免不同接口 (daily_basic vs daily · 频率门槛各异) 共享熔断器互相误伤。
    """

    priority: int
    """优先级 · 数字小优先 · 同值多源并发 race · 复用文件顶部 priority 约定。"""

    def is_available(self) -> bool:
        """运行时可用性 · False 时 chain 跳过此档 · 不计入 fallback 链。

        必须 cheap (不做网络调用) · chain 在 fetch 前对所有源依次查。
        典型实现: TushareMetricsSource: bool(token) + not breaker.is_down(name)。
        """
        ...

    def fetch(
        self, trade_date: str, symbols: list[str] | None = None,
    ) -> pd.DataFrame | None:
        """拉单日截面指标 · 失败返 None · 列名已 rename 到标准 schema。

        Args:
            trade_date: YYYYMMDD 交易日 (chain 已校验 · source 可信任)
            symbols: 限定股票子集 (6 位代码) · None = 全市场 · 截面源可忽略此参数
                     总拉全市场 (一次拉全 · 过滤交给编排层 · 利于缓存复用)

        Returns:
            DataFrame · 必含 symbol · 缺失列由编排层 _normalize_metrics 处理
            None 表示本源失败 · chain 自动 fallback 下一档

        实现注意 (同 KlineSource):
        - broad except Exception → debug_log + 熔断器 record(ok=False) + return None
        - 不让异常外泄到 chain · 不抛业务异常 · 只用 None 表达失败
        """
        ...
