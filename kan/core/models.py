from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    import pandas as pd


class Stock(BaseModel):
    symbol: str
    name: str
    added_at: date
    groups: dict[str, str | list[str]] = {}



class PeriodResult(BaseModel):
    period: int
    n_low: float
    n_high: float
    position_pct: float
    at_low: bool
    at_high: bool
    insufficient: bool = False
    trend: str = ""  # ↑ 反弹 / ↓ 下行 / → 持平


class StockScanResult(BaseModel):
    symbol: str
    name: str
    current_price: float
    scan_date: date
    periods: list[PeriodResult]
    low_resonance: int
    high_resonance: int
    is_st: bool = False
    limit_up: bool = False
    limit_down: bool = False


class ValuationMetrics(BaseModel):
    """单只股票截面市场指标 · daily_basic 衍生 · 原始指标值。

    合规 (compliance §6/§7):字段用原始指标名 · 不含评分 / 评级 / 判断词 ·
    分位 / 行业中位对照在输出层 (地基-2/3 有全市场池后) 呈现 · 数据层只承载
    防腐层出口的原始数据 (同构 K 线层存裸 OHLC · 展示层才算"位置%")。
    """

    trade_date: date
    close: float | None = None
    pe_ttm: float | None = None          # 市盈率 TTM
    pb: float | None = None              # 市净率
    ps_ttm: float | None = None          # 市销率 TTM
    dv_ttm: float | None = None          # 股息率 TTM (%)
    turnover_rate: float | None = None   # 换手率 (%)
    volume_ratio: float | None = None    # 量比
    total_mv: float | None = None        # 总市值 (万元)
    circ_mv: float | None = None         # 流通市值 (万元)
    source: str | None = None            # 数据源标注 (_source · 例 tushare_metrics)


class EnrichedResult(StockScanResult):
    """StockScanResult + 按需挂载的多维指标 (lazy · 不强制全拉)。

    继承 StockScanResult:保留位置 / 共振 / ST / 涨跌停字段 · 访问扁平
    (r.symbol / r.valuation.pe_ttm) · JSON 序列化时 scan 字段与子对象平铺 ·
    供 AI 消费友好 (地基-2 kan find --format json)。

    地基-1 只挂 valuation · fundamentals / moneyflow / sentiment 后续阶段补 ·
    字段膨胀风险靠"按需挂载 (None 默认) + 输出层只序列化已 enrich 维度"控制。
    """

    valuation: ValuationMetrics | None = None
    # 后续阶段预留 (本期不实现 · PRD §4 维度地图):
    # fundamentals: FundamentalMetrics | None = None  # fina_indicator (ROE / 增速)
    # moneyflow:    MoneyflowMetrics   | None = None  # moneyflow_dc (主力资金)
    # sentiment:    SentimentMetrics   | None = None  # limit_list_d (连板 / 炸板)

    @classmethod
    def from_scan(
        cls, scan: StockScanResult, valuation: ValuationMetrics | None = None,
    ) -> EnrichedResult:
        """把 StockScanResult 提升为 EnrichedResult + 挂 valuation (lazy 挂载入口)。

        model_dump() 拷贝 scan 全字段后重新构造 (periods 深拷 · 不共享引用) ·
        地基-2 整合时 pipeline 用此入口把 scan 结果按需 enrich 各维度。
        """
        return cls(**scan.model_dump(), valuation=valuation)


class VolumeState(BaseModel):
    """成交量异动状态 · 今日量 vs 近 window 日均量的比值。"""

    ratio: float   # 今日成交量 / 近 window 日均量
    label: str     # 明显放大 / 温和放大 / 量能平稳 / 温和萎缩 / 明显萎缩
    window: int    # 比较窗口(交易日数)


class Board(BaseModel):
    """申万行业板块 · catalog 条目。"""

    code: str    # 申万代码 · 规范化无后缀 · 如 "801080"
    name: str    # 如 "半导体"
    level: int   # 1 | 2 | 3 (申万一/二/三级)
    size: int    # 成份个数


class Theme(BaseModel):
    """题材板块 · catalog 条目。

    跟 Board 字段不重合(无 level · 有 source) · 不复用 Board · 见 design §5.1。
    """

    code: str          # THS index_code "886108" | EM concept_code "BK1629"
    name: str          # "AI应用" / "白酒概念"
    source: str        # "ths" | "em"
    size: int | None = None  # 成分股数 · catalog 接口未必提供 · 可空


# ───────────────────── 集合 meta (StockSet / scan_targets 共享) ─────────────────────


@dataclass
class BoardMeta:
    """IndustrySet / resolve_scan_targets industry 模式的附加产物。"""

    board: Board
    index_kline: pd.DataFrame          # 板块指数 K(已归一化)
    constituents: list[tuple[str, str]]  # 全成分股 (代码, 名称)
    highlight: set[str]                  # 成分股代码 ∩ 自选股代码


@dataclass
class HotMeta:
    """HotRankSet / resolve_scan_targets hot 模式的附加产物。"""

    list_name: str                # "东财人气榜" / "东财飙升榜"
    rank_map: dict[str, int]      # {代码: 热榜名次}
    highlight: set[str]           # 热榜代码 ∩ 自选股代码


@dataclass
class ThemeMeta:
    """ThemeSet / resolve_scan_targets theme 模式的附加产物 · 跟 BoardMeta 对称。"""

    theme: Theme
    index_kline: pd.DataFrame              # EM 题材指数 K(已 rename)· K 线失败时为空 DataFrame
    constituents: list[tuple[str, str]]    # 全成分股(THS 拉)
    highlight: set[str]                    # 成分股 ∩ 自选
    source_dispatch: dict[str, str] = field(
        default_factory=lambda: {
            "catalog": "ths",
            "cons": "ths",
            "kline": "em",
            "reverse": "em",
        }
    )
