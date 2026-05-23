"""N 日极值扫描 + 位置百分比"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd  # v0.0.4.4: lazy import · 避免 top-level pandas 触发 cold-start cost

from kan.models import PeriodResult, StockScanResult, VolumeState
from kan.paths import SNAPSHOT_PATH

PERIODS = [3, 5, 7, 10, 15, 30, 60, 90, 120, 180]

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
) -> StockScanResult:
    """对单只股票计算多周期位置 + 趋势。"""
    import pandas as pd  # v0.0.4.4: lazy · 函数体内 import 用于 pd.Timestamp 类型转换

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

        at_low = position_pct <= 5.0
        at_high = position_pct >= 95.0

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
        ))

    # ST 检测
    is_st = "ST" in name or "*ST" in name

    limit_up = False
    limit_down = False
    if len(df) >= 2:
        prev_close = float(df["close"].iloc[-2])
        if prev_close > 0:
            change_pct = (current_price - prev_close) / prev_close * 100
            threshold = get_limit_threshold(symbol, name, as_of=scan_date)
            limit_up = change_pct >= threshold - 0.1
            limit_down = change_pct <= -(threshold - 0.1)

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
    )


VOLUME_WINDOW = 5


def calc_volume_state(df: pd.DataFrame) -> VolumeState | None:
    """今日成交量相对近 VOLUME_WINDOW 日均量的状态。

    比值天然单位无关:同一缓存来自单一数据源(fetch_kline 整体重写整个
    缓存文件),量纲在"今日量 / 均量"的比值里抵消,所以不受 baostock(股)
    / 东财(手) 等跨源 volume 单位差异影响。
    volume 缺失(腾讯源不返 volume / 旧缓存)或历史不足 → 返 None。
    """
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
    ratio = round(float(today) / float(avg), 2)
    if ratio >= 2.0:
        label = "明显放大"
    elif ratio >= 1.5:
        label = "温和放大"
    elif ratio >= 0.67:
        label = "量能平稳"
    elif ratio >= 0.5:
        label = "温和萎缩"
    else:
        label = "明显萎缩"
    return VolumeState(ratio=ratio, label=label, window=VOLUME_WINDOW)


def _period_pct_key(r: StockScanResult, sentinel: float) -> tuple[float, ...]:
    """按 PERIODS 顺序生成 pct 元组 · insufficient 周期用 sentinel 占位。"""
    pcts = {p.period: p.position_pct for p in r.periods if not p.insufficient}
    return tuple(pcts.get(p, sentinel) for p in PERIODS)


def scan_batch(
    watchlist: list[tuple[str, str]],
    mode: str = "low",
) -> list[StockScanResult]:
    """批量扫描自选股 · 共振优先 + PERIODS 字典序 tie-break。

    排序语义：
      low:  -共振 → 3日pct升序 → 5日pct升序 → ... → 180日pct升序
      high: -共振 → 3日pct降序 → 5日pct降序 → ... → 180日pct降序

    insufficient 周期取 sentinel：low=100（排末尾）· high=0（取负后排末尾）。
    """
    from kan.fetcher import get_cached

    results: list[StockScanResult] = []

    for symbol, name in watchlist:
        df = get_cached(symbol)
        if df is None:
            continue
        result = scan_stock(df, symbol, name)
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
    from kan.fetcher import get_cached

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


# --- 增量快照 ---

_SNAPSHOT_KEEP_DAYS = 240


def save_snapshot(results: list[StockScanResult]) -> None:
    """保存本次 scan 结果快照（last_scan.json + 按日归档）。"""
    from kan.paths import SNAPSHOTS_DIR, ensure_dirs
    ensure_dirs()
    data = []
    for r in results:
        data.append({
            "symbol": r.symbol,
            "name": r.name,
            "periods": {
                str(p.period): {"pct": p.position_pct, "at_low": p.at_low, "at_high": p.at_high}
                for p in r.periods if not p.insufficient
            },
        })
    payload = json.dumps(data, ensure_ascii=False)

    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        f.write(payload)

    daily = SNAPSHOTS_DIR / f"{date.today().isoformat()}.json"
    with open(daily, "w", encoding="utf-8") as f:
        f.write(payload)

    cutoff = date.today() - __import__("datetime").timedelta(days=_SNAPSHOT_KEEP_DAYS)
    for old in SNAPSHOTS_DIR.glob("*.json"):
        try:
            file_date = date.fromisoformat(old.stem)
            if file_date < cutoff:
                old.unlink()
        except ValueError:
            pass


def load_snapshot() -> dict[str, dict[str, dict]] | None:
    """加载上次快照。返回 {symbol: {period_str: {pct, at_low, at_high}}}"""
    if not SNAPSHOT_PATH.exists():
        return None
    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {item["symbol"]: item["periods"] for item in data}


def compute_diff(
    current: list[StockScanResult], prev: dict[str, dict[str, dict]]
) -> list[tuple[str, str, int, str]]:
    """对比当前和上次快照，找出进入/离开极值区的变化。

    返回 [(symbol, name, period, change_desc), ...]
    """
    changes: list[tuple[str, str, int, str]] = []

    for r in current:
        prev_stock = prev.get(r.symbol, {})
        for p in r.periods:
            if p.insufficient:
                continue
            pkey = str(p.period)
            old = prev_stock.get(pkey)

            if old is None:
                continue

            if p.at_low and not old["at_low"]:
                changes.append((r.symbol, r.name, p.period, f"新进入 {p.period} 日低点区 [{p.position_pct:.0f}%]"))
            elif not p.at_low and old["at_low"]:
                changes.append((r.symbol, r.name, p.period, f"离开 {p.period} 日低点区 → {p.position_pct:.0f}%"))
            if p.at_high and not old["at_high"]:
                changes.append((r.symbol, r.name, p.period, f"新进入 {p.period} 日高点区 [{p.position_pct:.0f}%]"))
            elif not p.at_high and old["at_high"]:
                changes.append((r.symbol, r.name, p.period, f"离开 {p.period} 日高点区 → {p.position_pct:.0f}%"))

    return changes


# --- 连续涨跌 ---

class TrendResult:
    def __init__(
        self,
        symbol: str,
        name: str,
        current_price: float,
        streak: int,
        streak_pct: float,
        daily_changes: list[tuple[str, float]],
    ):
        self.symbol = symbol
        self.name = name
        self.current_price = current_price
        self.streak = streak  # 正=连涨 负=连跌
        self.streak_pct = streak_pct
        self.daily_changes = daily_changes  # [(date_str, change_pct), ...]

    @property
    def direction(self) -> str:
        if self.streak > 0:
            return f"涨{self.streak}天"
        elif self.streak < 0:
            return f"跌{abs(self.streak)}天"
        return "平"


def calc_trend(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    candle: bool = False,
) -> TrendResult:
    """计算连续涨跌。

    candle=False: 收盘价口径（close vs 前日 close）
    candle=True:  阳线阴线口径（close vs 当日 open）
    """
    if len(df) < 2:
        return TrendResult(symbol, name, float(df["close"].iloc[-1]), 0, 0.0, [])

    current_price = float(df["close"].iloc[-1])
    daily: list[tuple[str, float]] = []

    for i in range(1, min(len(df), 31)):
        idx = len(df) - i
        row = df.iloc[idx]
        d = str(row["date"])

        if candle:
            change = (float(row["close"]) - float(row["open"])) / float(row["open"]) * 100
        else:
            prev_close = float(df.iloc[idx - 1]["close"])
            change = (float(row["close"]) - prev_close) / prev_close * 100

        daily.append((d, round(change, 2)))

    # 计算连续天数（平盘穿透不断连续）
    streak = 0
    streak_pct = 0.0
    if daily:
        # 找到第一个非平盘的方向
        first_dir = 0
        for _, chg in daily:
            if chg > 0:
                first_dir = 1
                break
            elif chg < 0:
                first_dir = -1
                break

        if first_dir != 0:
            for _, chg in daily:
                if chg == 0.0:
                    # 平盘穿透：计入天数但不计入累计涨跌幅
                    streak += first_dir
                elif (first_dir > 0 and chg > 0) or (first_dir < 0 and chg < 0):
                    streak += first_dir
                    streak_pct += chg
                else:
                    break

    return TrendResult(
        symbol=symbol,
        name=name,
        current_price=current_price,
        streak=streak,
        streak_pct=round(streak_pct, 2),
        daily_changes=daily,
    )


def trend_batch(
    watchlist: list[tuple[str, str]],
    candle: bool = False,
) -> list[TrendResult]:
    """批量计算连续涨跌 · 连续天数 abs 降序 + 累计幅度 abs 降序 tie-break。

    排序语义：
      连跌 6 天 -8% 排在 连跌 5 天 -15% 之前（天数优先）
      同样连跌 5 天：-15% 排在 -3% 之前（同天数下幅度大的在前）
    """
    from kan.fetcher import get_cached

    results: list[TrendResult] = []
    for symbol, name in watchlist:
        df = get_cached(symbol)
        if df is None:
            continue
        results.append(calc_trend(df, symbol, name, candle=candle))

    results.sort(key=lambda r: (-abs(r.streak), -abs(r.streak_pct)))
    return results
