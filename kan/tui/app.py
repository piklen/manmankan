"""终端直接筛选当前趋势，并显式保存条件、核对历史与逐日证据。"""
from __future__ import annotations

from datetime import date
from typing import ClassVar, Literal, cast

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Input, Select, Static
from textual.worker import get_current_worker

from kan.domain.market_study import StudyEvent, StudyEvidence, StudyQuery, StudyResult, StudySummary
from kan.infra.log import redact_text
from kan.render.base import DISCLAIMER
from kan.service import market_study, trend_search
from kan.tui.conditions import TrendFilterForm
from kan.tui.screens import (
    STATUSES,
    condition_text,
    evidence_view,
    help_view,
    number,
    result_summary,
    segment_text,
    trend_evidence_view,
)

View = Literal["screen", "missing", "filter_evidence", "saved_filters", "studies", "current", "history", "evidence", "help"]
PAGE_SIZE = 50


class StudyApp(App[None]):
    TITLE = "慢慢看 · 趋势条件筛选"
    CSS_PATH = "workbench.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f", "filters", "条件"),
        Binding("ctrl+enter", "screen", "执行", priority=True),
        Binding("s", "save_filter", "保存条件", show=False),
        Binding("g", "saved_filters", "已存条件", show=False),
        Binding("h", "investigate", "历史核对", show=False),
        Binding("m", "missing", "缺口", show=False),
        Binding("escape", "back", "返回"),
        Binding("t", "trends", "个人趋势", show=False),
        Binding("a", "all_trends", "全市场", show=False),
        Binding("r", "rerun", "同条件重跑", show=False),
        Binding("1", "current", "当前匹配", show=False),
        Binding("2", "history", "历史样本", show=False),
        Binding("n", "next_page", "下一页", show=False),
        Binding("p", "previous_page", "上一页", show=False),
        Binding("slash", "search", "搜索", show=False),
        Binding("l", "list", "研究列表", show=False),
        Binding("question_mark", "help", "帮助"),
        Binding("q,ctrl+q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.view: View = "screen"
        self.help_return: View = "studies"
        self.evidence_return: View = "current"
        self.studies: list[StudySummary] = []
        self.result: StudyResult | None = None
        self.events: list[StudyEvent] = []
        self.evidence: StudyEvidence | None = None
        self.event_offset = 0
        self.selected_key: str | None = None
        self.busy = False
        self.screen_result: trend_search.TrendSearchResult | None = None
        self.screen_evidence: trend_search.TrendSearchEvidence | None = None
        self.saved_filters: list[trend_search.SavedTrendSearch] = []
        self.form_open = True
        self.history_edit = False
        self.save_edit = False

    def compose(self) -> ComposeResult:
        yield Static("慢慢看  /  趋势与位置研究", id="brand")
        with Horizontal(id="toolbar"):
            yield Input(placeholder="/ 搜索研究、代码或名称", id="search")
            yield Button("条件 f", id="filters")
            yield Button("个人 t", id="personal")
            yield Button("保存 s", id="save-filter")
            yield Button("已存 g", id="saved-filters")
            yield Button("核对 h", id="investigate")
            yield Button("研究 l", id="studies")
            yield Button("重跑 r", id="rerun", variant="primary")
            yield Button("当前 1", id="current")
            yield Button("历史 2", id="history")
            yield Button("返回", id="back")
        yield TrendFilterForm(id="filter-form")
        with Horizontal(id="save-form", classes="form-row"):
            yield Input(placeholder="给这份筛选条件命名", id="save-title")
            yield Button("保存条件", id="save-confirm", variant="primary")
        with Horizontal(id="history-form", classes="form-row"):
            yield Input(placeholder="回看交易日 5–1260", type="integer", id="history-lookback")
            yield Input(placeholder="后续观察日 1–60", type="integer", id="history-forward")
            yield Select([("首次命中", "first"), ("逐日命中", "every"), ("非重叠", "non_overlapping")], value="first", allow_blank=False, id="history-policy")
            yield Button("核对并保存", id="history-run", variant="primary")
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
        self._status("选择条件与天数后筛选；不会自动运行历史研究")
        self.query_one("#filter-kind", Select).focus()

    def _status(self, message: str, *, error: bool = False) -> None:
        widget = self.query_one("#status", Static)
        widget.update(message)
        widget.set_class(error, "error")

    def _load(self, action: str, key: str = "", day: date | None = None, offset: int = 0, query: trend_search.TrendSearchQuery | StudyQuery | None = None) -> None:
        if self.busy:
            return
        self.busy = True
        self.query_one("#rerun", Button).disabled = True
        self._status("正在用同一条件重新研究…" if action == "rerun" else "正在读取研究材料…")
        self._read(action, key, day, offset, query)

    @work(thread=True, exclusive=True, group="study")
    def _read(self, action: str, key: str, day: date | None, offset: int, query: trend_search.TrendSearchQuery | StudyQuery | None) -> None:
        worker = get_current_worker()
        try:
            value: object
            if action == "screen":
                value = trend_search.search_trends(cast(trend_search.TrendSearchQuery, query))
            elif action == "filter_evidence":
                value = trend_search.trend_search_evidence(cast(trend_search.TrendSearchQuery, query), key)
            elif action == "saved":
                value = trend_search.list_saved_trends()
            elif action == "save_filter":
                value = trend_search.save_trend_search(key, cast(trend_search.TrendSearchQuery, query))
            elif action == "investigate":
                value = market_study.run_study(cast(StudyQuery, query))
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
        self._status(f"未完成：{message} · 现有结果保留，修正后可重试", error=True)

    def _loaded(self, action: str, value) -> None:
        self.busy = False
        if action == "screen":
            self.screen_result = value
            self.view = "screen"
            self.history_edit = self.save_edit = False
            self.form_open = False
        elif action == "filter_evidence":
            self.screen_evidence = value
            self.view = "filter_evidence"
        elif action == "saved":
            self.saved_filters = value
            self.view = "saved_filters"
        elif action == "save_filter":
            self.save_edit = False
            self.view = "screen"
        elif action == "list":
            self.studies = value
            self.view = "studies"
        elif action in {"open", "rerun", "investigate"}:
            self.result = value
            self.events = value.events
            self.event_offset = 0
            self.view = "history" if action == "investigate" else "current"
        elif action == "events":
            self.events = value.items
            self.event_offset = value.offset
            self.view = "history"
        else:
            self.evidence = value
            self.view = "evidence"
        if action not in {"evidence", "filter_evidence", "save_filter"}:
            self.selected_key = None
            self.query_one("#search", Input).value = ""
        self._render()
        if action == "save_filter":
            self._status(f"已保存条件：{value.title}。g 可重新载入；没有运行历史研究。")
        elif self.view in {"screen", "filter_evidence", "saved_filters"}:
            self._status("；".join(self.screen_result.warnings) if self.view == "screen" and self.screen_result and self.screen_result.warnings else "f 编辑 · Enter 看实际段 · s 保存条件 · h 历史核对 · m 缺口")
        elif self.result is not None and self.view != "studies":
            self._status(
                "↑ ↓ 翻阅证据与数据说明 · Esc 返回列表" if self.view == "evidence" else
                "Enter 核对证据与样本口径 · 1 当前匹配 / 2 历史样本 · Esc 返回"
            )
        else:
            self._status("Enter 打开研究 · r 原日同条件重跑 · f 直接新建筛选")

    def _render(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        detail_view = self.view in {"evidence", "help", "filter_evidence"}
        study_view = self.view in {"current", "history", "evidence"}
        self.query_one("#filter-form").display = self.view == "screen" and self.form_open and not self.history_edit and not self.save_edit
        self.query_one("#save-form").display = self.view == "screen" and self.save_edit
        self.query_one("#history-form").display = self.view == "screen" and self.history_edit
        for name in ("save-filter", "investigate"):
            self.query_one(f"#{name}").display = self.view == "screen"
            self.query_one(f"#{name}", Button).disabled = self.screen_result is None or self.busy
        self.query_one("#saved-filters").display = self.view == "screen"
        self.query_one("#filters").display = not self.query_one("#filter-form").display
        self.query_one("#detail").display = detail_view
        self.query_one("#preview").display = not detail_view
        self.query_one("#search").display = not detail_view
        for name in ("current", "history"):
            self.query_one(f"#{name}").display = study_view
        for name in ("personal", "studies"):
            self.query_one(f"#{name}").display = not study_view
        self.query_one("#personal").display = not study_view and self.view != "screen"
        self.query_one("#back").display = self.view != "screen"
        self.query_one("#rerun").display = self.view in {"studies", "current", "history"}
        self.query_one("#rerun", Button).disabled = self.busy or (not self.studies and self.result is None)
        title = {"screen": "条件筛选", "missing": "缺口明细", "filter_evidence": "当前日线证据", "saved_filters": "已保存条件", "studies": "已保存研究", "current": "当前匹配", "history": "历史样本", "evidence": "当次证据", "help": "使用说明"}[self.view]
        context = f"{self.result.query.title[:22]} / " if study_view and self.result else ""
        self.query_one("#brand", Static).update(f"慢慢看  /  {context}{title}")
        query = self.query_one("#search", Input).value.strip().casefold()
        empty_text = "没有匹配项。Esc 清空搜索。"
        if self.view == "screen":
            table.add_columns("代码", "名称", "实际连续段", "条件实际值" if not self.screen_result or self.screen_result.query.conditions else "位置30/60/180%", "收盘", "涨跌")
            if self.screen_result:
                result = self.screen_result
                coverage = result.coverage
                pool = {"personal": "个人池", "all": "全市场", "codes": "代码池"}[result.query.universe]
                self.query_one("#summary", Static).update(f"{pool} · {result.as_of} · 匹配 {coverage.matched}/{coverage.total} · 可判断 {coverage.evaluated} · 缺口 {coverage.missing}（m）\n" + ("；".join(condition_text(c) for c in result.query.conditions) or "无条件浏览（没有预设筛选条件）"))
                for screen_row in result.rows:
                    if query in (screen_row.symbol + screen_row.name + (screen_row.industry or "")).casefold():
                        values = "/".join(("≥" if c.key in screen_row.lower_bounds else "") + number(screen_row.values.get(c.key)) for c in result.query.conditions if c.operator != "gt")
                        if not result.query.conditions:
                            values = "/".join(number(screen_row.positions.get(str(n))) for n in (30, 60, 180))
                        table.add_row(screen_row.symbol, Text(screen_row.name), segment_text(screen_row.current_segment), values, number(screen_row.close), number(screen_row.change_pct, "%", signed=True), key=screen_row.symbol)
                empty_text = (
                    "没有符合这些条件的股票。f 修改条件；m 查看缺口，未满足条件与缺行情分开统计。"
                    if result.query.conditions else
                    "此范围没有可列出的行情。t 浏览个人池，a 浏览全市场；m 核对缺口，f 填写条件。"
                )
            else:
                self.query_one("#summary", Static).update("条件和天数由你明确；这里只筛当前，不自动运行历史研究")
                empty_text = "选择连续上涨/下跌、阳线/阴线、前后两段或最近 N 日计数。\nTab 切换输入，Ctrl+Enter 执行。g 载入保存的条件；l 查看历史研究。"
        elif self.view == "missing" and self.screen_result:
            self.query_one("#summary", Static).update(f"{self.screen_result.coverage.missing} 个对象无法判断，计入股票池分母")
            table.add_columns("代码", "名称", "无法判断的原因")
            for missing_row in self.screen_result.missing_rows:
                if query in (missing_row.symbol + missing_row.name).casefold():
                    table.add_row(missing_row.symbol, Text(missing_row.name), Text(missing_row.reason), key=missing_row.symbol)
            empty_text = "没有行情缺口。Esc 返回筛选结果。"
        elif self.view == "filter_evidence" and self.screen_evidence:
            self.query_one("#summary", Static).update("当前缓存事实 · 实际交易日、条件值和连续段 · Esc 返回结果")
            self.query_one("#detail-content", Static).update(trend_evidence_view(self.screen_evidence))
        elif self.view == "saved_filters":
            self.query_one("#summary", Static).update("保存的是条件；Enter 才运行当前筛选，不自动核对历史")
            table.add_columns("条件名称", "范围", "明确条件")
            for item in self.saved_filters:
                if query in item.title.casefold():
                    table.add_row(Text(item.title), {"personal": "个人池", "all": "全市场", "codes": "代码池"}[item.query.universe], Text("；".join(condition_text(c) for c in item.query.conditions)), key=item.id)
            empty_text = "还没有保存条件。f 选择条件并筛选，然后按 s 命名保存。"
        elif self.view == "studies":
            self.query_one("#summary", Static).update(f"{len(self.studies)} 份研究 · 条件、当前匹配和历史证据一起保存")
            table.add_columns("研究名称", "数据截止", "当前匹配", "历史事件")
            for study in self.studies:
                if query in study.title.casefold():
                    table.add_row(Text(study.title), str(study.as_of), str(study.current_count), str(study.event_count), key=study.study_id)
            if not self.studies:
                empty_text = "还没有历史研究\n\n按 f 输入并运行条件；结果页按 h 明确回看与后续窗口。\n核对后研究自动保存，可在此读取全部历史事件与封存证据。"
        elif self.view in {"current", "history"} and self.result is not None:
            self.query_one("#summary", Static).update(result_summary(self.result))
            if self.view == "current":
                table.add_columns("代码", "名称", "行情日", "收盘", "涨跌")
                for match in self.result.current_matches:
                    if query in (match.symbol + match.name).casefold():
                        table.add_row(match.symbol, Text(match.name), str(match.date), number(match.close), number(match.change_pct, "%", signed=True), key=match.symbol)
                empty_text = "这份条件当前没有匹配。按 2 查看历史事件，或按 f 创建新条件。"
            else:
                table.add_columns("事件日", "代码", "名称", "窗口终点", "结果", "涨跌")
                for event in self.events:
                    if query in (event.symbol + event.name).casefold():
                        table.add_row(str(event.event_date), event.symbol, Text(event.name), str(event.forward_date or "—"), STATUSES[event.status], number(event.return_pct, "%", signed=True), key=event.event_id)
                last = min(self.event_offset + len(self.events), self.result.events_total)
                empty_text = "本页没有匹配的历史事件。搜索仅作用于本页；n / p 翻页。" if query else "所选范围没有历史事件。可核对数据覆盖，或按 f 创建新条件。"
                self.query_one("#preview", Static).update(f"第 {self.event_offset + 1 if self.events else 0}–{last} 条 / 共 {self.result.events_total} 条 · n 下一页 / p 上一页 · 搜索当前页")
        elif self.view == "evidence" and self.evidence is not None:
            self.query_one("#summary", Static).update("当次封存材料 · 事件结果来自当时数据")
            self.query_one("#detail-content", Static).update(evidence_view(self.evidence, self.result.warnings if self.result else []))
        elif self.view == "help":
            self.query_one("#summary", Static).update("输入明确条件，筛当前，按需保存与核对历史")
            self.query_one("#detail-content", Static).update(help_view())
        list_view = self.view in {"screen", "missing", "saved_filters", "studies", "current", "history"}
        table.display = list_view and table.row_count > 0
        empty = self.query_one("#empty", Static)
        empty.display = list_view and not table.row_count
        empty.update(empty_text)
        if self.view != "history":
            preview = "；".join(condition_text(c) for c in self.result.query.conditions) if self.result and study_view else "↑ ↓ 选择 · Enter 查证 · f 条件 · g 已存条件 · h 历史核对 · l 研究 · ? 帮助"
            self.query_one("#preview", Static).update(preview)
        if self.view == "screen" and self.history_edit:
            self.query_one("#history-lookback", Input).focus()
        elif self.view == "screen" and self.save_edit:
            self.query_one("#save-title", Input).focus()
        elif self.view == "screen" and self.form_open:
            self.query_one("#filter-kind", Select).focus()
        elif table.display:
            for index, key in enumerate(table.rows):
                if key.value == self.selected_key:
                    table.move_cursor(row=index)
                    break
            table.focus()
        elif detail_view:
            self.query_one("#detail", VerticalScroll).focus()
        else:
            next(button for button in self.query("#toolbar Button") if button.display and not button.disabled).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.selected_key = str(event.row_key.value)
        if self.view == "screen" and self.screen_result:
            row = next((item for item in self.screen_result.rows if item.symbol == self.selected_key), None)
            if row:
                returns = "/".join(number(row.returns.get(str(n)), signed=True) for n in (5, 20, 60))
                self.query_one("#preview", Static).update(f"{row.name} · {row.industry or '未分类'} · 区间涨跌5/20/60日 {returns}% · Enter查证")
        elif self.view == "studies":
            study = next((s for s in self.studies if s.study_id == self.selected_key), None)
            if study:
                self.query_one("#preview", Static).update("；".join(condition_text(c) for c in study.query.conditions))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        if self.view == "screen" and self.screen_result:
            self._load("filter_evidence", key, query=self.screen_result.query.model_copy(update={"as_of": self.screen_result.as_of}))
        elif self.view == "saved_filters":
            saved = next(item for item in self.saved_filters if item.id == key)
            self.query_one(TrendFilterForm).set_query(saved.query)
            self._load("screen", query=saved.query)
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
        if event.input.id == "search":
            self.query_one(DataTable).focus()
        elif event.input.id == "save-title":
            self._save_named_filter()
        elif event.input.id in {"history-lookback", "history-forward"}:
            self._run_history()
        else:
            self.action_screen()

    def action_search(self) -> None:
        if self.view in {"screen", "missing", "saved_filters", "studies", "current", "history"}:
            self.query_one("#search", Input).focus()

    def action_rerun(self) -> None:
        if self.view == "screen" and self.screen_result:
            self._load("screen", query=self.screen_result.query)
            return
        key = self.selected_key if self.view == "studies" else (self.result.study_id if self.result and self.view in {"current", "history"} else None)
        if key:
            self._load("rerun", key)

    def action_current(self) -> None:
        if self.result is not None and not self.busy:
            self.view = "current"
            self.query_one("#search", Input).value = ""
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
        self._browse("personal")

    def action_all_trends(self) -> None:
        self._browse("all")

    def _browse(self, universe: Literal["personal", "all"]) -> None:
        if not self.busy:
            query = trend_search.TrendSearchQuery(universe=universe)
            self.query_one(TrendFilterForm).set_query(query)
            self._load("screen", query=query)

    async def action_back(self) -> None:
        if self.busy:
            self._status("研究材料正在读取，完成后可返回；不会重复提交任务。")
        elif self.view == "help":
            self.view = self.help_return
            self._render()
        elif self.view == "evidence":
            self.view = self.evidence_return
            self._render()
        elif self.view in {"filter_evidence", "missing", "saved_filters"}:
            self.view = "screen"
            self._render()
        elif self.view == "screen" and (self.history_edit or self.save_edit or self.form_open):
            self.history_edit = self.save_edit = self.form_open = False
            self._render()
        elif self.query_one("#search", Input).value:
            self.query_one("#search", Input).value = ""
            self.query_one("#back", Button).focus()
        elif self.view in {"current", "history"}:
            self.action_list()
        elif self.view == "studies":
            self.view = "screen"
            self._render()

    def action_help(self) -> None:
        if not self.busy and self.view != "help":
            self.help_return = self.view
            self.view = "help"
            self._render()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "filters":
            self.action_filters()
        elif event.button.id == "filter-run":
            self.action_screen()
        elif event.button.id == "save-filter":
            self.action_save_filter()
        elif event.button.id == "saved-filters":
            self.action_saved_filters()
        elif event.button.id == "save-confirm":
            self._save_named_filter()
        elif event.button.id == "investigate":
            self.action_investigate()
        elif event.button.id == "history-run":
            self._run_history()
        elif event.button.id == "back":
            await self.action_back()
        elif event.button.id == "rerun":
            self.action_rerun()
        elif event.button.id == "current":
            self.action_current()
        elif event.button.id == "history":
            self.action_history()
        elif event.button.id == "personal":
            self.action_trends()
        elif event.button.id == "studies":
            self.action_list()


    def action_filters(self) -> None:
        if not self.busy:
            self.view = "screen"
            self.form_open = True
            self.history_edit = self.save_edit = False
            self._render()
            self._status("填写条件后 Enter 或 Ctrl+Enter 筛当前；Esc 回到上次结果")

    def action_screen(self) -> None:
        if self.busy:
            return
        if self.save_edit:
            self._save_named_filter()
            return
        if self.history_edit:
            self._run_history()
            return
        try:
            query = self.query_one(TrendFilterForm).read_query()
        except ValueError as exc:
            self._status(str(exc), error=True)
            return
        self._load("screen", query=query)

    def action_missing(self) -> None:
        if self.screen_result and not self.busy:
            self.view = "screen" if self.view == "missing" else "missing"
            self._render()

    def action_saved_filters(self) -> None:
        self._load("saved")

    def action_save_filter(self) -> None:
        if self.view == "screen" and self.screen_result and not self.busy:
            self.save_edit = True
            self.history_edit = False
            self._render()
            self._status("只保存上次已执行的条件；不自动运行历史。填名称后 Enter 保存。")

    def _save_named_filter(self) -> None:
        if self.screen_result and not self.busy:
            title = self.query_one("#save-title", Input).value.strip()
            if not title:
                self._status("请先输入条件名称", error=True)
                return
            self._load("save_filter", title, query=self.screen_result.query)

    def action_investigate(self) -> None:
        if self.view == "screen" and self.screen_result and not self.busy:
            if not self.screen_result.query.conditions:
                self._status("历史核对需要明确条件，按 f 填写后再筛选", error=True)
                return
            self.history_edit = True
            self.save_edit = False
            self._render()
            self._status("明确回看与后续交易日，核对并保存历史；覆盖原股票池，不只取当前命中。")

    def _run_history(self) -> None:
        if self.screen_result is None or self.busy:
            return
        try:
            query = StudyQuery(
                title="；".join(condition_text(c) for c in self.screen_result.query.conditions)[:120],
                universe="codes", codes=self.screen_result.scope_codes, as_of=self.screen_result.as_of,
                conditions=self.screen_result.query.conditions, reference=self.screen_result.query.reference,
                lookback_days=int(self.query_one("#history-lookback", Input).value),
                forward_days=int(self.query_one("#history-forward", Input).value),
                sample_policy=cast(Literal["first", "every", "non_overlapping"], self.query_one("#history-policy", Select).value),
            )
        except ValueError:
            self._status("请明确回看 5–1260 个交易日、后续 1–60 个交易日，再执行历史核对", error=True)
            return
        self.history_edit = False
        self._load("investigate", query=query)
