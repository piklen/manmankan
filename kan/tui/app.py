"""研究终端：研究列表 → 当前/历史结果 → 当次证据，单窗口逐级返回。"""
from __future__ import annotations

from datetime import date
from typing import ClassVar, Literal

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Input, Static
from textual.worker import get_current_worker

from kan.domain.market_study import StudyEvent, StudyEvidence, StudyResult, StudySummary
from kan.infra.log import redact_text
from kan.render.base import DISCLAIMER
from kan.service import market_study, trend_map
from kan.tui.screens import (
    STATUSES,
    condition_text,
    evidence_view,
    help_view,
    number,
    result_summary,
    trend_stock_view,
)

View = Literal["trends", "stock", "studies", "current", "history", "evidence", "help"]
PAGE_SIZE = 50


class StudyApp(App[None]):
    TITLE = "慢慢看 · 趋势与位置研究"
    CSS_PATH = "workbench.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "返回"),
        Binding("t", "trends", "个人趋势"),
        Binding("a", "all_trends", "全市场", show=False),
        Binding("r", "rerun", "同条件重跑"),
        Binding("1", "current", "当前匹配"),
        Binding("2", "history", "历史样本"),
        Binding("n", "next_page", "下一页", show=False),
        Binding("p", "previous_page", "上一页", show=False),
        Binding("slash", "search", "搜索", show=False),
        Binding("l", "list", "研究列表"),
        Binding("question_mark", "help", "帮助"),
        Binding("q,ctrl+q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.view: View = "trends"
        self.help_return: View = "studies"
        self.evidence_return: View = "current"
        self.studies: list[StudySummary] = []
        self.result: StudyResult | None = None
        self.events: list[StudyEvent] = []
        self.evidence: StudyEvidence | None = None
        self.trends: trend_map.TrendMapSnapshot | None = None
        self.stock: trend_map.TrendStockSnapshot | None = None
        self.event_offset = 0
        self.selected_key: str | None = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static("慢慢看  /  趋势与位置研究", id="brand")
        with Horizontal(id="toolbar"):
            yield Input(placeholder="/ 搜索研究、代码或名称", id="search")
            yield Button("个人 t", id="personal")
            yield Button("全市 a", id="all")
            yield Button("研究 l", id="studies")
            yield Button("重跑 r", id="rerun", variant="primary")
            yield Button("当前 1", id="current")
            yield Button("历史 2", id="history")
            yield Button("返回", id="back")
        yield Static("", id="summary", markup=False)
        yield Static("正在读取已保存研究…", id="status", markup=False)
        yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
        yield Static("", id="empty", markup=False)
        with VerticalScroll(id="detail"):
            yield Static("", id="detail-content", markup=False)
        yield Static("", id="preview", markup=False)
        yield Static(DISCLAIMER.strip(), id="disclaimer", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._render()
        self._status("t 扫描个人池 · a 扫描全市场 · l 打开已保存研究")

    def _status(self, message: str, *, error: bool = False) -> None:
        widget = self.query_one("#status", Static)
        widget.update(message)
        widget.set_class(error, "error")

    def _load(self, action: str, key: str = "", day: date | None = None, offset: int = 0) -> None:
        if self.busy:
            return
        self.busy = True
        self.query_one("#rerun", Button).disabled = True
        self._status("正在用同一条件重新研究…" if action == "rerun" else "正在读取研究材料…")
        self._read(action, key, day, offset)

    @work(thread=True, exclusive=True, group="study")
    def _read(self, action: str, key: str, day: date | None, offset: int) -> None:
        worker = get_current_worker()
        try:
            value: object
            if action == "trends":
                value = trend_map.build_trend_map(trend_map.TrendMapQuery(universe="all" if key == "all" else "personal"))
            elif action == "stock":
                value = trend_map.get_trend_stock(trend_map.TrendStockQuery(symbol=key, as_of=day))
            elif action == "list":
                value = market_study.list_studies()
            elif action == "open":
                value = market_study.get_study(key)
            elif action == "rerun":
                value = market_study.rerun_study(key)
            elif action == "events":
                value = market_study.study_events(key, offset=offset, limit=PAGE_SIZE)
            else:
                assert self.result is not None and day is not None
                value = market_study.study_evidence(self.result.run_id, key, day)
        except Exception as exc:
            if not worker.is_cancelled:
                self.call_from_thread(self._failed, redact_text(str(exc)))
            return
        if not worker.is_cancelled:
            self.call_from_thread(self._loaded, action, value)

    def _failed(self, message: str) -> None:
        self.busy = False
        self._render()
        self._status(f"未完成：{message} · 已保存结果未改变；可按 l 重新读取", error=True)

    def _loaded(self, action: str, value) -> None:
        self.busy = False
        if action == "trends":
            self.trends = value
            self.view = "trends"
        elif action == "stock":
            self.stock = value
            self.view = "stock"
        elif action == "list":
            self.studies = value
            self.view = "studies"
        elif action in {"open", "rerun"}:
            self.result = value
            self.events = value.events
            self.event_offset = 0
            self.view = "current"
        elif action == "events":
            self.events = value.items
            self.event_offset = value.offset
            self.view = "history"
        else:
            self.evidence = value
            self.view = "evidence"
        if action not in {"evidence", "stock"}:
            self.selected_key = None
            self.query_one(Input).value = ""
        self._render()
        if self.view in {"trends", "stock"}:
            warning = "；".join(self.trends.warnings) if self.trends else ""
            self._status(warning or "Enter 查看多周期位置、变化和实际日线 · l 进入研究")
        elif self.result is not None and self.view != "studies":
            self._status(
                "↑ ↓ 翻阅证据与数据说明 · Esc 返回列表" if self.view == "evidence" else
                "Enter 核对证据与样本口径 · 1 当前匹配 / 2 历史样本 · Esc 返回"
            )
        else:
            self._status("Enter 打开研究 · r 同条件重跑 · 新建/修改条件请运行 kan web")

    def _render(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        detail_view = self.view in {"evidence", "stock", "help"}
        study_view = self.view in {"current", "history", "evidence"}
        self.query_one("#detail").display = detail_view
        self.query_one("#preview").display = not detail_view
        self.query_one("#search").display = not detail_view
        for name in ("current", "history"):
            self.query_one(f"#{name}").display = study_view
        for name in ("personal", "all", "studies"):
            self.query_one(f"#{name}").display = not study_view
        self.query_one("#rerun").display = self.view in {"studies", "current", "history"}
        self.query_one("#rerun", Button).disabled = self.busy or (not self.studies and self.result is None)
        title = {"trends": "趋势与位置", "stock": "个股事实", "studies": "已保存研究", "current": "当前匹配", "history": "历史样本", "evidence": "当次证据", "help": "使用说明"}[self.view]
        context = f"{self.result.query.title[:22]} / " if study_view and self.result else ""
        self.query_one("#brand", Static).update(f"慢慢看  /  {context}{title}")
        query = self.query_one(Input).value.strip().casefold()
        empty_text = "没有匹配项。Esc 清空搜索。"
        if self.view == "trends":
            table.add_columns("代码", "名称", "位置 30/60/180 %", "涨跌 5/20/60 %", "数据日")
            if self.trends:
                pool = "个人池" if self.trends.query.universe == "personal" else "全市场"
                self.query_one("#summary", Static).update(f"{pool} · 截止 {self.trends.as_of} · 可定位 {self.trends.plotted}/{self.trends.total} · 缺失 {self.trends.missing}")
                for row in self.trends.rows:
                    if query in (row.symbol + row.name + (row.industry or "")).casefold():
                        positions = "/".join(number(row.positions.get(str(n))) for n in (30, 60, 180))
                        returns = "/".join(number(row.returns.get(str(n)), signed=True) for n in (5, 20, 60))
                        table.add_row(row.symbol, Text(row.name), positions, returns, str(row.data_cutoff or "无同日数据"), key=row.symbol)
                empty_text = "没有匹配的代码、名称或行业。Esc 清空搜索。" if query else "该股票池没有可列出的对象。a 扫描全市场，或运行 kan web 管理个人研究对象。"
            else:
                self.query_one("#summary", Static).update("把多周期位置与区间变化放在同一张表里")
                empty_text = "从趋势与位置开始\n\n按 t 扫描个人池，按 a 扫描全市场。\n按 l 打开已保存研究，继续核对同一条件的当前匹配与历史样本。\n复杂筛选在 kan web 编辑。"
        elif self.view == "stock" and self.stock is not None:
            self.query_one("#summary", Static).update("实际日期与多周期事实 · Esc 返回原列表")
            self.query_one("#detail-content", Static).update(trend_stock_view(self.stock))
        elif self.view == "studies":
            self.query_one("#summary", Static).update(f"{len(self.studies)} 份研究 · 条件、当前匹配和历史证据一起保存")
            table.add_columns("研究名称", "数据截止", "当前匹配", "历史事件")
            for study in self.studies:
                if query in study.title.casefold():
                    table.add_row(Text(study.title), str(study.as_of), str(study.current_count), str(study.event_count), key=study.study_id)
            if not self.studies:
                empty_text = "从一份明确的研究开始\n\n在另一个终端运行 kan web，选择趋势与位置条件并保存运行。\n回来按 l 读取研究；终端直接查看当前匹配、历史样本与证据。"
        elif self.view in {"current", "history"} and self.result is not None:
            self.query_one("#summary", Static).update(result_summary(self.result))
            if self.view == "current":
                table.add_columns("代码", "名称", "行情日", "收盘", "涨跌")
                for match in self.result.current_matches:
                    if query in (match.symbol + match.name).casefold():
                        table.add_row(match.symbol, Text(match.name), str(match.date), number(match.close), number(match.change_pct, "%", signed=True), key=match.symbol)
                empty_text = "这份条件当前没有匹配。按 2 查看历史事件，或在 Web 调整条件。"
            else:
                table.add_columns("事件日", "代码", "名称", "窗口终点", "结果", "涨跌")
                for event in self.events:
                    if query in (event.symbol + event.name).casefold():
                        table.add_row(str(event.event_date), event.symbol, Text(event.name), str(event.forward_date or "—"), STATUSES[event.status], number(event.return_pct, "%", signed=True), key=event.event_id)
                last = min(self.event_offset + len(self.events), self.result.events_total)
                empty_text = "本页没有匹配的历史事件。搜索仅作用于本页；n / p 翻页。" if query else "所选范围没有历史事件。可核对数据覆盖，或在 Web 调整明确条件。"
                self.query_one("#preview", Static).update(f"第 {self.event_offset + 1 if self.events else 0}–{last} 条 / 共 {self.result.events_total} 条 · n 下一页 / p 上一页 · 搜索当前页")
        elif self.view == "evidence" and self.evidence is not None:
            self.query_one("#summary", Static).update("当次封存材料 · 事件结果来自当时数据")
            self.query_one("#detail-content", Static).update(evidence_view(self.evidence, self.result.warnings if self.result else []))
        elif self.view == "help":
            self.query_one("#summary", Static).update("复杂条件在 Web 编辑，终端专注重跑与查证")
            self.query_one("#detail-content", Static).update(help_view())
        list_view = self.view in {"trends", "studies", "current", "history"}
        table.display = list_view and table.row_count > 0
        empty = self.query_one("#empty", Static)
        empty.display = list_view and not table.row_count
        empty.update(empty_text)
        if self.view != "history":
            preview = "；".join(condition_text(c) for c in self.result.query.conditions) if self.result and study_view else "↑ ↓ 选择 · Enter 打开 · t 个人趋势 / a 全市场 / l 我的研究 · ? 帮助"
            self.query_one("#preview", Static).update(preview)
        if table.display:
            for index, key in enumerate(table.rows):
                if key.value == self.selected_key:
                    table.move_cursor(row=index)
                    break
            table.focus()
        elif detail_view:
            self.query_one("#detail", VerticalScroll).focus()
        else:
            self.query_one("#personal" if self.query_one("#personal").display else "#back", Button).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.selected_key = str(event.row_key.value)
        if self.view == "trends" and self.trends:
            row = next((r for r in self.trends.rows if r.symbol == self.selected_key), None)
            if row:
                self.query_one("#preview", Static).update(f"{row.name} · {row.industry or '未分类'} · {row.reason or '同一截止日，多周期位置与区间变化'} · Enter 核对日线")
        elif self.view == "studies":
            study = next((s for s in self.studies if s.study_id == self.selected_key), None)
            if study:
                self.query_one("#preview", Static).update("；".join(condition_text(c) for c in study.query.conditions))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        if self.view == "trends" and self.trends:
            self._load("stock", key, self.trends.as_of)
        elif self.view == "studies":
            self._load("open", key)
        elif self.result is not None and self.view == "current":
            match = next(item for item in self.result.current_matches if item.symbol == key)
            self.evidence_return = "current"
            self._load("evidence", match.symbol, match.date)
        elif self.view == "history":
            row = next(item for item in self.events if item.event_id == key)
            self.evidence_return = "history"
            self._load("evidence", row.symbol, row.event_date)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search" and self.is_running:
            was_focused = event.input.has_focus
            self._render()
            if was_focused:
                event.input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one(DataTable).focus()

    def action_search(self) -> None:
        if self.view in {"trends", "studies", "current", "history"}:
            self.query_one(Input).focus()

    def action_rerun(self) -> None:
        key = self.selected_key if self.view == "studies" else (self.result.study_id if self.result and self.view in {"current", "history"} else None)
        if key:
            self._load("rerun", key)

    def action_current(self) -> None:
        if self.result is not None and not self.busy:
            self.view = "current"
            self.query_one(Input).value = ""
            self._render()

    def action_history(self) -> None:
        if self.result is not None and not self.busy:
            self._load("events", self.result.run_id)

    def action_next_page(self) -> None:
        if self.view == "history" and self.result and self.event_offset + PAGE_SIZE < self.result.events_total:
            self._load("events", self.result.run_id, offset=self.event_offset + PAGE_SIZE)

    def action_previous_page(self) -> None:
        if self.view == "history" and self.result and self.event_offset:
            self._load("events", self.result.run_id, offset=max(0, self.event_offset - PAGE_SIZE))

    def action_list(self) -> None:
        self._load("list")

    def action_trends(self) -> None:
        self._load("trends", "personal")

    def action_all_trends(self) -> None:
        self._load("trends", "all")

    async def action_back(self) -> None:
        if self.busy:
            self._status("研究材料正在读取，完成后可返回；不会重复提交任务。")
        elif self.view == "help":
            self.view = self.help_return
            self._render()
        elif self.view == "evidence":
            self.view = self.evidence_return
            self._render()
        elif self.view == "stock":
            self.view = "trends"
            self._render()
        elif self.query_one(Input).value:
            self.query_one(Input).value = ""
            self.query_one("#back", Button).focus()
        elif self.view in {"current", "history"}:
            self.action_list()
        elif self.view == "studies":
            self.view = "trends"
            self._render()

    def action_help(self) -> None:
        if not self.busy and self.view != "help":
            self.help_return = self.view
            self.view = "help"
            self._render()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            await self.action_back()
        elif event.button.id == "rerun":
            self.action_rerun()
        elif event.button.id == "current":
            self.action_current()
        elif event.button.id == "history":
            self.action_history()
        elif event.button.id == "personal":
            self.action_trends()
        elif event.button.id == "all":
            self.action_all_trends()
        elif event.button.id == "studies":
            self.action_list()
