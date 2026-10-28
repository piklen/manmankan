"""个人关注工作台；共享服务计算事实，Textual 只负责浏览和编辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.events import Resize
from textual.widgets import Button, DataTable, Footer, Input, Static
from textual.worker import get_current_worker

from kan.infra.log import redact_text
from kan.tui.screens import AddFocusScreen, DetailScreen, HelpScreen, number, source_labels

if TYPE_CHECKING:
    from kan.domain.focus import FocusRow, FocusSnapshot
    from kan.domain.job import WorkspaceJob


class FocusApp(App[None]):
    """在同一个列表完成关注、查证、记录与复看。"""

    TITLE = "慢慢看 · 我的关注"
    CSS_PATH = "workbench.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("slash", "search", "搜索"),
        Binding("a", "add", "添加"),
        Binding("n", "note", "记观察"),
        Binding("v", "review", "已复看", show=False),
        Binding("r", "reload", "重读"),
        Binding("u", "update", "更新数据"),
        Binding("question_mark", "help", "帮助"),
        Binding("escape", "reset_search", "返回", show=False),
        Binding("q,ctrl+q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.snapshot: FocusSnapshot | None = None
        self.visible_rows: list[FocusRow] = []
        self.selected_symbol: str | None = None
        self.refresh_job_id: str | None = None
        self._polling = False
        self._compact = False
        self._table_ready = False
        self._status_message = "正在读取本机关注与行情缓存…"
        self._refresh_notice: tuple[str, bool] | None = None

    def compose(self) -> ComposeResult:
        yield Static("慢慢看  /  我的关注", id="brand")
        yield Static("看清变化，留下观察。", id="purpose")
        with Horizontal(id="toolbar"):
            yield Input(placeholder="/ 搜索代码或名称", id="search")
            yield Button("添加关注", id="add-focus")
            yield Button("更新数据", id="update-data", variant="primary")
        yield Static("", id="summary", markup=False)
        yield Static("", id="status", markup=False)
        yield DataTable(id="focus-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="empty", markup=False)
        yield Static("↑ ↓ 选择 · Enter 核对证据 · n 记观察 · ? 查看帮助", id="preview", markup=False)
        yield Static("客观数据与个人记录，不构成投资建议。", id="disclaimer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self._compact = self.size.width < 100
        self._add_columns()
        self._table_ready = True
        self.query_one("#empty").display = False
        table.focus()
        self._set_status(self._status_message)
        self.reload_focus()
        self.set_interval(0.7, self._poll_job)

    def _add_columns(self) -> None:
        columns = ["代码", "名称", "涨跌", "30日位置"]
        if not self._compact:
            columns.append("180日位置")
        columns.extend(["行情日", "复看 / 观察"])
        self.query_one(DataTable).add_columns(*columns)

    def on_resize(self, event: Resize) -> None:
        compact = event.size.width < 100
        if self._table_ready and compact != self._compact:
            self._compact = compact
            self.query_one(DataTable).clear(columns=True)
            self._add_columns()
            self._filter_rows()

    def on_unmount(self) -> None:
        # TUI 的更新线程属于本进程；退出只收口本界面启动的任务，保留已写缓存。
        if self.refresh_job_id is None:
            return
        from kan.domain.job import JobStatus
        from kan.infra.log import debug_log
        from kan.service.job_service import TERMINAL_STATUSES, get_job
        from kan.storage import workspace_db

        try:
            job = get_job(self.refresh_job_id)
            if job.status not in TERMINAL_STATUSES:
                workspace_db.update_job(
                    job.job_id, status=JobStatus.INTERRUPTED,
                    message="终端工作台已退出，行情更新中断；重新更新可继续使用已完成缓存",
                )
        except Exception as exc:
            debug_log(__name__, "TUI job shutdown state update failed", exc)

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._status_message = message
        status = self.query_one("#status", Static)
        status.update(message)
        status.set_class(error, "error")

    @work(thread=True, exclusive=True, group="focus")
    def reload_focus(self) -> None:
        from kan.service.focus_service import build_focus_snapshot

        worker = get_current_worker()
        try:
            snapshot = build_focus_snapshot()
        except Exception as exc:
            if not worker.is_cancelled:
                self.call_from_thread(self._load_failed, redact_text(str(exc)))
            return
        if not worker.is_cancelled:
            self.call_from_thread(self._show_snapshot, snapshot)

    def _load_failed(self, message: str) -> None:
        self._set_status(f"读取失败：{message} · 按 r 重试", error=True)
        if self.snapshot is None:
            empty = self.query_one("#empty", Static)
            empty.update("未能读取关注列表。原有记录没有改变。")
            empty.display = True
            self.query_one(DataTable).display = False

    def _show_snapshot(self, snapshot: FocusSnapshot) -> None:
        self.snapshot = snapshot
        self.query_one("#summary", Static).update(
            f"关注 {snapshot.total} 只  ·  有行情 {snapshot.available} 只  ·  "
            f"待更新 {snapshot.stale} 只  ·  应有行情日 {snapshot.expected_cutoff or '未知'}"
        )
        if not self.refresh_job_id:
            if self._refresh_notice:
                message, error = self._refresh_notice
                self._set_status(message, error=error)
            else:
                self._set_status(
                    "；".join(snapshot.warnings)
                    if snapshot.warnings else
                    "本机缓存 · 涨跌与位置变化均较上一条行情；按 u 更新行情"
                )
        self._filter_rows()

    def _filter_rows(self) -> None:
        if self.snapshot is None:
            return
        query = self.query_one("#search", Input).value.strip().casefold()
        self.visible_rows = [
            row for row in self.snapshot.rows
            if query in row.symbol.casefold() or query in row.name.casefold()
        ]
        table = self.query_one(DataTable)
        table.clear()
        for row in self.visible_rows:
            periods = {item.period: item.position_pct for item in row.periods}
            change = Text(number(row.change_pct, "%", signed=True))
            if row.change_pct:
                change.stylize("#ef8187" if row.change_pct > 0 else "#82cbae")
            note = row.note.replace("\n", " ").strip()
            progress = "已复看" if row.reviewed else "待复看"
            if not row.available:
                progress = "缺行情"
            date_text = str(row.data_cutoff) if row.data_cutoff else "—"
            if row.stale and row.available:
                date_text += " *"
            cells: list[str | Text] = [
                Text(row.symbol), Text(row.name), change, number(periods.get(30), "%"),
            ]
            if not self._compact:
                cells.append(number(periods.get(180), "%"))
            cells.extend([date_text, Text(f"{progress} · {note[:18]}" if note else progress)])
            table.add_row(*cells, key=row.symbol)
        has_rows = bool(self.visible_rows)
        table.display = has_rows
        empty = self.query_one("#empty", Static)
        empty.display = not has_rows
        empty.update(
            "没有匹配的代码或名称。按 Esc 清空搜索。" if query else
            "从你关心的公司开始\n\n按 a 添加一个明确代码，或点击「添加关注」。\n"
            "已有自选、持仓与候选会自动汇总到这里，原有记录保持不变。"
        )
        if has_rows:
            selected = next(
                (i for i, row in enumerate(self.visible_rows) if row.symbol == self.selected_symbol),
                0,
            )
            table.move_cursor(row=selected)
            self._preview(self.visible_rows[selected])
        else:
            self.selected_symbol = None
            self.query_one("#preview", Static).update("添加关注后，Enter 核对事实，n 记录观察。")

    def _selected(self) -> FocusRow | None:
        return next((row for row in self.visible_rows if row.symbol == self.selected_symbol), None)

    def _preview(self, row: FocusRow) -> None:
        self.selected_symbol = row.symbol
        periods = "  ·  ".join(
            f"{period.period}日 {number(period.change_pp, signed=True)} pp"
            for period in row.periods
        )
        note = row.note.replace("\n", " ").strip()
        self.query_one("#preview", Static).update(
            f"{row.name} {row.symbol}  ·  收盘 {number(row.price)}  ·  {source_labels(row)}\n"
            f"位置较上一条行情：{periods or '暂无可比数据'}\n"
            f"观察：{note or '还没有记录，按 n 写下关注原因或待核对的问题'}"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self._filter_rows()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one(DataTable).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row = next((item for item in self.visible_rows if item.symbol == event.row_key.value), None)
        if row is not None:
            self._preview(row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_detail()

    def _open_detail(self, *, edit: bool = False) -> None:
        row = self._selected()
        if row is not None:
            self.push_screen(DetailScreen(row, edit=edit))

    def action_note(self) -> None:
        self._open_detail(edit=True)

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_reset_search(self) -> None:
        search = self.query_one("#search", Input)
        search.value = ""
        self.query_one(DataTable).focus()

    def action_add(self) -> None:
        self.push_screen(AddFocusScreen(), self._focus_added)

    def _focus_added(self, symbol: str | None) -> None:
        if symbol is not None:
            self.selected_symbol = symbol
            self.query_one("#search", Input).value = ""
            self.reload_focus()
            self.query_one(DataTable).focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_reload(self) -> None:
        self._refresh_notice = None
        self._set_status("正在重新读取本机数据…")
        self.reload_focus()

    def action_review(self) -> None:
        from kan.service.focus_service import mark_focus_reviewed

        row = self._selected()
        if row is None:
            return
        try:
            mark_focus_reviewed(
                row.symbol, expected_data_hash=row.data_hash, expected_note=row.note,
            )
        except Exception as exc:
            self._set_status(redact_text(str(exc)), error=True)
            return
        self.reload_focus()
        self.notify(f"已记录 {row.name} 的复看状态")

    def action_update(self) -> None:
        from kan.domain.job import MarketRefreshRequest, MarketRefreshScope
        from kan.service.job_service import start_market_refresh_job

        if self.refresh_job_id:
            self.notify("关注池数据正在更新")
            return
        if self.snapshot is not None and self.snapshot.total == 0:
            self._set_status("请先添加关注，再更新行情。")
            return
        self.query_one("#update-data", Button).disabled = True
        self._refresh_notice = None
        self._set_status("正在启动关注池行情更新…")
        try:
            job = start_market_refresh_job(MarketRefreshRequest(scope=MarketRefreshScope.FOCUS))
        except Exception as exc:
            self._update_failed(redact_text(str(exc)))
            return
        self.refresh_job_id = job.job_id
        self._set_status(job.message)

    def _update_failed(self, error: str) -> None:
        self.refresh_job_id = None
        self.query_one("#update-data", Button).disabled = False
        self._set_status(f"更新失败：{error} · 仍可查看本机缓存", error=True)

    def _poll_job(self) -> None:
        if self.refresh_job_id and not self._polling:
            self._polling = True
            self._read_job(self.refresh_job_id)

    @work(thread=True, exclusive=True, group="job")
    def _read_job(self, job_id: str) -> None:
        from kan.service.job_service import get_job

        worker = get_current_worker()
        try:
            job = get_job(job_id)
        except Exception as exc:
            if not worker.is_cancelled:
                self.call_from_thread(self._poll_failed, redact_text(str(exc)))
            return
        if not worker.is_cancelled:
            self.call_from_thread(self._show_job, job)

    def _poll_failed(self, error: str) -> None:
        self._polling = False
        self._set_status(f"暂时无法读取更新进度：{error}", error=True)

    def _show_job(self, job: WorkspaceJob) -> None:
        from kan.domain.job import JobStatus
        from kan.service.job_service import TERMINAL_STATUSES

        self._polling = False
        message = f"{job.message}{' · ' + job.error if job.error else ''}"
        if job.status not in TERMINAL_STATUSES:
            message += " · 退出会中断本次更新，已完成缓存保留"
        self._set_status(message, error=bool(job.error))
        if job.status in TERMINAL_STATUSES:
            self._refresh_notice = (message, bool(job.error))
            self.refresh_job_id = None
            self.query_one("#update-data", Button).disabled = False
            if job.status in {JobStatus.SUCCEEDED, JobStatus.PARTIAL}:
                self.reload_focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-focus":
            self.action_add()
        elif event.button.id == "update-data":
            self.action_update()
