"""Web find 表单到 service request 的适配层。"""
from __future__ import annotations

import math
import shlex
from typing import Any

from fastapi import HTTPException

from kan.cli.helpers import _parse_codes
from kan.core.find_dsl import ConditionSet, FilterParseError
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
FILTER_TYPES = {"pos", "resonance", "pe", "moneyflow", "turnover", "dv"}
OPS = {"lt", "gt"}
MAX_FILTERS = 6


def run_web_find(payload: dict[str, Any]) -> dict[str, Any]:
    """执行 Web find 查询；只读本地缓存，不触发补数据。"""
    raw_pool = payload.get("pool")
    pool = _parse_pool(raw_pool if isinstance(raw_pool, dict) else {})
    filters = _parse_filters(payload.get("filters"))
    exclude_st = bool(payload.get("exclude_st"))
    if _filters_empty(filters) and not exclude_st:
        raise HTTPException(status_code=400, detail="请至少填写一个筛选条件")

    try:
        conditions = ConditionSet.from_flags(
            pos=filters.get("pos"),
            resonance=filters.get("resonance"),
            pe=filters.get("pe"),
            moneyflow=filters.get("moneyflow"),
            turnover=filters.get("turnover"),
            exclude_st=exclude_st,
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
            limit=50,
        )
        try:
            cs_result = run_find_cross_section(cs_request)
        except FindServiceError as e:
            detail = _service_error_detail(e, pool["type"])
            raise HTTPException(status_code=400, detail=detail) from e
        return _serialize_cross_section_result(cs_result, command=_build_cli_command(pool, filters, exclude_st))

    kline_request = FindKlineRequest(
        conditions=conditions,
        output=output_profile,
        code_pairs=pool.get("code_pairs"),
        industry=pool.get("industry"),
        theme=pool.get("theme"),
        only_watchlist=pool["type"] == "watchlist",
        only_holdings=pool["type"] == "holdings",
        allow_auto_fetch=False,
        limit=50,
    )
    try:
        kline_result = run_find_kline(kline_request)
    except FindServiceError as e:
        detail = _service_error_detail(e, pool["type"])
        raise HTTPException(status_code=400, detail=detail) from e
    if not isinstance(kline_result, FindKlineResult):
        raise HTTPException(status_code=400, detail="当前查询没有可展示的 K 线结果")
    return _serialize_find_result(kline_result, command=_build_cli_command(pool, filters, exclude_st))


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
    out: dict[str, list[str]] = {"pos": [], "resonance": [], "pe": [], "moneyflow": []}
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="筛选条件格式错误")
        kind = str(item.get("type") or "").strip()
        if kind not in FILTER_TYPES:
            raise HTTPException(status_code=400, detail="暂不支持这个筛选条件")
        out[kind].append(_filter_param(kind, item))
    return out


def _filter_param(kind: str, item: dict[str, Any]) -> str:
    if kind == "pos":
        period = str(item.get("period") or "").strip()
        op = str(item.get("op") or "").strip()
        value = str(item.get("value") or "").strip()
        _require(op in OPS and bool(period) and bool(value), "--pos 需要周期、lt/gt 和数值")
        return f"{period}:{op}:{value}"
    if kind == "resonance":
        level = str(item.get("level") or "").strip()
        value = str(item.get("value") or "").strip()
        _require(level in {"low", "high"} and bool(value), "--resonance 需要 low/high 和数值")
        return f"{level}:gte:{value}"
    op = str(item.get("op") or "").strip()
    value = str(item.get("value") or "").strip()
    flag = "--pe" if kind == "pe" else "--moneyflow"
    _require(op in OPS and bool(value), f"{flag} 需要 lt/gt 和数值")
    return f"{op}:{value}"


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
            "triggered_text": _web_triggered_text(match),
            "metrics": _metrics(row, result.compact_dimensions),
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
    for row, triggered in result.limited:
        triggered_text = [f"{t.filter_type} {t.param}" for t in triggered]
        # 从 scan 结果提取位置数据
        positions: dict[str, float | None] = {"30": None, "60": None, "180": None}
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
            "triggered_text": triggered_text,
            "metrics": [],
            "positions": positions,
        })
    return {
        "ok": True,
        "title": "符合条件的股票",
        "command": command,
        "filters": result.filters,
        "pools": ["全市场"],
        "periods": [30, 60, 180],
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
            if triggered.filter_type != "pos":
                continue
            period = triggered.param.partition(":")[0]
            if period.isdigit():
                requested.add(int(period))
    return sorted(available & requested)


def _web_triggered_text(match) -> list[str]:
    labels: list[str] = []
    for triggered in match.triggered:
        parts = triggered.param.split(":")
        actual = triggered.value
        if triggered.filter_type == "pos" and len(parts) == 3:
            period, op, threshold = parts
            labels.append(
                f"{period} 日位置{_op_text(op)} {threshold}%，当前 {actual:.1f}%"
            )
        elif triggered.filter_type == "resonance" and len(parts) == 3:
            level, _op, threshold = parts
            direction = "低位" if level == "low" else "高位"
            labels.append(
                f"至少 {threshold} 个周期接近{direction}，当前 {actual:.0f} 个"
            )
        elif triggered.filter_type == "pe" and len(parts) == 2:
            op, threshold = parts
            labels.append(f"市盈率{_op_text(op)} {threshold}，当前 {actual:.2f}")
        elif triggered.filter_type == "moneyflow" and len(parts) == 2:
            op, threshold = parts
            labels.append(
                f"主力资金净额{_op_text(op)} {threshold} 万元，当前 {actual:.2f} 万元"
            )
        else:
            labels.append("已满足当前条件")
    return labels


def _op_text(op: str) -> str:
    return "低于" if op == "lt" else "高于"


def _metrics(row: Any, dimensions: set[str]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    if "valuation" in dimensions:
        valuation = getattr(row, "valuation", None)
        metrics.append({"label": "PE TTM", "value": _round(getattr(valuation, "pe_ttm", None))})
    if "moneyflow" in dimensions:
        moneyflow = getattr(row, "moneyflow", None)
        metrics.append({"label": "主力净额", "value": _round(getattr(moneyflow, "net_amount", None))})
        metrics.append({"label": "主力净额5日", "value": _round(getattr(moneyflow, "net_amount_5d", None))})
    return metrics


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
    return error.message


def _build_cli_command(pool: dict[str, Any], filters: dict[str, list[str]], exclude_st: bool) -> str:
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
    for flag in ("pos", "resonance", "pe", "moneyflow"):
        for value in filters.get(flag, []):
            parts.extend([f"--{flag}", value])
    if exclude_st:
        parts.append("--exclude-st")
    parts.extend(["--format", "json"])
    return " ".join(shlex.quote(part) for part in parts)
