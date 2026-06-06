from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

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


class CorporateActionMarker(BaseModel):
    """除权除息事件标记 · 只承载客观事件与参考价,不做解释性判断。"""

    ex_date: date                    # 除权除息日
    record_date: date | None = None  # 股权登记日
    cash_div_tax: float | None = None  # 每股税前现金分红
    stk_div: float | None = None       # 每股送转
    reference_price: float | None = None  # 按前一交易日收盘与分红送转粗算的除权除息参考价
    source: str | None = None


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
    ma_10: float | None = None        # 10 日均线 (前复权价格口径)
    ma_20: float | None = None        # 20 日均线 (前复权价格口径)
    recent_low_20: float | None = None  # 近 20 日最低价 (客观价位 · 非信号)
    pe_ttm: float | None = None       # PE TTM (scan 行内联裸值 · 无数据为 None)
    pb: float | None = None           # PB (daily_basic · scan JSON 行内联裸值)
    ps_ttm: float | None = None       # PS TTM (daily_basic · scan JSON 行内联裸值)
    dv_ttm: float | None = None       # 股息率 TTM (% · daily_basic)
    turnover_rate: float | None = None  # 换手率 (% · daily_basic)
    volume_ratio: float | None = None   # 量比 (daily_basic)
    total_mv: float | None = None       # 总市值 (万元 · daily_basic)
    circ_mv: float | None = None        # 流通市值 (万元 · daily_basic)
    valuation_trade_date: date | None = None  # 估值截面交易日
    moneyflow_net_amount: float | None = None  # 单日主力净额 (万元)
    moneyflow_buy_elg_amount: float | None = None  # 单日超大单净额 (万元)
    moneyflow_buy_lg_amount: float | None = None   # 单日大单净额 (万元)
    moneyflow_buy_md_amount: float | None = None   # 单日中单净额 (万元)
    moneyflow_buy_sm_amount: float | None = None   # 单日小单净额 (万元)
    moneyflow_inflow_days: int | None = None       # 连续主力净流入天数
    moneyflow_outflow_days: int | None = None      # 连续主力净流出天数
    moneyflow_trade_date: date | None = None       # 资金流截面交易日
    moneyflow_5d_net_amount: float | None = None  # 近 5 个交易日主力净额合计 (万元)
    moneyflow_5d_end_date: date | None = None
    ma_biases: dict[int, float] = Field(default_factory=dict)  # K 线衍生 BIAS · key=周期
    corporate_action: CorporateActionMarker | None = None


class ValuationMetrics(BaseModel):
    """单只股票截面市场指标 · daily_basic 衍生 · 原始指标值。

    合规 (compliance §6/§7):字段用原始指标名 · 不含评分 / 评级 / 判断词。
    估值裸值 (pe_ttm / pb / ps_ttm / dv_ttm) 可对外输出:filter 阈值由用户显式
    指定 (--pe 是用户主导的数据筛选 · 非工具荐股)。
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
    """估值位置对照 · 输出层合规呈现 (全市场截面层)。

    把个股估值比率 (pe_ttm / pb) 转成位置型表达 · 只承载分位 + 行业
    中位对照,不重复承载个股估值裸值:
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


class BoardPositionPeriod(BaseModel):
    """个股在所属板块内的位置对照 · 只承载客观排序/均值。"""

    period: int
    position_pct: float
    board_avg_pct: float
    rank_low_to_high: int
    sample: int


class BoardPositionContext(BaseModel):
    """kan info 板块位置对照 · 所属申万行业 + 本地缓存样本统计。"""

    industry: str
    board_code: str | None = None
    board_level: int | None = None
    constituent_count: int
    cached_sample: int
    periods: list[BoardPositionPeriod]


class FundamentalMetrics(BaseModel):
    """单只股票财务质量·成长指标 · fina_indicator 衍生 · 最新一期报告原始值 (估值/质量/资金维度)。

    合规 (compliance §6/§7):原始指标名 · 不含评分 / 判断词。ROE / 增速是单向正向
    因子 (越高越好 · 无"贵/便宜"双向误导) · 裸值可对外 (用户主导 --roe filter)。
    逐股 fina_indicator 拉取 (全市场代价高 · 只在小池按需)。
    """

    end_date: date | None = None        # 报告期 (季度末日期)
    roe: float | None = None            # 净资产收益率 (%)
    netprofit_yoy: float | None = None  # 净利润同比增速 (%)
    or_yoy: float | None = None         # 营业收入同比增速 (%)
    source: str | None = None           # 数据源标注 (例 tushare_fina)


class MoneyflowMetrics(BaseModel):
    """单只股票主力资金截面指标 · TuShare moneyflow 衍生 · 原始净额 (估值/质量/资金维度)。

    合规 (compliance §2):主力净额是客观资金事实 (同 OHLCV 安全区) · 裸值可出。
    截面 (trade_date) 维度 · 数据从 20230911 起 (早期 None · 优雅降级)。
    """

    trade_date: date | None = None       # 资金流向交易日
    net_amount: float | None = None      # 主力净额 (万元)
    buy_elg_amount: float | None = None  # 超大单净额 (万元)
    buy_lg_amount: float | None = None   # 大单净额 (万元)
    buy_md_amount: float | None = None   # 中单净额 (万元)
    buy_sm_amount: float | None = None   # 小单净额 (万元)
    inflow_days: int | None = None       # 截至 trade_date 连续主力净流入天数
    outflow_days: int | None = None      # 截至 trade_date 连续主力净流出天数
    net_amount_5d: float | None = None   # 近 5 个交易日主力净额合计 (万元)
    source: str | None = None            # 数据源标注 (例 tushare_moneyflow)


class TechnicalMetrics(BaseModel):
    """单只股票技术面因子 · stk_factor_pro 衍生 · 前复权 (_qfq) 原始指标值 (技术/情绪/筹码维度)。

    合规 (compliance §3/§7):原始指标名 (macd/kdj/rsi/ma/boll) · 不含"超买/超卖/
    金叉/死叉"等信号判断词 · 只出裸值让用户自判。filter 阈值用户显式指定
    (--rsi lt:30 同 --pe 逻辑 · 非工具信号订阅)。截面 (trade_date) 维度。

    复权:技术分析标准用前复权 (_qfq) · 对外字段去 _qfq 后缀中性命名。金叉/死叉
    不做 (需跨日对比 · 截面单日算不出 + 踩信号订阅红线 · 见 PRD 技术/情绪/筹码维度)。
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
    """单只股票情绪面 · limit_list_d 衍生 · 涨跌停/连板原始事实 (技术/情绪/筹码维度)。

    合规 (compliance §2/§3):连板天数 / 炸板次数是客观市场事实 · 不输出"妖股/
    强势"判断词 · 只出裸值。filter 用户显式指定 (--streak gte:3 = 连板 ≥ 3)。

    稀疏事件型:limit_list_d 只返回当日有涨跌停/炸板的票 · 不在榜的股票
    SentimentMetrics 为 None (语义 = "该股当日未涨跌停" · 非数据缺失) · 不含 ST 股
    (接口本身不统计 ST) · 数据从 2020 起。
    """

    trade_date: date | None = None    # 事件交易日
    limit_times: float | None = None  # 连板天数 (连续涨/跌停板数)
    open_times: float | None = None   # 炸板/开板次数 (盘中打开板的次数)
    first_time: str | None = None      # 首次封板时间 (HHMMSS 或源格式)
    last_time: str | None = None       # 最后封板时间 (HHMMSS 或源格式)
    fd_amount: float | None = None     # 封单金额 (源单位 · TuShare 原始值)
    limit: str | None = None          # 涨跌停类型 (U 涨停 / D 跌停 / Z 炸板)
    up_stat: str | None = None        # 涨停统计 (例 "3/3" = 几天几板)
    source: str | None = None         # 数据源标注 (例 tushare_limit)


class ChipMetrics(BaseModel):
    """单只股票筹码分布 · cyq_perf 衍生 · 获利盘/成本分布原始值 (技术/情绪/筹码维度)。

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
    """单只股票股东·持股结构 · stk_holdernumber + top10_floatholders 衍生 · 季度披露 (股东持股维度)。

    合规 (compliance §7 股东持股维度 守则):户数环比 / 前十大流通集中度 / 北向名义持有人占比
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


class RelativeStrengthMetrics(BaseModel):
    """个股相对强度 · 个股区间涨幅 − 对照(大盘指数 / 所属申万一级行业)区间涨幅 · 客观差值(趋势/动量扩展)。

    合规 (compliance §6/§7):相对强度是两段客观涨幅的算术差 (个股 gain − 对照 gain) ·
    裸值可出 · **不输出「真龙头 / 独立行情 / 跟风 / 强势 / 领涨」等判断词** (§3 黑名单延伸 ·
    个股跑赢板块极易被误读为"工具在荐龙头" · 工具只出差值数字 · 判断权在用户/消费方)。
    filter 用户显式指定 (--rs-index 30:gt:0 = 近 30 日跑赢大盘基准;--rs-board 30:gt:0 =
    近 30 日跑赢所属申万一级行业)。

    rs_index / rs_board 按周期存差值 (百分点) · 周期不足 / 个股行业未知 / 对照指数缺 →
    该周期不入 dict (matcher 不命中 · None 语义 · 不静默当 0)。stock_gain / index_gain /
    board_gain 存原始对照涨幅供 audit + 输出透明 (用户可见 个股涨 X、对照涨 Y、差 Z)。
    """

    industry: str | None = None       # 个股所属申万一级行业名 (board 对照口径 · None=未知)
    index_code: str | None = None     # 大盘对照指数 ts_code (例 000300.SH)
    index_name: str | None = None     # 大盘对照指数名 (例 沪深300)
    stock_gain: dict[int, float] = Field(default_factory=dict)  # {周期: 个股区间涨幅 %}
    index_gain: dict[int, float] = Field(default_factory=dict)  # {周期: 大盘指数区间涨幅 %}
    board_gain: dict[int, float] = Field(default_factory=dict)  # {周期: 所属行业指数区间涨幅 %}
    rs_index: dict[int, float] = Field(default_factory=dict)    # {周期: 个股 − 大盘 差值 (百分点)}
    rs_board: dict[int, float] = Field(default_factory=dict)    # {周期: 个股 − 行业 差值 (百分点)}
    source: str | None = None         # 数据源标注 (例 tushare_index+sw)


class EnrichedResult(StockScanResult):
    """StockScanResult + 按需挂载的多维指标 (lazy · 不强制全拉)。

    继承 StockScanResult:保留位置 / 共振 / ST / 涨跌停字段 · 访问扁平
    (r.symbol / r.valuation.pe_ttm) · JSON 序列化时 scan 字段与子对象平铺 ·
    供 AI 消费友好 (AI JSON 层 kan find --format json)。

    挂载 valuation / fundamentals / moneyflow / technical / sentiment / chip /
    shareholder。字段膨胀风险靠"按需挂载 (None 默认) + 输出层只序列化已 enrich
    维度"控制。
    """

    valuation: ValuationMetrics | None = None
    fundamentals: FundamentalMetrics | None = None  # fina_indicator (ROE / 增速 · 估值/质量/资金维度)
    moneyflow: MoneyflowMetrics | None = None        # moneyflow_dc (主力资金 · 估值/质量/资金维度)
    technical: TechnicalMetrics | None = None        # stk_factor_pro (MACD/KDJ/RSI · 技术/情绪/筹码维度)
    sentiment: SentimentMetrics | None = None        # limit_list_d (连板 / 炸板 · 技术/情绪/筹码维度)
    chip: ChipMetrics | None = None                  # cyq_perf (获利盘 · 技术/情绪/筹码维度)
    shareholder: ShareholderMetrics | None = None    # 股东户数/十大流通/北向 (逐股 · 股东持股维度)
    relative_strength: RelativeStrengthMetrics | None = None  # 相对强度 (个股 − 大盘/行业 区间涨幅差 · 趋势/动量扩展)

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
        relative_strength: RelativeStrengthMetrics | None = None,
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
            relative_strength=relative_strength,
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


# ───────────────────── 集合 meta (StockSet 子类的附加产物) ─────────────────────


@dataclass
class BoardMeta:
    """IndustrySet 的附加产物(板块指数 K + 成分股 + 自选高亮)。"""

    board: Board
    index_kline: pd.DataFrame          # 板块指数 K(已归一化)
    constituents: list[tuple[str, str]]  # 全成分股 (代码, 名称)
    highlight: set[str]                  # 成分股代码 ∩ 自选股代码


@dataclass
class HotMeta:
    """HotRankSet 的附加产物(热榜名次 map + 自选高亮)。"""

    list_name: str                # "东财人气榜" / "东财飙升榜"
    rank_map: dict[str, int]      # {代码: 热榜名次}
    highlight: set[str]           # 热榜代码 ∩ 自选股代码


@dataclass
class ThemeMeta:
    """ThemeSet 的附加产物(题材指数 K + 成分股 + 自选高亮)· 跟 BoardMeta 对称。"""

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
