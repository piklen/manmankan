"""Web find 表单到 service request 的适配层。"""
from __future__ import annotations

import math
import shlex
from typing import Any

from fastapi import HTTPException

from kan.cli.helpers import _parse_codes
from kan.core.find_dsl import ALLOWED_OPS, ConditionSet, FilterParseError
from kan.core.find_registry import FILTER_SPECS
from kan.render.base import FIND_DISCLAIMER_TEXT
from kan.service.find_service import (
    FindCrossSectionRequest,
    FindCrossSectionResult,
    FindKlineRequest,
    FindKlineResult,
    FindOutputProfile,
    FindServiceError,
    run_find_cross_section,
    run_find_kline,
)
from kan.storage import watchlist

POOL_TYPES = {"watchlist", "holdings", "codes", "industry", "theme", "all"}
FILTER_TYPES = set(FILTER_SPECS) - {"exclude_st"}
OPS = set(ALLOWED_OPS)
PERIOD_FILTERS = {"pos", "gain", "ma_bias", "rs_index", "rs_board"}
MAX_FILTERS = 12
WEB_RESULT_LIMIT = 10_000

_WEB_FILTER_GROUPS = (
    (
        "价格位置与趋势",
        (
            ("pos", "价格区间位置", "%", "period"),
            ("resonance", "多周期位置共振", "周期", "resonance"),
            ("gain", "区间涨跌幅", "%", "period"),
            ("up_days", "连续阳线天数", "天", "scalar"),
            ("ma_bias", "均线乖离率", "%", "period"),
            ("rs_index", "相对大盘涨幅差", "百分点", "period"),
            ("rs_board", "相对行业涨幅差", "百分点", "period"),
        ),
    ),
    (
        "估值、质量与交易",
        (
            ("pe", "市盈率 PE TTM", "倍", "scalar"),
            ("pb", "市净率 PB", "倍", "scalar"),
            ("dv", "股息率 TTM", "%", "scalar"),
            ("roe", "净资产收益率 ROE", "%", "scalar"),
            ("turnover", "换手率", "%", "scalar"),
            ("market_cap", "总市值", "亿元", "scalar"),
            ("volume_ratio", "量比", "倍", "scalar"),
        ),
    ),
    (
        "资金、技术与筹码",
        (
            ("moneyflow", "主力净额（近5日优先）", "万元", "scalar"),
            ("moneyflow_daily", "单日主力净额", "万元", "scalar"),
            ("moneyflow_days", "连续主力净流入", "天", "scalar"),
            ("rsi", "RSI（6日）", "", "scalar"),
            ("macd_dif", "MACD DIF", "", "scalar"),
            ("macd", "MACD 柱", "", "scalar"),
            ("kdj_j", "KDJ J值", "", "scalar"),
            ("atr_pct", "ATR 波动率", "%", "scalar"),
            ("winner", "获利盘比例", "%", "scalar"),
            ("streak", "连板天数", "天", "scalar"),
        ),
    ),
    (
        "股东与持股结构",
        (
            ("holders", "股东户数环比", "%", "scalar"),
            ("top10", "前十大流通集中度", "%", "scalar"),
            ("north", "北向持股比例", "%", "scalar"),
        ),
    ),
)

WEB_FILTER_BY_TYPE = {
    filter_type: {
        "type": filter_type,
        "label": label,
        "unit": unit,
        "input": input_kind,
        "flag": FILTER_SPECS[filter_type].flag,
        "supports_all": FILTER_SPECS[filter_type].supports_all,
    }
    for _group, options in _WEB_FILTER_GROUPS
    for filter_type, label, unit, input_kind in options
}


def web_filter_groups() -> list[dict[str, Any]]:
    """返回 Web 表单元数据；可选项必须与核心 FILTER_SPECS 同源。"""
    return [
        {
            "label": group,
            "options": [WEB_FILTER_BY_TYPE[filter_type] for filter_type, *_ in options],
        }
        for group, options in _WEB_FILTER_GROUPS
    ]


def run_web_find(payload: dict[str, Any]) -> dict[str, Any]:
    """执行 Web find 查询；只读本地缓存，不触发补数据。"""
    raw_pool = payload.get("pool")
    pool = _parse_pool(raw_pool if isinstance(raw_pool, dict) else {})
    filters = _parse_filters(payload.get("filters"))
    exclude_st = bool(payload.get("exclude_st"))
    match_any = bool(payload.get("match_any"))
    if _filters_empty(filters) and not exclude_st:
        raise HTTPException(status_code=400, detail="请至少填写一个筛选条件")
    if pool["type"] == "all":
        unsupported = [
            FILTER_SPECS[kind].flag
            for kind, values in filters.items()
            if values and not FILTER_SPECS[kind].supports_all
        ]
        if unsupported:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"全市场暂不支持 {'、'.join(unsupported)}；"
                    "请改用自选、持仓、行业、题材或自定义代码池"
                ),
            )

    try:
        conditions = ConditionSet.from_flags(
            **filters,
            exclude_st=exclude_st,
            match_any=match_any,
        )
    except FilterParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    output_profile = FindOutputProfile(
        mode="json",
        compact=True,
        compact_context=True,
        field_paths=("code",),
    )

    # 全市场模式使用 cross-section 路径
    if pool["type"] == "all":
        cs_request = FindCrossSectionRequest(
            conditions=conditions,
            output=output_profile,
            source_mode=False,
            limit=WEB_RESULT_LIMIT,
        )
        try:
            cs_result = run_find_cross_section(cs_request)
        except FindServiceError as e:
            detail = _service_error_detail(e, pool["type"])
            raise HTTPException(status_code=400, detail=detail) from e
        return _serialize_cross_section_result(
            cs_result,
            command=_build_cli_command(pool, filters, exclude_st, match_any),
        )

    kline_request = FindKlineRequest(
        conditions=conditions,
        output=output_profile,
        code_pairs=pool.get("code_pairs"),
        industry=pool.get("industry"),
        theme=pool.get("theme"),
        only_watchlist=pool["type"] == "watchlist",
        only_holdings=pool["type"] == "holdings",
        allow_auto_fetch=False,
        limit=WEB_RESULT_LIMIT,
    )
    try:
        kline_result = run_find_kline(kline_request)
    except FindServiceError as e:
        detail = _service_error_detail(e, pool["type"])
        raise HTTPException(status_code=400, detail=detail) from e
    if not isinstance(kline_result, FindKlineResult):
        raise HTTPException(status_code=400, detail="当前查询没有可展示的 K 线结果")
    return _serialize_find_result(
        kline_result,
        command=_build_cli_command(pool, filters, exclude_st, match_any),
    )


def _parse_pool(raw: dict[str, Any]) -> dict[str, Any]:
    pool_type = str(raw.get("type") or "").strip()
    if pool_type not in POOL_TYPES:
        raise HTTPException(status_code=400, detail="请选择候选池")
    value = str(raw.get("value") or "").strip()
    if pool_type == "codes":
        codes, invalid = _parse_codes(value)
        if invalid:
            raise HTTPException(status_code=400, detail=f"自定义代码含非法代码: {', '.join(invalid[:5])}")
        if not codes:
            raise HTTPException(status_code=400, detail="请填写自定义代码")
        names = watchlist.load_stock_names_cache(allow_stale=True) or {}
        return {"type": pool_type, "value": value, "code_pairs": [(c, names.get(c, c)) for c in codes]}
    if pool_type in {"industry", "theme"} and not value:
        label = "行业" if pool_type == "industry" else "题材"
        raise HTTPException(status_code=400, detail=f"请填写{label}名称")
    out: dict[str, Any] = {"type": pool_type, "value": value}
    if pool_type == "industry":
        out["industry"] = value
    if pool_type == "theme":
        out["theme"] = value
    return out


def _filters_empty(filters: dict[str, list[str]]) -> bool:
    return all(not values for values in filters.values())


def _parse_filters(raw: Any) -> dict[str, list[str]]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="筛选条件格式错误")
    if len(raw) > MAX_FILTERS:
        raise HTTPException(status_code=400, detail=f"最多同时填写 {MAX_FILTERS} 条筛选条件")
    out: dict[str, list[str]] = {kind: [] for kind in FILTER_TYPES}
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="筛选条件格式错误")
        kind = str(item.get("type") or "").strip()
        if kind not in FILTER_TYPES:
            raise HTTPException(status_code=400, detail="暂不支持这个筛选条件")
        out[kind].append(_filter_param(kind, item))
    return out


def _filter_param(kind: str, item: dict[str, Any]) -> str:
    if kind in PERIOD_FILTERS:
        period = _field_text(item, "period")
        op = _field_text(item, "op")
        value = _field_text(item, "value")
        flag = FILTER_SPECS[kind].flag
        _require(op in OPS and bool(period) and bool(value), f"{flag} 需要周期、比较方式和数值")
        return f"{period}:{op}:{value}"
    if kind == "resonance":
        level = _field_text(item, "level")
        op = _field_text(item, "op")
        value = _field_text(item, "value")
        _require(
            level in {"low", "high"} and op in OPS and bool(value),
            "--resonance 需要方向、比较方式和数值",
        )
        return f"{level}:{op}:{value}"
    op = _field_text(item, "op")
    value = _field_text(item, "value")
    flag = FILTER_SPECS[kind].flag
    _require(op in OPS and bool(value), f"{flag} 需要比较方式和数值")
    return f"{op}:{value}"


def _field_text(item: dict[str, Any], key: str) -> str:
    """表单数字 0 也是有效值，不能用 ``value or ''`` 吞掉。"""
    value = item.get(key)
    return "" if value is None else str(value).strip()


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise HTTPException(status_code=400, detail=message)


def _serialize_find_result(result: FindKlineResult, *, command: str) -> dict[str, Any]:
    rows = []
    periods = _display_periods(result)
    for match in result.matches_limited:
        row = match.result
        rows.append({
            "code": row.symbol,
            "name": row.name.replace(" ", ""),
            "price": _round(row.current_price),
            "in_watchlist": bool(getattr(row, "in_watchlist", False)),
            "triggered_text": _web_triggered_text(match),
            "metrics": _trigger_metrics(match.triggered),
            "sort_values": _trigger_sort_values(match.triggered),
            "positions": {
                str(p.period): None if p.insufficient else _round(p.position_pct, 1)
                for p in row.periods if p.period in periods
            },
        })
    skipped_no_cache = max(0, len(result.ctx.targets) - len(result.ctx.results))
    return {
        "ok": True,
        "title": "符合条件的股票",
        "command": command,
        "filters": result.filters,
        "pools": result.pools,
        "periods": periods,
        "rows": rows,
        "stats": {
            "targets": len(result.ctx.targets),
            "pool_size": len(result.ctx.results),
            "matched": len(result.matches),
            "shown": len(rows),
            "skipped_no_cache": skipped_no_cache,
            "data_cutoff": (
                result.ctx.freshness.data_cutoff.isoformat()
                if result.ctx.freshness.data_cutoff else None
            ),
            "stale": result.ctx.freshness.is_stale,
        },
        "message": _gap_message(skipped_no_cache),
        "disclaimer": FIND_DISCLAIMER_TEXT,
    }


def _serialize_cross_section_result(result: FindCrossSectionResult, *, command: str) -> dict[str, Any]:
    """序列化全市场 cross-section 结果。"""
    rows = []
    try:
        watchlist_symbols = {stock.symbol for stock in watchlist.list_all()}
    except Exception:
        watchlist_symbols = set()
    periods = {30, 60, 180}
    for _row, triggered in result.limited:
        for item in triggered:
            if item.filter_type in PERIOD_FILTERS:
                raw_period = item.param.partition(":")[0]
                if raw_period.isdigit():
                    periods.add(int(raw_period))
    display_periods = sorted(periods)
    for row, triggered in result.limited:
        triggered_text = _web_triggered_text(triggered)
        # 从 scan 结果提取位置数据
        positions: dict[str, float | None] = {
            str(period): None for period in display_periods
        }
        price: float | None = None
        if row.scan is not None:
            price = row.scan.current_price
            for p in row.scan.periods:
                key = str(p.period)
                if key in positions and not p.insufficient:
                    positions[key] = _round(p.position_pct, 1)
        rows.append({
            "code": row.code,
            "name": row.name.replace(" ", "") if row.name else row.code,
            "price": _round(price),
            "in_watchlist": row.code in watchlist_symbols,
            "triggered_text": triggered_text,
            "metrics": _trigger_metrics(triggered),
            "sort_values": _trigger_sort_values(triggered),
            "positions": positions,
        })
    return {
        "ok": True,
        "title": "符合条件的股票",
        "command": command,
        "filters": result.filters,
        "pools": ["全市场"],
        "periods": display_periods,
        "rows": rows,
        "stats": {
            "targets": result.ctx.pool_size,
            "pool_size": result.ctx.pool_size,
            "matched": len(result.matched),
            "shown": len(rows),
            "skipped_no_cache": 0,
            "data_cutoff": (
                result.ctx.data_cutoff.isoformat() if result.ctx.data_cutoff else None
            ),
            "stale": result.ctx.stale,
        },
        "message": None,
        "disclaimer": FIND_DISCLAIMER_TEXT,
    }


def _display_periods(result: FindKlineResult) -> list[int]:
    available = {period.period for match in result.matches_limited for period in match.result.periods}
    requested = {30, 60, 180}
    for match in result.matches_limited:
        for triggered in match.triggered:
            if triggered.filter_type not in PERIOD_FILTERS:
                continue
            period = triggered.param.partition(":")[0]
            if period.isdigit():
                requested.add(int(period))
    return sorted(available & requested)


def _web_triggered_text(match_or_triggered: Any) -> list[str]:
    triggered_items = getattr(match_or_triggered, "triggered", match_or_triggered)
    labels: list[str] = []
    for triggered in triggered_items:
        parts = triggered.param.split(":")
        actual = triggered.value
        meta = WEB_FILTER_BY_TYPE.get(triggered.filter_type)
        label = meta["label"] if meta else triggered.filter_type
        unit = meta["unit"] if meta else ""
        unit_suffix = f"{unit}" if unit else ""
        if triggered.filter_type in PERIOD_FILTERS and len(parts) == 3:
            period, op, threshold = parts
            labels.append(
                f"{period} 日{label}{_op_text(op)} {threshold}{unit_suffix}，"
                f"当前 {_format_actual(actual)}{unit_suffix}"
            )
        elif triggered.filter_type == "resonance" and len(parts) == 3:
            level, op, threshold = parts
            direction = "低位" if level == "low" else "高位"
            labels.append(
                f"接近{direction}的周期数{_op_text(op)} {threshold}，当前 {actual:.0f} 个"
            )
        elif len(parts) == 2:
            op, threshold = parts
            labels.append(
                f"{label}{_op_text(op)} {threshold}{unit_suffix}，"
                f"当前 {_format_actual(actual)}{unit_suffix}"
            )
        else:
            labels.append(f"{label}已满足当前条件")
    return labels


def _op_text(op: str) -> str:
    return {
        "lt": "低于",
        "lte": "不高于",
        "gt": "高于",
        "gte": "不低于",
        "eq": "等于",
        "ne": "不等于",
    }.get(op, op)


def _format_actual(value: float) -> str:
    rounded = round(float(value), 2)
    return f"{rounded:g}"


def _trigger_metrics(triggered_items: Any) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for triggered in triggered_items:
        if triggered.filter_type in {"pos", "resonance"}:
            continue
        meta = WEB_FILTER_BY_TYPE.get(triggered.filter_type)
        if not meta:
            continue
        key = _trigger_sort_key(triggered)
        if key in seen:
            continue
        seen.add(key)
        metrics.append({
            "label": meta["label"],
            "value": _round(triggered.value),
            "unit": meta["unit"],
        })
    return metrics


def _trigger_sort_key(triggered: Any) -> str:
    parts = triggered.param.split(":")
    if triggered.filter_type in PERIOD_FILTERS and parts:
        return f"{triggered.filter_type}:{parts[0]}"
    if triggered.filter_type == "resonance" and parts:
        return f"resonance:{parts[0]}"
    return triggered.filter_type


def _trigger_sort_values(triggered_items: Any) -> dict[str, float | None]:
    return {
        _trigger_sort_key(triggered): _round(triggered.value)
        for triggered in triggered_items
    }


def _round(value: float | None, digits: int = 2) -> float | None:
    # 见 serialize._round:NaN/Inf → None,防 Starlette allow_nan=False 渲染 500。
    if value is None:
        return None
    f = float(value)
    return None if math.isnan(f) or math.isinf(f) else round(f, digits)


def _gap_message(skipped_no_cache: int) -> str | None:
    if skipped_no_cache <= 0:
        return None
    return f"{skipped_no_cache} 只股票无本地缓存,已跳过"


def _service_error_detail(error: FindServiceError, pool_type: str) -> str:
    if pool_type in {"industry", "theme"} and error.code == "data_unavailable":
        return "该池大部分股票无本地缓存,请先在看盘台补数据或先跑 CLI"
    if pool_type == "all" and error.code == "data_unavailable":
        return (
            f"{error.message}。全市场筛选需要 TuShare 数据；"
            "请到“数据设置”配置 token，或改查自选、持仓、自定义代码"
        )
    return f"{error.message}。{error.hint}" if error.hint else error.message


def _build_cli_command(
    pool: dict[str, Any],
    filters: dict[str, list[str]],
    exclude_st: bool,
    match_any: bool = False,
) -> str:
    parts = ["kan", "find"]
    pool_type = pool["type"]
    if pool_type == "watchlist":
        parts.append("--only-watchlist")
    elif pool_type == "holdings":
        parts.append("--only-holdings")
    elif pool_type == "codes":
        parts.extend(["--codes", str(pool["value"])])
    elif pool_type == "industry":
        parts.extend(["--industry", str(pool["value"])])
    elif pool_type == "theme":
        parts.extend(["--theme", str(pool["value"])])
    if match_any:
        parts.append("--any")
    for filter_type, spec in FILTER_SPECS.items():
        if filter_type == "exclude_st":
            continue
        for value in filters.get(filter_type, []):
            parts.extend([spec.flag, value])
    if exclude_st:
        parts.append("--exclude-st")
    parts.extend(["--format", "json"])
    return " ".join(shlex.quote(part) for part in parts)
