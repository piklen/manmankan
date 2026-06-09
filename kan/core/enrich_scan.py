"""scan 行补充估值、资金与除权除息事件。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.enrich_index import _index_moneyflow, _index_valuations
from kan.core.enrich_rows import _opt_float

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from kan.core.models import MoneyflowMetrics, StockScanResult, ValuationMetrics


def enrich_scan_rows(
    results: list[StockScanResult],
    *,
    data_cutoff: date | None = None,
) -> list[StockScanResult]:
    """给 scan 行挂 AI 消费常用客观字段:PE、近 5 日主力净额、除权除息事件。

    10/20 日均线与近 20 日低价已在 scan_stock 中从本地 K 线计算;这里补需要
    截面源/事件源的数据。所有外部数据失败都降级为 None,不阻断位置扫描主路径。
    """
    from kan.core.models import CorporateActionMarker
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.fetcher import get_cached
    from kan.data.metrics import fetch_metrics

    if not results:
        return []

    end = data_cutoff or latest_trade_date()
    trade_date = end.strftime("%Y%m%d")
    symbols = [r.symbol for r in results]

    val_by_symbol: dict[str, ValuationMetrics] = {}
    try:
        val_df = fetch_metrics(trade_date=trade_date, symbols=symbols)
        val_by_symbol = _index_valuations(val_df, end)
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "scan enrich metrics", e)

    daily_mf_by_symbol: dict[str, MoneyflowMetrics] = {}
    try:
        from kan.data.moneyflow import fetch_moneyflow

        mf_df = fetch_moneyflow(trade_date=trade_date, symbols=symbols)
        daily_mf_by_symbol = _index_moneyflow(mf_df, end)
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "scan enrich daily moneyflow", e)

    mf_5d = _moneyflow_5d_by_symbol(symbols, end=end)

    out: list[StockScanResult] = []
    for r in results:
        action = None
        try:
            df = get_cached(r.symbol)
            action = _latest_corporate_action_marker(r, df, CorporateActionMarker)
        except Exception as e:
            from kan.infra.log import debug_log

            debug_log(__name__, f"scan enrich corporate action · {r.symbol}", e)

        val = val_by_symbol.get(r.symbol)
        daily_mf = daily_mf_by_symbol.get(r.symbol)
        mf = mf_5d.get(r.symbol)
        updates = {
            "pe_ttm": val.pe_ttm if val is not None else None,
            "pb": val.pb if val is not None else None,
            "ps_ttm": val.ps_ttm if val is not None else None,
            "dv_ttm": val.dv_ttm if val is not None else None,
            "turnover_rate": val.turnover_rate if val is not None else None,
            "volume_ratio": val.volume_ratio if val is not None else None,
            "total_mv": val.total_mv if val is not None else None,
            "circ_mv": val.circ_mv if val is not None else None,
            "valuation_trade_date": val.trade_date if val is not None else None,
            "moneyflow_net_amount": (
                daily_mf.net_amount if daily_mf is not None else None
            ),
            "moneyflow_buy_elg_amount": (
                daily_mf.buy_elg_amount if daily_mf is not None else None
            ),
            "moneyflow_buy_lg_amount": (
                daily_mf.buy_lg_amount if daily_mf is not None else None
            ),
            "moneyflow_buy_md_amount": (
                daily_mf.buy_md_amount if daily_mf is not None else None
            ),
            "moneyflow_buy_sm_amount": (
                daily_mf.buy_sm_amount if daily_mf is not None else None
            ),
            "moneyflow_inflow_days": (
                daily_mf.inflow_days if daily_mf is not None else None
            ),
            "moneyflow_outflow_days": (
                daily_mf.outflow_days if daily_mf is not None else None
            ),
            "moneyflow_trade_date": (
                daily_mf.trade_date if daily_mf is not None else None
            ),
            "moneyflow_5d_net_amount": mf[0] if mf is not None else None,
            "moneyflow_5d_end_date": mf[1] if mf is not None else None,
            "corporate_action": action,
        }
        out.append(r.model_copy(update=updates))
    return out


def _recent_trade_dates(end: date, count: int) -> list[date]:
    """取 <= end 的最近 count 个交易日 · 日历不可用时退化 weekday。"""
    from datetime import timedelta

    try:
        from kan.core.trading_calendar import get_trade_dates

        days = sorted(d for d in get_trade_dates() if d <= end)
    except Exception:
        days = []
    if len(days) >= count:
        return days[-count:]

    out: list[date] = []
    cursor = end
    while len(out) < count:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(out)


def _moneyflow_5d_by_symbol(
    symbols: list[str], *, end: date,
) -> dict[str, tuple[float, date]]:
    """近 5 个交易日主力净额合计 · 单位万元 · 无数据的 symbol 不入 dict。"""
    from kan.data.moneyflow import fetch_moneyflow
    from kan.infra.log import debug_log

    sums: dict[str, float] = {}
    seen: set[str] = set()
    dates = _recent_trade_dates(end, 5)
    for d in dates:
        try:
            df = fetch_moneyflow(d.strftime("%Y%m%d"), symbols=symbols)
        except Exception as e:
            debug_log(__name__, f"scan enrich moneyflow {d}", e)
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            if not symbol:
                continue
            value = _opt_float(row.get("net_amount"))
            if value is None:
                continue
            sums[symbol] = sums.get(symbol, 0.0) + value
            seen.add(symbol)
    end_date = dates[-1]
    return {symbol: (round(sums[symbol], 2), end_date) for symbol in seen}


def _latest_corporate_action_marker(
    result: StockScanResult,
    df: pd.DataFrame | None,
    marker_cls,
):
    if df is None or df.empty or "date" not in df.columns:
        return None
    import pandas as pd

    from kan.data.dividend import latest_event_between

    dates = pd.to_datetime(df["date"], errors="coerce").dt.date
    valid_dates = [d for d in dates if d is not None and not pd.isna(d)]
    if not valid_dates:
        return None
    start = valid_dates[-180] if len(valid_dates) >= 180 else valid_dates[0]
    event = latest_event_between(result.symbol, start, result.scan_date)
    if not event:
        return None
    ex_date = event.get("ex_date")
    if ex_date is None or pd.isna(ex_date):
        return None
    cash = _opt_float(event.get("cash_div_tax"))
    if cash is None:
        cash = _opt_float(event.get("cash_div")) or 0.0
    stk_div = _opt_float(event.get("stk_div")) or 0.0
    ref_price = _ex_reference_price(df, ex_date, cash=cash, stk_div=stk_div)
    return marker_cls(
        ex_date=ex_date,
        record_date=event.get("record_date") if not pd.isna(event.get("record_date")) else None,
        cash_div_tax=cash,
        stk_div=stk_div,
        reference_price=ref_price,
        source=event.get("_source") if isinstance(event.get("_source"), str) else None,
    )


def _ex_reference_price(
    df: pd.DataFrame, ex_date: date, *, cash: float, stk_div: float,
) -> float | None:
    """用前一交易日收盘粗算除权除息参考价 · 前复权缓存下为同口径参考。"""
    import pandas as pd

    dated = df.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce").dt.date
    prev = dated[dated["date"] < ex_date].tail(1)
    if prev.empty:
        return None
    prev_close = _opt_float(prev.iloc[0].get("close"))
    if prev_close is None:
        return None
    denom = 1.0 + max(stk_div, 0.0)
    if denom <= 0:
        return None
    return round((prev_close - cash) / denom, 2)


__all__ = ["enrich_scan_rows"]
