"""当前趋势筛选 CLI；与 Web、TUI 共用条件和计算。"""
from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from typing import Annotated

import typer

from kan.app import app
from kan.domain.market_study import StudyCondition, StudyField, StudyReference
from kan.render.trend import factor_value, swing_phase
from kan.service.market_study import FIELD_CATALOG
from kan.service.trend_search import TrendSearchQuery, save_trend_search, search_trends


class TrendFormat(StrEnum):
    terminal = "terminal"
    json = "json"


class TrendUniverse(StrEnum):
    all = "all"
    personal = "personal"
    codes = "codes"


class TrendComparison(StrEnum):
    gte = "gte"
    eq = "eq"
    lte = "lte"


class SwingStructure(StrEnum):
    up = "up"
    down = "down"
    mixed = "mixed"


@app.command()
def trend(
    universe: Annotated[TrendUniverse | None, typer.Option("--universe", help="明确范围：all / personal / codes")] = None,
    codes: Annotated[str | None, typer.Option("--codes", help="逗号分隔股票代码；即明确选择代码范围")] = None,
    industry: Annotated[list[str] | None, typer.Option("--industry", help="在所选范围内按行业过滤，可重复")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of", help="完整收盘日 YYYY-MM-DD，默认最近收盘")] = None,
    compare_to: Annotated[str | None, typer.Option("--compare-to", help="对照 previous_session 或更早交易日 YYYY-MM-DD；不保存运行记录")] = None,
    up_days: Annotated[int | None, typer.Option("--up-days", min=1, help="连续收盘上涨天数")] = None,
    down_days: Annotated[int | None, typer.Option("--down-days", min=1, help="连续收盘下跌天数")] = None,
    bull_days: Annotated[int | None, typer.Option("--bull-days", min=1, help="连续阳线天数：收盘高于开盘")] = None,
    bear_days: Annotated[int | None, typer.Option("--bear-days", min=1, help="连续阴线天数：收盘低于开盘")] = None,
    joint_up_days: Annotated[int | None, typer.Option("--joint-up-days", min=1, help="连续收阳且收盘上涨天数")] = None,
    previous_down_days: Annotated[int | None, typer.Option("--previous-down-days", min=1, help="当前上涨段紧邻的前一段下跌天数")] = None,
    previous_up_days: Annotated[int | None, typer.Option("--previous-up-days", min=1, help="当前下跌段紧邻的前一段上涨天数")] = None,
    rising_days: Annotated[int | None, typer.Option("--rising-days", min=0, help="最近 --window 个市场日中的上涨天数")] = None,
    falling_days: Annotated[int | None, typer.Option("--falling-days", min=0, help="最近 --window 个市场日中的下跌天数")] = None,
    bull_count: Annotated[int | None, typer.Option("--bull-count", min=0, help="最近 --window 根 K 线中的阳线数量")] = None,
    bear_count: Annotated[int | None, typer.Option("--bear-count", min=0, help="最近 --window 根 K 线中的阴线数量")] = None,
    bull_excess: Annotated[int | None, typer.Option("--bull-excess", help="阳线数减阴线数严格大于此值；0 表示阳多于阴")] = None,
    return_above: Annotated[float | None, typer.Option("--return-above", help="--window 日区间涨跌幅严格大于此百分数")] = None,
    return_below: Annotated[float | None, typer.Option("--return-below", help="--window 日区间涨跌幅严格小于此百分数")] = None,
    slope_above: Annotated[float | None, typer.Option("--slope-above", help="趋势斜率严格大于此值，单位 %/交易日")] = None,
    slope_below: Annotated[float | None, typer.Option("--slope-below", help="趋势斜率严格小于此值，单位 %/交易日")] = None,
    efficiency_min: Annotated[float | None, typer.Option("--efficiency-min", min=0, max=1, help="趋势效率下限，0–1；只描述路径直接程度")] = None,
    swing: Annotated[SwingStructure | None, typer.Option("--swing", help="波段结构：up 高低点抬高 / down 降低 / mixed 混合")] = None,
    reversal_pct: Annotated[float, typer.Option("--reversal-pct", help="收盘反向移动达到此百分比才确认波段转折，须大于 0 且小于 100")] = 5,
    window: Annotated[int | None, typer.Option("--window", min=2, max=360, help="区间、趋势因子及波段的市场交易日窗口")] = None,
    comparison: Annotated[TrendComparison, typer.Option("--comparison", help="天数比较：gte 至少 / eq 恰好 / lte 最多，连续段的最多限定 1–N 天")] = TrendComparison.gte,
    like: Annotated[str | None, typer.Option("--like", help="形态参照股票代码")] = None,
    reference_date: Annotated[str | None, typer.Option("--reference-date", help="形态参照截止日 YYYY-MM-DD")] = None,
    shape_window: Annotated[int | None, typer.Option("--shape-window", min=2, max=360)] = None,
    shape_distance: Annotated[float | None, typer.Option("--shape-distance", min=0, help="形态RMS距离上限，单位百分点")] = None,
    browse: Annotated[bool, typer.Option("--browse", help="明确选择无条件浏览股票范围")] = False,
    save: Annotated[str | None, typer.Option("--save", help="以指定名称保存本次条件，不运行历史研究")] = None,
    format: Annotated[TrendFormat, typer.Option("--format")] = TrendFormat.terminal,
) -> None:
    """按明确条件筛当前趋势；平盘/缺行中断连续段，默认不取数、不保存历史研究。"""
    try:
        if universe is None and codes is None:
            raise ValueError("请明确 --universe all/personal 或 --codes 代码列表")
        chosen = universe or TrendUniverse.codes
        fields: list[tuple[StudyField, int | None]] = [
            ("up_days", up_days), ("down_days", down_days), ("bull_days", bull_days),
            ("bear_days", bear_days), ("joint_up_days", joint_up_days),
            ("previous_down_days", previous_down_days), ("previous_up_days", previous_up_days),
            ("rising_days", rising_days), ("falling_days", falling_days),
            ("bull_count", bull_count), ("bear_count", bear_count),
        ]
        counted = {"rising_days", "falling_days", "bull_count", "bear_count"}
        conditions = []
        for field, value in fields:
            if value is None:
                continue
            condition_window = window if field in counted else None
            if condition_window is not None and value > condition_window:
                raise ValueError("区间计数不能超过 --window")
            conditions.append(StudyCondition(field=field, operator=comparison.value, value=value, window=condition_window))
            if comparison is TrendComparison.lte and field not in counted:
                conditions.append(StudyCondition(field=field, operator="gt", value=0, window=condition_window))
        for factor, relation, threshold in (
            ("candle_balance", "gt", bull_excess),
            ("return_pct", "gt", return_above), ("return_pct", "lt", return_below),
            ("trend_slope", "gt", slope_above), ("trend_slope", "lt", slope_below),
            ("trend_efficiency", "gte", efficiency_min),
        ):
            if threshold is not None:
                conditions.append(StudyCondition.model_validate({"field": factor, "operator": relation, "value": threshold, "window": window}))
        if swing is not None:
            conditions.append(StudyCondition(field="swing_structure", operator="eq", value={"up": 1, "down": -1, "mixed": 0}[swing], window=window))
        if window is not None and not any(c.window is not None for c in conditions):
            raise ValueError("--window 需要配合区间计数、涨幅、趋势因子或 --swing")
        reference = None
        if any(value is not None for value in (like, reference_date, shape_window, shape_distance)):
            if like is None or reference_date is None or shape_window is None or shape_distance is None:
                raise ValueError("形态筛选需同时填写 --like / --reference-date / --shape-window / --shape-distance")
            reference = StudyReference(symbol=like, as_of=date.fromisoformat(reference_date))
            conditions.append(StudyCondition(field="shape_distance", operator="lte", value=shape_distance, window=shape_window))
        if not conditions and not browse:
            raise ValueError("请填写条件及阈值；无条件查看请显式加 --browse")
        query = TrendSearchQuery(
            universe=chosen.value, codes=codes.split(",") if codes else [], industries=industry or [],
            as_of=date.fromisoformat(as_of) if as_of else None, conditions=conditions, reference=reference,
            compare_to="previous_session" if compare_to == "previous_session" else date.fromisoformat(compare_to) if compare_to else None,
            swing_reversal_pct=reversal_pct,
        )
        result = search_trends(query)
        if save:
            save_trend_search(save, query)
        if format is TrendFormat.json:
            typer.echo(result.model_dump_json())
            return
        from rich.console import Console
        from rich.table import Table

        console = Console()
        field_labels = {str(item["field"]): item for item in FIELD_CATALOG}
        coverage = result.coverage
        console.print(f"趋势筛选 · {result.as_of} · 匹配 {coverage.matched}/{coverage.total} · 可判断 {coverage.evaluated} · 资料不足 {coverage.missing}")
        if query.conditions:
            console.print(" AND ".join(f"{str(item.window) + '日 ' if item.window else ''}{field_labels[item.field]['label']} {item.operator} {factor_value(item.field, item.value, str(field_labels[item.field]['unit']))}" for item in query.conditions))
        if any(c.field.startswith("swing_") for c in query.conditions):
            console.print(f"波段口径：收盘反向幅度 {query.swing_reversal_pct:g}% · 仅用截止日已确认转折 · 最近一段尚未完成")
        wave_window = next((c.window for c in query.conditions if c.field.startswith("swing_")), None)
        table = Table("代码", "名称", "行业", "收盘", "条件实际值", "波段阶段" if wave_window else "当前连续段")
        for row in result.rows:
            actual = " · ".join(f"{field_labels[item.field]['label']}={'≥' if item.key in row.lower_bounds else ''}{factor_value(item.field, row.values[item.key], str(field_labels[item.field]['unit']))}" for item in query.conditions)
            segment = row.current_segment
            span = swing_phase(row.values, wave_window) if wave_window else "缺前收" if segment is None else f"{segment.direction} {'≥' if segment.bound == 'at_least' else ''}{segment.days} 天 · {segment.return_pct:+.2f}%"
            table.add_row(row.symbol, row.name, row.industry or "未分类", f"{row.close:.2f}", actual, span)
        console.print(table)
        if result.comparison:
            changes = result.comparison
            counts = changes.coverage
            console.print(f"对照 {changes.as_of} → {result.as_of} · 新出现 {counts.entered} · 持续匹配 {counts.continued} · 已退出 {counts.exited} · 无法确认 {counts.uncertain}")
            change_table = Table("代码", "名称", "变化", "对照日", "当前日")
            labels = {"entered": "新出现", "exited": "已退出", "uncertain": "无法确认"}
            for item in changes.rows:
                if item.status == "continued":
                    continue
                descriptions = []
                for state in (item.previous, item.current):
                    descriptions.append(state.reason or " · ".join(f"{field_labels[check.condition.field]['label']}={'≥' if check.bound == 'at_least' else ''}{factor_value(check.condition.field, check.actual)}" for check in state.conditions) or "符合")
                change_table.add_row(item.symbol, item.name, labels[item.status], *descriptions)
            if change_table.row_count:
                console.print(change_table)
            if counts.excluded:
                console.print(f"{counts.excluded} 只参照自身窗口不参与变化判断。")
        for warning in result.warnings:
            console.print(warning)
        if result.common_data_date and result.common_data_date < result.as_of:
            console.print(f"{result.common_data_count} 只可用缓存截至 {result.common_data_date}；可显式 --as-of {result.common_data_date} 或更新数据。")
    except (OSError, ValueError) as exc:
        if format is TrendFormat.json:
            typer.echo(json.dumps({"error": {"message": str(exc)}}, ensure_ascii=False))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
