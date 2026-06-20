"""普通 `kan find` 结果 payload / markdown 导出。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from kan.core.find_registry import (
    DATA_DIMENSIONS,
    DIMENSION_DATA_FIELDS,
    FIND_FIELD_SPECS,
    TRIGGER_FLAG,
    dimensions_from_filters,
)
from kan.storage.export_base import FIND_SCHEMA_VERSION, md_table
from kan.storage.export_find_dimensions import (
    _chip_public_dict,
    _fundamentals_public_dict,
    _moneyflow_public_dict,
    _relative_strength_public_dict,
    _sentiment_public_dict,
    _shareholder_public_dict,
    _technical_public_dict,
    _valuation_public_dict,
)

if TYPE_CHECKING:
    from kan.core.find_filter import FindMatch
    from kan.core.models import EnrichedResult, StockScanResult
    from kan.core.pipeline import Freshness

def _find_disclaimer_quote() -> str:
    """find 专属免责 → markdown 引用块 (compliance §5 · 项目内强制输出)。"""
    from kan.render.base import FIND_DISCLAIMER_TEXT

    return "> " + FIND_DISCLAIMER_TEXT

def _find_result_dict(match: FindMatch, enriched: EnrichedResult) -> dict:
    """单只命中 → JSON 对象 (find JSON schema · AI JSON 层扩 valuation + context)。"""
    er = enriched
    return {
        "code": er.symbol,
        "name": er.name.replace(" ", ""),
        "price": er.current_price,
        "data_time": er.scan_date.isoformat(),
        "is_st": er.is_st,
        "limit_up": er.limit_up,
        "limit_down": er.limit_down,
        **_retail_fact_dict(er),
        "triggered_filters": [
            {
                "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
                "param": t.param,
                "value": t.value,
            }
            for t in match.triggered
        ],
        "context": {
            "low_resonance": er.low_resonance,
            "high_resonance": er.high_resonance,
            "positions": {
                str(p.period): p.position_pct
                for p in er.periods
                if not p.insufficient
            },
        },
        "valuation": _valuation_public_dict(getattr(er, "valuation", None)),
        "fundamentals": _fundamentals_public_dict(getattr(er, "fundamentals", None)),
        "moneyflow": _moneyflow_public_dict(getattr(er, "moneyflow", None)),
        "technical": _technical_public_dict(getattr(er, "technical", None)),
        "sentiment": _sentiment_public_dict(getattr(er, "sentiment", None)),
        "chip": _chip_public_dict(getattr(er, "chip", None)),
        "shareholder": _shareholder_public_dict(getattr(er, "shareholder", None)),
        "relative_strength": _relative_strength_public_dict(
            getattr(er, "relative_strength", None)
        ),
    }


def _retail_fact_dict(result: StockScanResult) -> dict:
    """散户体验事实字段 · 顶层输出,不表达交易动作。"""
    return {
        "lot_cost": result.lot_cost,
        "cash_usage_pct": result.cash_usage_pct,
        "market_board": result.market_board,
        "permission_note": result.permission_note,
        "volume_price_state": result.volume_price_state,
    }


def _triggered_filters_public(match: FindMatch) -> list[dict]:
    """TriggeredFilter tuple → JSON public audit trail."""
    return [
        {
            "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
            "param": t.param,
            "value": t.value,
        }
        for t in match.triggered
    ]


def _positions_dict(result: StockScanResult) -> dict:
    """StockScanResult.periods → compact positions dict."""
    return {
        str(p.period): p.position_pct
        for p in result.periods
        if not p.insufficient
    }


def _gains_dict(result: StockScanResult) -> dict:
    """StockScanResult.periods → compact gains dict (only populated values)."""
    return {
        str(p.period): p.gain_pct
        for p in result.periods
        if not p.insufficient and p.gain_pct is not None
    }


def _pick_non_null(data: dict | None, keys: tuple[str, ...]) -> dict | None:
    """Select keys and drop all-null dimension summaries."""
    if data is None:
        return None
    picked = {k: data.get(k) for k in keys if k in data}
    def has_value(value: object) -> bool:
        if isinstance(value, dict):
            return any(has_value(v) for v in value.values())
        return value is not None

    return picked if any(has_value(v) for v in picked.values()) else None


def _compact_dimension_summary(dim: str, obj: object | None) -> dict | None:
    """Full dimension object → compact summary used by --compact."""
    if dim == "valuation":
        return _pick_non_null(
            _valuation_public_dict(obj),  # type: ignore[arg-type]
            ("trade_date", "pe_ttm", "pb", "ps_ttm", "dv_ttm", "turnover_rate", "total_mv", "source"),
        )
    if dim == "fundamentals":
        return _pick_non_null(
            _fundamentals_public_dict(obj),  # type: ignore[arg-type]
            ("end_date", "roe", "netprofit_yoy", "or_yoy", "source"),
        )
    if dim == "moneyflow":
        return _pick_non_null(
            _moneyflow_public_dict(obj),  # type: ignore[arg-type]
            (
                "trade_date", "net_amount", "net_amount_5d", "buy_elg_amount",
                "buy_lg_amount", "inflow_days", "source",
            ),
        )
    if dim == "technical":
        return _pick_non_null(
            _technical_public_dict(obj),  # type: ignore[arg-type]
            ("trade_date", "rsi_6", "macd_dif", "macd", "kdj_j", "ma_bias", "atr_pct", "source"),
        )
    if dim == "sentiment":
        return _pick_non_null(
            _sentiment_public_dict(obj),  # type: ignore[arg-type]
            (
                "trade_date", "limit_times", "open_times", "first_time",
                "last_time", "fd_amount", "limit", "source",
            ),
        )
    if dim == "chip":
        return _pick_non_null(
            _chip_public_dict(obj),  # type: ignore[arg-type]
            ("trade_date", "winner_rate", "source"),
        )
    if dim == "shareholder":
        return _pick_non_null(
            _shareholder_public_dict(obj),  # type: ignore[arg-type]
            (
                "holder_end_date", "holder_chg_pct", "top10_end_date",
                "top10_float_ratio", "north_hold_ratio", "source",
            ),
        )
    return None


def _find_result_compact_dict(
    match: FindMatch,
    enriched: EnrichedResult,
    *,
    included_dimensions: set[str],
    include_context: bool = True,
) -> dict:
    """单只命中 → compact JSON 对象.

    compact 只保留首轮筛选常用字段:身份、价格、触发 filter、位置/共振,
    以及本次已取数维度的少量摘要。维度被请求但无数据时保留 None,让调用方
    区分“缺数据”和“未请求”。
    """
    er = enriched
    result: dict = {
        "code": er.symbol,
        "name": er.name.replace(" ", ""),
        "price": er.current_price,
        "data_time": er.scan_date.isoformat(),
        "triggered_filters": _triggered_filters_public(match),
        **_retail_fact_dict(er),
    }
    if include_context:
        result.update({
            "positions": _positions_dict(er),
            "low_resonance": er.low_resonance,
            "high_resonance": er.high_resonance,
        })
        gains = _gains_dict(er)
        if gains:
            result["gains"] = gains
        if er.up_days:
            result["up_days"] = er.up_days
    if er.is_st:
        result["is_st"] = True
    if er.limit_up:
        result["limit_up"] = True
    if er.limit_down:
        result["limit_down"] = True
    for dim in DATA_DIMENSIONS:
        if dim in included_dimensions:
            result[dim] = _compact_dimension_summary(dim, getattr(er, dim, None))
    return result


def _object_has_dimension_data(dim: str, obj: object | None) -> bool:
    """Return True when the dimension object carries at least one useful value."""
    if obj is None:
        return False
    return any(getattr(obj, field, None) is not None for field in DIMENSION_DATA_FIELDS[dim])


def _infer_included_dimensions(items: Sequence[object]) -> set[str]:
    """Fallback for direct unit calls that do not pass included_dimensions."""
    dims: set[str] = set()
    for item in items:
        for dim in DATA_DIMENSIONS:
            if getattr(item, dim, None) is not None:
                dims.add(dim)
    return dims


def _data_availability(
    items: Sequence[object],
    *,
    included_dimensions: set[str] | None = None,
    unsupported_dimensions: set[str] | None = None,
    basis: str = "candidate_pool",
) -> dict:
    """Build top-level data_availability stats for machine consumers.

    Counts are only meaningful for dimensions attempted by this command. Dimensions
    not fetched are marked not_requested; dimensions unsupported by the current mode
    are marked not_supported instead of being mistaken for zero facts.
    """
    included = included_dimensions if included_dimensions is not None else _infer_included_dimensions(items)
    unsupported = unsupported_dimensions or set()
    total = len(items)
    out: dict = {"basis": basis, "pool_size": total}
    for dim in DATA_DIMENSIONS:
        if dim in unsupported:
            out[dim] = {"status": "not_supported", "available": None, "missing": None}
            continue
        if dim not in included:
            out[dim] = {"status": "not_requested", "available": None, "missing": None}
            continue
        available = sum(1 for item in items if _object_has_dimension_data(dim, getattr(item, dim, None)))
        out[dim] = {
            "status": "included",
            "available": available,
            "missing": total - available,
        }
    return out


def _nested_get(source: dict, path: tuple[str, ...]) -> object:
    current: object = source
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _nested_set(target: dict, path: tuple[str, ...], value: object) -> None:
    current = target
    for part in path[:-1]:
        current = current.setdefault(part, {})
    current[path[-1]] = value


def _select_find_fields(source: dict, fields: tuple[str, ...]) -> dict:
    """Select whitelisted result fields while preserving nested output paths."""
    out: dict = {}
    for field in fields:
        spec = FIND_FIELD_SPECS[field]
        _nested_set(out, spec.output_path, _nested_get(source, spec.output_path))
    return out


def _find_result_field_source(match: FindMatch, enriched: EnrichedResult) -> dict:
    """Full source dict used by --fields for normal find results."""
    source = _find_result_dict(match, enriched)
    source["context"]["gains"] = _gains_dict(enriched)
    source["context"]["up_days"] = enriched.up_days
    return source


def find_payload(
    entries: list[tuple[FindMatch, EnrichedResult]],
    *,
    query_time: str,
    pools: list[str],
    filters: list[dict],
    pool_size: int,
    matched_total: int,
    freshness: Freshness,
    compact: bool = False,
    availability_results: list[EnrichedResult] | None = None,
    included_dimensions: set[str] | None = None,
    compact_dimensions: set[str] | None = None,
    fields: tuple[str, ...] = (),
    compact_context: bool = True,
    match_mode: str = "all",
) -> dict:
    """kan find --format json 的结构化 payload (AI JSON 层 · AI 消费入口)。

    find JSON schema · 扩 context (位置/共振) + valuation (量价/市值客观事实)。

    Args:
        entries: 已 enrich + limit 后的 (FindMatch, EnrichedResult) 配对 · 顺序即输出序
        query_time: 查询发起时间 (ISO · caller 注入 · 利于测试确定性)
        pools: 候选池标识 (例 ["industry:半导体"] / ["watchlist"])
        filters: rule.filters · 每项 {"name": "--pos", "param": "180:lt:5"}
        pool_size: 池内总股票数 (筛前)
        matched_total: limit 前的总命中数 (stats.matched · len(entries)=shown)
        freshness: 数据新鲜度 (data_cutoff / stale)

    强制 disclaimer 字段 (compliance §5/§7 · 项目内强制输出 · 测试守护)。
    """
    from kan.render.base import FIND_DISCLAIMER_TEXT

    availability_source = availability_results if availability_results is not None else [
        er for _, er in entries
    ]
    result_dimensions = (
        compact_dimensions
        if compact_dimensions is not None
        else dimensions_from_filters(filters)
    )
    if compact and not result_dimensions and compact_dimensions is None:
        result_dimensions = _infer_included_dimensions(availability_source)

    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "result_schema": "fields" if fields else ("compact" if compact else "full"),
        "query_time": query_time,
        "rule": {"pools": pools, "filters": filters, "match": match_mode},
        "results": [
            _select_find_fields(_find_result_field_source(m, er), fields)
            if fields
            else (
                _find_result_compact_dict(
                    m,
                    er,
                    included_dimensions=result_dimensions,
                    include_context=compact_context,
                )
                if compact else _find_result_dict(m, er)
            )
            for m, er in entries
        ],
        "disclaimer": FIND_DISCLAIMER_TEXT,
        "data_availability": _data_availability(
            availability_source,
            included_dimensions=included_dimensions,
        ),
        "stats": {
            "pool_size": pool_size,
            "matched": matched_total,
            "shown": len(entries),
            "data_cutoff": (
                freshness.data_cutoff.isoformat() if freshness.data_cutoff else None
            ),
            "stale": freshness.is_stale,
        },
    }


def code_pool_payload(
    pairs: list[tuple[str, str]],
    *,
    query_time: str,
    pools: list[str],
    fields: tuple[str, ...] = (),
) -> dict:
    """`kan find --codes ... --format json` without filters.

    Explicit code pools should be able to act as a cheap metadata provider.
    Pulling K-line data just to echo the user-supplied pool makes first-run JSON
    automation depend on slow external sources.
    """
    from kan.render.base import FIND_DISCLAIMER_TEXT

    allowed = {"code", "name", "market_board", "permission_note"}
    selected = tuple(fields or ("code", "name"))
    unsupported = [f for f in selected if f not in allowed]
    if unsupported:
        raise ValueError(
            "外部代码池无 filter 取数只支持 code/name/market_board/permission_note 字段；"
            f"不支持: {', '.join(unsupported)}"
        )

    def _row(code: str, name: str) -> dict:
        from kan.core.retail_facts import market_board, permission_note

        source = {
            "code": code,
            "name": name.replace(" ", ""),
            "market_board": market_board(code),
            "permission_note": permission_note(code),
        }
        return {k: source[k] for k in selected}

    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "mode": "code_pool",
        "result_schema": "fields" if fields else "code_pool",
        "query_time": query_time,
        "rule": {"pools": pools, "filters": []},
        "results": [_row(code, name) for code, name in pairs],
        "disclaimer": FIND_DISCLAIMER_TEXT,
        "data_availability": {
            dim: {"requested": False, "available": False, "coverage": 0.0}
            for dim in DATA_DIMENSIONS
        },
        "stats": {
            "pool_size": len(pairs),
            "matched": len(pairs),
            "shown": len(pairs),
            "data_cutoff": None,
            "stale": False,
        },
    }


def code_pool_markdown(pairs: list[tuple[str, str]], *, title: str) -> str:
    """Markdown for an explicit code pool without filters."""
    rows = [[name.replace(" ", ""), code] for code, name in pairs]
    table = md_table(["股票", "代码"], rows) if rows else "无代码"
    return f"# {title}\n\n{table}\n\n{_find_disclaimer_quote()}"


def find_markdown(
    entries: list[tuple[FindMatch, EnrichedResult]],
    *,
    title: str,
    pool_size: int,
    matched_total: int,
) -> str:
    """kan find --format md · 命中股票表 + 触发 filter + disclaimer (项目内强制输出)。"""
    headers = ["股票", "现价", "触发 filter", "低共振", "高共振"]
    rows: list[list[str]] = []
    for m, er in entries:
        name_short = er.name.replace(" ", "")
        tag = " 涨停" if er.limit_up else (" 跌停" if er.limit_down else "")
        st = " ST" if er.is_st else ""
        trigs = " · ".join(
            f"{TRIGGER_FLAG.get(t.filter_type, t.filter_type)}={t.param}@{t.value:g}"
            for t in m.triggered
        )
        rows.append([
            f"{name_short} {er.symbol}{tag}{st}",
            f"{er.current_price:.2f}",
            trigs or "—",
            f"×{er.low_resonance}" if er.low_resonance else "—",
            f"×{er.high_resonance}" if er.high_resonance else "—",
        ])
    head = f"# {title} · 命中 {matched_total} / {pool_size}"
    body = md_table(headers, rows) if rows else "_无股票符合您设置的所有 filter_"
    return f"{head}\n\n{body}\n\n{_find_disclaimer_quote()}"


# ── cross section (kan find --all 全市场截面取数 · 全市场截面层) ────────────────
