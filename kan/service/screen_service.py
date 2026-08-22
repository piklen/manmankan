"""选股工作台 application service。

本模块把稳定 ScreenSpec 翻译为既有 find engine 请求，并将两条 find 路径归一为
同一个 ScreenRun。CLI、HTTP、MCP 和 Python API 不得各自复制这段编排。
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime
from functools import cmp_to_key
from typing import Any
from uuid import uuid4

from pydantic_core import to_jsonable_python

from kan.core.find_dsl import ConditionSet, FilterParseError
from kan.core.find_filter_models import TriggeredFilter
from kan.core.find_registry import FILTER_SPECS
from kan.domain.screen import (
    Candidate,
    CandidateList,
    CandidateStatus,
    CompareSet,
    DataCoverage,
    MatchMode,
    NullPolicy,
    RankChange,
    SavedScreen,
    ScreenCondition,
    ScreenDiff,
    ScreenEvidence,
    ScreenRow,
    ScreenRun,
    ScreenScalar,
    ScreenSort,
    ScreenSpec,
    SortDirection,
    UniverseKind,
)
from kan.service.find_service import (
    FindCrossSectionRequest,
    FindKlineRequest,
    FindKlineResult,
    FindOutputProfile,
    FindServiceError,
    run_find_cross_section,
    run_find_kline,
)
from kan.service.screen_catalog import SCREEN_FILTER_CATALOG


class ScreenServiceError(Exception):
    """选股用例稳定错误，由入口映射为 CLI/HTTP/MCP 结果。"""

    def __init__(self, code: str, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def canonical_json(value: object) -> str:
    payload = to_jsonable_python(value)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _condition_flags(spec: ScreenSpec) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = {
        filter_type: [] for filter_type in SCREEN_FILTER_CATALOG
    }
    for condition in spec.conditions:
        flags[condition.type.value].append(condition.to_dsl())
    return flags


def condition_set_from_spec(spec: ScreenSpec) -> ConditionSet:
    try:
        return ConditionSet.from_flags(
            **_condition_flags(spec),
            exclude_st=spec.exclude_st,
            match_any=spec.match_mode is MatchMode.ANY,
        )
    except FilterParseError as exc:
        raise ScreenServiceError("invalid_condition", str(exc)) from exc


def _field_dimensions(spec: ScreenSpec) -> frozenset[str]:
    dims = {
        FILTER_SPECS[condition.type.value].dimension
        for condition in spec.conditions
        if FILTER_SPECS[condition.type.value].dimension is not None
    }
    field_prefix_dimensions = {
        "valuation",
        "fundamentals",
        "moneyflow",
        "technical",
        "sentiment",
        "chip",
        "shareholder",
        "relative_strength",
    }
    for field in [*spec.columns, *(item.field_id for item in spec.sort)]:
        prefix = field.partition(".")[0]
        if prefix in field_prefix_dimensions:
            dims.add(prefix)
    return frozenset(item for item in dims if item is not None)


def _output_profile(spec: ScreenSpec) -> FindOutputProfile:
    return FindOutputProfile(
        mode="json",
        compact=True,
        compact_context=True,
        field_paths=(),
        field_dimensions=_field_dimensions(spec),
    )


def _normalize_codes(codes: Sequence[str]) -> list[tuple[str, str]]:
    from kan.storage.watchlist import _normalize_symbol, load_stock_names_cache

    names = load_stock_names_cache(allow_stale=True) or {}
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in codes:
        try:
            symbol = _normalize_symbol(raw)
        except ValueError as exc:
            raise ScreenServiceError("invalid_codes", str(exc)) from exc
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append((symbol, names.get(symbol, symbol)))
    return out


def _run_engine(spec: ScreenSpec) -> tuple[list[tuple[object, tuple[TriggeredFilter, ...]]], DataCoverage]:
    if spec.as_of.trade_date != "latest_complete":
        raise ScreenServiceError(
            "unsupported_as_of",
            "当前选股运行只支持 latest_complete；历史回放必须使用已保存的 ScreenRun",
        )
    conditions = condition_set_from_spec(spec)
    output = _output_profile(spec)
    try:
        if spec.universe.kind is UniverseKind.ALL:
            unsupported = [
                condition.type.value
                for condition in spec.conditions
                if not FILTER_SPECS[condition.type.value].supports_all
            ]
            if unsupported:
                flags = "、".join(FILTER_SPECS[name].flag for name in unsupported)
                raise ScreenServiceError(
                    "unsupported_all_filters",
                    f"全市场暂不支持 {flags}",
                    hint="改用自选、持仓、行业、题材或自定义代码池",
                )
            cross_result = run_find_cross_section(
                FindCrossSectionRequest(
                    conditions=conditions,
                    output=output,
                    limit=10_000,
                )
            )
            matches: list[tuple[object, tuple[TriggeredFilter, ...]]] = [
                (row, triggered)
                for row, triggered in cross_result.matched
                if not (spec.exclude_star and row.code.startswith("688"))
                and not (spec.exclude_bj and row.code.startswith(("8", "9")))
            ]
            cutoff = cross_result.ctx.data_cutoff
            coverage = DataCoverage(
                universe_size=cross_result.ctx.pool_size,
                evaluated=len(cross_result.ctx.rows),
                matched=len(matches),
                returned=0,
                missing=max(0, cross_result.ctx.pool_size - len(cross_result.ctx.rows)),
                ratio=(len(cross_result.ctx.rows) / cross_result.ctx.pool_size)
                if cross_result.ctx.pool_size
                else 0,
                stale=cross_result.ctx.stale,
                data_cutoff=cutoff,
                missing_by_field=_missing_by_field(cross_result.ctx.rows, spec),
            )
            return matches, coverage

        universe = spec.universe
        request = FindKlineRequest(
            conditions=conditions,
            output=output,
            code_pairs=_normalize_codes(universe.codes)
            if universe.kind is UniverseKind.CODES else None,
            industry=universe.value if universe.kind is UniverseKind.INDUSTRY else None,
            theme=universe.value if universe.kind is UniverseKind.THEME else None,
            only_watchlist=universe.kind is UniverseKind.WATCHLIST,
            only_holdings=universe.kind is UniverseKind.HOLDINGS,
            exclude_star=spec.exclude_star,
            exclude_bj=spec.exclude_bj,
            allow_auto_fetch=False,
            group=universe.group,
            limit=10_000,
        )
        kline_result = run_find_kline(request)
        if not isinstance(kline_result, FindKlineResult):
            raise ScreenServiceError("data_unavailable", "当前股票池没有可执行的行情结果")
        matches = [(match.result, match.triggered) for match in kline_result.matches]
        coverage = DataCoverage(
            universe_size=len(kline_result.ctx.targets),
            evaluated=len(kline_result.ctx.results),
            matched=len(matches),
            returned=0,
            missing=max(
                0, len(kline_result.ctx.targets) - len(kline_result.ctx.results)
            ),
            ratio=(len(kline_result.ctx.results) / len(kline_result.ctx.targets))
            if kline_result.ctx.targets
            else 0,
            stale=kline_result.ctx.freshness.is_stale,
            data_cutoff=kline_result.ctx.freshness.data_cutoff,
            missing_by_field=_missing_by_field(kline_result.ctx.results, spec),
        )
        return matches, coverage
    except FindServiceError as exc:
        raise ScreenServiceError(exc.code, exc.message, hint=exc.hint) from exc


def _safe_number(value: object) -> float | int | None:
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return int(number) if isinstance(value, int) else number


def _date_value(value: object) -> date | None:
    return value if isinstance(value, date) else None


def _dimension_values(
    obj: object, prefix: str, fields: Sequence[str]
) -> dict[str, ScreenScalar]:
    holder = getattr(obj, prefix, None)
    if holder is None:
        return {}
    out: dict[str, ScreenScalar] = {}
    for field in fields:
        value = getattr(holder, field, None)
        if callable(value):
            continue
        if isinstance(value, date):
            out[f"{prefix}.{field}"] = value.isoformat()
        else:
            out[f"{prefix}.{field}"] = _safe_number(value)
    source = getattr(holder, "source", None)
    if source is not None:
        out[f"{prefix}.source"] = str(source)
    return out


_DIMENSION_FIELDS = {
    "valuation": (
        "close", "pe_ttm", "pb", "ps_ttm", "dv_ttm", "turnover_rate",
        "volume_ratio", "total_mv", "circ_mv", "trade_date",
    ),
    "fundamentals": ("roe", "netprofit_yoy", "or_yoy", "end_date"),
    "moneyflow": (
        "net_amount", "net_amount_5d", "buy_elg_amount", "buy_lg_amount",
        "inflow_days", "outflow_days", "trade_date",
    ),
    "technical": (
        "rsi_6", "macd_dif", "macd", "kdj_j", "atr", "trade_date",
    ),
    "sentiment": ("limit_times", "open_times", "fd_amount", "trade_date"),
    "chip": ("winner_rate", "cost_5pct", "cost_50pct", "cost_95pct", "trade_date"),
    "shareholder": (
        "holder_chg_pct", "top10_float_ratio", "north_hold_ratio",
        "holder_end_date", "top10_end_date",
    ),
}


def _base_result(obj: object) -> object | None:
    scan = getattr(obj, "scan", None)
    return scan if scan is not None else obj


def _row_values(obj: object, triggered: tuple[TriggeredFilter, ...]) -> tuple[
    str, str, float | None, bool, dict[str, ScreenScalar], dict[str, float | None]
]:
    base = _base_result(obj)
    symbol = str(getattr(base, "symbol", getattr(obj, "code", "")))
    name = str(getattr(base, "name", getattr(obj, "name", symbol))).replace(" ", "")
    price = _safe_number(getattr(base, "current_price", None))
    if price is None:
        valuation = getattr(obj, "valuation", None)
        price = _safe_number(getattr(valuation, "close", None))
    values: dict[str, ScreenScalar] = {
        "symbol": symbol,
        "name": name,
        "price": price,
        "low_resonance": _safe_number(getattr(base, "low_resonance", None)),
        "high_resonance": _safe_number(getattr(base, "high_resonance", None)),
        "up_days": _safe_number(getattr(base, "up_days", None)),
        "resonance.low": _safe_number(getattr(base, "low_resonance", None)),
        "resonance.high": _safe_number(getattr(base, "high_resonance", None)),
    }
    positions: dict[str, float | None] = {}
    for period in getattr(base, "periods", []) or []:
        key = str(period.period)
        position = None if period.insufficient else _safe_number(period.position_pct)
        positions[key] = None if position is None else float(position)
        values[f"position.{period.period}d"] = position
        values[f"gain.{period.period}d"] = _safe_number(period.gain_pct)
    for prefix, fields in _DIMENSION_FIELDS.items():
        values.update(_dimension_values(obj, prefix, fields))
    for period, value in (getattr(base, "ma_biases", {}) or {}).items():
        values[f"ma_bias.{period}d"] = _safe_number(value)
    relative = getattr(obj, "relative_strength", None)
    if relative is not None:
        for field in ("rs_index", "rs_board"):
            for period, value in (getattr(relative, field, {}) or {}).items():
                values[f"{field}.{period}d"] = _safe_number(value)
    technical = getattr(obj, "technical", None)
    if technical is not None:
        atr_pct = getattr(technical, "atr_pct", None)
        if callable(atr_pct):
            values["atr_pct"] = _safe_number(atr_pct())
    values.update(_filter_alias_values(values))
    for item in triggered:
        values[item.filter_type] = _safe_number(item.value)
        parts = item.param.split(":")
        if item.filter_type in {"pos", "gain", "ma_bias", "rs_index", "rs_board"}:
            if parts and parts[0].isdigit():
                values[f"{item.filter_type}.{parts[0]}d"] = _safe_number(item.value)
        elif item.filter_type == "resonance" and parts:
            values[f"resonance.{parts[0]}"] = _safe_number(item.value)
    return (
        symbol,
        name,
        None if price is None else float(price),
        bool(getattr(base, "in_watchlist", False)),
        values,
        positions,
    )


def _filter_alias_values(
    values: dict[str, ScreenScalar],
) -> dict[str, ScreenScalar]:
    """把领域字段投影为筛选/排序使用的稳定短字段。"""
    total_mv = values.get("valuation.total_mv")
    market_cap = (
        float(total_mv) / 10_000
        if isinstance(total_mv, (int, float)) else None
    )
    moneyflow = values.get("moneyflow.net_amount_5d")
    if moneyflow is None:
        moneyflow = values.get("moneyflow.net_amount")
    return {
        "pe": values.get("valuation.pe_ttm"),
        "pb": values.get("valuation.pb"),
        "dv": values.get("valuation.dv_ttm"),
        "turnover": values.get("valuation.turnover_rate"),
        "market_cap": market_cap,
        "volume_ratio": values.get("valuation.volume_ratio"),
        "roe": values.get("fundamentals.roe"),
        "moneyflow": moneyflow,
        "moneyflow_daily": values.get("moneyflow.net_amount"),
        "moneyflow_days": values.get("moneyflow.inflow_days"),
        "rsi": values.get("technical.rsi_6"),
        "macd_dif": values.get("technical.macd_dif"),
        "macd": values.get("technical.macd"),
        "kdj_j": values.get("technical.kdj_j"),
        "streak": values.get("sentiment.limit_times"),
        "winner": values.get("chip.winner_rate"),
        "holders": values.get("shareholder.holder_chg_pct"),
        "top10": values.get("shareholder.top10_float_ratio"),
        "north": values.get("shareholder.north_hold_ratio"),
    }


def _condition_lookup(spec: ScreenSpec) -> dict[tuple[str, str], ScreenCondition]:
    return {
        (condition.type.value, condition.to_dsl()): condition
        for condition in spec.conditions
    }


def _condition_field_id(condition: ScreenCondition) -> str:
    if condition.period is not None:
        return f"{condition.type.value}.{condition.period}d"
    if condition.level is not None:
        return f"{condition.type.value}.{condition.level}"
    return condition.type.value


def _missing_by_field(objects: Sequence[object], spec: ScreenSpec) -> dict[str, int]:
    counts = {_condition_field_id(item): 0 for item in spec.conditions}
    for obj in objects:
        _, _, _, _, values, _ = _row_values(obj, ())
        for condition in spec.conditions:
            field_id = _condition_field_id(condition)
            if values.get(field_id) is None:
                counts[field_id] += 1
    return {field: count for field, count in counts.items() if count}


def _source_and_date(obj: object, condition: ScreenCondition) -> tuple[str | None, date | None]:
    spec = FILTER_SPECS[condition.type.value]
    dimension = spec.dimension
    if dimension is None:
        base = _base_result(obj)
        return spec.source, _date_value(getattr(base, "scan_date", None))
    holder = getattr(obj, dimension, None)
    if holder is None:
        return spec.source, None
    data_date = (
        _date_value(getattr(holder, "trade_date", None))
        or _date_value(getattr(holder, "end_date", None))
        or _date_value(getattr(holder, "holder_end_date", None))
    )
    return str(getattr(holder, "source", spec.source)), data_date


def _evidence(
    *,
    run_id: str,
    obj: object,
    symbol: str,
    triggered: tuple[TriggeredFilter, ...],
    lookup: dict[tuple[str, str], ScreenCondition],
) -> list[ScreenEvidence]:
    out: list[ScreenEvidence] = []
    for index, item in enumerate(triggered):
        condition = lookup.get((item.filter_type, item.param))
        if condition is None:
            continue
        meta = SCREEN_FILTER_CATALOG[item.filter_type]
        source, data_date = _source_and_date(obj, condition)
        out.append(
            ScreenEvidence(
                evidence_ref=f"run:{run_id}:row:{symbol}:condition:{index}",
                filter_type=condition.type,
                field_id=(
                    _condition_field_id(condition)
                ),
                operator=condition.operator,
                threshold=condition.value,
                actual=float(item.value),
                unit=meta["unit"],
                period=condition.period,
                level=condition.level,
                data_date=data_date,
                source=source,
            )
        )
    return out


def _compare_values(left: object, right: object, direction: SortDirection) -> int:
    left_none = left is None
    right_none = right is None
    if left_none or right_none:
        if left_none and right_none:
            return 0
        return 1 if left_none else -1
    if left == right:
        return 0
    try:
        result = -1 if left < right else 1  # type: ignore[operator]
    except TypeError:
        result = -1 if str(left) < str(right) else 1
    return -result if direction is SortDirection.DESC else result


def _sort_rows(rows: list[ScreenRow], sort_specs: Sequence[ScreenSort]) -> list[ScreenRow]:
    if not sort_specs:
        return rows

    def compare(left: ScreenRow, right: ScreenRow) -> int:
        for item in sort_specs:
            result = _compare_values(
                left.values.get(item.field_id),
                right.values.get(item.field_id),
                item.direction,
            )
            if result:
                return result
        return -1 if left.symbol < right.symbol else (1 if left.symbol > right.symbol else 0)

    return sorted(rows, key=cmp_to_key(compare))


def _make_rows(
    *,
    run_id: str,
    spec: ScreenSpec,
    matches: Sequence[tuple[object, tuple[TriggeredFilter, ...]]],
) -> list[ScreenRow]:
    lookup = _condition_lookup(spec)
    rows: list[ScreenRow] = []
    for obj, triggered in matches:
        symbol, name, price, in_watchlist, values, positions = _row_values(obj, triggered)
        rows.append(
            ScreenRow(
                symbol=symbol,
                name=name,
                rank=0,
                price=price,
                in_watchlist=in_watchlist,
                values=values,
                positions=positions,
                evidence=_evidence(
                    run_id=run_id,
                    obj=obj,
                    symbol=symbol,
                    triggered=triggered,
                    lookup=lookup,
                ),
            )
        )
    rows = _sort_rows(rows, spec.sort)[: spec.limit]
    return [row.model_copy(update={"rank": index}) for index, row in enumerate(rows, 1)]


def _diff(previous: ScreenRun | None, rows: Sequence[ScreenRow]) -> ScreenDiff:
    if previous is None:
        return ScreenDiff(added=[row.symbol for row in rows])
    old_rank = {row.symbol: row.rank for row in previous.rows}
    new_rank = {row.symbol: row.rank for row in rows}
    old_symbols = set(old_rank)
    new_symbols = set(new_rank)
    changes = [
        RankChange(
            symbol=symbol,
            previous_rank=old_rank[symbol],
            current_rank=new_rank[symbol],
            delta=old_rank[symbol] - new_rank[symbol],
        )
        for symbol in sorted(old_symbols & new_symbols)
        if old_rank[symbol] != new_rank[symbol]
    ]
    changes.sort(key=lambda item: (-abs(item.delta), item.symbol))
    return ScreenDiff(
        previous_run_id=previous.run_id,
        added=sorted(new_symbols - old_symbols),
        removed=sorted(old_symbols - new_symbols),
        rank_changes=changes,
    )


def _enforce_missing_policy(spec: ScreenSpec, coverage: DataCoverage) -> None:
    if coverage.stale and spec.as_of.freshness_policy == "require_complete":
        raise ScreenServiceError(
            "stale_data",
            "行情数据尚未到达最新完整交易日",
            hint="先更新数据，或把 freshness_policy 改为 allow_stale",
        )
    fail_fields = {
        _condition_field_id(item)
        for item in spec.conditions
        if item.null_policy is NullPolicy.FAIL
    }
    field_missing = {
        field: count
        for field, count in coverage.missing_by_field.items()
        if field in fail_fields and count
    }
    if fail_fields and (coverage.missing or field_missing):
        details = "、".join(f"{field} 缺 {count}" for field, count in field_missing.items())
        if coverage.missing:
            details = f"行情缺 {coverage.missing}" + (f"、{details}" if details else "")
        raise ScreenServiceError(
            "incomplete_data",
            f"候选池存在不可接受的缺失数据：{details}",
            hint="更新数据或将条件 null_policy 改为 exclude",
        )


def _hashable_rows(rows: Sequence[ScreenRow]) -> list[dict[str, object]]:
    """生成不含运行 ID 的稳定结果摘要，保证相同输入得到相同内容哈希。"""
    return [
        row.model_dump(
            mode="json",
            exclude={"evidence": {"__all__": {"evidence_ref"}}},
        )
        for row in rows
    ]


def run_screen(
    spec: ScreenSpec,
    *,
    screen_id: str | None = None,
    screen_version: int | None = None,
    persist: bool = True,
) -> ScreenRun:
    """执行一份 ScreenSpec，并按需保存不可变运行。"""
    started = time.perf_counter()
    run_id = uuid4().hex
    spec_hash = content_hash(spec)
    previous: ScreenRun | None = None
    if screen_id is not None:
        from kan.storage.workspace_db import latest_run_for_screen

        previous = latest_run_for_screen(screen_id)
    matches, coverage = _run_engine(spec)
    _enforce_missing_policy(spec, coverage)
    rows = _make_rows(run_id=run_id, spec=spec, matches=matches)
    coverage = coverage.model_copy(update={"returned": len(rows)})
    warnings: list[str] = []
    if coverage.stale:
        warnings.append("行情数据可能需要更新")
    if coverage.missing:
        warnings.append(f"{coverage.missing} 只股票缺少可评估数据")
    if coverage.missing_by_field:
        detail = "、".join(
            f"{field} 缺 {count}" for field, count in coverage.missing_by_field.items()
        )
        warnings.append(f"条件字段缺失：{detail}")
    hashable_rows = _hashable_rows(rows)
    snapshot_id = content_hash(
        {
            "data_cutoff": coverage.data_cutoff,
            "universe_size": coverage.universe_size,
            "rows": hashable_rows,
        }
    )
    result_hash = content_hash(hashable_rows)
    run = ScreenRun(
        run_id=run_id,
        screen_id=screen_id,
        screen_version=screen_version,
        spec=spec,
        spec_hash=spec_hash,
        snapshot_id=snapshot_id,
        result_hash=result_hash,
        created_at=datetime.now(UTC),
        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        coverage=coverage,
        warnings=warnings,
        rows=rows,
        diff=_diff(previous, rows),
    )
    if persist:
        from kan.storage.workspace_db import save_run

        save_run(run)
    return run


def save_screen(spec: ScreenSpec, *, screen_id: str | None = None) -> SavedScreen:
    from kan.storage.workspace_db import save_screen as save

    return save(spec, content_hash(spec), screen_id=screen_id)


def run_saved_screen(screen_id: str) -> ScreenRun:
    from kan.storage.workspace_db import get_screen

    screen = get_screen(screen_id)
    if screen is None:
        raise ScreenServiceError("screen_not_found", f"Screen 不存在: {screen_id}")
    return run_screen(
        screen.spec,
        screen_id=screen.screen_id,
        screen_version=screen.current_version,
        persist=True,
    )


def list_screens() -> list[SavedScreen]:
    from kan.storage.workspace_db import list_screens as load

    return load()


def get_screen(screen_id: str) -> SavedScreen:
    from kan.storage.workspace_db import get_screen as load

    screen = load(screen_id)
    if screen is None:
        raise ScreenServiceError("screen_not_found", f"Screen 不存在: {screen_id}")
    return screen


def delete_screen(screen_id: str) -> None:
    from kan.storage.workspace_db import delete_screen as remove

    if not remove(screen_id):
        raise ScreenServiceError("screen_not_found", f"Screen 不存在: {screen_id}")


def get_run(run_id: str) -> ScreenRun:
    from kan.storage.workspace_db import get_run as load

    run = load(run_id)
    if run is None:
        raise ScreenServiceError("run_not_found", f"ScreenRun 不存在: {run_id}")
    return run


def list_runs(*, screen_id: str | None = None, limit: int = 50) -> list[ScreenRun]:
    from kan.storage.workspace_db import list_runs as load

    return load(screen_id=screen_id, limit=limit)


def list_candidate_lists() -> list[CandidateList]:
    from kan.storage.workspace_db import list_candidate_lists as load

    return load()


def add_candidate(
    *,
    list_id: str,
    symbol: str,
    name: str,
    source_run_id: str | None = None,
    status: CandidateStatus = CandidateStatus.RESEARCH,
    note: str = "",
) -> Candidate:
    from kan.storage.workspace_db import upsert_candidate

    return upsert_candidate(
        list_id=list_id,
        symbol=symbol,
        name=name,
        source_run_id=source_run_id,
        status=status,
        note=note,
    )


def remove_candidate(list_id: str, symbol: str) -> None:
    from kan.storage.workspace_db import remove_candidate as remove

    if not remove(list_id, symbol):
        raise ScreenServiceError(
            "candidate_not_found", f"候选池 {list_id} 中没有 {symbol}"
        )


def save_compare_set(name: str, symbols: list[str]) -> CompareSet:
    from kan.storage.workspace_db import save_compare_set as save

    return save(name, symbols)


def list_compare_sets() -> list[CompareSet]:
    from kan.storage.workspace_db import list_compare_sets as load

    return load()


def filter_catalog() -> list[dict[str, object]]:
    from kan.service.screen_catalog import screen_filter_groups

    return screen_filter_groups()


def screen_schema() -> dict[str, Any]:
    return ScreenSpec.model_json_schema()


def validate_evidence_claims(
    run: ScreenRun,
    evidence_refs: Sequence[str],
) -> None:
    """AI 解释层引用不存在的证据时 fail-fast。"""
    available = {
        item.evidence_ref
        for row in run.rows
        for item in row.evidence
    }
    missing = sorted(set(evidence_refs) - available)
    if missing:
        raise ScreenServiceError(
            "invalid_evidence_refs",
            f"解释引用了不存在的证据: {', '.join(missing[:5])}",
        )
