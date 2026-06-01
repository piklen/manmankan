"""DSL parser for `kan find` · v0.0.6.4 MVP

按用户输入条件 · 解析成结构化 Filter 对象。

支持 filter (MVP v0.0.6.4):
- --pos PERIOD:OP:VAL    位置百分位 (例 180:lt:5 = 180 日位置 < 5%)
- --resonance LEVEL:OP:VAL  共振信号 (例 low:gte:3 = 低点共振 ≥ 3 周期)
- --exclude-st           排 ST/*ST

Future (v0.0.6.5+ candidates):
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
from typing import Literal

ALLOWED_OPS = ("lt", "lte", "gt", "gte", "eq", "ne")
ALLOWED_PERIODS = (3, 5, 7, 10, 15, 30, 60, 90, 120, 180)
RESONANCE_LEVELS = ("low", "high")


class FilterParseError(ValueError):
    """DSL parse error · raised when user input violates grammar."""


@dataclass(frozen=True)
class PosFilter:
    """位置百分位 filter · 例 PERIOD=180 OP=lt VALUE=5.0 = 180 日位置 < 5%."""

    period: int
    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> PosFilter:
        """Parse 'PERIOD:OP:VAL' string · 例 '180:lt:5'."""
        parts = raw.split(":")
        if len(parts) != 3:
            raise FilterParseError(
                f"--pos 格式错误 '{raw}' · 需要 PERIOD:OP:VAL 例 180:lt:5"
            )
        try:
            period = int(parts[0])
        except ValueError as e:
            raise FilterParseError(
                f"--pos 周期非整数 '{parts[0]}' · 例: --pos 180:lt:5"
            ) from e
        if period not in ALLOWED_PERIODS:
            raise FilterParseError(
                f"--pos 周期 {period} 不支持 · 仅 {list(ALLOWED_PERIODS)} · 例: --pos 180:lt:5"
            )
        op = parts[1].lower()
        if op not in ALLOWED_OPS:
            raise FilterParseError(
                f"--pos 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · 例: --pos 180:lt:5"
            )
        try:
            value = float(parts[2])
        except ValueError as e:
            raise FilterParseError(
                f"--pos 数值非数字 '{parts[2]}' · 例: --pos 180:lt:5"
            ) from e
        if not 0 <= value <= 100:
            raise FilterParseError(
                f"--pos 数值 {value} 越界 · 需 [0, 100] · 例: --pos 180:lt:5"
            )
        return cls(period=period, op=op, value=value)


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


# ─── 整合-1 新增 filter (OP:VAL · 裸值/净额阈值 · 复用 apply_op) ───

def _parse_op_val(raw: str, *, flag: str, example: str) -> tuple[str, float]:
    """Parse 'OP:VAL' string (整合-1 · pe/roe/moneyflow 共用)· 例 'lt:20'.

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
class PeFilter:
    """市盈率 filter · 例 OP=lt VALUE=20 = PE TTM < 20 (裸值筛 · 整合-1).

    裸 PE 阈值由用户显式指定 · 不做行业分位 (拍板:分位主观性强 · 后续优化)·
    读 valuation.pe_ttm (None → 不命中)。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> PeFilter:
        op, value = _parse_op_val(raw, flag="--pe", example="lt:20")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class RoeFilter:
    """净资产收益率 filter · 例 OP=gte VALUE=15 = ROE ≥ 15% (裸值筛 · 整合-1).

    读 fundamentals.roe (None → 不命中)· ROE 单向正向因子 · 裸值可筛可回显。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> RoeFilter:
        op, value = _parse_op_val(raw, flag="--roe", example="gte:15")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class MoneyflowFilter:
    """主力净额 filter · 例 OP=gt VALUE=0 = 主力净流入 (整合-1).

    读 moneyflow.net_amount (东财口径 · 单位万元 · None → 不命中)· 客观资金事实。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> MoneyflowFilter:
        op, value = _parse_op_val(raw, flag="--moneyflow", example="gt:0")
        return cls(op=op, value=value)


# ─── 整合-2 新增 filter (技术/情绪/筹码 · OP:VAL 裸值阈值 · 全截面) ───
# 合规:全部用户主导阈值 (同 --pe) · 只筛裸值 · 不内置金叉/超买等信号 preset。

@dataclass(frozen=True)
class RsiFilter:
    """RSI (6 日) filter · 例 OP=lt VALUE=30 = RSI < 30 (裸值筛 · 整合-2).

    读 technical.rsi_6 (前复权 · None → 不命中)· 用户主导阈值 · 不输出"超买/超卖"判断。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> RsiFilter:
        op, value = _parse_op_val(raw, flag="--rsi", example="lt:30")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class MacdDifFilter:
    """MACD DIF 快线 filter · 例 OP=gt VALUE=0 = DIF > 0 (裸值筛 · 整合-2).

    读 technical.macd_dif (前复权 · None → 不命中)· 不做金叉/死叉 (跨日 + 信号订阅红线)。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> MacdDifFilter:
        op, value = _parse_op_val(raw, flag="--macd-dif", example="gt:0")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class MacdFilter:
    """MACD 柱 filter · 例 OP=gt VALUE=0 = 柱 > 0 (当前 DIF 在 DEA 上方 · 整合-2).

    读 technical.macd (= (DIF-DEA)×2 · None → 不命中)· 柱正负 = 当日多空状态 ·
    非"金叉"(金叉是状态切换瞬间 · 需跨日对比 · 截面单日算不出)。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> MacdFilter:
        op, value = _parse_op_val(raw, flag="--macd", example="gt:0")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class KdjJFilter:
    """KDJ J 值 filter · 例 OP=lt VALUE=20 = J < 20 (裸值筛 · 整合-2).

    读 technical.kdj_j (前复权 · None → 不命中)· 用户主导阈值 · 不输出超买超卖判断。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> KdjJFilter:
        op, value = _parse_op_val(raw, flag="--kdj-j", example="lt:20")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class StreakFilter:
    """连板天数 filter · 例 OP=gte VALUE=3 = 连板 ≥ 3 (裸值筛 · 整合-2).

    读 sentiment.limit_times (None → 不命中 · 即该股当日未涨跌停)· 客观事实 ·
    不输出"妖股/强势"判断词。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> StreakFilter:
        op, value = _parse_op_val(raw, flag="--streak", example="gte:3")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class WinnerFilter:
    """获利盘 filter · 例 OP=gte VALUE=50 = 获利盘 ≥ 50% (裸值筛 · 整合-2).

    读 chip.winner_rate (% · None → 不命中)· 客观计算值 · 不输出判断词。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> WinnerFilter:
        op, value = _parse_op_val(raw, flag="--winner", example="gte:50")
        return cls(op=op, value=value)


# ─── 整合-3 新增 filter (股东·持股结构 · OP:VAL 裸值阈值 · 逐股 · --all 不支持) ───
# 合规:用户主导阈值 · 只筛已披露客观事实衍生 · 不输出主力建仓/洗盘/控盘等判断词。

@dataclass(frozen=True)
class HoldersFilter:
    """股东户数环比 filter · 例 OP=lt VALUE=0 = 户数环比减少 (裸值筛 · 整合-3).

    读 shareholder.holder_chg_pct (% · None → 不命中)· 相邻两次披露环比 · 季度级 ·
    负=户数减少 · 客观事实衍生 · 不输出"主力建仓/控盘"判断词。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> HoldersFilter:
        op, value = _parse_op_val(raw, flag="--holders", example="lt:0")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class Top10Filter:
    """前十大流通集中度 filter · 例 OP=gte VALUE=50 = 集中度 ≥ 50% (裸值筛 · 整合-3).

    读 shareholder.top10_float_ratio (% · None → 不命中)· 前十大流通股东持股合计占
    流通比 · 季度级 · 客观披露事实 · 不输出"高度控盘"判断词。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> Top10Filter:
        op, value = _parse_op_val(raw, flag="--top10", example="gte:50")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class NorthFilter:
    """北向持股 filter · 例 OP=gte VALUE=3 = 北向 ≥ 3% (裸值筛 · 整合-3).

    读 shareholder.north_hold_ratio (% · None → 不命中 / 未进前十)· "香港中央结算"
    季度名义持有人占流通比代理 (hk_hold 日频 2024-08 断供 · 降级)· 客观披露事实。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> NorthFilter:
        op, value = _parse_op_val(raw, flag="--north", example="gte:3")
        return cls(op=op, value=value)


# ─── 趋势/动量扩展 filter (客观裸值 · 截面 ma_bias/atr_pct 全市场 + K 线衍生 gain/up_days) ───
# 合规:乖离率/波动率/涨幅/连阳全部客观裸值 · 阈值用户主导 · 不判「多头排列/强势/加速末端」。

ALLOWED_MA = (5, 10, 20, 60)
"""--ma-bias 支持的均线周期 (对应 stk_factor_pro 已拉 ma_5/10/20/60)。"""


@dataclass(frozen=True)
class MaBiasFilter:
    """均线乖离率 filter · 例 PERIOD=20 OP=gt VALUE=0 = 收盘距 20 日线 > 0% (站上).

    乖离率 = (close − ma_N) / ma_N × 100 · 读 technical.ma_bias(period) (纯算 · 现成均线)·
    PERIOD ∈ {5,10,20,60} · 客观 BIAS · 不判「多头排列/趋势」· 全市场 --all 支持。
    """

    period: int
    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> MaBiasFilter:
        parts = raw.split(":")
        if len(parts) != 3:
            raise FilterParseError(
                f"--ma-bias 格式错误 '{raw}' · 需要 PERIOD:OP:VAL 例 20:gt:0"
            )
        try:
            period = int(parts[0])
        except ValueError as e:
            raise FilterParseError(
                f"--ma-bias 周期非整数 '{parts[0]}' · 例: --ma-bias 20:gt:0"
            ) from e
        if period not in ALLOWED_MA:
            raise FilterParseError(
                f"--ma-bias 周期 {period} 不支持 · 仅 {list(ALLOWED_MA)} · 例: --ma-bias 20:gt:0"
            )
        op = parts[1].lower()
        if op not in ALLOWED_OPS:
            raise FilterParseError(
                f"--ma-bias 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · 例: --ma-bias 20:gt:0"
            )
        try:
            value = float(parts[2])
        except ValueError as e:
            raise FilterParseError(
                f"--ma-bias 数值非数字 '{parts[2]}' · 例: --ma-bias 20:gt:0"
            ) from e
        return cls(period=period, op=op, value=value)


@dataclass(frozen=True)
class GainFilter:
    """近 N 日涨幅 filter · 例 PERIOD=30 OP=gt VALUE=20 = 近 30 日涨幅 > 20%.

    读 StockScanResult.periods[N].gain_pct (K 线衍生 · 需 K 线池 · --all 不支持)·
    客观涨幅 · 双关动量/涨速 (工具不判机会还是末端)· PERIOD ∈ ALLOWED_PERIODS (注意无 20)。
    """

    period: int
    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> GainFilter:
        parts = raw.split(":")
        if len(parts) != 3:
            raise FilterParseError(
                f"--gain 格式错误 '{raw}' · 需要 PERIOD:OP:VAL 例 30:gt:20"
            )
        try:
            period = int(parts[0])
        except ValueError as e:
            raise FilterParseError(
                f"--gain 周期非整数 '{parts[0]}' · 例: --gain 30:gt:20"
            ) from e
        if period not in ALLOWED_PERIODS:
            raise FilterParseError(
                f"--gain 周期 {period} 不支持 · 仅 {list(ALLOWED_PERIODS)} · 例: --gain 30:gt:20"
            )
        op = parts[1].lower()
        if op not in ALLOWED_OPS:
            raise FilterParseError(
                f"--gain 运算符 '{op}' 不支持 · 仅 {list(ALLOWED_OPS)} · 例: --gain 30:gt:20"
            )
        try:
            value = float(parts[2])
        except ValueError as e:
            raise FilterParseError(
                f"--gain 数值非数字 '{parts[2]}' · 例: --gain 30:gt:20"
            ) from e
        return cls(period=period, op=op, value=value)


@dataclass(frozen=True)
class AtrPctFilter:
    """ATR 波动率百分比 filter · 例 OP=lt VALUE=5 = ATR/close < 5% (波动率裸值 · 风险数据).

    读 technical.atr_pct() = atr / close × 100 (固定周期 · stk_factor_pro 截面)·
    全市场 --all 支持 · 客观波动率 · 不判「高波动危险/低波动安全」。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> AtrPctFilter:
        op, value = _parse_op_val(raw, flag="--atr-pct", example="lt:5")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class UpDaysFilter:
    """连阳天数 filter · 例 OP=gte VALUE=3 = 连续 ≥ 3 根阳线 (涨速/加速裸值).

    读 StockScanResult.up_days (candle 口径 close>open · K 线衍生 · --all 走预计算快照)·
    客观连阳计数 · 不判「强势/妖股」· 区别于 --streak (连板天数 · 涨跌停口径)。
    """

    op: str
    value: float

    @classmethod
    def parse(cls, raw: str) -> UpDaysFilter:
        op, value = _parse_op_val(raw, flag="--up-days", example="gte:3")
        return cls(op=op, value=value)


@dataclass(frozen=True)
class ConditionSet:
    """DSL 解析后的完整 filter 集合 · 多 filter 间 AND 语义.

    K 线类 (位置/共振):pos_filters / resonance_filters · 走 scan 衍生字段。
    截面类 (估值/资金 · 整合-1):pe_filters / moneyflow_filters · 走 enrich 子对象。
    财务类 (整合-1):roe_filters · 走 fundamentals (逐股 · 全市场 --all 不支持)。
    技术/情绪/筹码类 (整合-2 · 全截面):rsi/macd_dif/macd/kdj_j/streak/winner ·
      走 enrich 子对象 (technical/sentiment/chip) · K 线池 + --all 两路都支持。
    股东类 (整合-3):holders/top10/north · 走 shareholder (逐股 · --all 不支持 · 同 roe)。
    exclude_st:quiet filter (不记 triggered · 直接 drop)。
    """

    pos_filters: tuple[PosFilter, ...] = ()
    resonance_filters: tuple[ResonanceFilter, ...] = ()
    pe_filters: tuple[PeFilter, ...] = ()
    roe_filters: tuple[RoeFilter, ...] = ()
    moneyflow_filters: tuple[MoneyflowFilter, ...] = ()
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
    exclude_st: bool = False

    @classmethod
    def from_flags(
        cls,
        *,
        pos: list[str] | None = None,
        resonance: list[str] | None = None,
        pe: list[str] | None = None,
        roe: list[str] | None = None,
        moneyflow: list[str] | None = None,
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
        exclude_st: bool = False,
    ) -> ConditionSet:
        """Build ConditionSet from CLI flag strings (raw user input)."""
        return cls(
            pos_filters=tuple(PosFilter.parse(p) for p in (pos or [])),
            resonance_filters=tuple(ResonanceFilter.parse(r) for r in (resonance or [])),
            pe_filters=tuple(PeFilter.parse(p) for p in (pe or [])),
            roe_filters=tuple(RoeFilter.parse(r) for r in (roe or [])),
            moneyflow_filters=tuple(MoneyflowFilter.parse(m) for m in (moneyflow or [])),
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
            exclude_st=exclude_st,
        )

    def is_empty(self) -> bool:
        return not (
            self.pos_filters
            or self.resonance_filters
            or self.pe_filters
            or self.roe_filters
            or self.moneyflow_filters
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
            or self.exclude_st
        )

    def has_kline_filters(self) -> bool:
        """K 线衍生 filter (位置/共振/涨幅/连阳) · --all 走预计算快照。"""
        return bool(
            self.pos_filters
            or self.resonance_filters
            or self.gain_filters
            or self.up_days_filters
        )

    def has_cross_section_filters(self) -> bool:
        """截面类 filter (估值/资金/技术/情绪/筹码) · K 线池 + --all 两路都支持。"""
        return bool(
            self.pe_filters
            or self.moneyflow_filters
            or self.needs_technical()
            or self.needs_sentiment()
            or self.needs_chip()
        )

    def needs_fundamentals(self) -> bool:
        """是否需挂 fundamentals (--roe · 逐股 · 全市场 --all 不支持)。"""
        return bool(self.roe_filters)

    def needs_moneyflow(self) -> bool:
        """是否需挂 moneyflow (--moneyflow · 截面)。"""
        return bool(self.moneyflow_filters)

    def needs_technical(self) -> bool:
        """是否需挂 technical (--rsi/--macd-dif/--macd/--kdj-j/--ma-bias/--atr-pct · 截面)。"""
        return bool(
            self.rsi_filters
            or self.macd_dif_filters
            or self.macd_filters
            or self.kdj_j_filters
            or self.ma_bias_filters
            or self.atr_pct_filters
        )

    def needs_sentiment(self) -> bool:
        """是否需挂 sentiment (--streak · 截面稀疏 · 整合-2)。"""
        return bool(self.streak_filters)

    def needs_chip(self) -> bool:
        """是否需挂 chip (--winner · 截面 · 整合-2)。"""
        return bool(self.winner_filters)

    def needs_shareholder(self) -> bool:
        """是否需挂 shareholder (--holders/--top10/--north · 逐股 · 全市场 --all 不支持)。"""
        return bool(
            self.holders_filters
            or self.top10_filters
            or self.north_filters
        )


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
    "RESONANCE_LEVELS",
    "AtrPctFilter",
    "ConditionSet",
    "FilterParseError",
    "GainFilter",
    "HoldersFilter",
    "KdjJFilter",
    "MaBiasFilter",
    "MacdDifFilter",
    "MacdFilter",
    "MoneyflowFilter",
    "NorthFilter",
    "PeFilter",
    "PosFilter",
    "ResonanceFilter",
    "RoeFilter",
    "RsiFilter",
    "StreakFilter",
    "Top10Filter",
    "UpDaysFilter",
    "WinnerFilter",
    "apply_op",
]
