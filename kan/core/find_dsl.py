"""DSL parser for `kan find`.

按用户输入条件 · 解析成结构化 Filter 对象。

支持 filter:
- --pos PERIOD:OP:VAL    位置百分位 (例 180:lt:5 = 180 日位置 < 5%)
- --resonance LEVEL:OP:VAL  共振状态 (例 low:gte:3 = 低点共振 ≥ 3 周期)
- --exclude-st           排 ST/*ST

Future (candidates):
- --vol-ratio OP:VAL     量比 filter (需要 calc_volume_state)
- --streak up|down:OP:VAL  连涨连跌 (需要 calc_trend)
- --exclude-newshare DAYS  新股排除 (需要上市日期)

合规边界(manmankan/docs/compliance.md §7):
- 用户显式指定 filter · 不内置 preset
- 输出 "符合条件的股票" · 不"推荐 / 评级"
- 严格 grammar 校验 + 错误信息引导用户
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Self

ALLOWED_OPS = ("lt", "lte", "gt", "gte", "eq", "ne")
MIN_PERIOD = 2
MAX_PERIOD = 360
ALLOWED_PERIODS = tuple(range(MIN_PERIOD, MAX_PERIOD + 1))
RESONANCE_LEVELS = ("low", "high")


class FilterParseError(ValueError):
    """DSL parse error · raised when user input violates grammar."""


@dataclass(frozen=True)
class ResonanceFilter:
    """共振 filter · 例 LEVEL=low OP=gte VALUE=3 = 低点共振 ≥ 3 周期."""

    level: Literal["low", "high"]
    op: str
    value: int

    @classmethod
    def parse(cls, raw: str) -> ResonanceFilter:
        """Parse 'LEVEL:OP:VAL' string · 例 'low:gte:3'."""
        parts = raw.split(":")
        if len(parts) != 3:
            raise FilterParseError(
                f"--resonance 格式错误 '{raw}' · 需要 LEVEL:OP:VAL 例 low:gte:3"
            )
        level = parts[0].lower()
        if level not in RESONANCE_LEVELS:
            raise FilterParseError(
                f"--resonance 级别 '{level}' 不支持 · 仅 low/high · 例: --resonance low:gte:3"
            )
        op = parts[1].lower()
        if op not in ALLOWED_OPS:
            raise FilterParseError(
                f"--resonance 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · 例: --resonance low:gte:3"
            )
        try:
            value = int(parts[2])
        except ValueError as e:
            raise FilterParseError(
                f"--resonance 数值非整数 '{parts[2]}' · 例: --resonance low:gte:3"
            ) from e
        if not 0 <= value <= 10:
            raise FilterParseError(
                f"--resonance 数值 {value} 越界 · 需 [0, 10] · 例: --resonance low:gte:3"
            )
        return cls(level=level, op=op, value=value)  # type: ignore[arg-type]


def _parse_op_val(raw: str, *, flag: str, example: str) -> tuple[str, float]:
    """Parse 'OP:VAL' string (估值/质量/资金维度 · pe/roe/moneyflow 共用)· 例 'lt:20'.

    不卡数值范围 (PE 可负 / ROE 可负 / 资金净额量级跨度大 · 硬卡范围误伤合理输入)·
    仅校验 op 合法 + 数值有限 (排 NaN / inf)。
    """
    import math

    parts = raw.split(":")
    if len(parts) != 2:
        raise FilterParseError(f"{flag} 格式错误 '{raw}' · 需要 OP:VAL 例 {example}")
    op = parts[0].lower()
    if op not in ALLOWED_OPS:
        raise FilterParseError(
            f"{flag} 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · 例: {example}"
        )
    try:
        value = float(parts[1])
    except ValueError as e:
        raise FilterParseError(f"{flag} 数值非数字 '{parts[1]}' · 例: {example}") from e
    if not math.isfinite(value):
        raise FilterParseError(f"{flag} 数值 '{parts[1]}' 非有限数 · 例: {example}")
    return op, value


@dataclass(frozen=True)
class ScalarFilter:
    """通用 `OP:VAL` 裸值 filter.

    子类只声明 `flag` / `example` / docstring。这样新增同构 filter 时不再复制
    parse 逻辑，filter 语义仍由 registry + matcher 决定。
    """

    flag: ClassVar[str]
    example: ClassVar[str]
    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> Self:
        op, value = _parse_op_val(raw, flag=cls.flag, example=cls.example)
        return cls(op=op, value=value)


@dataclass(frozen=True)
class PeriodScalarFilter:
    """通用 `PERIOD:OP:VAL` filter.

    用于位置、涨幅、均线乖离率这类带周期参数的裸值筛选。`value_range`
    只在确有硬边界的 filter 上启用，例如位置百分位 [0, 100]。
    """

    flag: ClassVar[str]
    example: ClassVar[str]
    allowed_periods: ClassVar[tuple[int, ...]]
    value_range: ClassVar[tuple[float, float] | None] = None
    period: int
    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> Self:
        parts = raw.split(":")
        if len(parts) != 3:
            raise FilterParseError(
                f"{cls.flag} 格式错误 '{raw}' · 需要 PERIOD:OP:VAL 例 {cls.example}"
            )
        try:
            period = int(parts[0])
        except ValueError as e:
            raise FilterParseError(
                f"{cls.flag} 周期非整数 '{parts[0]}' · 例: {cls.flag} {cls.example}"
            ) from e
        min_period = min(cls.allowed_periods)
        max_period = max(cls.allowed_periods)
        if not min_period <= period <= max_period:
            closest = min_period if period < min_period else max_period
            raise FilterParseError(
                f"{cls.flag} 周期 {period} 不支持 · 范围 {min_period}-{max_period} · "
                f"最接近的是 {closest} · "
                f"例: {cls.flag} {cls.example}"
            )
        op = parts[1].lower()
        if op not in ALLOWED_OPS:
            raise FilterParseError(
                f"{cls.flag} 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · "
                f"例: {cls.flag} {cls.example}"
            )
        try:
            value = float(parts[2])
        except ValueError as e:
            raise FilterParseError(
                f"{cls.flag} 数值非数字 '{parts[2]}' · 例: {cls.flag} {cls.example}"
            ) from e
        if cls.value_range is not None:
            low, high = cls.value_range
            if not low <= value <= high:
                raise FilterParseError(
                    f"{cls.flag} 数值 {value} 越界 · 需 [{low:g}, {high:g}] · "
                    f"例: {cls.flag} {cls.example}"
                )
        return cls(period=period, op=op, value=value)


class PosFilter(PeriodScalarFilter):
    """位置百分位 filter · 例 PERIOD=180 OP=lt VALUE=5.0 = 180 日位置 < 5%."""

    flag = "--pos"
    example = "180:lt:5"
    allowed_periods = ALLOWED_PERIODS
    value_range = (0.0, 100.0)


class PeFilter(ScalarFilter):
    """市盈率 filter · 例 OP=lt VALUE=20 = PE TTM < 20 (裸值筛 · 估值/质量/资金维度).

    裸 PE 阈值由用户显式指定 · 不做行业分位。读 valuation.pe_ttm (None → 不命中)。
    """

    flag = "--pe"
    example = "lt:20"


class RoeFilter(ScalarFilter):
    """净资产收益率 filter · 例 OP=gte VALUE=15 = ROE ≥ 15% (裸值筛 · 估值/质量/资金维度)."""

    flag = "--roe"
    example = "gte:15"


class MoneyflowFilter(ScalarFilter):
    """主力资金 filter · 例 OP=gt VALUE=0 = 近 5 日合计优先、缺失回落单日净额.

    读 moneyflow.net_amount_5d 优先,缺失时读 moneyflow.net_amount (单位万元 · None → 不命中)。
    """

    flag = "--moneyflow"
    example = "gt:0"


class MoneyflowDailyFilter(ScalarFilter):
    """单日主力净额 filter · 例 OP=gt VALUE=0 = 当日主力净额 > 0 (单位万元)."""

    flag = "--moneyflow-daily"
    example = "gt:0"


class MoneyflowDaysFilter(ScalarFilter):
    """连续主力净流入天数 filter · 例 OP=gte VALUE=3 = 连续净流入 ≥ 3 天."""

    flag = "--moneyflow-days"
    example = "gte:3"


class PbFilter(ScalarFilter):
    """市净率 filter · 例 OP=lt VALUE=3 = PB < 3 (裸值筛 · 估值/质量/资金维度).

    读 valuation.pb (None → 不命中)· 用户主导阈值 · 不做行业分位 / 高低估判断。
    """

    flag = "--pb"
    example = "lt:3"


class DvFilter(ScalarFilter):
    """股息率 TTM filter · 例 OP=gte VALUE=3 = 近 12 个月股息率 ≥ 3%。

    读 valuation.dv_ttm (% · None → 不命中)；仅比较用户指定的客观阈值。
    """

    flag = "--dv"
    example = "gte:3"


class TurnoverFilter(ScalarFilter):
    """换手率 filter · 例 OP=gt VALUE=5 = 换手 > 5% (裸值筛 · 估值/质量/资金维度).

    读 valuation.turnover_rate (% · None → 不命中)· 客观成交活跃度 · 不输出"活跃/对倒"判断。
    """

    flag = "--turnover"
    example = "gt:5"


class MarketCapFilter(ScalarFilter):
    """总市值 filter · 例 OP=gt VALUE=100 = 总市值 > 100 亿 (裸值筛 · 估值/质量/资金维度).

    单位: 亿元 (matcher 内把 valuation.total_mv 万元 ÷ 1e4 换算)· None → 不命中 ·
    客观规模事实 · 不输出"大/小盘股"标签判断。
    """

    flag = "--market-cap"
    example = "gt:100"


class VolumeRatioFilter(ScalarFilter):
    """量比 filter · 例 OP=gt VALUE=1.5 = 量比 > 1.5 (裸值筛 · 估值/质量/资金维度).

    读 valuation.volume_ratio (tushare 口径 ~今日量/5日均量倍数 · None → 不命中)·
    客观放缩量 · 不输出"放量突破/缩量"等趋势判断。
    """

    flag = "--volume-ratio"
    example = "gt:1.5"


# ─── 技术/情绪/筹码维度 新增 filter (技术/情绪/筹码 · OP:VAL 裸值阈值 · 全截面) ───
# 合规:全部用户主导阈值 (同 --pe) · 只筛裸值 · 不内置金叉/超买等信号 preset。

class RsiFilter(ScalarFilter):
    """RSI (6 日) filter · 例 OP=lt VALUE=30 = RSI < 30 (裸值筛 · 技术/情绪/筹码维度).

    读 technical.rsi_6 (前复权 · None → 不命中)· 用户主导阈值 · 不输出"超买/超卖"判断。
    """

    flag = "--rsi"
    example = "lt:30"


class MacdDifFilter(ScalarFilter):
    """MACD DIF 快线 filter · 例 OP=gt VALUE=0 = DIF > 0 (裸值筛 · 技术/情绪/筹码维度).

    读 technical.macd_dif (前复权 · None → 不命中)· 不做金叉/死叉 (跨日 + 信号订阅红线)。
    """

    flag = "--macd-dif"
    example = "gt:0"


class MacdFilter(ScalarFilter):
    """MACD 柱 filter · 例 OP=gt VALUE=0 = 柱 > 0 (当前 DIF 在 DEA 上方 · 技术/情绪/筹码维度).

    读 technical.macd (= (DIF-DEA)×2 · None → 不命中)· 柱正负 = 当日多空状态 ·
    非"金叉"(金叉是状态切换瞬间 · 需跨日对比 · 截面单日算不出)。
    """

    flag = "--macd"
    example = "gt:0"


class KdjJFilter(ScalarFilter):
    """KDJ J 值 filter · 例 OP=lt VALUE=20 = J < 20 (裸值筛 · 技术/情绪/筹码维度).

    读 technical.kdj_j (前复权 · None → 不命中)· 用户主导阈值 · 不输出超买超卖判断。
    """

    flag = "--kdj-j"
    example = "lt:20"


class StreakFilter(ScalarFilter):
    """连板天数 filter · 例 OP=gte VALUE=3 = 连板 ≥ 3 (裸值筛 · 技术/情绪/筹码维度).

    读 sentiment.limit_times (None → 不命中 · 即该股当日未涨跌停)· 客观事实 ·
    不输出"妖股/强势"判断词。
    """

    flag = "--streak"
    example = "gte:3"


class WinnerFilter(ScalarFilter):
    """获利盘 filter · 例 OP=gte VALUE=50 = 获利盘 ≥ 50% (裸值筛 · 技术/情绪/筹码维度).

    读 chip.winner_rate (% · None → 不命中)· 客观计算值 · 不输出判断词。
    """

    flag = "--winner"
    example = "gte:50"


# ─── 股东持股维度 新增 filter (股东·持股结构 · OP:VAL 裸值阈值 · 逐股 · --all 不支持) ───
# 合规:用户主导阈值 · 只筛已披露客观事实衍生 · 不输出主力建仓/洗盘/控盘等判断词。

class HoldersFilter(ScalarFilter):
    """股东户数环比 filter · 例 OP=lt VALUE=0 = 户数环比减少 (裸值筛 · 股东持股维度).

    读 shareholder.holder_chg_pct (% · None → 不命中)· 相邻两次披露环比 · 季度级 ·
    负=户数减少 · 客观事实衍生 · 不输出"主力建仓/控盘"判断词。
    """

    flag = "--holders"
    example = "lt:0"


class Top10Filter(ScalarFilter):
    """前十大流通集中度 filter · 例 OP=gte VALUE=50 = 集中度 ≥ 50% (裸值筛 · 股东持股维度).

    读 shareholder.top10_float_ratio (% · None → 不命中)· 前十大流通股东持股合计占
    流通比 · 季度级 · 客观披露事实 · 不输出"高度控盘"判断词。
    """

    flag = "--top10"
    example = "gte:50"


class NorthFilter(ScalarFilter):
    """北向持股 filter · 例 OP=gte VALUE=3 = 北向 ≥ 3% (裸值筛 · 股东持股维度).

    读 shareholder.north_hold_ratio (% · None → 不命中 / 未进前十)· "香港中央结算"
    季度名义持有人占流通比代理 (hk_hold 日频 2024-08 断供 · 降级)· 客观披露事实。
    """

    flag = "--north"
    example = "gte:3"


# ─── 趋势/动量扩展 filter (客观裸值 · 截面 ma_bias/atr_pct 全市场 + K 线衍生 gain/up_days) ───
# 合规:乖离率/波动率/涨幅/连阳全部客观裸值 · 阈值用户主导 · 不判「多头排列/强势/加速末端」。

ALLOWED_MA = ALLOWED_PERIODS
"""--ma-bias 支持 2-360 任意整数周期,由本地 K 线计算。"""


class MaBiasFilter(PeriodScalarFilter):
    """均线乖离率 filter · 例 PERIOD=20 OP=gt VALUE=0 = 收盘距 20 日线 > 0% (站上).

    乖离率 = (close − ma_N) / ma_N × 100 · 读本地 K 线/全市场 K 线快照纯算 ·
    PERIOD 支持 2-360 · 客观 BIAS · 不判「多头排列/趋势」。
    """

    flag = "--ma-bias"
    example = "20:gt:0"
    allowed_periods = ALLOWED_MA


class GainFilter(PeriodScalarFilter):
    """近 N 日涨幅 filter · 例 PERIOD=30 OP=gt VALUE=20 = 近 30 日涨幅 > 20%.

    读 StockScanResult.periods[N].gain_pct (K 线衍生 · 需 K 线池 · --all 不支持)·
    客观涨幅 · 双关动量/涨速 (工具不判机会还是末端)· PERIOD 支持 2-360。
    """

    flag = "--gain"
    example = "30:gt:20"
    allowed_periods = ALLOWED_PERIODS


class AtrPctFilter(ScalarFilter):
    """ATR 波动率百分比 filter · 例 OP=lt VALUE=5 = ATR/close < 5% (波动率裸值 · 风险数据).

    读 technical.atr_pct() = atr / close × 100 (固定周期 · stk_factor_pro 截面)·
    全市场 --all 支持 · 客观波动率 · 不判「高波动危险/低波动安全」。
    """

    flag = "--atr-pct"
    example = "lt:5"


class UpDaysFilter(ScalarFilter):
    """连阳天数 filter · 例 OP=gte VALUE=3 = 连续 ≥ 3 根阳线 (涨速/加速裸值).

    读 StockScanResult.up_days (candle 口径 close>open · K 线衍生 · --all 走预计算快照)·
    客观连阳计数 · 不判「强势/妖股」· 区别于 --streak (连板天数 · 涨跌停口径)。
    """

    flag = "--up-days"
    example = "gte:3"


# ─── 相对强度 filter (个股 区间涨幅 − 对照 区间涨幅 · 客观差值 · 趋势/动量扩展) ───
# 合规:相对强度 = 两段客观涨幅算术差 · 阈值用户主导 · 不判「真龙头/独立行情/跟风/强势」。

class RsIndexFilter(PeriodScalarFilter):
    """个股相对大盘强度 filter · 例 PERIOD=30 OP=gt VALUE=0 = 近 30 日 个股涨幅 − 大盘涨幅 > 0 (跑赢大盘).

    读 relative_strength.rs_index[N] = 个股 N 日涨幅 − 大盘指数 N 日涨幅 (默认沪深300 ·
    可 --rs-index-code 改对照指数)· 客观涨幅差 (百分点)· 工具不判「独立行情/跟风/龙头」·
    PERIOD 支持 2-360 · 需 K 线池算个股 gain + 指数对照。差值可正可负 · 不设 value_range。
    """

    flag = "--rs-index"
    example = "30:gt:0"
    allowed_periods = ALLOWED_PERIODS


class RsBoardFilter(PeriodScalarFilter):
    """个股相对所属申万一级行业强度 filter · 例 PERIOD=30 OP=gt VALUE=0 = 近 30 日 个股涨幅 − 行业涨幅 > 0 (跑赢板块).

    读 relative_strength.rs_board[N] = 个股 N 日涨幅 − 所属申万一级行业指数 N 日涨幅 ·
    客观涨幅差 (百分点)· 工具不判「真龙头/跟风/领涨」· PERIOD 支持 2-360 ·
    需 K 线池算个股 gain + 申万行业映射 + 行业指数对照。差值可正可负 · 不设 value_range。
    """

    flag = "--rs-board"
    example = "30:gt:0"
    allowed_periods = ALLOWED_PERIODS


@dataclass(frozen=True)
class ConditionSet:
    """DSL 解析后的完整 filter 集合 · 多 filter 间 AND 语义.

    K 线类 (位置/共振):pos_filters / resonance_filters · 走 scan 衍生字段。
    截面类 (估值/资金 · 估值/质量/资金维度):pe_filters / moneyflow_filters · 走 enrich 子对象。
    财务类 (估值/质量/资金维度):roe_filters · 走 fundamentals (逐股 · 全市场 --all 不支持)。
    技术/情绪/筹码类 (技术/情绪/筹码维度 · 全截面):rsi/macd_dif/macd/kdj_j/streak/winner ·
      走 enrich 子对象 (technical/sentiment/chip) · K 线池 + --all 两路都支持。
    股东类 (股东持股维度):holders/top10/north · 走 shareholder (逐股 · --all 不支持 · 同 roe)。
    exclude_st:quiet filter (不记 triggered · 直接 drop)。
    """

    pos_filters: tuple[PosFilter, ...] = ()
    resonance_filters: tuple[ResonanceFilter, ...] = ()
    pe_filters: tuple[PeFilter, ...] = ()
    pb_filters: tuple[PbFilter, ...] = ()
    dv_filters: tuple[DvFilter, ...] = ()
    turnover_filters: tuple[TurnoverFilter, ...] = ()
    market_cap_filters: tuple[MarketCapFilter, ...] = ()
    volume_ratio_filters: tuple[VolumeRatioFilter, ...] = ()
    roe_filters: tuple[RoeFilter, ...] = ()
    moneyflow_filters: tuple[MoneyflowFilter, ...] = ()
    moneyflow_daily_filters: tuple[MoneyflowDailyFilter, ...] = ()
    moneyflow_days_filters: tuple[MoneyflowDaysFilter, ...] = ()
    rsi_filters: tuple[RsiFilter, ...] = ()
    macd_dif_filters: tuple[MacdDifFilter, ...] = ()
    macd_filters: tuple[MacdFilter, ...] = ()
    kdj_j_filters: tuple[KdjJFilter, ...] = ()
    streak_filters: tuple[StreakFilter, ...] = ()
    winner_filters: tuple[WinnerFilter, ...] = ()
    holders_filters: tuple[HoldersFilter, ...] = ()
    top10_filters: tuple[Top10Filter, ...] = ()
    north_filters: tuple[NorthFilter, ...] = ()
    ma_bias_filters: tuple[MaBiasFilter, ...] = ()
    gain_filters: tuple[GainFilter, ...] = ()
    atr_pct_filters: tuple[AtrPctFilter, ...] = ()
    up_days_filters: tuple[UpDaysFilter, ...] = ()
    rs_index_filters: tuple[RsIndexFilter, ...] = ()
    rs_board_filters: tuple[RsBoardFilter, ...] = ()
    exclude_st: bool = False
    match_any: bool = False

    @classmethod
    def from_flags(
        cls,
        *,
        pos: list[str] | None = None,
        resonance: list[str] | None = None,
        pe: list[str] | None = None,
        pb: list[str] | None = None,
        dv: list[str] | None = None,
        turnover: list[str] | None = None,
        market_cap: list[str] | None = None,
        volume_ratio: list[str] | None = None,
        roe: list[str] | None = None,
        moneyflow: list[str] | None = None,
        moneyflow_daily: list[str] | None = None,
        moneyflow_days: list[str] | None = None,
        rsi: list[str] | None = None,
        macd_dif: list[str] | None = None,
        macd: list[str] | None = None,
        kdj_j: list[str] | None = None,
        streak: list[str] | None = None,
        winner: list[str] | None = None,
        holders: list[str] | None = None,
        top10: list[str] | None = None,
        north: list[str] | None = None,
        ma_bias: list[str] | None = None,
        gain: list[str] | None = None,
        atr_pct: list[str] | None = None,
        up_days: list[str] | None = None,
        rs_index: list[str] | None = None,
        rs_board: list[str] | None = None,
        exclude_st: bool = False,
        match_any: bool = False,
    ) -> ConditionSet:
        """Build ConditionSet from CLI flag strings (raw user input)."""
        return cls(
            pos_filters=tuple(PosFilter.parse(p) for p in (pos or [])),
            resonance_filters=tuple(ResonanceFilter.parse(r) for r in (resonance or [])),
            pe_filters=tuple(PeFilter.parse(p) for p in (pe or [])),
            pb_filters=tuple(PbFilter.parse(p) for p in (pb or [])),
            dv_filters=tuple(DvFilter.parse(d) for d in (dv or [])),
            turnover_filters=tuple(TurnoverFilter.parse(t) for t in (turnover or [])),
            market_cap_filters=tuple(
                MarketCapFilter.parse(m) for m in (market_cap or [])
            ),
            volume_ratio_filters=tuple(
                VolumeRatioFilter.parse(v) for v in (volume_ratio or [])
            ),
            roe_filters=tuple(RoeFilter.parse(r) for r in (roe or [])),
            moneyflow_filters=tuple(MoneyflowFilter.parse(m) for m in (moneyflow or [])),
            moneyflow_daily_filters=tuple(
                MoneyflowDailyFilter.parse(m) for m in (moneyflow_daily or [])
            ),
            moneyflow_days_filters=tuple(
                MoneyflowDaysFilter.parse(m) for m in (moneyflow_days or [])
            ),
            rsi_filters=tuple(RsiFilter.parse(x) for x in (rsi or [])),
            macd_dif_filters=tuple(MacdDifFilter.parse(x) for x in (macd_dif or [])),
            macd_filters=tuple(MacdFilter.parse(x) for x in (macd or [])),
            kdj_j_filters=tuple(KdjJFilter.parse(x) for x in (kdj_j or [])),
            streak_filters=tuple(StreakFilter.parse(x) for x in (streak or [])),
            winner_filters=tuple(WinnerFilter.parse(x) for x in (winner or [])),
            holders_filters=tuple(HoldersFilter.parse(x) for x in (holders or [])),
            top10_filters=tuple(Top10Filter.parse(x) for x in (top10 or [])),
            north_filters=tuple(NorthFilter.parse(x) for x in (north or [])),
            ma_bias_filters=tuple(MaBiasFilter.parse(x) for x in (ma_bias or [])),
            gain_filters=tuple(GainFilter.parse(x) for x in (gain or [])),
            atr_pct_filters=tuple(AtrPctFilter.parse(x) for x in (atr_pct or [])),
            up_days_filters=tuple(UpDaysFilter.parse(x) for x in (up_days or [])),
            rs_index_filters=tuple(RsIndexFilter.parse(x) for x in (rs_index or [])),
            rs_board_filters=tuple(RsBoardFilter.parse(x) for x in (rs_board or [])),
            exclude_st=exclude_st,
            match_any=match_any,
        )

    def is_empty(self) -> bool:
        return not (
            self.pos_filters
            or self.resonance_filters
            or self.pe_filters
            or self.pb_filters
            or self.dv_filters
            or self.turnover_filters
            or self.market_cap_filters
            or self.volume_ratio_filters
            or self.roe_filters
            or self.moneyflow_filters
            or self.moneyflow_daily_filters
            or self.moneyflow_days_filters
            or self.rsi_filters
            or self.macd_dif_filters
            or self.macd_filters
            or self.kdj_j_filters
            or self.streak_filters
            or self.winner_filters
            or self.holders_filters
            or self.top10_filters
            or self.north_filters
            or self.ma_bias_filters
            or self.gain_filters
            or self.atr_pct_filters
            or self.up_days_filters
            or self.rs_index_filters
            or self.rs_board_filters
            or self.exclude_st
        )

    def has_kline_filters(self) -> bool:
        """K 线衍生 filter (位置/共振/涨幅/连阳/相对强度) · --all 走预计算快照。

        相对强度 (rs_index/rs_board) 的个股侧也吃 K 线 gain · 计入 · 确保 --all 快照
        与 scan periods 覆盖对应周期 (对照数据另由 attach_relative_strength 挂载)。
        """
        return bool(
            self.pos_filters
            or self.resonance_filters
            or self.ma_bias_filters
            or self.gain_filters
            or self.up_days_filters
            or self.rs_index_filters
            or self.rs_board_filters
        )

    def has_cross_section_filters(self) -> bool:
        """截面类 filter (估值/资金/技术/情绪/筹码) · K 线池 + --all 两路都支持。"""
        return bool(
            self.pe_filters
            or self.pb_filters
            or self.dv_filters
            or self.turnover_filters
            or self.market_cap_filters
            or self.volume_ratio_filters
            or self.moneyflow_filters
            or self.moneyflow_daily_filters
            or self.moneyflow_days_filters
            or self.needs_technical()
            or self.needs_sentiment()
            or self.needs_chip()
        )

    def needs_fundamentals(self) -> bool:
        """是否需挂 fundamentals (--roe · 逐股 · 全市场 --all 不支持)。"""
        return bool(self.roe_filters)

    def needs_moneyflow(self) -> bool:
        """是否需挂 moneyflow (--moneyflow/--moneyflow-daily/--moneyflow-days · 截面)。"""
        return bool(
            self.moneyflow_filters
            or self.moneyflow_daily_filters
            or self.moneyflow_days_filters
        )

    def needs_technical(self) -> bool:
        """是否需挂 technical (--rsi/--macd-dif/--macd/--kdj-j/--atr-pct · 截面)。"""
        return bool(
            self.rsi_filters
            or self.macd_dif_filters
            or self.macd_filters
            or self.kdj_j_filters
            or self.atr_pct_filters
        )

    def needs_sentiment(self) -> bool:
        """是否需挂 sentiment (--streak · 截面稀疏 · 技术/情绪/筹码维度)。"""
        return bool(self.streak_filters)

    def needs_chip(self) -> bool:
        """是否需挂 chip (--winner · 截面 · 技术/情绪/筹码维度)。"""
        return bool(self.winner_filters)

    def needs_shareholder(self) -> bool:
        """是否需挂 shareholder (--holders/--top10/--north · 逐股 · 全市场 --all 不支持)。"""
        return bool(
            self.holders_filters
            or self.top10_filters
            or self.north_filters
        )

    def needs_relative_strength(self) -> bool:
        """是否需挂 relative_strength (--rs-index/--rs-board · 个股 K 线 + 指数/行业对照)。"""
        return bool(self.rs_index_filters or self.rs_board_filters)

    def rs_index_periods(self) -> set[int]:
        """--rs-index 请求的周期集合 (大盘对照只算这些 period · 省对照取数)。"""
        return {f.period for f in self.rs_index_filters}

    def rs_board_periods(self) -> set[int]:
        """--rs-board 请求的周期集合 (行业对照只算这些 period · 省对照取数)。"""
        return {f.period for f in self.rs_board_filters}

    def relative_strength_periods(self) -> set[int]:
        """RS 需要的全部周期 (个股 gain 必须覆盖的并集 · 给 kline period 收集)。"""
        return self.rs_index_periods() | self.rs_board_periods()


_OP_FUNCS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def apply_op(op: str, lhs: float, rhs: float) -> bool:
    """Apply comparison op · case-insensitive · raises if unknown."""
    if op not in _OP_FUNCS:
        raise ValueError(f"unsupported op '{op}'")
    return _OP_FUNCS[op](lhs, rhs)


__all__ = [
    "ALLOWED_MA",
    "ALLOWED_OPS",
    "ALLOWED_PERIODS",
    "MAX_PERIOD",
    "MIN_PERIOD",
    "RESONANCE_LEVELS",
    "AtrPctFilter",
    "ConditionSet",
    "DvFilter",
    "FilterParseError",
    "GainFilter",
    "HoldersFilter",
    "KdjJFilter",
    "MaBiasFilter",
    "MacdDifFilter",
    "MacdFilter",
    "MoneyflowDailyFilter",
    "MoneyflowDaysFilter",
    "MoneyflowFilter",
    "NorthFilter",
    "PeFilter",
    "PeriodScalarFilter",
    "PosFilter",
    "ResonanceFilter",
    "RoeFilter",
    "RsBoardFilter",
    "RsIndexFilter",
    "RsiFilter",
    "ScalarFilter",
    "StreakFilter",
    "Top10Filter",
    "UpDaysFilter",
    "WinnerFilter",
    "apply_op",
]
