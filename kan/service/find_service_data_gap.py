"""find service upstream data-gap detection."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kan.core.find_dsl import ConditionSet


def _any_metric(results: list[Any], attr: str, fields: tuple[str, ...]) -> bool:
    """Any result has a non-null value in the requested dimension."""
    for r in results:
        obj = getattr(r, attr, None)
        if obj is None:
            continue
        if any(getattr(obj, field, None) is not None for field in fields):
            return True
    return False


def _any_technical_for_filters(
    results: list[Any],
    conditions: ConditionSet,
) -> bool:
    """Check whether requested technical filter data is available."""
    for r in results:
        t = getattr(r, "technical", None)
        if t is None:
            continue
        if conditions.rsi_filters and getattr(t, "rsi_6", None) is not None:
            return True
        if conditions.macd_dif_filters and getattr(t, "macd_dif", None) is not None:
            return True
        if conditions.macd_filters and getattr(t, "macd", None) is not None:
            return True
        if conditions.kdj_j_filters and getattr(t, "kdj_j", None) is not None:
            return True
        if conditions.atr_pct_filters and t.atr_pct() is not None:
            return True
    return False


def _any_ma_bias_for_filters(
    results: list[Any],
    conditions: ConditionSet,
) -> bool:
    """Check whether requested K-line ma_bias values are available."""
    for r in results:
        values = getattr(r, "ma_biases", None)
        if not isinstance(values, dict):
            continue
        if any(values.get(f.period) is not None for f in conditions.ma_bias_filters):
            return True
    return False


def _any_rs(results: list[Any], conditions: ConditionSet) -> bool:
    """Any result has a non-empty relative_strength diff for requested rs filters."""
    for r in results:
        rs = getattr(r, "relative_strength", None)
        if rs is None:
            continue
        if conditions.rs_index_filters and rs.rs_index:
            return True
        if conditions.rs_board_filters and rs.rs_board:
            return True
    return False


def _find_data_gap(
    conditions: ConditionSet,
    results: list[Any],
) -> tuple[str, str, str] | None:
    """Identify upstream data gaps instead of silently returning zero matches."""
    if not results:
        return None
    token_hint = "例: kan config set tushare-token <你的_token>；或去掉对应 filter"
    missing_valuation_flags: list[str] = []
    for attr, field, flag in (
        ("pe_filters", "pe_ttm", "--pe"),
        ("pb_filters", "pb", "--pb"),
        ("dv_filters", "dv_ttm", "--dv"),
        ("turnover_filters", "turnover_rate", "--turnover"),
        ("market_cap_filters", "total_mv", "--market-cap"),
        ("volume_ratio_filters", "volume_ratio", "--volume-ratio"),
    ):
        if getattr(conditions, attr) and not _any_metric(
            results, "valuation", (field,)
        ):
            missing_valuation_flags.append(flag)
    if missing_valuation_flags:
        flags = "/".join(missing_valuation_flags)
        return ("data_unavailable", f"当前候选池缺少估值数据，无法执行 {flags} filter", token_hint)
    if conditions.moneyflow_filters and not _any_metric(
        results, "moneyflow", ("net_amount", "net_amount_5d")
    ):
        return ("data_unavailable", "当前候选池缺少资金流数据，无法执行 --moneyflow filter", token_hint)
    if conditions.moneyflow_daily_filters and not _any_metric(results, "moneyflow", ("net_amount",)):
        return ("data_unavailable", "当前候选池缺少单日资金流数据，无法执行 --moneyflow-daily filter", token_hint)
    if conditions.moneyflow_days_filters and not _any_metric(results, "moneyflow", ("inflow_days",)):
        return ("data_unavailable", "当前候选池缺少连续资金流数据，无法执行 --moneyflow-days filter", token_hint)
    if conditions.roe_filters and not _any_metric(results, "fundamentals", ("roe",)):
        return ("data_unavailable", "当前候选池缺少财务数据，无法执行 --roe filter", token_hint)
    if conditions.needs_technical() and not _any_technical_for_filters(results, conditions):
        return ("data_unavailable", "当前候选池缺少技术指标数据，无法执行技术 filter", token_hint)
    if conditions.ma_bias_filters and not _any_ma_bias_for_filters(results, conditions):
        return ("data_unavailable", "当前候选池缺少 K 线乖离率数据，无法执行 --ma-bias filter", token_hint)
    if conditions.winner_filters and not _any_metric(results, "chip", ("winner_rate",)):
        return ("data_unavailable", "当前候选池缺少筹码数据，无法执行 --winner filter", token_hint)
    if conditions.needs_relative_strength() and not _any_rs(results, conditions):
        return (
            "data_unavailable",
            "当前候选池缺少相对强度对照数据(指数/行业区间涨幅),无法执行 --rs-index/--rs-board filter",
            token_hint,
        )
    if conditions.needs_shareholder() and not _any_metric(
        results,
        "shareholder",
        ("holder_chg_pct", "top10_float_ratio", "north_hold_ratio"),
    ):
        return ("data_unavailable", "当前候选池缺少股东持股结构数据，无法执行股东 filter", token_hint)
    return None
