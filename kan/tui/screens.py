"""研究终端的文本视图；字段名称取自共享目录，不重算指标。"""
from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text

from kan.domain.market_study import StudyBar, StudyCondition, StudyEvidence, StudyResult
from kan.render.base import DISCLAIMER
from kan.service.market_study import FIELD_CATALOG
from kan.service.trend_map import TrendStockSnapshot

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


def trend_stock_view(stock: TrendStockSnapshot) -> Group:
    positions = " / ".join(number(stock.positions.get(str(n)), "%") for n in (30, 60, 180))
    returns = " / ".join(number(stock.returns.get(str(n)), "%", signed=True) for n in (5, 20, 60))
    return Group(
        Text(f"{stock.name} {stock.symbol} · 截止 {stock.as_of}", style="bold #95d5bd"),
        Text(f"行业 {stock.industry or '未分类'} · 来源 {stock.source}\n"),
        Text(f"区间位置 30 / 60 / 180 日\n{positions}\n"),
        Text(f"区间涨跌 5 / 20 / 60 日\n{returns}\n"),
        Text("位置反映所在区间，涨跌反映区间变化；缺失值显示 —。\n复杂条件与历史检验请在 kan web 建立研究。\n\n"),
        bars_table(stock.bars),
    )


def help_view() -> Text:
    return Text(
        "先看趋势与位置，再用同一条件核对当前和历史\n\n"
        "t / a                   扫描个人池 / 全市场趋势\n"
        "↑ ↓ / PageUp PageDown  选择研究或结果\n"
        "Enter                   打开研究 / 查看当次证据\n"
        "r                       用已保存的同一条件重新运行\n"
        "1 / 2                   切换当前匹配 / 历史样本\n"
        "n / p                   下一页 / 上一页历史事件\n"
        "/                       搜索当前列表\n"
        "l                       重新读取已保存研究\n"
        "Esc                     清空搜索 / 返回上一级\n"
        "?                       查看这份帮助\n"
        "q                       退出\n\n"
        "创建或修改条件：在另一个终端运行 kan web。\n"
        "在网页保存并运行研究后，回到这里按 l 读取。\n"
        "自动化与 JSON：kan study --help\n\n"
        "终端不预填阈值、不自动更新行情；重跑会使用当前可用数据，"
        "日期、覆盖、未完成样本与缺口均由同一研究服务返回。\n\n"
        + DISCLAIMER.strip()
    )
