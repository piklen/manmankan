"""N 日极值扫描 + 位置百分比"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd  # 背景: lazy import · 避免 top-level pandas 触发 cold-start cost

from kan.core.models import PeriodResult, StockScanResult
from kan.core.scanner_history import (
    SymbolHistoryEntry,
    _iter_snapshot_files,
    history_mark,
    history_resonance,
    load_symbol_history,
    snapshot_symbol_names,
)
from kan.core.scanner_snapshot import compute_diff, load_snapshot, save_snapshot
from kan.core.scanner_trend import TrendResult, calc_trend
from kan.core.scanner_volume import VOLUME_WINDOW, calc_volume_state
from kan.storage.paths import SNAPSHOT_PATH

__all__ = [
    "MAX_PERIOD",
    "MIN_PERIOD",
    "PERIODS",
    "SNAPSHOT_PATH",
    "ST_LIMIT_CHANGE_DATE",
    "VOLUME_WINDOW",
    "SymbolHistoryEntry",
    "TrendResult",
    "_calc_position",
    "_iter_snapshot_files",
    "_period_pct_key",
    "calc_trend",
    "calc_volume_state",
    "compute_diff",
    "filter_extreme",
    "get_limit_threshold",
    "history_mark",
    "history_resonance",
    "load_snapshot",
    "load_symbol_history",
    "save_snapshot",
    "scan_batch",
    "scan_stock",
    "snapshot_symbol_names",
    "trend_batch",
]

PERIODS = [3, 5, 7, 10, 15, 30, 60, 90, 120, 180]
MIN_PERIOD = 2
MAX_PERIOD = 360

# *ST 涨跌停新规：2026-07-06 起主板 *ST 从 5% 调整为 10%
# 来源：沪深北交易所 2026-04 公告
ST_LIMIT_CHANGE_DATE = date(2026, 7, 6)


def get_limit_threshold(symbol: str, name: str, as_of: date | None = None) -> float:
    """获取股票涨跌停限制百分比。"""
    is_st = "ST" in name
    if as_of is None:
        as_of = date.today()

    if symbol.startswith(("30", "68")):
        return 20.0
    elif symbol.startswith(("8", "4")):
        return 30.0
    elif is_st and as_of < ST_LIMIT_CHANGE_DATE:
        return 5.0
    else:
        return 10.0


def _calc_position(df: pd.DataFrame, p: int, row_offset: int = 0) -> float | None:
    """计算位置百分比。row_offset=1 表示用前一天的收盘价。"""
    total = len(df) - row_offset
    if total < p:
        return None
    end = len(df) - row_offset
    start = end - p
    window = df.iloc[start:end]
    close = float(df["close"].iloc[end - 1])
    n_low = float(window["low"].min())
    n_high = float(window["high"].max())
    if n_high == n_low:
        return 50.0
    return round((close - n_low) / (n_high - n_low) * 100, 1)


def scan_stock(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    periods: list[int] | None = None,
    ma_bias_periods: list[int] | None = None,
) -> StockScanResult:
    """对单只股票计算多周期位置 + 趋势。"""
    import pandas as pd  # 背景: lazy · 函数体内 import 用于 pd.Timestamp 类型转换

    if periods is None:
        periods = PERIODS

    current_price = float(df["close"].iloc[-1])
    scan_date = df["date"].iloc[-1]
    if not isinstance(scan_date, date):
        scan_date = pd.Timestamp(scan_date).date()

    total_rows = len(df)
    period_results: list[PeriodResult] = []
    low_resonance = 0
    high_resonance = 0

    for p in periods:
        if total_rows < p:
            period_results.append(PeriodResult(
                period=p,
                n_low=0.0,
                n_high=0.0,
                position_pct=0.0,
                at_low=False,
                at_high=False,
                insufficient=True,
            ))
            continue

        window = df.tail(p)
        n_low = float(window["low"].min())
        n_high = float(window["high"].max())

        if n_high == n_low:
            position_pct = 50.0
        else:
            position_pct = round((current_price - n_low) / (n_high - n_low) * 100, 1)
        distance_to_low = round(current_price - n_low, 2)
        distance_to_low_pct = (
            round((current_price - n_low) / n_low * 100, 2)
            if n_low > 0 else None
        )
        distance_to_high = round(current_price - n_high, 2)
        distance_to_high_pct = (
            round((current_price - n_high) / n_high * 100, 2)
            if n_high > 0 else None
        )

        at_low = position_pct <= 5.0
        at_high = position_pct >= 95.0

        # 近 p 日涨幅 % (动量/涨速裸值 · 需 p+1 根:今收 vs p 日前收 · 不足 → None)
        gain_pct: float | None = None
        if total_rows >= p + 1:
            base = float(df["close"].iloc[-(p + 1)])
            if base > 0:
                gain_pct = round((current_price - base) / base * 100, 2)

        # 趋势：跟前一天的位置比较
        trend = ""
        prev_pct = _calc_position(df, p, row_offset=1)
        if prev_pct is not None:
            diff = position_pct - prev_pct
            if diff > 1.0:
                trend = "↑"
            elif diff < -1.0:
                trend = "↓"
            else:
                trend = "→"

        if at_low:
            low_resonance += 1
        if at_high:
            high_resonance += 1

        period_results.append(PeriodResult(
            period=p,
            n_low=round(n_low, 2),
            n_high=round(n_high, 2),
            position_pct=position_pct,
            at_low=at_low,
            at_high=at_high,
            trend=trend,
            gain_pct=gain_pct,
            distance_to_low=distance_to_low,
            distance_to_low_pct=distance_to_low_pct,
            distance_to_high=distance_to_high,
            distance_to_high_pct=distance_to_high_pct,
        ))

    # ST 检测
    is_st = "ST" in name or "*ST" in name

    limit_up = False
    limit_down = False
    price_direction = None
    volume_price = None
    if len(df) >= 2:
        prev_close = float(df["close"].iloc[-2])
        if prev_close > 0:
            change_pct = (current_price - prev_close) / prev_close * 100
            threshold = get_limit_threshold(symbol, name, as_of=scan_date)
            limit_up = change_pct >= threshold - 0.1
            limit_down = change_pct <= -(threshold - 0.1)
            from kan.core.retail_facts import volume_price_state

            price_direction, volume_price = volume_price_state(
                volume_ratio=_local_volume_ratio(df),
                close=current_price,
                prev_close=prev_close,
            )

    # 连阳天数 (candle 口径:close>open 连续根数 · 从最新往前数 · 当前非阳线=0)
    # 涨速/加速裸值 · 区别于 limit_times 连板 (涨跌停口径) · 不判 "强势/妖股"。
    up_days = 0
    if "open" in df.columns:
        for i in range(len(df) - 1, -1, -1):
            o = df["open"].iloc[i]
            c = df["close"].iloc[i]
            if pd.isna(o) or pd.isna(c) or float(c) <= float(o):
                break
            up_days += 1

    def _ma(days: int) -> float | None:
        if len(df) < days:
            return None
        return round(float(df["close"].tail(days).mean()), 2)

    ma_biases: dict[int, float] = {}
    for days in sorted(set(ma_bias_periods or [])):
        ma = _ma(days)
        if ma is None or ma == 0:
            continue
        ma_biases[days] = round((current_price - ma) / ma * 100, 2)

    recent_low_20 = None
    if len(df) >= 20:
        recent_low_20 = round(float(df["low"].tail(20).min()), 2)

    return StockScanResult(
        symbol=symbol,
        name=name,
        current_price=round(current_price, 2),
        scan_date=scan_date,
        periods=period_results,
        low_resonance=low_resonance,
        high_resonance=high_resonance,
        is_st=is_st,
        limit_up=limit_up,
        limit_down=limit_down,
        up_days=up_days,
        ma_10=_ma(10),
        ma_20=_ma(20),
        recent_low_20=recent_low_20,
        volume_price_state=volume_price or price_direction,
        ma_biases=ma_biases,
    )


def _local_volume_ratio(df: pd.DataFrame) -> float | None:
    """用本地 K 线估算今日量 / 近 5 日均量。"""
    import pandas as pd

    if "volume" not in df.columns or len(df) < VOLUME_WINDOW + 1:
        return None
    today = df["volume"].iloc[-1]
    prior = df["volume"].iloc[-(VOLUME_WINDOW + 1):-1]
    if pd.isna(today):
        return None
    avg = prior.mean()
    if pd.isna(avg) or avg <= 0:
        return None
    return round(float(today) / float(avg), 2)


def _period_pct_key(r: StockScanResult, sentinel: float) -> tuple[float, ...]:
    """按 PERIODS 顺序生成 pct 元组 · insufficient 周期用 sentinel 占位。"""
    pcts = {p.period: p.position_pct for p in r.periods if not p.insufficient}
    return tuple(pcts.get(p, sentinel) for p in PERIODS)


def scan_batch(
    watchlist: list[tuple[str, str]],
    mode: str = "low",
    periods: list[int] | None = None,
    ma_bias_periods: list[int] | None = None,
) -> list[StockScanResult]:
    """批量扫描自选股 · 共振优先 + PERIODS 字典序 tie-break。

    排序语义：
      low:  -共振 → 3日pct升序 → 5日pct升序 → ... → 180日pct升序
      high: -共振 → 3日pct降序 → 5日pct降序 → ... → 180日pct降序

    insufficient 周期取 sentinel：low=100（排末尾）· high=0（取负后排末尾）。
    """
    from kan.data.fetcher import get_cached

    results: list[StockScanResult] = []

    for symbol, name in watchlist:
        df = get_cached(symbol)
        if df is None:
            continue
        if periods is None and ma_bias_periods is None:
            result = scan_stock(df, symbol, name)
        else:
            result = scan_stock(
                df,
                symbol,
                name,
                periods=periods,
                ma_bias_periods=ma_bias_periods,
            )
        results.append(result)

    if mode == "high":
        results.sort(key=lambda r: (
            -r.high_resonance,
            tuple(-x for x in _period_pct_key(r, sentinel=0.0)),
        ))
    else:
        results.sort(key=lambda r: (
            -r.low_resonance,
            _period_pct_key(r, sentinel=100.0),
        ))

    return results


def filter_extreme(
    watchlist: list[tuple[str, str]],
    periods: list[int],
    mode: str = "low",
) -> dict[int, list[tuple[StockScanResult, PeriodResult]]]:
    """筛选触及 N 日低/高点的自选股，支持多周期。

    返回 {period: [(scan_result, period_result), ...]}
    """
    from kan.data.fetcher import get_cached

    results_by_period: dict[int, list[tuple[StockScanResult, PeriodResult]]] = {}

    for n in periods:
        hits: list[tuple[StockScanResult, PeriodResult]] = []
        for symbol, name in watchlist:
            df = get_cached(symbol)
            if df is None:
                continue
            result = scan_stock(df, symbol, name, periods=[n])
            pr = result.periods[0]
            if pr.insufficient:
                continue
            if (mode == "low" and pr.at_low) or (mode == "high" and pr.at_high):
                hits.append((result, pr))

        hits.sort(key=lambda x: x[1].position_pct if mode == "low" else -x[1].position_pct)
        if hits:
            results_by_period[n] = hits

    return results_by_period


def trend_batch(
    watchlist: list[tuple[str, str]],
    candle: bool = False,
) -> list[TrendResult]:
    """批量计算连续涨跌 · 连续天数 abs 降序 + 累计幅度 abs 降序 tie-break。

    排序语义：
      连跌 6 天 -8% 排在 连跌 5 天 -15% 之前（天数优先）
      同样连跌 5 天：-15% 排在 -3% 之前（同天数下幅度大的在前）
    """
    from kan.data.fetcher import get_cached

    results: list[TrendResult] = []
    for symbol, name in watchlist:
        df = get_cached(symbol)
        if df is None:
            continue
        results.append(calc_trend(df, symbol, name, candle=candle))

    results.sort(key=lambda r: (-abs(r.streak), -abs(r.streak_pct)))
    return results
