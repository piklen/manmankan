"""把 scan 结果按需 enrich 多维指标。

`StockScanResult` (K 线衍生位置 / 共振) + 按需挂载的截面/财务子对象 → `EnrichedResult`:
- valuation (daily_basic 截面 · 总挂 · 一次 HTTP 拉全市场切子集)
- moneyflow (moneyflow_dc 截面 · need_moneyflow · 同截面廉价)
- fundamentals (fina_indicator 逐股 · need_fundamentals · 逐股 HTTP 贵 · 严格按需)

设计要点:
- 成本分级:截面 (valuation/moneyflow) 一次拉全市场切子集 · 逐股 (fundamentals) N 次 HTTP ·
  fundamentals 仅 need_fundamentals=True (用户传 --roe) 才拉 · 避免无谓逐股
- 优雅降级:无 token / 失败 → 对应子对象 None · AI 消费契约仍成立 (结构 + disclaimer 在)
- 顺序保持:返回顺序与入参 results 一致 (find 命中排序不被打乱)

合规 (compliance §6/§7):本层只把原始指标值挂到对象上 · 不算分位 / 不判断。
输出层负责把已请求维度序列化为 JSON / Markdown。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from kan.core.models import (
        ChipMetrics,
        EnrichedResult,
        FundamentalMetrics,
        MoneyflowMetrics,
        SentimentMetrics,
        ShareholderMetrics,
        StockScanResult,
        TechnicalMetrics,
        ValuationMetrics,
    )


def _opt_float(value: object) -> float | None:
    """截面单元格 → float | None · NaN / None / 不可解析一律 None。"""
    import pandas as pd

    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _row_to_valuation(row: pd.Series, fallback_date: date) -> ValuationMetrics:
    """单行截面 DataFrame → ValuationMetrics · NaN 数值置 None。

    trade_date 取行内规范化后的 date · NaT 时退回 fallback_date
    (ValuationMetrics.trade_date 必填 · 不能 None)。
    """
    import pandas as pd

    from kan.core.models import ValuationMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return ValuationMetrics(
        trade_date=td,
        close=_opt_float(row.get("close")),
        pe_ttm=_opt_float(row.get("pe_ttm")),
        pb=_opt_float(row.get("pb")),
        ps_ttm=_opt_float(row.get("ps_ttm")),
        dv_ttm=_opt_float(row.get("dv_ttm")),
        turnover_rate=_opt_float(row.get("turnover_rate")),
        volume_ratio=_opt_float(row.get("volume_ratio")),
        total_mv=_opt_float(row.get("total_mv")),
        circ_mv=_opt_float(row.get("circ_mv")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_fundamentals(row: pd.Series) -> FundamentalMetrics:
    """单股最新一期财务 Series → FundamentalMetrics (估值/质量/资金维度)。

    row 来自 fetch_fundamentals (已 normalize · end_date 是 date · 数值已清洗)。
    """
    import pandas as pd

    from kan.core.models import FundamentalMetrics

    end_date = row.get("end_date")
    if end_date is None or (not hasattr(end_date, "isoformat")) or pd.isna(end_date):
        end_date = None
    return FundamentalMetrics(
        end_date=end_date,
        roe=_opt_float(row.get("roe")),
        netprofit_yoy=_opt_float(row.get("netprofit_yoy")),
        or_yoy=_opt_float(row.get("or_yoy")),
        source="tushare_fina",
    )


def _row_to_moneyflow(row: pd.Series, fallback_date: date) -> MoneyflowMetrics:
    """单行主力资金截面 → MoneyflowMetrics · NaN 数值置 None (估值/质量/资金维度)。"""
    import pandas as pd

    from kan.core.models import MoneyflowMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return MoneyflowMetrics(
        trade_date=td,
        net_amount=_opt_float(row.get("net_amount")),
        buy_elg_amount=_opt_float(row.get("buy_elg_amount")),
        buy_lg_amount=_opt_float(row.get("buy_lg_amount")),
        buy_md_amount=_opt_float(row.get("buy_md_amount")),
        buy_sm_amount=_opt_float(row.get("buy_sm_amount")),
        inflow_days=(
            int(v) if (v := _opt_float(row.get("inflow_days"))) is not None else None
        ),
        outflow_days=(
            int(v) if (v := _opt_float(row.get("outflow_days"))) is not None else None
        ),
        net_amount_5d=_opt_float(row.get("net_amount_5d")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_technical(row: pd.Series, fallback_date: date) -> TechnicalMetrics:
    """单行技术面截面 → TechnicalMetrics · NaN 数值置 None。"""
    import pandas as pd

    from kan.core.models import TechnicalMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return TechnicalMetrics(
        trade_date=td,
        close=_opt_float(row.get("close")),
        macd_dif=_opt_float(row.get("macd_dif")),
        macd_dea=_opt_float(row.get("macd_dea")),
        macd=_opt_float(row.get("macd")),
        atr=_opt_float(row.get("atr")),
        kdj_k=_opt_float(row.get("kdj_k")),
        kdj_d=_opt_float(row.get("kdj_d")),
        kdj_j=_opt_float(row.get("kdj_j")),
        rsi_6=_opt_float(row.get("rsi_6")),
        rsi_12=_opt_float(row.get("rsi_12")),
        rsi_24=_opt_float(row.get("rsi_24")),
        ma_5=_opt_float(row.get("ma_5")),
        ma_10=_opt_float(row.get("ma_10")),
        ma_20=_opt_float(row.get("ma_20")),
        ma_60=_opt_float(row.get("ma_60")),
        boll_upper=_opt_float(row.get("boll_upper")),
        boll_mid=_opt_float(row.get("boll_mid")),
        boll_lower=_opt_float(row.get("boll_lower")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_sentiment(row: pd.Series, fallback_date: date) -> SentimentMetrics:
    """单行情绪截面 → SentimentMetrics · 数值 NaN 置 None · limit/up_stat 保 str (技术/情绪/筹码维度)。"""
    import pandas as pd

    from kan.core.models import SentimentMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return SentimentMetrics(
        trade_date=td,
        limit_times=_opt_float(row.get("limit_times")),
        open_times=_opt_float(row.get("open_times")),
        first_time=row.get("first_time") if isinstance(row.get("first_time"), str) else None,
        last_time=row.get("last_time") if isinstance(row.get("last_time"), str) else None,
        fd_amount=_opt_float(row.get("fd_amount")),
        limit=row.get("limit") if isinstance(row.get("limit"), str) else None,
        up_stat=row.get("up_stat") if isinstance(row.get("up_stat"), str) else None,
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_chip(row: pd.Series, fallback_date: date) -> ChipMetrics:
    """单行筹码截面 → ChipMetrics · NaN 数值置 None (技术/情绪/筹码维度)。"""
    import pandas as pd

    from kan.core.models import ChipMetrics

    td = row.get("trade_date")
    if td is None or (not hasattr(td, "isoformat")) or pd.isna(td):
        td = fallback_date
    return ChipMetrics(
        trade_date=td,
        winner_rate=_opt_float(row.get("winner_rate")),
        cost_5pct=_opt_float(row.get("cost_5pct")),
        cost_50pct=_opt_float(row.get("cost_50pct")),
        cost_95pct=_opt_float(row.get("cost_95pct")),
        weight_avg=_opt_float(row.get("weight_avg")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def _row_to_shareholder(row: pd.Series) -> ShareholderMetrics:
    """单股股东·持股结构衍生 Series → ShareholderMetrics (逐股 · 股东持股维度)。

    row 来自 fetch_shareholder (已 normalize · 日期是 date · 数值已清洗)。季度披露 ·
    各字段独立可空 (未披露 / 未进前十 → None · 优雅降级)。
    """
    import pandas as pd

    from kan.core.models import ShareholderMetrics

    h_end = row.get("holder_end_date")
    if h_end is None or (not hasattr(h_end, "isoformat")) or pd.isna(h_end):
        h_end = None
    t_end = row.get("top10_end_date")
    if t_end is None or (not hasattr(t_end, "isoformat")) or pd.isna(t_end):
        t_end = None
    return ShareholderMetrics(
        holder_end_date=h_end,
        holder_num=_opt_float(row.get("holder_num")),
        holder_chg_pct=_opt_float(row.get("holder_chg_pct")),
        top10_end_date=t_end,
        top10_float_ratio=_opt_float(row.get("top10_float_ratio")),
        north_hold_ratio=_opt_float(row.get("north_hold_ratio")),
        source=row.get("_source") if isinstance(row.get("_source"), str) else None,
    )


def enrich_results(
    results: list[StockScanResult],
    *,
    trade_date: str | None = None,
    need_fundamentals: bool = False,
    need_moneyflow: bool = False,
    need_technical: bool = False,
    need_sentiment: bool = False,
    need_chip: bool = False,
    need_shareholder: bool = False,
) -> list[EnrichedResult]:
    """给 scan 结果按需挂多维指标 · 返回 EnrichedResult 列表 (原序)。

    valuation 总挂 (截面廉价 · 现有行为)· fundamentals (逐股 · 贵) / moneyflow /
    technical / sentiment / chip (截面 · 廉价) 仅在对应 need_* 为 True 时挂
    (caller 按 filter 需求传 · 见 find_cmds)。

    Args:
        results: scan_batch / find 命中的 StockScanResult 列表
        trade_date: YYYYMMDD 截面日 · None → 最近交易日 (fetch 内部解析)
        need_fundamentals: True 时逐股拉 fina_indicator (--roe filter · 全市场代价高)
        need_moneyflow: True 时拉 moneyflow_dc 截面 (--moneyflow filter · 截面廉价)
        need_technical: True 时拉 stk_factor_pro 截面 (--rsi/--macd-dif/--macd/--kdj-j · 技术/情绪/筹码维度)
        need_sentiment: True 时拉 limit_list_d 截面 (--streak · 稀疏事件型 · 技术/情绪/筹码维度)
        need_chip: True 时拉 cyq_perf 截面 (--winner · 技术/情绪/筹码维度)
        need_shareholder: True 时逐股拉 stk_holdernumber + top10_floatholders
            (--holders/--top10/--north filter · 逐股 · 全市场 --all 不支持 · 股东持股维度)

    Returns:
        list[EnrichedResult] · 与 results 等长同序 · 每只按需挂各维度 (无数据时 None)。
        空 results → 空列表 (不触网)。
    """
    from kan.core.models import EnrichedResult
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.metrics import fetch_metrics

    if not results:
        return []

    symbols = [r.symbol for r in results]
    fallback_date = _resolve_fallback_date(trade_date, latest_trade_date)

    df = fetch_metrics(trade_date=trade_date, symbols=symbols)
    val_by_symbol = _index_valuations(df, fallback_date)

    fund_by_symbol: dict[str, FundamentalMetrics] = {}
    if need_fundamentals:
        from kan.data.fundamentals import fetch_fundamentals

        for sym, row in fetch_fundamentals(symbols).items():
            fund_by_symbol[sym] = _row_to_fundamentals(row)

    mf_by_symbol: dict[str, MoneyflowMetrics] = {}
    if need_moneyflow:
        from kan.data.moneyflow import fetch_moneyflow

        mf_df = fetch_moneyflow(trade_date=trade_date, symbols=symbols)
        mf_by_symbol = _index_moneyflow(mf_df, fallback_date)

    tech_by_symbol: dict[str, TechnicalMetrics] = {}
    if need_technical:
        from kan.data.technical import fetch_technical

        tech_df = fetch_technical(trade_date=trade_date, symbols=symbols)
        tech_by_symbol = _index_technical(tech_df, fallback_date)

    senti_by_symbol: dict[str, SentimentMetrics] = {}
    if need_sentiment:
        from kan.data.sentiment import fetch_sentiment

        senti_df = fetch_sentiment(trade_date=trade_date, symbols=symbols)
        senti_by_symbol = _index_sentiment(senti_df, fallback_date)

    chip_by_symbol: dict[str, ChipMetrics] = {}
    if need_chip:
        from kan.data.chip import fetch_chip

        chip_df = fetch_chip(trade_date=trade_date, symbols=symbols)
        chip_by_symbol = _index_chip(chip_df, fallback_date)

    sh_by_symbol: dict[str, ShareholderMetrics] = {}
    if need_shareholder:
        from kan.data.shareholder import fetch_shareholder

        for sym, row in fetch_shareholder(symbols).items():
            sh_by_symbol[sym] = _row_to_shareholder(row)

    return [
        EnrichedResult.from_scan(
            r,
            valuation=val_by_symbol.get(r.symbol),
            fundamentals=fund_by_symbol.get(r.symbol),
            moneyflow=mf_by_symbol.get(r.symbol),
            technical=tech_by_symbol.get(r.symbol),
            sentiment=senti_by_symbol.get(r.symbol),
            chip=chip_by_symbol.get(r.symbol),
            shareholder=sh_by_symbol.get(r.symbol),
        )
        for r in results
    ]


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

        mf = mf_5d.get(r.symbol)
        updates = {
            "pe_ttm": (
                val_by_symbol[r.symbol].pe_ttm
                if r.symbol in val_by_symbol else None
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


def _resolve_fallback_date(trade_date: str | None, latest_fn) -> date:
    """ValuationMetrics.trade_date 的兜底日期 (行内 trade_date 缺失时用)。"""
    if trade_date is None:
        return latest_fn()
    from datetime import datetime

    try:
        return datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError:
        return latest_fn()


def _index_valuations(df: pd.DataFrame, fallback_date: date) -> dict[str, ValuationMetrics]:
    """截面 DataFrame → {symbol: ValuationMetrics} · 空 df 返空 dict。"""
    if df is None or df.empty:
        return {}
    out: dict[str, ValuationMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_valuation(row, fallback_date)
    return out


def _index_moneyflow(df: pd.DataFrame, fallback_date: date) -> dict[str, MoneyflowMetrics]:
    """主力资金截面 DataFrame → {symbol: MoneyflowMetrics} · 空 df 返空 dict (估值/质量/资金维度)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, MoneyflowMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_moneyflow(row, fallback_date)
    return out


def _index_technical(df: pd.DataFrame, fallback_date: date) -> dict[str, TechnicalMetrics]:
    """技术面截面 DataFrame → {symbol: TechnicalMetrics} · 空 df 返空 dict (技术/情绪/筹码维度)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, TechnicalMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_technical(row, fallback_date)
    return out


def _index_sentiment(df: pd.DataFrame, fallback_date: date) -> dict[str, SentimentMetrics]:
    """情绪截面 DataFrame → {symbol: SentimentMetrics} · 空 df 返空 dict (技术/情绪/筹码维度 · 稀疏)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, SentimentMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_sentiment(row, fallback_date)
    return out


def _index_chip(df: pd.DataFrame, fallback_date: date) -> dict[str, ChipMetrics]:
    """筹码截面 DataFrame → {symbol: ChipMetrics} · 空 df 返空 dict (技术/情绪/筹码维度)。"""
    if df is None or df.empty:
        return {}
    out: dict[str, ChipMetrics] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            out[symbol] = _row_to_chip(row, fallback_date)
    return out


__all__ = ["enrich_results", "enrich_scan_rows"]
