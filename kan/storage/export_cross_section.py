"""`kan find --all` 截面结果与 history 导出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.find_registry import (
    DATA_DIMENSIONS,
    DIMENSIONS_UNSUPPORTED_IN_ALL,
    TRIGGER_FLAG,
    dimensions_from_filters,
)
from kan.storage.export_base import (
    FIND_SCHEMA_VERSION,
    _disclaimer_quote,
    _disclaimer_text,
    md_table,
)
from kan.storage.export_find_dimensions import (
    _chip_public_dict,
    _moneyflow_public_dict,
    _relative_strength_public_dict,
    _sentiment_public_dict,
    _technical_public_dict,
    _valuation_public_dict,
)
from kan.storage.export_find_results import (
    _compact_dimension_summary,
    _data_availability,
    _find_disclaimer_quote,
    _gains_dict,
    _infer_included_dimensions,
    _positions_dict,
    _select_find_fields,
)

if TYPE_CHECKING:
    from datetime import date

    from kan.core.cross_section import CrossSectionRow
    from kan.core.find_filter import TriggeredFilter
    from kan.core.models import StockScanResult

def _scan_context_public_dict(scan: StockScanResult | None) -> dict | None:
    """`--all` K 线快照上下文 → JSON 裸值。

    只有 `kan find --all` 搭配位置 / 共振 / 涨幅 / 连阳 filter 时才会挂载 scan。
    无 K 线快照时返回 None,让调用方能区分"没请求/没数据"和"有快照但裸值为空"。
    """
    if scan is None:
        return None
    positions = {
        str(p.period): p.position_pct
        for p in scan.periods
        if not p.insufficient
    }
    gains = {
        str(p.period): p.gain_pct
        for p in scan.periods
        if not p.insufficient and p.gain_pct is not None
    }
    return {
        "low_resonance": scan.low_resonance,
        "high_resonance": scan.high_resonance,
        "up_days": scan.up_days,
        "positions": positions,
        "gains": gains,
    }


def _row_price(row: CrossSectionRow) -> float | None:
    if row.scan is not None:
        return row.scan.current_price
    return row.valuation.close if row.valuation is not None else None


def _row_data_time(row: CrossSectionRow) -> str | None:
    if row.scan is not None:
        return row.scan.scan_date.isoformat()
    for obj in (row.valuation, row.moneyflow, row.technical, row.sentiment, row.chip):
        trade_date = getattr(obj, "trade_date", None)
        if trade_date is not None:
            return trade_date.isoformat()
    return None


def _cross_section_result_compact_dict(
    row: CrossSectionRow,
    triggered: tuple[TriggeredFilter, ...] = (),
    *,
    included_dimensions: set[str],
    include_context: bool = True,
) -> dict:
    """单只截面取数结果 → compact JSON 对象."""
    result: dict = {
        "code": row.code,
        "name": row.name.replace(" ", ""),
        "price": _row_price(row),
        "data_time": _row_data_time(row),
        "triggered_filters": [
            {
                "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
                "param": t.param,
                "value": t.value,
            }
            for t in triggered
        ],
    }
    if include_context and row.scan is not None:
        result.update({
            "positions": _positions_dict(row.scan),
            "low_resonance": row.scan.low_resonance,
            "high_resonance": row.scan.high_resonance,
        })
        gains = _gains_dict(row.scan)
        if gains:
            result["gains"] = gains
        if row.scan.up_days:
            result["up_days"] = row.scan.up_days
    for dim in DATA_DIMENSIONS:
        if dim in included_dimensions and hasattr(row, dim):
            result[dim] = _compact_dimension_summary(dim, getattr(row, dim))
    return result


def _cross_section_result_field_source(
    row: CrossSectionRow,
    triggered: tuple[TriggeredFilter, ...] = (),
) -> dict:
    """Full source dict used by --fields for cross-section results."""
    source = _cross_section_result_dict(row, triggered)
    source["price"] = _row_price(row)
    source["data_time"] = _row_data_time(row)
    return source


def _cross_section_result_dict(
    row: CrossSectionRow,
    triggered: tuple[TriggeredFilter, ...] = (),
) -> dict:
    """单只截面取数结果 → JSON 对象 (估值/质量/资金维度 · 估值裸值放开 + moneyflow + triggered)。

    基础截面输出:code/name + valuation (量价/市值 + 估值裸值) + valuation_context
    (行业内分位 + 行业中位 · *_pct_rank 截面恒 None) + moneyflow + technical/
    sentiment/chip + triggered_filters。需要 K 线类 filter 时,row.scan 额外挂载
    预计算位置 / 共振 / 涨幅 / 连阳裸值到 context。
    """
    return {
        "code": row.code,
        "name": row.name.replace(" ", ""),
        "context": _scan_context_public_dict(row.scan),
        "valuation": _valuation_public_dict(row.valuation),
        "valuation_context": (
            row.valuation_context.model_dump() if row.valuation_context else None
        ),
        "moneyflow": _moneyflow_public_dict(row.moneyflow),
        "technical": _technical_public_dict(row.technical),
        "sentiment": _sentiment_public_dict(row.sentiment),
        "chip": _chip_public_dict(row.chip),
        "relative_strength": _relative_strength_public_dict(row.relative_strength),
        "triggered_filters": [
            {
                "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
                "param": t.param,
                "value": t.value,
            }
            for t in triggered
        ],
    }


def cross_section_payload(
    entries: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]],
    *,
    query_time: str,
    pool_size: int,
    matched_total: int | None = None,
    data_cutoff: date | None,
    stale: bool,
    filters: list[dict] | None = None,
    compact: bool = False,
    availability_rows: list[CrossSectionRow] | None = None,
    included_dimensions: set[str] | None = None,
    compact_dimensions: set[str] | None = None,
    fields: tuple[str, ...] = (),
    compact_context: bool = True,
    match_mode: str = "all",
) -> dict:
    """kan find --all --format json 截面取数/筛选 payload (全市场截面层 + 估值/质量/资金维度 截面 filter)。

    与 find_payload 区别 (项目决策的新 schema · 不复用):全市场基础截面不逐股拉 K,
    只在请求 K 线类 filter 时挂载批量预计算 context。mode="cross_section" 标记
    形态供 AI 区分。当前契约支持截面类 filter (--pe / --moneyflow) · entries
    带 triggered · rule.filters 反映输入。

    Args:
        entries: (CrossSectionRow, triggered) 配对列表 (已筛 + limit · 顺序即输出序 ·
            无 filter 取数时 triggered 为 ())
        query_time: 查询发起时间 (ISO · caller 注入 · 利于测试确定性)
        pool_size: 池内总股票数 (筛前 · 全市场约 5500)
        data_cutoff: 截面数据交易日 (date | None)
        stale: 截面缓存是否滞后
        filters: rule.filters (--pe/--moneyflow 的 DSL · None=取数无 filter)

    强制 disclaimer 字段 (compliance §5/§7 · 衍生不可删 · 测试守护)。
    """
    from kan.render.base import FIND_DISCLAIMER_TEXT

    rows_for_availability = availability_rows if availability_rows is not None else [
        row for row, _ in entries
    ]
    result_dimensions = (
        compact_dimensions
        if compact_dimensions is not None
        else dimensions_from_filters(filters or [])
    )
    if compact and not result_dimensions and compact_dimensions is None:
        result_dimensions = _infer_included_dimensions(rows_for_availability)

    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "mode": "cross_section",
        "result_schema": "fields" if fields else ("compact" if compact else "full"),
        "query_time": query_time,
        "rule": {"pools": ["all"], "filters": filters or [], "match": match_mode},
        "results": [
            _select_find_fields(_cross_section_result_field_source(r, t), fields)
            if fields
            else (
                _cross_section_result_compact_dict(
                    r,
                    t,
                    included_dimensions=result_dimensions,
                    include_context=compact_context,
                )
                if compact else _cross_section_result_dict(r, t)
            )
            for r, t in entries
        ],
        "disclaimer": FIND_DISCLAIMER_TEXT,
        "data_availability": _data_availability(
            rows_for_availability,
            included_dimensions=included_dimensions,
            unsupported_dimensions=DIMENSIONS_UNSUPPORTED_IN_ALL,
        ),
        "stats": {
            "pool_size": pool_size,
            "matched": len(entries) if matched_total is None else matched_total,
            "shown": len(entries),
            "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
            "stale": stale,
        },
    }


def cross_section_markdown(
    rows: list[CrossSectionRow],
    *,
    title: str,
    pool_size: int,
) -> str:
    """kan find --all --format md · 全市场截面简表 + disclaimer (衍生不可删)。

    列:股票 / 申万行业 / PE / PE 行业内分位 / 换手率% / 主力净额 (估值/质量/资金维度 · 裸 PE 放开
    + 换手率 + 主力净额 · PE 分位作对照 · 全字段 (PB/资金明细) 见 --format json)。
    """
    headers = ["股票", "申万行业", "PE", "PE行业分位", "换手率%", "主力净额(万)"]
    md_rows: list[list[str]] = []
    for r in rows:
        ctx = r.valuation_context
        val = r.valuation
        mf = r.moneyflow
        ind = ctx.industry if ctx and ctx.industry else "—"
        pe = f"{val.pe_ttm:.2f}" if val and val.pe_ttm is not None else "—"
        pe_pct = (
            f"{ctx.pe_industry_pct:.0f}%"
            if ctx and ctx.pe_industry_pct is not None else "—"
        )
        turnover = (
            f"{val.turnover_rate:.2f}"
            if val and val.turnover_rate is not None else "—"
        )
        net = f"{mf.net_amount:,.0f}" if mf and mf.net_amount is not None else "—"
        md_rows.append([
            f"{r.name.replace(' ', '')} {r.code}",
            ind, pe, pe_pct, turnover, net,
        ])
    head = f"# {title} · 全市场 {pool_size} 只"
    body = md_table(headers, md_rows) if md_rows else "_无截面数据_"
    return f"{head}\n\n{body}\n\n{_find_disclaimer_quote()}"


# ── history ───────────────────────────────────────────────────────────

def _history_mark_label(res: int, direction: str) -> str:
    """共振方向 → md/json 共用的中文标记 · 1-2 只方向词 · ≥3 加"多周期"。"""
    if res == 0 or not direction:
        return "—"
    word = "低位" if direction == "low" else "高位"
    return f"多周期{word}" if res >= 3 else word


def history_payload(
    symbol: str,
    name: str,
    entries: list,
    *,
    period: int,
) -> dict:
    """kan history --format json 的结构化 payload(新→旧)。"""
    from kan.core.scanner import history_mark, history_resonance

    series = []
    for e in entries:
        cell = e.periods.get(period)
        low_res, high_res = history_resonance(e.periods)
        res, direction = history_mark(e.periods)
        series.append({
            "date": e.snapshot_date.isoformat(),
            "name": e.name,
            "position_pct": cell["pct"] if cell else None,
            "at_low": bool(cell["at_low"]) if cell else None,
            "at_high": bool(cell["at_high"]) if cell else None,
            "low_resonance": low_res,
            "high_resonance": high_res,
            "resonance": res,
            "direction": direction or None,
        })
    return {
        "command": "history",
        "symbol": symbol,
        "name": name,
        "period": period,
        "disclaimer": _disclaimer_text(),
        "series": series,
    }


def history_markdown(
    entries: list,
    *,
    period: int,
    title: str,
) -> str:
    """kan history --format md · 单周期纵向时间线(新→旧)。"""
    from kan.core.scanner import history_mark

    headers = ["日期", f"{period}日位置", "共振", "标记"]
    rows: list[list[str]] = []
    for e in entries:
        cell = e.periods.get(period)
        if cell is None:
            pct_str = "-"
        else:
            text = f"{cell['pct']:.0f}%"
            pct_str = f"[{text}]" if (cell.get("at_low") or cell.get("at_high")) else text
        res, direction = history_mark(e.periods)
        rows.append([
            e.snapshot_date.isoformat(),
            pct_str,
            f"×{res}" if res else "—",
            _history_mark_label(res, direction),
        ])
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"
