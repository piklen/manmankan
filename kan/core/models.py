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
    gain_pct: float | None = None  # 近 period 日涨幅 % (K 线衍生 · 不足 period+1 根→None)


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
    up_days: int = 0  # 连阳天数 (candle 口径 · close>open 连续根数 · 当前非阳线=0)


class ValuationMetrics(BaseModel):
    """单只股票截面市场指标 · daily_basic 衍生 · 原始指标值。

    合规 (compliance §6/§7 · 整合-1 拍板更新):字段用原始指标名 · 不含评分 / 评级 /
    判断词。估值裸值 (pe_ttm / pb / ps_ttm / dv_ttm) 自整合-1 起**可对外输出** ——
    filter 阈值由用户显式指定 (--pe 是用户主导的数据筛选 · 非工具荐股) · 行业分位
    主观性强 (回看窗口 / 行业划分皆为选择) · 裸值反而客观。输出过滤见 export
    (_valuation_public_dict 不再删裸值 · 推翻"估值不给裸值"旧设计 · 见 compliance §7)。
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


class ValuationContext(BaseModel):
    """估值位置对照 · 输出层合规呈现 (地基-3)。

    把个股估值比率 (pe_ttm / pb · 易误读裸值) 转成位置型表达 · 对外只出分位 + 行业
    中位对照 · **绝不含个股估值裸值** (compliance · PRD §6 · 估值位置 = 价格位置同构延伸):
    - *_pct_rank:     历史分位 (当前值在自身近 N 年序列的百分位 · temporal)
    - *_industry_pct: 行业内分位 (当前值在申万一级同行的百分位 · cross-sectional · 50=中位)
    - *_industry_median: 申万一级同行中位 (aggregate 参照值 · 非个股裸值)

    所有字段可空 (无 token / 历史不足 / 行业样本不足 → None · 优雅降级)。
    """

    industry: str | None = None              # 申万一级行业名
    lookback_days: int | None = None         # 历史分位回看天数
    industry_sample: int | None = None       # 行业样本数 (分位/中位可信度)
    pe_pct_rank: float | None = None         # PE 历史分位 (0-100)
    pb_pct_rank: float | None = None         # PB 历史分位 (0-100)
    pe_industry_pct: float | None = None     # PE 行业内分位 (0-100)
    pb_industry_pct: float | None = None     # PB 行业内分位 (0-100)
    pe_industry_median: float | None = None  # 申万一级 PE 中位 (参照)
    pb_industry_median: float | None = None  # 申万一级 PB 中位 (参照)


class FundamentalMetrics(BaseModel):
    """单只股票财务质量·成长指标 · fina_indicator 衍生 · 最新一期报告原始值 (整合-1)。

    合规 (compliance §6/§7):原始指标名 · 不含评分 / 判断词。ROE / 增速是单向正向
    因子 (越高越好 · 无"贵/便宜"双向误导) · 裸值可对外 (用户主导 --roe filter)。
    逐股 fina_indicator 拉取 (全市场代价高 · 只在小池按需 · PRD §3.2)。
    """

    end_date: date | None = None        # 报告期 (季度末日期)
    roe: float | None = None            # 净资产收益率 (%)
    netprofit_yoy: float | None = None  # 净利润同比增速 (%)
    or_yoy: float | None = None         # 营业收入同比增速 (%)
    source: str | None = None           # 数据源标注 (例 tushare_fina)


class MoneyflowMetrics(BaseModel):
    """单只股票主力资金截面指标 · moneyflow_dc 衍生 · 原始净额 (整合-1)。

    合规 (compliance §2):主力净额是客观资金事实 (同 OHLCV 安全区) · 裸值可出。
    截面 (trade_date) 维度 · 数据从 20230911 起 (早期 None · 优雅降级)。
    """

    trade_date: date | None = None       # 资金流向交易日
    net_amount: float | None = None      # 主力净额 (东财口径 · 单位万元)
    buy_elg_amount: float | None = None  # 超大单净额 (万元)
    buy_lg_amount: float | None = None   # 大单净额 (万元)
    source: str | None = None            # 数据源标注 (例 tushare_moneyflow)


class TechnicalMetrics(BaseModel):
    """单只股票技术面因子 · stk_factor_pro 衍生 · 前复权 (_qfq) 原始指标值 (整合-2)。

    合规 (compliance §3/§7):原始指标名 (macd/kdj/rsi/ma/boll) · 不含"超买/超卖/
    金叉/死叉"等信号判断词 · 只出裸值让用户自判。filter 阈值用户显式指定
    (--rsi lt:30 同 --pe 逻辑 · 非工具信号订阅)。截面 (trade_date) 维度。

    复权:技术分析标准用前复权 (_qfq) · 对外字段去 _qfq 后缀中性命名。金叉/死叉
    不做 (需跨日对比 · 截面单日算不出 + 踩信号订阅红线 · 见 PRD 整合-2)。
    """

    trade_date: date | None = None     # 因子交易日
    close: float | None = None         # 前复权收盘价
    macd_dif: float | None = None      # MACD DIF 快线
    macd_dea: float | None = None      # MACD DEA 慢线 (信号线)
    macd: float | None = None          # MACD 柱 = (DIF - DEA) × 2
    kdj_k: float | None = None         # KDJ K 值
    kdj_d: float | None = None         # KDJ D 值
    kdj_j: float | None = None         # KDJ J 值
    rsi_6: float | None = None         # RSI 6 日
    rsi_12: float | None = None        # RSI 12 日
    rsi_24: float | None = None        # RSI 24 日
    ma_5: float | None = None          # 5 日均线
    ma_10: float | None = None         # 10 日均线
    ma_20: float | None = None         # 20 日均线
    ma_60: float | None = None         # 60 日均线
    atr: float | None = None           # ATR 波动率 (前复权 · 绝对值 · 趋势/动量扩展)
    boll_upper: float | None = None    # BOLL 上轨
    boll_mid: float | None = None      # BOLL 中轨
    boll_lower: float | None = None    # BOLL 下轨
    source: str | None = None          # 数据源标注 (例 tushare_factor)

    def ma_bias(self, period: int) -> float | None:
        """乖离率 = (close − ma_period) / ma_period × 100 · 客观技术指标 (BIAS)。

        period ∈ {5,10,20,60} (对应已拉均线) · close / ma 缺失或 ma=0 → None。
        裸值 · 不判断「多头排列 / 趋势」(compliance §7 · 判断权在用户/消费方)。
        """
        ma = {5: self.ma_5, 10: self.ma_10, 20: self.ma_20, 60: self.ma_60}.get(period)
        if self.close is None or ma is None or ma == 0:
            return None
        return (self.close - ma) / ma * 100

    def atr_pct(self) -> float | None:
        """ATR 波动率百分比 = atr / close × 100 · 跨标的可比 · 缺失或 close=0 → None。"""
        if self.atr is None or self.close is None or self.close == 0:
            return None
        return self.atr / self.close * 100


class SentimentMetrics(BaseModel):
    """单只股票情绪面 · limit_list_d 衍生 · 涨跌停/连板原始事实 (整合-2)。

    合规 (compliance §2/§3):连板天数 / 炸板次数是客观市场事实 · 不输出"妖股/
    强势"判断词 · 只出裸值。filter 用户显式指定 (--streak gte:3 = 连板 ≥ 3)。

    稀疏事件型:limit_list_d 只返回当日有涨跌停/炸板的票 · 不在榜的股票
    SentimentMetrics 为 None (语义 = "该股当日未涨跌停" · 非数据缺失) · 不含 ST 股
    (接口本身不统计 ST) · 数据从 2020 起。
    """

    trade_date: date | None = None    # 事件交易日
    limit_times: float | None = None  # 连板天数 (连续涨/跌停板数)
    open_times: float | None = None   # 炸板/开板次数 (盘中打开板的次数)
    limit: str | None = None          # 涨跌停类型 (U 涨停 / D 跌停 / Z 炸板)
    up_stat: str | None = None        # 涨停统计 (例 "3/3" = 几天几板)
    source: str | None = None         # 数据源标注 (例 tushare_limit)


class ChipMetrics(BaseModel):
    """单只股票筹码分布 · cyq_perf 衍生 · 获利盘/成本分布原始值 (整合-2)。

    合规 (compliance §2/§7):获利盘比例 / 成本分位是客观计算值 · 不输出判断词 ·
    只出裸值。filter 用户显式指定 (--winner gte:50 = 获利盘 ≥ 50%)。
    截面 (trade_date) 维度 · 数据从 2018 起 (早期 None · 优雅降级)。
    """

    trade_date: date | None = None    # 筹码交易日
    winner_rate: float | None = None  # 获利盘比例 (%)
    cost_5pct: float | None = None    # 5 分位成本 (低位筹码)
    cost_50pct: float | None = None   # 50 分位成本 (中位筹码)
    cost_95pct: float | None = None   # 95 分位成本 (高位筹码)
    weight_avg: float | None = None   # 加权平均成本
    source: str | None = None         # 数据源标注 (例 tushare_cyq)


class ShareholderMetrics(BaseModel):
    """单只股票股东·持股结构 · stk_holdernumber + top10_floatholders 衍生 · 季度披露 (整合-3)。

    合规 (compliance §7 整合-3 守则):户数环比 / 前十大流通集中度 / 北向名义持有人占比
    均为已披露客观事实的算术衍生 · 裸值可出 · 不输出"主力建仓 / 洗盘 / 控盘 / 高度控盘"
    等判断词 (§3 信号化黑名单延伸)。filter 用户显式指定 (--holders / --top10 / --north)。

    季度披露 (非日频)· None = 该期无披露 / 未进前十 (非故障 · 仿 SentimentMetrics None 语义)。
    北向用"香港中央结算有限公司"季度名义持有人占流通比作代理 (hk_hold 日频 2024-08 断供 ·
    tushare 实测核实) · 未进前十大流通 → north_hold_ratio None。逐股拉取 (--all 不支持)。
    """

    holder_end_date: date | None = None     # 户数最近报告期 (季度披露)
    holder_num: float | None = None         # 最近期股东户数
    holder_chg_pct: float | None = None     # 户数环比 % (相邻两次披露 · 负=户数减少)
    top10_end_date: date | None = None      # 十大流通最近报告期
    top10_float_ratio: float | None = None  # 前十大流通股东持股合计占流通比 %
    north_hold_ratio: float | None = None   # 香港中央结算占流通比 % (北向季度代理)
    source: str | None = None               # 数据源标注 (例 tushare_shareholder)


class EnrichedResult(StockScanResult):
    """StockScanResult + 按需挂载的多维指标 (lazy · 不强制全拉)。

    继承 StockScanResult:保留位置 / 共振 / ST / 涨跌停字段 · 访问扁平
    (r.symbol / r.valuation.pe_ttm) · JSON 序列化时 scan 字段与子对象平铺 ·
    供 AI 消费友好 (地基-2 kan find --format json)。

    整合-1 挂 valuation / fundamentals / moneyflow · sentiment 后续阶段补 ·
    字段膨胀风险靠"按需挂载 (None 默认) + 输出层只序列化已 enrich 维度"控制。
    """

    valuation: ValuationMetrics | None = None
    fundamentals: FundamentalMetrics | None = None  # fina_indicator (ROE / 增速 · 整合-1)
    moneyflow: MoneyflowMetrics | None = None        # moneyflow_dc (主力资金 · 整合-1)
    technical: TechnicalMetrics | None = None        # stk_factor_pro (MACD/KDJ/RSI · 整合-2)
    sentiment: SentimentMetrics | None = None        # limit_list_d (连板 / 炸板 · 整合-2)
    chip: ChipMetrics | None = None                  # cyq_perf (获利盘 · 整合-2)
    shareholder: ShareholderMetrics | None = None    # 股东户数/十大流通/北向 (逐股 · 整合-3)

    @classmethod
    def from_scan(
        cls,
        scan: StockScanResult,
        valuation: ValuationMetrics | None = None,
        fundamentals: FundamentalMetrics | None = None,
        moneyflow: MoneyflowMetrics | None = None,
        technical: TechnicalMetrics | None = None,
        sentiment: SentimentMetrics | None = None,
        chip: ChipMetrics | None = None,
        shareholder: ShareholderMetrics | None = None,
    ) -> EnrichedResult:
        """把 StockScanResult 提升为 EnrichedResult + 按需挂多维指标 (lazy 挂载入口)。

        model_dump() 拷贝 scan 全字段后重新构造 (periods 深拷 · 不共享引用) · 各维度
        (valuation / fundamentals / moneyflow / technical / sentiment / chip) 按需传入 ·
        None 表该维度未 enrich。
        """
        return cls(
            **scan.model_dump(),
            valuation=valuation,
            fundamentals=fundamentals,
            moneyflow=moneyflow,
            technical=technical,
            sentiment=sentiment,
            chip=chip,
            shareholder=shareholder,
        )


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
