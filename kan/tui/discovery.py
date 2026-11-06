"""市场观察屏：复用聚合结果，沿行业、成员和日线逐层查证。"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Literal, cast

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Input, Select, Static
from textual.worker import get_current_worker

from kan.domain.discovery import DiscoveryGroup, DiscoveryQuery, DiscoveryResult
from kan.infra.log import redact_text
from kan.service import discovery, trend_search
from kan.tui.screens import number, trend_evidence_view


class DiscoveryScreen(Screen[str]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+enter", "refresh", "观察", priority=True),
        Binding("v", "profile", "分布与轨迹"),
        Binding("f", "filters", "高级筛选"),
        Binding("d", "common_date", "已有数据日", show=False),
        Binding("escape", "back", "返回"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.result: DiscoveryResult | None = None
        self.industry: str | None = None
        self.view: Literal["industries", "members", "profile", "evidence"] = "industries"
        self.busy = False
        self.industry_cursor = 0
        self.member_cursor = 0

    def compose(self) -> ComposeResult:
        yield Static("慢慢看  /  市场观察", id="discovery-brand")
        yield Static("看参与范围怎样改变，再进入行业与日线核对。", id="discovery-intro")
        with Horizontal(id="discovery-controls", classes="form-row"):
            yield Select([("全市场", "all"), ("个人范围", "personal")], value="all", allow_blank=False, id="discovery-universe")
            yield Static("窗口/日", id="discovery-window-label")
            yield Input("20", placeholder="窗口 2–120 日", type="integer", id="discovery-window")
            yield Input(placeholder="截止日 YYYY-MM-DD", id="discovery-date")
            yield Button("观察", id="discovery-run", variant="primary")
        yield Static("正在读取本地行情…", id="discovery-status", markup=False)
        with Horizontal(id="discovery-common"):
            yield Static("", id="discovery-common-text", markup=False)
            yield Button("查看此日 d", id="discovery-use-date")
        yield Static("", id="discovery-summary", markup=False)
        yield Static("", id="discovery-observations", markup=False)
        yield DataTable(id="discovery-results", cursor_type="row", zebra_stripes=True)
        with VerticalScroll(id="discovery-detail"):
            yield Static("", id="discovery-detail-content", markup=False)
        yield Static("", id="discovery-preview", markup=False)
        yield Static("当前范围与行业归属 · 本地日线 · 缺失不填零 · 历史事实", id="discovery-boundary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#discovery-common").display = False
        self.query_one("#discovery-detail").display = False
        self.action_refresh()

    def on_screen_resume(self) -> None:
        if self.is_mounted and self.result is None and not self.busy:
            self.action_refresh()

    def _status(self, message: str, *, error: bool = False) -> None:
        widget = self.query_one("#discovery-status", Static)
        widget.update(message)
        widget.set_class(error, "error")

    def action_refresh(self) -> None:
        if self.busy:
            return
        try:
            day = self.query_one("#discovery-date", Input).value.strip()
            query = DiscoveryQuery(
                universe=cast(Literal["all", "personal"], self.query_one("#discovery-universe", Select).value),
                window=int(self.query_one("#discovery-window", Input).value),
                as_of=date.fromisoformat(day) if day else None,
            )
        except ValueError:
            self._status("窗口填写 2–120 个交易日；截止日用 YYYY-MM-DD，留空取最近完整收盘。", error=True)
            return
        self._load(query)

    def _load(self, query: DiscoveryQuery, symbol: str | None = None) -> None:
        self.busy = True
        self.query_one("#discovery-run", Button).disabled = True
        self._status("正在核对日线…" if symbol else "正在计算完整范围的分布与变化…")
        self._read(query, symbol)

    @work(thread=True, exclusive=True, group="discovery")
    def _read(self, query: DiscoveryQuery, symbol: str | None) -> None:
        worker = get_current_worker()
        try:
            value = trend_search.trend_search_evidence(
                trend_search.TrendSearchQuery(universe="codes", codes=[symbol], as_of=query.as_of), symbol,
            ) if symbol else discovery.discover_market(query)
        except Exception as exc:
            if not worker.is_cancelled:
                self.app.call_from_thread(self._failed, redact_text(str(exc)))
            return
        if not worker.is_cancelled:
            self.app.call_from_thread(self._loaded, value)

    def _failed(self, message: str) -> None:
        self.busy = False
        self.query_one("#discovery-run", Button).disabled = False
        self._status(f"未完成：{message}。现有结果保留。", error=True)

    def _loaded(self, value: DiscoveryResult | trend_search.TrendSearchEvidence) -> None:
        self.busy = False
        self.query_one("#discovery-run", Button).disabled = False
        if isinstance(value, DiscoveryResult):
            self.result = value
            self.industry = None
            self.view = "industries"
            self.industry_cursor = self.member_cursor = 0
        else:
            self.view = "evidence"
            self.query_one("#discovery-detail-content", Static).update(trend_evidence_view(value))
        self._show_results()
        self._status("Enter 行业 → 成员 → 日线 · v 分布与轨迹 · f 高级筛选")

    def _group(self) -> DiscoveryGroup:
        assert self.result is not None
        return next(group for group in self.result.industries if group.name == self.industry) if self.industry else self.result.market

    def _show_results(self) -> None:
        result = self.result
        if result is None:
            return
        group = self._group()
        stats, comparison = group.current, group.comparison
        details = self.view in {"profile", "evidence"}
        self.query_one("#discovery-results").display = not details
        self.query_one("#discovery-detail").display = details
        self.query_one("#discovery-observations").display = not details
        self.query_one("#discovery-preview").display = not details
        self.query_one("#discovery-brand", Static).update(f"慢慢看  /  市场观察  /  {self.industry or '全部范围'}")
        self.query_one("#discovery-summary", Static).update(
            f"{result.query.window} 交易日 · {result.current_start or '起日不足'} → {result.as_of} · 有效 {stats.available}/{stats.total}，缺口 {stats.missing}\n"
            f"上涨 {stats.up} / 下跌 {stats.down} / 持平 {stats.flat} · 中位数 {number(stats.median_return, '%', signed=True)}\n"
            f"两段同组 {comparison.available}/{stats.total} · 上涨占比变化 {number(comparison.breadth_delta_pp, ' 个百分点', signed=True)}"
        )
        self.query_one("#discovery-observations", Static).update("\n".join(item.title for item in group.observations[1:]))
        stale = result.common_data_date is not None and result.common_data_date < result.as_of
        self.query_one("#discovery-common").display = stale
        self.query_one("#discovery-common-text", Static).update(f"本地主要行情 {result.common_data_date} · {result.common_data_count} 只")
        if self.view == "profile":
            self.query_one("#discovery-detail-content", Static).update(self._profile(group))
        if details:
            self.query_one("#discovery-detail", VerticalScroll).scroll_home(animate=False)
            self.query_one("#discovery-detail", VerticalScroll).focus()
            return
        table = self.query_one("#discovery-results", DataTable)
        table.clear(columns=True)
        if self.view == "industries":
            for label, width in (("行业", 14), ("有效/范围", 10), ("上涨占比", 10), ("涨跌中位数", 12), ("变化/百分点", 12)):
                table.add_column(label, width=width)
            for item in result.industries:
                table.add_row(Text(item.name), f"{item.current.available}/{item.total}", number(item.current.positive_share, "%"), number(item.current.median_return, "%", signed=True), number(item.comparison.breadth_delta_pp, signed=True), key=item.name)
        else:
            labels = {item.key: item.label for item in group.transitions}
            for label, width in (("代码", 7), ("名称", 12), ("本段%", 9), ("前段%", 9), ("两段关系", 24)):
                table.add_column(label, width=width)
            for member in result.members:
                if member.industry == self.industry:
                    table.add_row(member.symbol, Text(member.name), number(member.return_pct, signed=True), number(member.previous_return_pct, signed=True), labels[member.transition], key=member.symbol)
        self.query_one("#discovery-preview", Static).update("完整范围为空：先在数据工具中添加个人关注或更新市场范围。" if not table.row_count else "↑ ↓ 选择 · Enter 下钻 · Esc 返回上一层；缺行情成员仍保留在范围中。")
        table.move_cursor(row=self.industry_cursor if self.view == "industries" else self.member_cursor)
        table.focus() if table.row_count else self.query_one("#discovery-universe", Select).focus()

    def _profile(self, group: DiscoveryGroup) -> Group:
        assert self.result is not None
        distribution = Table("本窗口涨跌分布", "家数", box=None, expand=True)
        for item in group.distribution:
            distribution.add_row(item.label, str(item.count))
        transitions = Table("相邻等长窗口", "家数", box=None, expand=True)
        for transition in group.transitions:
            transitions.add_row(transition.label, str(transition.count))
        history = Table("滚动窗口截止日", "上涨/固定范围", "中位涨跌", box=None, expand=True)
        for point in reversed(group.history):
            history.add_row(str(point.date), f"{point.up}/{point.available}", number(point.median_return, "%", signed=True))
        return Group(
            *[Text(f"{item.title}\n{item.detail}\n") for item in group.observations],
            distribution, Text(f"另有 {group.current.missing} 只本窗口资料不足\n"),
            Text(f"前段 {self.result.previous_start or '起日不足'} → {self.result.previous_as_of or '末日不足'}"), transitions,
            Text(f"\n滚动轨迹使用整段均完整的固定 {group.history_available} 只\n"), history,
            Text("\n" + "\n".join(self.result.warnings), style="#a6babf"),
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if self.busy or self.result is None:
            return
        key = str(event.row_key.value)
        if self.view == "industries":
            self.industry_cursor = event.cursor_row
            self.member_cursor = 0
            self.industry, self.view = key, "members"
            self._show_results()
        elif self.view == "members":
            self.member_cursor = event.cursor_row
            member = next(item for item in self.result.members if item.symbol == key)
            if not member.latest_available:
                self._status(f"{member.name}：{member.reason or '所选日无行情'}。缺失不算不符合。", error=True)
                return
            self._load(self.result.query.model_copy(update={"as_of": self.result.as_of}), key)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        if self.result and self.view == "members":
            member = next((item for item in self.result.members if item.symbol == str(event.row_key.value)), None)
            if member:
                self.query_one("#discovery-preview", Static).update(f"{member.name} · {member.reason or member.source} · Enter 核对日线")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "discovery-run":
            self.action_refresh()
        elif event.button.id == "discovery-use-date":
            self.action_common_date()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_refresh()

    def action_common_date(self) -> None:
        if not self.busy and self.result and self.result.common_data_date and self.result.common_data_date < self.result.as_of:
            self.query_one("#discovery-date", Input).value = str(self.result.common_data_date)
            self.action_refresh()

    def action_profile(self) -> None:
        if not self.busy and self.result:
            self.view = "profile"
            self._show_results()

    def action_back(self) -> None:
        if not self.busy:
            if self.view in {"profile", "evidence"}:
                self.view = "members" if self.industry else "industries"
            elif self.view == "members":
                self.industry, self.view = None, "industries"
            self._show_results()

    def action_filters(self) -> None:
        self.workers.cancel_group(self, "discovery")
        self.busy = False
        self.query_one("#discovery-run", Button).disabled = False
        self.dismiss("filters")
