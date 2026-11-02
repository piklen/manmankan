"""终端的明确趋势条件输入；只组装共享查询，不计算指标。"""
from __future__ import annotations

import re
from typing import Literal, cast

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Select, Static

from kan.domain.market_study import StudyCondition, StudyField
from kan.service.trend_search import TrendSearchQuery

KINDS = [
    ("连续上涨", "up_days"), ("连续下跌", "down_days"),
    ("连续阳线", "bull_days"), ("连续阴线", "bear_days"),
    ("先跌后涨", "down_then_up"), ("先涨后跌", "up_then_down"),
    ("最近 N 日上涨次数", "rising"), ("最近 N 日下跌次数", "falling"),
]


class TrendFilterForm(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Select(KINDS, prompt="选择条件类型", id="filter-kind")
            yield Select([("个人池", "personal"), ("全市场", "all"), ("明确代码", "codes")], value="personal", allow_blank=False, id="filter-universe")
            yield Input(placeholder="代码，用空格或逗号分隔", id="filter-codes", disabled=True)
        with Horizontal(classes="form-row"):
            yield Input(placeholder="天数 N（必填）", type="integer", id="filter-days")
            yield Input(placeholder="另一段天数（必填）", type="integer", id="filter-other")
            yield Select([("至少 ≥", "gte"), ("恰好 =", "eq"), ("最多 ≤", "lte")], value="gte", allow_blank=False, id="filter-operator")
            yield Button("执行筛选", variant="primary", id="filter-run")
        yield Static("Ctrl+Enter 执行 · Tab 切换 · 最多连续只包含 1–N 天 · Esc 回结果", id="filter-hint", markup=False)

    def on_mount(self) -> None:
        self._labels()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._labels()

    def _labels(self) -> None:
        kind = self.query_one("#filter-kind", Select).value
        days, other = self.query_one("#filter-days", Input), self.query_one("#filter-other", Input)
        other.display = kind in {"down_then_up", "up_then_down", "rising", "falling"}
        days.placeholder = {
            "down_then_up": "后上涨 N 天", "up_then_down": "后下跌 N 天",
            "rising": "最近 N 个交易日", "falling": "最近 N 个交易日",
        }.get(str(kind), "天数 N（必填）")
        other.placeholder = {"down_then_up": "此前下跌 M 天", "up_then_down": "此前上涨 M 天", "rising": "其中上涨 M 天", "falling": "其中下跌 M 天"}.get(str(kind), "天数 M")
        self.query_one("#filter-codes", Input).disabled = self.query_one("#filter-universe", Select).value != "codes"

    def read_query(self) -> TrendSearchQuery:
        kind = self.query_one("#filter-kind", Select).value
        if kind is Select.BLANK:
            raise ValueError("先选择连续涨跌、阳阴线、前后两段或最近 N 日计数")
        count = self._integer("#filter-days", "天数 N")
        operator = cast(Literal["gte", "eq", "lte"], self.query_one("#filter-operator", Select).value)
        other = self._integer("#filter-other", "天数 M", minimum=0 if kind in {"rising", "falling"} else 1) if kind in {"down_then_up", "up_then_down", "rising", "falling"} else None
        if kind in {"rising", "falling"}:
            conditions = [StudyCondition(field=cast(StudyField, f"{kind}_days"), operator=operator, window=count, value=cast(int, other))]
        elif kind in {"down_then_up", "up_then_down"}:
            current, previous = ("up_days", "previous_down_days") if kind == "down_then_up" else ("down_days", "previous_up_days")
            conditions = [StudyCondition(field=cast(StudyField, current), operator=operator, value=count), StudyCondition(field=cast(StudyField, previous), operator=operator, value=cast(int, other))]
        else:
            conditions = [StudyCondition(field=cast(StudyField, kind), operator=operator, value=count)]
        if operator == "lte" and kind not in {"rising", "falling"}:
            conditions += [StudyCondition(field=c.field, operator="gt", value=0) for c in conditions]
        universe = cast(Literal["personal", "all", "codes"], self.query_one("#filter-universe", Select).value)
        codes = re.split(r"[,，\s]+", self.query_one("#filter-codes", Input).value.strip()) if universe == "codes" else []
        return TrendSearchQuery(universe=universe, codes=[code for code in codes if code], conditions=conditions)

    def _integer(self, selector: str, label: str, minimum: int = 1) -> int:
        value = self.query_one(selector, Input).value.strip()
        if not value.isdigit() or int(value) < minimum:
            raise ValueError(f"请明确填写 {label}，至少为 {minimum}")
        return int(value)


    def set_query(self, query: TrendSearchQuery) -> None:
        """恢复本面板能完整表达的条件；不将高级查询静默简化。"""
        conditions = [c for c in query.conditions if not (c.operator == "gt" and c.value == 0)]
        kind: str | None = None
        days = other = ""
        if not query.industries and query.as_of is None and query.reference is None and conditions and all(c.operator in {"gte", "eq", "lte"} and c.value.is_integer() for c in conditions):
            first = conditions[0]
            if len(conditions) == 1 and first.field in ({value for _label, value in KINDS} | {"rising_days", "falling_days"}):
                kind = {"rising_days": "rising", "falling_days": "falling"}.get(first.field, first.field)
                days = str(first.window if kind in {"rising", "falling"} else int(first.value))
                other = str(int(first.value)) if kind in {"rising", "falling"} else ""
            elif len(conditions) == 2 and first.operator == conditions[1].operator:
                pair = (first.field, conditions[1].field)
                kind = {("up_days", "previous_down_days"): "down_then_up", ("down_days", "previous_up_days"): "up_then_down"}.get(pair)
                days, other = str(int(first.value)), str(int(conditions[1].value))
        self.query_one("#filter-kind", Select).value = kind if kind else Select.BLANK
        self.query_one("#filter-days", Input).value = days if kind else ""
        self.query_one("#filter-other", Input).value = other if kind else ""
        self.query_one("#filter-universe", Select).value = query.universe
        self.query_one("#filter-codes", Input).value = ",".join(query.codes)
        if kind:
            self.query_one("#filter-operator", Select).value = conditions[0].operator
        self._labels()
        if not query.conditions:
            self.query_one("#filter-hint", Static).update("无条件浏览此范围；选择类型与天数后可筛选")
        elif not kind:
            self.query_one("#filter-hint", Static).update("已存条件完整运行；此面板用于新建，不会简化或改写原条件。")
