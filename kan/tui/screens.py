"""工作台的详情与短表单；输入始终按文本显示，避免 Rich 标记误解析。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast
from zoneinfo import ZoneInfo

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from kan.infra.log import redact_text
from kan.render.base import DISCLAIMER

if TYPE_CHECKING:
    from kan.domain.focus import FocusRow
    from kan.tui.app import FocusApp


def number(value: float | None, suffix: str = "", *, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}{suffix}" if signed else f"{value:.2f}{suffix}"


def source_labels(row: FocusRow) -> str:
    labels = {"watchlist": "自选", "holding": "持仓", "candidate": "研究关注"}
    return " / ".join(labels.get(source, source) for source in row.sources)


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,question_mark,q", "dismiss", "返回")]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog", classes="dialog"):
            yield Static("慢慢看 · 键盘帮助", classes="dialog-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(
                "↑ ↓ / PageUp PageDown    选择关注的股票\n"
                "Enter                    打开证据与观察笔记\n"
                "/                        搜索代码或名称\n"
                "a                        添加明确股票代码\n"
                "n                        编辑所选股票的观察笔记\n"
                "v                        标记所选行情日已复看\n"
                "r                        重新读取本机数据\n"
                "u                        从已配置数据源更新关注池\n"
                "Esc                      清空搜索 / 返回列表\n"
                "q / Ctrl+Q               退出工作台\n\n"
                "初次打开只读取本机缓存。数据日、缺失与陈旧状态会明确显示。\n"
                "位置变化按同一复权序列的上一条行情比较，不代表交易信号。\n"
                "备注与复看记录保存在本机，Web 与终端共用。",
                    markup=False,
                    id="help-copy",
                )
                yield Static(Text(DISCLAIMER.strip()), classes="muted")
            yield Button("返回工作台", id="help-close", variant="primary")

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class AddFocusScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "返回")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog", id="add-dialog"):
            yield Static("添加关注", classes="dialog-title")
            yield Static("输入 6 位股票代码。添加后可在列表里写下关注原因。", markup=False)
            yield Input(placeholder="例如 600519", id="add-symbol", max_length=6)
            yield Static("", id="add-error", classes="error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button("添加关注", id="add-submit", variant="primary")
                yield Button("取消", id="add-cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-cancel":
            self.dismiss(None)
        else:
            self._submit()

    def _submit(self) -> None:
        from kan.service.focus_service import add_focus

        symbol = self.query_one(Input).value.strip()
        try:
            add_focus(symbol)
        except Exception as exc:
            self.query_one("#add-error", Static).update(redact_text(str(exc)))
            return
        self.dismiss(symbol)


class DetailScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "返回列表"),
        Binding("ctrl+s", "save", "保存笔记"),
    ]

    def __init__(self, row: FocusRow, *, edit: bool = False) -> None:
        super().__init__()
        self.row = row
        self.edit = edit
        self._discard_armed = False

    def compose(self) -> ComposeResult:
        row = self.row
        with Vertical(id="detail-dialog", classes="dialog"):
            yield Static(Text(f"{row.name}  {row.symbol}"), classes="dialog-title")
            with VerticalScroll(id="detail-evidence"):
                date_text = str(row.data_cutoff) if row.data_cutoff else "尚无行情"
                yield Static(
                    Text(
                        f"收盘 {number(row.price)}  ·  较上一条行情 {number(row.change_pct, '%', signed=True)}\n"
                        f"行情日 {date_text}  ·  对比日 {row.previous_cutoff or '—'}\n"
                        f"来自 {source_labels(row)}  ·  {'数据待更新' if row.stale else '本机缓存'}\n"
                        f"行情来源 {row.source}  ·  缓存更新 {row.fetched_at or '未知'}"
                    ),
                    id="detail-facts",
                )
                if row.message:
                    yield Static(Text(row.message), classes="muted")
                yield Static("区间位置与变化", classes="section-title")
                lines = ["周期       当前位置       上条位置        变化（百分点）"]
                for period in row.periods:
                    lines.append(
                        f"{period.period:>3} 日      {number(period.position_pct, '%'):>8}"
                        f"       {number(period.previous_position_pct, '%'):>8}"
                        f"         {number(period.change_pp, signed=True):>7}"
                    )
                yield Static(Text("\n".join(lines)), id="detail-periods")
                yield Static(
                    "位置 =（收盘价 − 区间最低价）÷（区间最高价 − 区间最低价）。\n"
                    "变化使用同一复权序列，历史不足的周期显示 —。",
                    classes="muted", markup=False,
                )
                if row.review_history:
                    yield Static("最近复看", classes="section-title")
                    history_lines: list[str] = []
                    for entry in row.review_history:
                        recorded_at = entry.reviewed_at.astimezone(ZoneInfo("Asia/Shanghai"))
                        positions = " / ".join(
                            f"{period}日 {number(entry.positions.get(str(period)), '%')}"
                            for period in (30, 60, 180)
                        )
                        history_lines.extend([
                            f"行情 {entry.data_cutoff} · 复看 {recorded_at:%m-%d %H:%M}",
                            f"当时收盘 {number(entry.price)} · 位置 {positions}",
                            f"当时观察：{entry.note or '未记录'}",
                            "",
                        ])
                    yield Static(
                        Text("\n".join(history_lines).rstrip()),
                        id="detail-history",
                    )
            yield Static("我的观察 · 记录关注原因与待核对的问题", classes="section-title")
            yield TextArea(row.note, id="note-editor", soft_wrap=True, show_line_numbers=False)
            yield Static("Ctrl+S 保存 · 备注只保存在本机", id="note-status", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button("保存笔记", id="save-note", variant="primary")
                yield Button(
                    "已复看" if row.reviewed else "标记已复看", id="review-row",
                    disabled=not row.available or row.reviewed,
                )
                yield Button("返回列表", id="detail-close")
            yield Static(Text(DISCLAIMER.strip()), classes="muted")

    def on_mount(self) -> None:
        self.query_one("#detail-dialog").set_class(self.size.height < 30, "compact")
        if self.edit:
            self.query_one("#note-editor", TextArea).focus()
        else:
            self.query_one("#detail-evidence", VerticalScroll).focus()

    def on_resize(self, event: Resize) -> None:
        if self.query("#detail-dialog"):
            self.query_one("#detail-dialog").set_class(event.size.height < 30, "compact")

    def action_close(self) -> None:
        editor = self.query_one("#note-editor", TextArea)
        if editor.text != self.row.note and not self._discard_armed:
            self.query_one("#note-status", Static).update(
                "笔记尚未保存。按 Ctrl+S 保存，或再次按 Esc 放弃本次修改。"
            )
            # 第二次返回只放弃当前编辑，不改写本机已保存的笔记。
            self._discard_armed = True
            return
        self.dismiss(None)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._discard_armed = False

    def action_save(self) -> None:
        from kan.service.focus_service import update_focus_note

        note = self.query_one("#note-editor", TextArea).text
        status = self.query_one("#note-status", Static)
        if len(note) > 2_000:
            status.update("保存失败：观察笔记最多 2000 字；当前输入仍保留。")
            return
        try:
            update_focus_note(self.row.symbol, note, list_id=self.row.candidate_list_id)
        except Exception as exc:
            status.update(f"保存失败：{redact_text(str(exc))}")
            return
        self.row = self.row.model_copy(update={"note": note})
        self._discard_armed = False
        status.update("已保存 · Web 与终端共用这份观察笔记")
        cast("FocusApp", self.app).reload_focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-note":
            self.action_save()
        elif event.button.id == "detail-close":
            self.action_close()
        elif event.button.id == "review-row":
            from kan.service.focus_service import mark_focus_reviewed

            if self.query_one(TextArea).text != self.row.note:
                self.query_one("#note-status", Static).update("请先保存当前笔记，再标记已复看。")
                return
            try:
                mark_focus_reviewed(
                    self.row.symbol, expected_data_hash=self.row.data_hash, expected_note=self.row.note,
                )
            except Exception as exc:
                self.query_one("#note-status", Static).update(redact_text(str(exc)))
                return
            event.button.label = "已复看"
            event.button.disabled = True
            self.query_one("#note-status", Static).update("已记录当前行情日的复看状态")
            cast("FocusApp", self.app).reload_focus()
