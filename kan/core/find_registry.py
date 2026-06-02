"""Registry for `kan find` filters and JSON field selection.

This module keeps public filter metadata and `--fields` whitelist in one place.
Callers may split user input, but accepted field paths must come from
FIND_FIELD_SPECS; no dynamic nested-path evaluation is allowed.
"""
from __future__ import annotations

from dataclasses import dataclass

DATA_DIMENSIONS = (
    "valuation",
    "fundamentals",
    "moneyflow",
    "technical",
    "sentiment",
    "chip",
    "shareholder",
)
"""Dimensions reported by find JSON data_availability."""

DIMENSIONS_UNSUPPORTED_IN_ALL = {"fundamentals", "shareholder"}

DIMENSION_DATA_FIELDS = {
    "valuation": (
        "close", "pe_ttm", "pb", "ps_ttm", "dv_ttm",
        "turnover_rate", "volume_ratio", "total_mv", "circ_mv",
    ),
    "fundamentals": ("roe", "netprofit_yoy", "or_yoy"),
    "moneyflow": ("net_amount", "buy_elg_amount", "buy_lg_amount"),
    "technical": (
        "close", "macd_dif", "macd_dea", "macd", "kdj_k", "kdj_d", "kdj_j",
        "rsi_6", "rsi_12", "rsi_24", "ma_5", "ma_10", "ma_20", "ma_60",
        "atr", "boll_upper", "boll_mid", "boll_lower",
    ),
    "sentiment": ("limit_times", "open_times", "limit", "up_stat"),
    "chip": ("winner_rate", "cost_5pct", "cost_50pct", "cost_95pct", "weight_avg"),
    "shareholder": ("holder_chg_pct", "top10_float_ratio", "north_hold_ratio"),
}
"""Fields that make a dimension count as available; date/source alone do not."""


@dataclass(frozen=True)
class FindFilterSpec:
    filter_type: str
    flag: str
    dimension: str | None
    supports_all: bool
    source: str
    frequency: str
    missing_semantics: str


FILTER_SPECS = {
    "pos": FindFilterSpec(
        "pos", "--pos", None, True,
        "local_kline_or_kline_snapshot", "daily",
        "insufficient_window_or_missing_snapshot",
    ),
    "resonance": FindFilterSpec(
        "resonance", "--resonance", None, True,
        "local_kline_or_kline_snapshot", "daily",
        "derived_from_position_windows",
    ),
    "gain": FindFilterSpec(
        "gain", "--gain", None, True,
        "local_kline_or_kline_snapshot", "daily",
        "insufficient_window",
    ),
    "up_days": FindFilterSpec(
        "up_days", "--up-days", None, True,
        "local_kline_or_kline_snapshot", "daily",
        "zero_is_valid_fact",
    ),
    "pe": FindFilterSpec(
        "pe", "--pe", "valuation", True,
        "tushare_daily_basic", "daily",
        "metric_null_or_data_unavailable",
    ),
    "roe": FindFilterSpec(
        "roe", "--roe", "fundamentals", False,
        "tushare_fina_indicator", "quarterly_report",
        "metric_null_or_data_unavailable",
    ),
    "moneyflow": FindFilterSpec(
        "moneyflow", "--moneyflow", "moneyflow", True,
        "tushare_moneyflow_dc", "daily",
        "metric_null_or_data_unavailable",
    ),
    "rsi": FindFilterSpec(
        "rsi", "--rsi", "technical", True,
        "tushare_stk_factor_pro", "daily",
        "metric_null_or_data_unavailable",
    ),
    "macd_dif": FindFilterSpec(
        "macd_dif", "--macd-dif", "technical", True,
        "tushare_stk_factor_pro", "daily",
        "metric_null_or_data_unavailable",
    ),
    "macd": FindFilterSpec(
        "macd", "--macd", "technical", True,
        "tushare_stk_factor_pro", "daily",
        "metric_null_or_data_unavailable",
    ),
    "kdj_j": FindFilterSpec(
        "kdj_j", "--kdj-j", "technical", True,
        "tushare_stk_factor_pro", "daily",
        "metric_null_or_data_unavailable",
    ),
    "ma_bias": FindFilterSpec(
        "ma_bias", "--ma-bias", "technical", True,
        "tushare_stk_factor_pro", "daily",
        "metric_null_or_data_unavailable",
    ),
    "atr_pct": FindFilterSpec(
        "atr_pct", "--atr-pct", "technical", True,
        "tushare_stk_factor_pro", "daily",
        "metric_null_or_data_unavailable",
    ),
    "streak": FindFilterSpec(
        "streak", "--streak", "sentiment", True,
        "tushare_limit_list_d", "daily",
        "sparse_event_absence_is_valid_fact",
    ),
    "winner": FindFilterSpec(
        "winner", "--winner", "chip", True,
        "tushare_cyq_perf", "daily",
        "metric_null_or_data_unavailable",
    ),
    "holders": FindFilterSpec(
        "holders", "--holders", "shareholder", False,
        "tushare_stk_holdernumber_and_top10_floatholders", "quarterly_disclosure",
        "undisclosed_or_not_in_top10_can_be_null",
    ),
    "top10": FindFilterSpec(
        "top10", "--top10", "shareholder", False,
        "tushare_stk_holdernumber_and_top10_floatholders", "quarterly_disclosure",
        "undisclosed_or_not_in_top10_can_be_null",
    ),
    "north": FindFilterSpec(
        "north", "--north", "shareholder", False,
        "tushare_stk_holdernumber_and_top10_floatholders", "quarterly_disclosure",
        "undisclosed_or_not_in_top10_can_be_null",
    ),
}

TRIGGER_FLAG = {k: spec.flag for k, spec in FILTER_SPECS.items()}
FILTER_DIMENSIONS_BY_FLAG = {
    spec.flag: spec.dimension for spec in FILTER_SPECS.values() if spec.dimension is not None
}


@dataclass(frozen=True)
class FindFieldSpec:
    path: str
    output_path: tuple[str, ...]
    dimension: str | None = None
    needs_kline: bool = False
    needs_valuation_context: bool = False


def _field(
    path: str,
    *,
    dimension: str | None = None,
    needs_kline: bool = False,
    needs_valuation_context: bool = False,
) -> FindFieldSpec:
    return FindFieldSpec(
        path,
        tuple(path.split(".")),
        dimension=dimension,
        needs_kline=needs_kline,
        needs_valuation_context=needs_valuation_context,
    )


_VALUATION_FIELDS = (
    "trade_date", "close", "pe_ttm", "pb", "ps_ttm", "dv_ttm",
    "turnover_rate", "volume_ratio", "total_mv", "circ_mv", "source",
)
_VALUATION_CONTEXT_FIELDS = (
    "industry", "lookback_days", "industry_sample", "pe_pct_rank", "pb_pct_rank",
    "pe_industry_pct", "pb_industry_pct", "pe_industry_median", "pb_industry_median",
)
_FUNDAMENTALS_FIELDS = ("end_date", "roe", "netprofit_yoy", "or_yoy", "source")
_MONEYFLOW_FIELDS = ("trade_date", "net_amount", "buy_elg_amount", "buy_lg_amount", "source")
_TECHNICAL_FIELDS = (
    "trade_date", "close", "macd_dif", "macd_dea", "macd", "kdj_k", "kdj_d",
    "kdj_j", "rsi_6", "rsi_12", "rsi_24", "ma_5", "ma_10", "ma_20", "ma_60",
    "atr", "atr_pct", "ma_bias", "boll_upper", "boll_mid", "boll_lower", "source",
)
_SENTIMENT_FIELDS = ("trade_date", "limit_times", "open_times", "limit", "up_stat", "source")
_CHIP_FIELDS = (
    "trade_date", "winner_rate", "cost_5pct", "cost_50pct", "cost_95pct",
    "weight_avg", "source",
)
_SHAREHOLDER_FIELDS = (
    "holder_end_date", "holder_num", "holder_chg_pct", "top10_end_date",
    "top10_float_ratio", "north_hold_ratio", "source",
)

_BASE_FIELD_SPECS = [
    _field("code"),
    _field("name"),
    _field("price"),
    _field("data_time"),
    _field("is_st"),
    _field("limit_up"),
    _field("limit_down"),
    _field("triggered_filters"),
    _field("context.positions", needs_kline=True),
    _field("context.low_resonance", needs_kline=True),
    _field("context.high_resonance", needs_kline=True),
    _field("context.gains", needs_kline=True),
    _field("context.up_days", needs_kline=True),
]

FIND_FIELD_SPECS = {
    spec.path: spec
    for spec in (
        *_BASE_FIELD_SPECS,
        *(_field(f"valuation.{name}", dimension="valuation") for name in _VALUATION_FIELDS),
        *(
            _field(
                f"valuation_context.{name}",
                dimension="valuation",
                needs_valuation_context=True,
            )
            for name in _VALUATION_CONTEXT_FIELDS
        ),
        *(_field(f"fundamentals.{name}", dimension="fundamentals") for name in _FUNDAMENTALS_FIELDS),
        *(_field(f"moneyflow.{name}", dimension="moneyflow") for name in _MONEYFLOW_FIELDS),
        *(_field(f"technical.{name}", dimension="technical") for name in _TECHNICAL_FIELDS),
        *(_field(f"sentiment.{name}", dimension="sentiment") for name in _SENTIMENT_FIELDS),
        *(_field(f"chip.{name}", dimension="chip") for name in _CHIP_FIELDS),
        *(_field(f"shareholder.{name}", dimension="shareholder") for name in _SHAREHOLDER_FIELDS),
    )
}

FIND_FIELD_PRESETS = {
    "@core": (
        "code", "name", "price", "data_time", "triggered_filters",
    ),
    "@context": (
        "context.positions", "context.low_resonance", "context.high_resonance",
    ),
    "@valuation": (
        "valuation.trade_date", "valuation.close", "valuation.pe_ttm", "valuation.pb",
        "valuation.ps_ttm", "valuation.dv_ttm", "valuation.turnover_rate",
        "valuation.volume_ratio", "valuation.total_mv", "valuation.circ_mv",
        "valuation.source",
    ),
    "@valuation_context": (
        "valuation_context.industry", "valuation_context.industry_sample",
        "valuation_context.pe_industry_pct", "valuation_context.pb_industry_pct",
        "valuation_context.pe_industry_median", "valuation_context.pb_industry_median",
    ),
    "@moneyflow": (
        "moneyflow.trade_date", "moneyflow.net_amount", "moneyflow.buy_elg_amount",
        "moneyflow.buy_lg_amount", "moneyflow.source",
    ),
    "@technical": (
        "technical.trade_date", "technical.rsi_6", "technical.macd_dif",
        "technical.macd_dea", "technical.macd", "technical.kdj_j",
        "technical.ma_5", "technical.ma_10", "technical.ma_20", "technical.ma_60",
        "technical.atr_pct", "technical.ma_bias", "technical.source",
    ),
    "@sentiment": (
        "sentiment.trade_date", "sentiment.limit_times", "sentiment.open_times",
        "sentiment.limit", "sentiment.up_stat", "sentiment.source",
    ),
    "@chip": (
        "chip.trade_date", "chip.winner_rate", "chip.cost_5pct", "chip.cost_50pct",
        "chip.cost_95pct", "chip.weight_avg", "chip.source",
    ),
    "@shareholder": (
        "shareholder.holder_end_date", "shareholder.holder_chg_pct",
        "shareholder.top10_end_date", "shareholder.top10_float_ratio",
        "shareholder.north_hold_ratio", "shareholder.source",
    ),
}


def parse_find_fields(raw_values: list[str] | None) -> tuple[str, ...]:
    """Parse --fields values against FIND_FIELD_SPECS.

    Accepted syntax is comma and/or whitespace separated exact field paths or
    registry presets: `--fields @core,@valuation,context.positions`.
    """
    if not raw_values:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    for raw in raw_values:
        for part in raw.replace(",", " ").split():
            field = part.strip()
            if not field:
                continue
            if field.startswith("@"):
                preset = FIND_FIELD_PRESETS.get(field)
                if preset is None:
                    unknown.append(field)
                    continue
                for preset_field in preset:
                    if preset_field not in seen:
                        seen.add(preset_field)
                        out.append(preset_field)
                continue
            if field not in FIND_FIELD_SPECS:
                unknown.append(field)
                continue
            if field not in seen:
                seen.add(field)
                out.append(field)
    if unknown:
        allowed = ", ".join([*sorted(FIND_FIELD_PRESETS), *sorted(FIND_FIELD_SPECS)])
        raise ValueError(f"不支持的 --fields 字段: {', '.join(unknown)} · 可用字段: {allowed}")
    if not out:
        raise ValueError("--fields 不能为空 · 例: --fields @core,context.positions")
    return tuple(out)


def dimensions_from_filters(filters: list[dict]) -> set[str]:
    return {
        dim
        for f in filters
        if (dim := FILTER_DIMENSIONS_BY_FLAG.get(str(f.get("name", "")))) is not None
    }


def dimensions_from_fields(fields: tuple[str, ...]) -> set[str]:
    return {
        spec.dimension
        for field in fields
        if (spec := FIND_FIELD_SPECS[field]).dimension is not None
    }


def fields_need_kline(fields: tuple[str, ...]) -> bool:
    return any(FIND_FIELD_SPECS[field].needs_kline for field in fields)


def fields_need_valuation_context(fields: tuple[str, ...]) -> bool:
    return any(FIND_FIELD_SPECS[field].needs_valuation_context for field in fields)


__all__ = [
    "DATA_DIMENSIONS",
    "DIMENSIONS_UNSUPPORTED_IN_ALL",
    "DIMENSION_DATA_FIELDS",
    "FILTER_SPECS",
    "FIND_FIELD_PRESETS",
    "FIND_FIELD_SPECS",
    "TRIGGER_FLAG",
    "dimensions_from_fields",
    "dimensions_from_filters",
    "fields_need_kline",
    "fields_need_valuation_context",
    "parse_find_fields",
]
