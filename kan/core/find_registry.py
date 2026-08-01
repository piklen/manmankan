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
    "relative_strength",
)
"""Dimensions reported by find JSON data_availability."""

DIMENSIONS_UNSUPPORTED_IN_ALL = {"fundamentals", "shareholder"}

DIMENSION_DATA_FIELDS = {
    "valuation": (
        "close", "pe_ttm", "pb", "ps_ttm", "dv_ttm",
        "turnover_rate", "volume_ratio", "total_mv", "circ_mv",
    ),
    "fundamentals": ("roe", "netprofit_yoy", "or_yoy"),
    "moneyflow": (
        "net_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount",
        "buy_sm_amount", "inflow_days", "outflow_days", "net_amount_5d",
    ),
    "technical": (
        "close", "macd_dif", "macd_dea", "macd", "kdj_k", "kdj_d", "kdj_j",
        "rsi_6", "rsi_12", "rsi_24", "ma_5", "ma_10", "ma_20", "ma_60",
        "atr", "boll_upper", "boll_mid", "boll_lower",
    ),
    "sentiment": (
        "limit_times", "open_times", "first_time", "last_time", "fd_amount",
        "limit", "up_stat",
    ),
    "chip": ("winner_rate", "cost_5pct", "cost_50pct", "cost_95pct", "weight_avg"),
    "shareholder": ("holder_chg_pct", "top10_float_ratio", "north_hold_ratio"),
    "relative_strength": ("rs_index", "rs_board"),
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


@dataclass(frozen=True)
class FindFilterHelpGroup:
    key: str
    title: str
    filters: tuple[str, ...]
    note: str = ""


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
    "rs_index": FindFilterSpec(
        "rs_index", "--rs-index", "relative_strength", True,
        "local_kline_and_index", "daily",
        "insufficient_window_or_benchmark_missing",
    ),
    "rs_board": FindFilterSpec(
        "rs_board", "--rs-board", "relative_strength", True,
        "local_kline_and_sw_board", "daily",
        "insufficient_window_or_industry_unknown",
    ),
    "pe": FindFilterSpec(
        "pe", "--pe", "valuation", True,
        "tushare_daily_basic", "daily",
        "metric_null_or_data_unavailable",
    ),
    "pb": FindFilterSpec(
        "pb", "--pb", "valuation", True,
        "tushare_daily_basic", "daily",
        "metric_null_or_data_unavailable",
    ),
    "dv": FindFilterSpec(
        "dv", "--dv", "valuation", True,
        "tushare_daily_basic", "daily",
        "metric_null_or_data_unavailable",
    ),
    "turnover": FindFilterSpec(
        "turnover", "--turnover", "valuation", True,
        "tushare_daily_basic", "daily",
        "metric_null_or_data_unavailable",
    ),
    "market_cap": FindFilterSpec(
        "market_cap", "--market-cap", "valuation", True,
        "tushare_daily_basic", "daily",
        "metric_null_or_data_unavailable",
    ),
    "volume_ratio": FindFilterSpec(
        "volume_ratio", "--volume-ratio", "valuation", True,
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
        "tushare_moneyflow", "daily",
        "metric_null_or_data_unavailable",
    ),
    "moneyflow_daily": FindFilterSpec(
        "moneyflow_daily", "--moneyflow-daily", "moneyflow", True,
        "tushare_moneyflow", "daily",
        "metric_null_or_data_unavailable",
    ),
    "moneyflow_days": FindFilterSpec(
        "moneyflow_days", "--moneyflow-days", "moneyflow", True,
        "tushare_moneyflow", "daily",
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
        "ma_bias", "--ma-bias", None, True,
        "local_kline_or_kline_snapshot", "daily",
        "insufficient_window_or_missing_snapshot",
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
    "exclude_st": FindFilterSpec(
        "exclude_st", "--exclude-st", None, True,
        "candidate_pool_metadata", "pool_metadata",
        "quiet_filter_not_triggered",
    ),
}

TRIGGER_FLAG = {k: spec.flag for k, spec in FILTER_SPECS.items()}
FILTER_DIMENSIONS_BY_FLAG = {
    spec.flag: spec.dimension for spec in FILTER_SPECS.values() if spec.dimension is not None
}

FIND_FILTER_HELP_GROUPS = (
    FindFilterHelpGroup(
        "core",
        "核心层 · 位置 / 共振 / ST",
        ("pos", "resonance", "exclude_st"),
        "新手先从 `--pos` / `--resonance` 开始；低点/高点快捷入口可用 `kan low` / `kan high`。",
    ),
    FindFilterHelpGroup(
        "valuation_quality_money",
        "估值 / 质量 / 资金",
        (
            "pe", "pb", "dv", "turnover", "market_cap", "volume_ratio", "roe",
            "moneyflow", "moneyflow_daily", "moneyflow_days",
        ),
        "`--market-cap` 单位亿元;`--roe` 为逐股报告期数据，`--all` 不支持；资金流单位万元。",
    ),
    FindFilterHelpGroup(
        "technical_momentum",
        "技术 / 趋势动量",
        (
            "rsi", "macd_dif", "macd", "kdj_j", "ma_bias", "gain", "atr_pct",
            "up_days", "rs_index", "rs_board",
        ),
        "进阶 · 需理解指标口径；这里输出裸值事实，不做超买/趋势判断。"
        "相对强度 (--rs-index/--rs-board) 输出 个股 − 对照 区间涨幅差，不判强弱/龙头。",
    ),
    FindFilterHelpGroup(
        "sentiment_chip_shareholder",
        "情绪 / 筹码 / 股东",
        ("streak", "winner", "holders", "top10", "north"),
        "进阶 · 股东类为季度披露代理，`--all` 不支持；需理解缺数据与未披露语义。",
    ),
)


def condition_attr_for_filter(filter_type: str) -> str:
    """Return `ConditionSet` attribute for a registered filter type."""
    if filter_type == "exclude_st":
        return "exclude_st"
    return f"{filter_type}_filters"


@dataclass(frozen=True)
class FindFilterDocsRow:
    flags: str
    source: str
    needs_token: str
    supports_all: str
    frequency: str
    missing_semantics: str


_SOURCE_LABELS = {
    "local_kline_or_kline_snapshot": "小池走本地日 K 缓存;`--all` 走全市场 K 线快照",
    "tushare_daily_basic": "TuShare `daily_basic` 衍生截面指标",
    "tushare_fina_indicator": "TuShare `fina_indicator` 最新报告期",
    "tushare_moneyflow": "TuShare `moneyflow` 衍生资金流向",
    "tushare_stk_factor_pro": "TuShare `stk_factor_pro` 衍生技术指标",
    "tushare_limit_list_d": "TuShare `limit_list_d` 涨跌停事件表",
    "tushare_cyq_perf": "TuShare `cyq_perf` 筹码分布",
    "tushare_stk_holdernumber_and_top10_floatholders": (
        "TuShare `stk_holdernumber` + `top10_floatholders` 衍生"
    ),
    "candidate_pool_metadata": "股票名称 / 候选池元数据",
    "local_kline_and_index": "个股本地/快照 K 线 + 大盘指数 index_daily 对照",
    "local_kline_and_sw_board": "个股本地/快照 K 线 + 申万一级行业指数对照",
}

_TOKEN_LABELS = {
    "local_kline_or_kline_snapshot": "小池否;`--all` 是",
    "tushare_daily_basic": "是",
    "tushare_fina_indicator": "是",
    "tushare_moneyflow": "是",
    "tushare_stk_factor_pro": "是",
    "tushare_limit_list_d": "是",
    "tushare_cyq_perf": "是",
    "tushare_stk_holdernumber_and_top10_floatholders": "是",
    "candidate_pool_metadata": "否",
    "local_kline_and_index": "是",
    "local_kline_and_sw_board": "是",
}

_FREQUENCY_LABELS = {
    "daily": "日频",
    "quarterly_report": "季度/报告期",
    "quarterly_disclosure": "季度/披露期",
    "pool_metadata": "随候选池",
}

_MISSING_SEMANTICS_LABELS = {
    "insufficient_window_or_benchmark_missing": (
        "个股或大盘指数周期不足 / 指数对照缺失为不命中"
    ),
    "insufficient_window_or_industry_unknown": (
        "个股或行业指数周期不足 / 个股行业未知为不命中"
    ),
    "insufficient_window_or_missing_snapshot": (
        "周期不足为不命中;全市场快照不可用时返回 `data_unavailable`"
    ),
    "derived_from_position_windows": "由位置结果计算;周期不足不计入共振",
    "insufficient_window": "周期不足或缺少前值为不命中",
    "zero_is_valid_fact": "非连续阳线可为 `0`,不是缺数据",
    "metric_null_or_data_unavailable": (
        "指标为空为缺数据;整池缺失时返回 `data_unavailable`"
    ),
    "sparse_event_absence_is_valid_fact": (
        "稀疏事件;未出现在事件表通常表示当日未涨跌停"
    ),
    "undisclosed_or_not_in_top10_can_be_null": (
        "未披露或未进前十大流通可为 `None`;整池缺失时返回 `data_unavailable`"
    ),
    "quiet_filter_not_triggered": "静默过滤,不写入 `triggered_filters`",
}


def format_find_filter_flags() -> str:
    """Return registry filter flags for short help text."""
    return " / ".join(spec.flag for spec in FILTER_SPECS.values())


def format_find_filter_groups() -> str:
    """Return grouped registry filters for root help short text."""
    lines: list[str] = []
    for group in FIND_FILTER_HELP_GROUPS:
        flags = " / ".join(FILTER_SPECS[name].flag for name in group.filters)
        lines.append(f"{group.title}: {flags}")
        if group.note:
            lines.append(f"  {group.note}")
    return "\n".join(lines)


def format_find_field_presets() -> str:
    """Return registry field presets for short help text."""
    return " / ".join(FIND_FIELD_PRESETS)


def find_filter_docs_rows() -> tuple[FindFilterDocsRow, ...]:
    """Human-readable filter metadata rows derived from FILTER_SPECS."""
    return tuple(
        FindFilterDocsRow(
            flags=spec.flag,
            source=_SOURCE_LABELS[spec.source],
            needs_token=_TOKEN_LABELS[spec.source],
            supports_all="是" if spec.supports_all else "否",
            frequency=_FREQUENCY_LABELS[spec.frequency],
            missing_semantics=_MISSING_SEMANTICS_LABELS[spec.missing_semantics],
        )
        for spec in FILTER_SPECS.values()
    )


def render_find_filter_docs_table() -> str:
    """Render the docs/find.md filter-source table from registry metadata."""
    lines = [
        "| filter | 数据源 | 需要 token | `--all` | 频率 | 缺数据语义 |",
        "|---|---|---:|---:|---|---|",
    ]
    lines.extend(
        (
            f"| `{row.flags}` | {row.source} | {row.needs_token} | "
            f"{row.supports_all} | {row.frequency} | {row.missing_semantics} |"
        )
        for row in find_filter_docs_rows()
    )
    return "\n".join(lines)


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
_MONEYFLOW_FIELDS = (
    "trade_date", "net_amount", "buy_elg_amount", "buy_lg_amount",
    "buy_md_amount", "buy_sm_amount", "inflow_days", "outflow_days",
    "net_amount_5d", "source",
)
_TECHNICAL_FIELDS = (
    "trade_date", "close", "macd_dif", "macd_dea", "macd", "kdj_k", "kdj_d",
    "kdj_j", "rsi_6", "rsi_12", "rsi_24", "ma_5", "ma_10", "ma_20", "ma_60",
    "atr", "atr_pct", "ma_bias", "boll_upper", "boll_mid", "boll_lower", "source",
)
_SENTIMENT_FIELDS = (
    "trade_date", "limit_times", "open_times", "first_time", "last_time",
    "fd_amount", "limit", "up_stat", "source",
)
_CHIP_FIELDS = (
    "trade_date", "winner_rate", "cost_5pct", "cost_50pct", "cost_95pct",
    "weight_avg", "source",
)
_SHAREHOLDER_FIELDS = (
    "holder_end_date", "holder_num", "holder_chg_pct", "top10_end_date",
    "top10_float_ratio", "north_hold_ratio", "source",
)
_RELATIVE_STRENGTH_FIELDS = (
    "industry", "index_code", "index_name",
    "stock_gain", "index_gain", "board_gain",
    "rs_index", "rs_board", "source",
)

_BASE_FIELD_SPECS = [
    _field("code"),
    _field("name"),
    _field("price"),
    _field("data_time"),
    _field("is_st"),
    _field("limit_up"),
    _field("limit_down"),
    _field("lot_cost"),
    _field("cash_usage_pct"),
    _field("market_board"),
    _field("permission_note"),
    _field("volume_price_state", needs_kline=True),
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
        *(
            _field(f"relative_strength.{name}", dimension="relative_strength")
            for name in _RELATIVE_STRENGTH_FIELDS
        ),
    )
}

FIND_FIELD_PRESETS = {
    "@core": (
        "code", "name", "price", "data_time", "triggered_filters",
    ),
    "@retail": (
        "lot_cost", "cash_usage_pct", "market_board", "permission_note",
        "volume_price_state",
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
    "@fundamentals": (
        "fundamentals.end_date", "fundamentals.roe", "fundamentals.netprofit_yoy",
        "fundamentals.or_yoy", "fundamentals.source",
    ),
    "@moneyflow": (
        "moneyflow.trade_date", "moneyflow.net_amount", "moneyflow.buy_elg_amount",
        "moneyflow.buy_lg_amount", "moneyflow.buy_md_amount", "moneyflow.buy_sm_amount",
        "moneyflow.inflow_days", "moneyflow.net_amount_5d", "moneyflow.source",
    ),
    "@technical": (
        "technical.trade_date", "technical.rsi_6", "technical.macd_dif",
        "technical.macd_dea", "technical.macd", "technical.kdj_j",
        "technical.ma_5", "technical.ma_10", "technical.ma_20", "technical.ma_60",
        "technical.atr_pct", "technical.ma_bias", "technical.source",
    ),
    "@sentiment": (
        "sentiment.trade_date", "sentiment.limit_times", "sentiment.open_times",
        "sentiment.first_time", "sentiment.last_time", "sentiment.fd_amount",
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
    "@relative_strength": (
        "relative_strength.industry", "relative_strength.index_name",
        "relative_strength.stock_gain", "relative_strength.index_gain",
        "relative_strength.board_gain", "relative_strength.rs_index",
        "relative_strength.rs_board", "relative_strength.source",
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
        presets = ", ".join(sorted(FIND_FIELD_PRESETS))
        raise ValueError(
            f"不支持的 --fields 字段: {', '.join(unknown)} · "
            f"可用 preset: {presets} · 字段全集见 docs/find.md"
        )
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
    "FIND_FILTER_HELP_GROUPS",
    "TRIGGER_FLAG",
    "condition_attr_for_filter",
    "dimensions_from_fields",
    "dimensions_from_filters",
    "fields_need_kline",
    "fields_need_valuation_context",
    "find_filter_docs_rows",
    "format_find_field_presets",
    "format_find_filter_flags",
    "format_find_filter_groups",
    "parse_find_fields",
    "render_find_filter_docs_table",
]
