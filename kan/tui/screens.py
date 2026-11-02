"""研究终端的文本视图；字段名称取自共享目录，不重算指标。"""
from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text

from kan.domain.market_study import StudyBar, StudyCondition, StudyEvidence, StudyResult
from kan.render.base import DISCLAIMER
from kan.service.market_study import FIELD_CATALOG
from kan.service.trend_search import TrendSearchEvidence, TrendSegment

_FIELDS = {str(item["field"]): item for item in FIELD_CATALOG}
_OPERATORS = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "="}
STATUSES = {"complete": "完整", "pending": "窗口未满", "missing": "行情缺失"}


def number(value: float | None, suffix: str = "", *, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}{suffix}" if signed else f"{value:.2f}{suffix}"


def condition_text(condition: StudyCondition) -> str:
    field = _FIELDS[condition.field]
    window = f"{condition.window}日 " if condition.window else ""
    return f"{window}{field['label']} {_OPERATORS[condition.operator]} {condition.value:g}{field['unit']}"


def result_summary(result: StudyResult) -> str:
    coverage, distribution = result.coverage, result.distribution
    sample = (
        f"完整 {distribution.count} · 上涨 {distribution.positive}/{distribution.count} · "
        f"中位 {number(distribution.median_pct, '%', signed=True)}"
        if distribution.count else "没有完整历史样本，暂不汇总后续结果"
    )
    return (
        f"{result.as_of} · 当前 {coverage.current_matches}/{coverage.total_symbols} · "
        f"缺资料 {coverage.current_missing} · 历史 {result.events_total}\n"
        f"后 {result.query.forward_days} 日 · {sample} · 未满/缺失 {coverage.pending_events}/{coverage.missing_events}"
    )


def evidence_view(evidence: StudyEvidence, warnings: list[str]) -> Group:
    checks = Table(expand=True, box=None, padding=(0, 1))
    for label in ("当时条件", "实际值", "核对"):
        checks.add_column(label)
    for check in evidence.conditions:
        field = _FIELDS[check.condition.field]
        actual = number(check.actual, str(field["unit"]))
        if check.bound == "at_least" and check.actual is not None:
            actual = "至少 " + actual
        checks.add_row(
            Text(condition_text(check.condition)), Text(actual),
            "符合" if check.matched else ("不符合" if check.matched is False else "未知"),
        )
    outcome = evidence.outcome
    if outcome is None:
        result_text = "这条当前匹配没有已选择的历史事件结果。"
    else:
        result_text = (
            f"实际结果 · {STATUSES[outcome.status]}\n"
            f"事件日 {outcome.event_date} · 收盘 {number(outcome.event_close)} · "
            f"窗口终点 {outcome.forward_date or '未到期'}\n"
            f"期末涨跌 {number(outcome.return_pct, '%', signed=True)} · "
            f"期间最高 {number(outcome.max_return_pct, '%', signed=True)} · "
            f"期间最低 {number(outcome.min_return_pct, '%', signed=True)}"
        )
    return Group(
        Text(f"{evidence.name} {evidence.symbol} · 事件日期 {evidence.event_date}", style="bold #95d5bd"),
        Text(f"当次保存的数据源：{evidence.source}\n"),
        checks, Text("\n" + result_text),
        Text("\n数据与样本说明\n" + "\n".join([*warnings, *evidence.warnings]), style="#afbdc3"),
        Text("\n当次封存日线 · 空值表示缺口\n", style="bold"), bars_table(evidence.bars),
    )


def bars_table(items: list[StudyBar]) -> Table:
    bars = Table(expand=True, box=None, padding=(0, 1))
    for label in ("实际日期", "开盘", "最高", "最低", "收盘"):
        bars.add_column(label, justify="left" if label == "实际日期" else "right")
    for bar in items:
        bars.add_row(
            str(bar.date), number(bar.open), number(bar.high), number(bar.low), number(bar.close),
        )
    return bars


def segment_text(segment: TrendSegment | None) -> str:
    if segment is None:
        return "无法确认连续段"
    direction = {"up": "上涨", "down": "下跌", "flat": "平盘"}[segment.direction]
    return f"{direction} {'≥' if segment.bound == 'at_least' else ''}{segment.days} 天"


def trend_evidence_view(evidence: TrendSearchEvidence) -> Group:
    row = evidence.row
    checks = Table(expand=True, box=None, padding=(0, 1))
    for label in ("明确条件", "实际值", "核对"):
        checks.add_column(label)
    for check in evidence.conditions:
        actual = ("至少 " if check.bound == "at_least" and check.actual is not None else "") + number(check.actual)
        checks.add_row(Text(condition_text(check.condition)), actual, "符合" if check.matched else "未知" if check.matched is None else "不符合")
    segment = row.current_segment
    dates = f"段首 {segment.start_date} · 比较基日 {segment.base_date}" if segment else "日线不足，无法确认当前连续段"
    bars = Table(expand=True, box=None, padding=(0, 1))
    for label in ("实际日期", "开盘", "收盘", "较前收", "实体涨跌"):
        bars.add_column(label)
    for bar in reversed(evidence.bars):
        bars.add_row(str(bar.date), number(bar.open), number(bar.close), number(bar.change_pct, "%", signed=True), number(bar.body_pct, "%", signed=True))
    return Group(
        Text(f"{row.name} {row.symbol} · 截止 {evidence.as_of}", style="bold #95d5bd"),
        Text(f"{segment_text(segment)} · 段涨跌 {number(segment.return_pct if segment else None, '%', signed=True)}\n{dates}\n来源 {row.source}"), checks if evidence.conditions else Text("无条件浏览，仅展示当前事实"),
        Text("位置30/60/180日：" + "/".join(number(row.positions.get(str(n)), "%") for n in (30, 60, 180))),
        Text("实际日线（最近日期在前，空值表示缺口）", style="bold"), bars,
        Text("\n平盘与缺行中断连续；上涨/下跌比较前收，阳线/阴线比较当日开收。\n"),
        Text("\n".join(evidence.warnings), style="#afbdc3"),
    )


def help_view() -> Text:
    return Text(
        "直接输入明确条件，筛当前，再按需核对历史\n\n"
        "f             打开条件：方向键选择类型，Tab 切换输入\n"
        "Ctrl+Enter    按已填天数筛选；不自动运行历史研究\n"
        "↑ ↓ / Enter   选结果 / 看条件实际值、连续段和日线\n"
        "s / g         命名保存条件 / 读取已保存条件\n"
        "h             明确回看与后续天数，再核对并保存历史\n"
        "m             当前筛选缺口明细，缺数据不当成未命中\n"
        "t / a         无条件浏览个人池 / 全市场，显示多周期位置\n"
        "l / r         读取历史研究 / 按原观察日同条件复算\n"
        "1 / 2         研究的当前匹配 / 历史样本\n"
        "n / p         下一页 / 上一页历史事件\n"
        "/             搜索当前列表\n"
        "Esc           返回结果、取消输入或清空搜索\n"
        "? / q         帮助 / 退出（输入框内用 Ctrl+Q）\n\n"
        "连续上涨/下跌比较前一日收盘；阳线/阴线比较当日开收。\n"
        "平盘与缺行中断连续；最多 N 天仍要求该方向至少 1 天。\n"
        "先跌后涨/先涨后跌的两段相邻，分别填写各段天数。\n"
        "最近 N 日计数与连续 N 日不同，按实际交易日核对。\n\n"
        "命令行直接筛选：kan trend --help；历史与 JSON：kan study --help\n"
        "读取本地行情，不自动联网更新；数据日和缺口随结果展示。\n\n"
        + DISCLAIMER.strip()
    )
