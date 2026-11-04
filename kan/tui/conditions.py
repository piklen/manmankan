"""终端的明确趋势条件输入；只组装共享查询，不计算指标。"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal, cast

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Select, Static

from kan.domain.market_study import StudyCondition, StudyField
from kan.service.trend_search import TrendSearchQuery

KINDS = [
    ("上升波段结构", "swing_up"), ("下降波段结构", "swing_down"), ("混合波段结构", "swing_mixed"),
    ("区间阳多于阴且上涨", "bullish_window"), ("区间阴多于阳且下跌", "bearish_window"),
    ("连续上涨", "up_days"), ("连续下跌", "down_days"),
    ("连续阳线", "bull_days"), ("连续阴线", "bear_days"),
    ("先跌后涨", "down_then_up"), ("先涨后跌", "up_then_down"),
    ("最近 N 日上涨次数", "rising"), ("最近 N 日下跌次数", "falling"),
    ("最近 N 根阳线数量", "bull_count"), ("最近 N 根阴线数量", "bear_count"),
]
WINDOW_COUNTS = {"rising": "rising_days", "falling": "falling_days", "bull_count": "bull_count", "bear_count": "bear_count"}
SWING_KINDS = {"swing_up": 1, "swing_down": -1, "swing_mixed": 0}
BALANCED_KINDS = {"bullish_window", "bearish_window"}


class TrendFilterForm(Vertical):
    _original_query: TrendSearchQuery | None = None
    _locked = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Select(KINDS, prompt="选择条件类型", id="filter-kind")
            yield Select([("个人池", "personal"), ("全市场", "all"), ("明确代码", "codes")], value="personal", allow_blank=False, id="filter-universe")
            yield Input(placeholder="代码，用空格或逗号分隔", id="filter-codes", disabled=True)
        with Horizontal(classes="form-row"):
            yield Input(placeholder="天数 N（必填）", type="integer", id="filter-days")
            yield Input(placeholder="另一段天数（必填）", type="integer", id="filter-other")
            yield Input(value="5", placeholder="转折确认幅度 %", type="number", id="filter-reversal", tooltip="收盘反向移动达到此百分比才确认一次转折；0–100 之间")
            yield Select([("至少 ≥", "gte"), ("恰好 =", "eq"), ("最多 ≤", "lte")], value="gte", allow_blank=False, id="filter-operator")
            yield Button("执行筛选", variant="primary", id="filter-run")
        with Horizontal(classes="form-row"):
            yield Input(placeholder="截止日 YYYY-MM-DD；留空取最近收盘", id="filter-as-of")
            yield Select([("不对比", "none"), ("对比上个交易日", "previous_session")], value="none", allow_blank=False, id="filter-compare")
            yield Button("新建条件", id="filter-new")
        yield Static("Ctrl+Enter 执行 · Tab 切换 · 最多连续只包含 1–N 天 · Esc 回结果", id="filter-hint", markup=False)

    def on_mount(self) -> None:
        self._labels()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._labels()

    def _labels(self) -> None:
        kind = self.query_one("#filter-kind", Select).value
        days, other = self.query_one("#filter-days", Input), self.query_one("#filter-other", Input)
        other.display = kind in {"down_then_up", "up_then_down", *WINDOW_COUNTS}
        self.query_one("#filter-reversal", Input).display = kind in SWING_KINDS
        self.query_one("#filter-operator", Select).display = kind not in {*SWING_KINDS, *BALANCED_KINDS}
        days.placeholder = {
            "down_then_up": "后上涨 N 天", "up_then_down": "后下跌 N 天",
            **dict.fromkeys([*WINDOW_COUNTS, *SWING_KINDS, *BALANCED_KINDS], "观察窗口 N（交易日）"),
        }.get(str(kind), "天数 N（必填）")
        other.placeholder = {"down_then_up": "此前下跌 M 天", "up_then_down": "此前上涨 M 天", "rising": "其中上涨 M 天", "falling": "其中下跌 M 天", "bull_count": "其中阳线 M 根", "bear_count": "其中阴线 M 根"}.get(str(kind), "天数 M")
        self.query_one("#filter-codes", Input).disabled = self.query_one("#filter-universe", Select).value != "codes"
        for selector in ("#filter-kind", "#filter-days", "#filter-other", "#filter-operator", "#filter-reversal"):
            self.query_one(selector).disabled = self._locked
        hint = "Ctrl+Enter 执行 · Tab 切换 · 最多连续只含 1–N 天 · Ctrl+N 新建"
        if kind in SWING_KINDS:
            hint = "N 根收盘 · 右侧为反向确认幅度 % · 至少两组确认峰谷判断结构"
        elif kind in BALANCED_KINDS:
            hint = "N 根 K 线阳阴数之差与 N 日净涨跌同向；十字线不计入阳阴"
        self.query_one("#filter-hint", Static).update(
            "原条件完整保留；可改范围和日期。修改条件请先点「新建」。" if self._locked else
            hint
        )

    def read_query(self) -> TrendSearchQuery:
        universe = cast(Literal["personal", "all", "codes"], self.query_one("#filter-universe", Select).value)
        codes = re.split(r"[,，\s]+", self.query_one("#filter-codes", Input).value.strip()) if universe == "codes" else []
        raw_date = self.query_one("#filter-as-of", Input).value.strip()
        try:
            as_of = date.fromisoformat(raw_date) if raw_date else None
        except ValueError as exc:
            raise ValueError("截止日请填写有效日期，例如 2026-09-29；留空取最近收盘") from exc
        values = self._original_query.model_dump() if self._original_query else {}
        comparison = str(self.query_one("#filter-compare", Select).value)
        values.update(universe=universe, codes=[code for code in codes if code], as_of=as_of,
                      compare_to=None if comparison == "none" else comparison)
        if self._locked:
            return TrendSearchQuery.model_validate(values)
        kind = self.query_one("#filter-kind", Select).value
        if kind is Select.BLANK:
            if self._original_query is not None and not self._original_query.conditions:
                return TrendSearchQuery.model_validate(values)
            raise ValueError("先选择波段结构、区间、连续涨跌或阳阴线条件")
        window_kind = kind in {*WINDOW_COUNTS, *SWING_KINDS, *BALANCED_KINDS}
        count = self._integer("#filter-days", "天数 N", minimum=2 if window_kind else 1)
        operator = cast(Literal["gte", "eq", "lte"], self.query_one("#filter-operator", Select).value)
        other = self._integer("#filter-other", "数量 M", minimum=0 if kind in WINDOW_COUNTS else 1) if kind in {"down_then_up", "up_then_down", *WINDOW_COUNTS} else None
        if kind in SWING_KINDS:
            conditions = [StudyCondition(field="swing_structure", operator="eq", window=count, value=SWING_KINDS[str(kind)])]
            try:
                values["swing_reversal_pct"] = float(self.query_one("#filter-reversal", Input).value)
            except ValueError as exc:
                raise ValueError("转折确认幅度请填写大于 0 且小于 100 的百分数") from exc
        elif kind in BALANCED_KINDS:
            direction = "gt" if kind == "bullish_window" else "lt"
            conditions = [StudyCondition(field=field, operator=cast(Literal["gt", "lt"], direction), window=count, value=0) for field in ("candle_balance", "return_pct")]
        elif kind in WINDOW_COUNTS:
            if other is not None and other > count:
                raise ValueError("区间计数不能超过交易日窗口")
            conditions = [StudyCondition(field=cast(StudyField, WINDOW_COUNTS[str(kind)]), operator=operator, window=count, value=cast(int, other))]
        elif kind in {"down_then_up", "up_then_down"}:
            current, previous = ("up_days", "previous_down_days") if kind == "down_then_up" else ("down_days", "previous_up_days")
            conditions = [StudyCondition(field=cast(StudyField, current), operator=operator, value=count), StudyCondition(field=cast(StudyField, previous), operator=operator, value=cast(int, other))]
        else:
            conditions = [StudyCondition(field=cast(StudyField, kind), operator=operator, value=count)]
        if operator == "lte" and not window_kind:
            conditions += [StudyCondition(field=c.field, operator="gt", value=0) for c in conditions]
        values["conditions"] = conditions
        return TrendSearchQuery.model_validate(values)

    def _integer(self, selector: str, label: str, minimum: int = 1) -> int:
        value = self.query_one(selector, Input).value.strip()
        if not value.isdigit() or int(value) < minimum:
            raise ValueError(f"请明确填写 {label}，至少为 {minimum}")
        return int(value)


    def set_query(self, query: TrendSearchQuery) -> None:
        """恢复本面板能完整表达的条件；不将高级查询静默简化。"""
        self._original_query = query
        streak_fields = {"up_days", "down_days", "bull_days", "bear_days", "previous_up_days", "previous_down_days"}
        # 只折叠“最多连续 N 天”配套的方向限制，涨幅 > 0 等真实条件不能丢。
        bounded_fields = {c.field for c in query.conditions if c.field in streak_fields and c.operator == "lte"}
        guards = {c.field for c in query.conditions if c.field in bounded_fields and c.operator == "gt" and c.value == 0}
        conditions = [c for c in query.conditions if not (c.field in guards and c.operator == "gt" and c.value == 0)]
        kind: str | None = None
        days = other = ""
        simple_scope = not query.industries and query.reference is None
        if simple_scope and len(conditions) == 1 and conditions[0].field == "swing_structure" and conditions[0].operator == "eq" and conditions[0].value in {-1, 0, 1}:
            kind = next(key for key, value in SWING_KINDS.items() if value == conditions[0].value)
            days = str(conditions[0].window)
        elif simple_scope and len(conditions) == 2 and {c.field for c in conditions} == {"candle_balance", "return_pct"} and conditions[0].window == conditions[1].window and all(c.value == 0 and c.operator == conditions[0].operator for c in conditions) and conditions[0].operator in {"gt", "lt"}:
            kind = "bullish_window" if conditions[0].operator == "gt" else "bearish_window"
            days = str(conditions[0].window)
        elif simple_scope and conditions and bounded_fields == guards and all(c.operator in {"gte", "eq", "lte"} and c.value.is_integer() and c.value >= (0 if c.field in WINDOW_COUNTS.values() else 1) for c in conditions):
            first = conditions[0]
            if len(conditions) == 1 and first.field in (streak_fields | set(WINDOW_COUNTS.values())):
                kind = {field: key for key, field in WINDOW_COUNTS.items()}.get(first.field, first.field)
                days = str(first.window if kind in WINDOW_COUNTS else int(first.value))
                other = str(int(first.value)) if kind in WINDOW_COUNTS else ""
            elif len(conditions) == 2 and first.operator == conditions[1].operator:
                by_field: dict[str, StudyCondition] = {c.field: c for c in conditions}
                for current, previous, candidate in (("up_days", "previous_down_days", "down_then_up"), ("down_days", "previous_up_days", "up_then_down")):
                    if set(by_field) == {current, previous}:
                        kind = candidate
                        days, other = str(int(by_field[current].value)), str(int(by_field[previous].value))
        self._locked = bool(query.conditions) and kind is None
        self.query_one("#filter-kind", Select).value = kind if kind else Select.BLANK
        self.query_one("#filter-days", Input).value = days if kind else ""
        self.query_one("#filter-other", Input).value = other if kind else ""
        self.query_one("#filter-reversal", Input).value = f"{query.swing_reversal_pct:g}"
        self.query_one("#filter-universe", Select).value = query.universe
        self.query_one("#filter-codes", Input).value = ",".join(query.codes)
        self.query_one("#filter-as-of", Input).value = str(query.as_of or "")
        options = [("不对比", "none"), ("对比上个交易日", "previous_session")]
        if isinstance(query.compare_to, date):
            options.append((f"对照 {query.compare_to}", str(query.compare_to)))
        comparison = self.query_one("#filter-compare", Select)
        comparison.set_options(options)
        comparison.value = str(query.compare_to or "none")
        if kind and kind not in {*SWING_KINDS, *BALANCED_KINDS}:
            self.query_one("#filter-operator", Select).value = conditions[0].operator
        self._labels()
        if not query.conditions:
            self.query_one("#filter-hint", Static).update("无条件浏览此范围；可改日期，或选择类型与天数后筛选")

    def new_query(self) -> None:
        """用户明确新建后，才解除高级条件的完整保留状态。"""
        self.set_query(TrendSearchQuery(universe="personal"))
        self._original_query = None
        self._labels()
