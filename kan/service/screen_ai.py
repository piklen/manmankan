"""ScreenSpec 的确定性 AI / MCP 适配层。

这里不调用模型，也不生成第二套选股逻辑。模型或人类只负责把意图整理成 ScreenSpec；
plan、run、get 与 explain 最终都回到 ``screen_service`` 和 SQLite repository。
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from kan.core.find_registry import FILTER_SPECS
from kan.domain.screen import (
    ComparisonOperator,
    SavedScreen,
    ScreenCondition,
    ScreenFilterType,
    ScreenRun,
    ScreenSpec,
    StrictModel,
    UniverseKind,
    UniverseSpec,
)
from kan.service import screen_service
from kan.service.screen_catalog import SCREEN_FILTER_CATALOG
from kan.storage import workspace_db


class ParseConfidence(StrEnum):
    EXACT = "exact"
    PARTIAL = "partial"
    NONE = "none"


class ScreenParseInput(StrictModel):
    text: str = Field(min_length=1, max_length=4_000)
    name: str = Field(default="AI 整理的选股条件", min_length=1, max_length=80)


class ScreenParseResult(StrictModel):
    spec: ScreenSpec | None = None
    confidence: ParseConfidence
    matched_expressions: list[str] = Field(default_factory=list)
    ignored_text: str | None = None
    errors: list[str] = Field(default_factory=list)
    executable: bool = False


class ScreenPlanInput(StrictModel):
    spec: ScreenSpec


class ScreenPlan(StrictModel):
    spec: ScreenSpec
    spec_hash: str
    engine_path: Literal["cross_section", "kline"]
    required_dimensions: list[str]
    sources: list[str]
    frequencies: list[str]
    unsupported_filters: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    executable: bool


class ScreenRunInput(StrictModel):
    spec: ScreenSpec | None = None
    screen_id: str | None = None
    persist: bool = True

    @model_validator(mode="after")
    def require_one_target(self) -> ScreenRunInput:
        if (self.spec is None) == (self.screen_id is None):
            raise ValueError("spec 与 screen_id 必须且只能提供一个")
        return self


class ScreenGetInput(StrictModel):
    run_id: str | None = None
    screen_id: str | None = None

    @model_validator(mode="after")
    def require_one_target(self) -> ScreenGetInput:
        if (self.run_id is None) == (self.screen_id is None):
            raise ValueError("run_id 与 screen_id 必须且只能提供一个")
        return self


class ScreenArtifact(StrictModel):
    kind: Literal["screen", "run"]
    screen: SavedScreen | None = None
    run: ScreenRun | None = None


class ScreenExplainInput(StrictModel):
    run_id: str


class RowExplanation(StrictModel):
    symbol: str
    name: str
    rank: int
    facts: list[str]


class ScreenExplanation(StrictModel):
    run_id: str
    screen_name: str
    coverage: str
    freshness: str
    changes: str
    rows: list[RowExplanation]
    warnings: list[str] = Field(default_factory=list)


_ALIASES = {
    "价格区间位置": "pos",
    "位置": "pos",
    "市盈率": "pe",
    "市净率": "pb",
    "股息率": "dv",
    "净资产收益率": "roe",
    "换手率": "turnover",
    "总市值": "market_cap",
    "量比": "volume_ratio",
    "主力净额": "moneyflow",
    "单日主力净额": "moneyflow_daily",
    "连续主力净流入": "moneyflow_days",
    "连板": "streak",
    "获利盘": "winner",
    "股东户数环比": "holders",
    "前十大流通集中度": "top10",
    "北向持股比例": "north",
}
for _filter_type in ScreenFilterType:
    _ALIASES[_filter_type.value] = _filter_type.value

_OPERATORS = {
    "<": ComparisonOperator.LT,
    "<=": ComparisonOperator.LTE,
    ">": ComparisonOperator.GT,
    ">=": ComparisonOperator.GTE,
    "=": ComparisonOperator.EQ,
    "==": ComparisonOperator.EQ,
    "!=": ComparisonOperator.NE,
    "低于": ComparisonOperator.LT,
    "小于": ComparisonOperator.LT,
    "不高于": ComparisonOperator.LTE,
    "至多": ComparisonOperator.LTE,
    "高于": ComparisonOperator.GT,
    "大于": ComparisonOperator.GT,
    "不低于": ComparisonOperator.GTE,
    "至少": ComparisonOperator.GTE,
    "等于": ComparisonOperator.EQ,
    "不等于": ComparisonOperator.NE,
}

_FIELD_PATTERN = "|".join(
    re.escape(item) for item in sorted(_ALIASES, key=len, reverse=True)
)
_OP_PATTERN = "|".join(
    re.escape(item) for item in sorted(_OPERATORS, key=len, reverse=True)
)
_CONDITION_RE = re.compile(
    rf"(?:(?P<period>\d{{1,3}})\s*(?:日|d)\s*)?"
    rf"(?P<field>{_FIELD_PATTERN})\s*"
    rf"(?P<operator>{_OP_PATTERN})\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)
_CODE_RE = re.compile(r"(?<!\d)([0-689]\d{5})(?!\d)")


def _parse_universe(text: str) -> tuple[UniverseSpec, list[tuple[int, int]]]:
    spans: list[tuple[int, int]] = []
    codes = list(dict.fromkeys(_CODE_RE.findall(text)))
    if codes:
        for match in _CODE_RE.finditer(text):
            spans.append(match.span())
        return UniverseSpec(kind=UniverseKind.CODES, codes=codes), spans

    industry = re.search(r"行业\s*[:：]\s*([^,，;；\s]+)", text)
    if industry:
        spans.append(industry.span())
        return UniverseSpec(kind=UniverseKind.INDUSTRY, value=industry.group(1)), spans
    theme = re.search(r"题材\s*[:：]\s*([^,，;；\s]+)", text)
    if theme:
        spans.append(theme.span())
        return UniverseSpec(kind=UniverseKind.THEME, value=theme.group(1)), spans

    for pattern, kind in (
        (r"全市场", UniverseKind.ALL),
        (r"(?:我的)?持仓", UniverseKind.HOLDINGS),
        (r"(?:我的)?自选", UniverseKind.WATCHLIST),
    ):
        universe_match = re.search(pattern, text)
        if universe_match:
            spans.append(universe_match.span())
            return UniverseSpec(kind=kind), spans
    return UniverseSpec(kind=UniverseKind.WATCHLIST), spans


def _remaining_text(text: str, spans: list[tuple[int, int]]) -> str | None:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    remaining = re.sub(r"[\s,，;；。]+", " ", "".join(chars)).strip()
    remaining = re.sub(r"^(请|帮我|筛选|查找|找出|找|看看)+\s*", "", remaining)
    return remaining or None


def parse_screen_text(request: ScreenParseInput) -> ScreenParseResult:
    """把可审计的显式阈值表达式整理为 ScreenSpec，不猜测隐含阈值。"""
    text = request.text.strip()
    universe, spans = _parse_universe(text)
    conditions: list[ScreenCondition] = []
    matched: list[str] = []
    errors: list[str] = []
    for match in _CONDITION_RE.finditer(text):
        spans.append(match.span())
        raw = match.group(0).strip()
        filter_name = _ALIASES[match.group("field").lower()]
        try:
            conditions.append(
                ScreenCondition(
                    type=ScreenFilterType(filter_name),
                    operator=_OPERATORS[match.group("operator")],
                    value=float(match.group("value")),
                    period=(
                        int(match.group("period"))
                        if match.group("period") is not None
                        else None
                    ),
                )
            )
            matched.append(raw)
        except (ValueError, ValidationError) as exc:
            errors.append(f"{raw}: {exc}")

    exclude_st_match = re.search(r"(?:排除|剔除|不要)\s*\*?ST", text, re.IGNORECASE)
    exclude_star_match = re.search(r"(?:排除|剔除|不要)\s*科创板", text)
    exclude_bj_match = re.search(r"(?:排除|剔除|不要)\s*北交所", text)
    for exclusion_match in (exclude_st_match, exclude_star_match, exclude_bj_match):
        if exclusion_match:
            spans.append(exclusion_match.span())

    ignored = _remaining_text(text, spans)
    try:
        spec = ScreenSpec(
            name=request.name,
            universe=universe,
            conditions=conditions,
            exclude_st=exclude_st_match is not None,
            exclude_star=exclude_star_match is not None,
            exclude_bj=exclude_bj_match is not None,
        )
    except ValidationError as exc:
        errors.append(str(exc))
        spec = None
    if spec is None:
        confidence = ParseConfidence.NONE
    elif ignored or errors:
        confidence = ParseConfidence.PARTIAL
    else:
        confidence = ParseConfidence.EXACT
    return ScreenParseResult(
        spec=spec,
        confidence=confidence,
        matched_expressions=matched,
        ignored_text=ignored,
        errors=errors,
        executable=spec is not None,
    )


def plan_screen(spec: ScreenSpec) -> ScreenPlan:
    dimension_set: set[str] = set()
    for item in spec.conditions:
        dimension = FILTER_SPECS[item.type.value].dimension
        if dimension is not None:
            dimension_set.add(dimension)
    dimensions = sorted(dimension_set)
    sources = sorted(
        {SCREEN_FILTER_CATALOG[item.type.value]["source"] for item in spec.conditions}
    )
    frequencies = sorted(
        {SCREEN_FILTER_CATALOG[item.type.value]["frequency"] for item in spec.conditions}
    )
    unsupported = (
        [
            item.type.value
            for item in spec.conditions
            if not FILTER_SPECS[item.type.value].supports_all
        ]
        if spec.universe.kind is UniverseKind.ALL
        else []
    )
    warnings: list[str] = []
    if unsupported:
        warnings.append("全市场路径不支持部分逐股数据条件，请缩小股票池")
    if spec.as_of.trade_date != "latest_complete":
        warnings.append("当前执行引擎只支持 latest_complete")
    return ScreenPlan(
        spec=spec,
        spec_hash=screen_service.content_hash(spec),
        engine_path=(
            "cross_section"
            if spec.universe.kind is UniverseKind.ALL
            else "kline"
        ),
        required_dimensions=dimensions,
        sources=sources,
        frequencies=frequencies,
        unsupported_filters=unsupported,
        warnings=warnings,
        executable=not unsupported and spec.as_of.trade_date == "latest_complete",
    )


def run_from_input(request: ScreenRunInput) -> ScreenRun:
    if request.screen_id is not None:
        return screen_service.run_saved_screen(request.screen_id)
    assert request.spec is not None
    return screen_service.run_screen(request.spec, persist=request.persist)


def get_artifact(request: ScreenGetInput) -> ScreenArtifact:
    if request.run_id is not None:
        run = workspace_db.get_run(request.run_id)
        if run is None:
            raise screen_service.ScreenServiceError(
                "run_not_found", f"ScreenRun 不存在: {request.run_id}"
            )
        return ScreenArtifact(kind="run", run=run)
    assert request.screen_id is not None
    screen = workspace_db.get_screen(request.screen_id)
    if screen is None:
        raise screen_service.ScreenServiceError(
            "screen_not_found", f"Screen 不存在: {request.screen_id}"
        )
    return ScreenArtifact(kind="screen", screen=screen)


_OP_TEXT = {
    ComparisonOperator.LT: "低于",
    ComparisonOperator.LTE: "不高于",
    ComparisonOperator.GT: "高于",
    ComparisonOperator.GTE: "不低于",
    ComparisonOperator.EQ: "等于",
    ComparisonOperator.NE: "不等于",
}


def explain_run(run_id: str) -> ScreenExplanation:
    run = workspace_db.get_run(run_id)
    if run is None:
        raise screen_service.ScreenServiceError(
            "run_not_found", f"ScreenRun 不存在: {run_id}"
        )
    rows: list[RowExplanation] = []
    for row in run.rows:
        facts = [
            (
                f"{SCREEN_FILTER_CATALOG[item.filter_type.value]['label']}"
                f" {_OP_TEXT[item.operator]} {item.threshold:g}"
                f"{item.unit}，实际 {item.actual:g}{item.unit}"
                + (f"，数据日 {item.data_date.isoformat()}" if item.data_date else "")
            )
            for item in row.evidence
        ]
        rows.append(
            RowExplanation(
                symbol=row.symbol,
                name=row.name,
                rank=row.rank,
                facts=facts,
            )
        )
    diff = run.diff
    changes = (
        f"新增 {len(diff.added)}，移出 {len(diff.removed)}，"
        f"排名变化 {len(diff.rank_changes)}"
        if diff.previous_run_id
        else f"首次运行，记录 {len(run.rows)} 只符合条件股票"
    )
    return ScreenExplanation(
        run_id=run.run_id,
        screen_name=run.spec.name,
        coverage=(
            f"评估 {run.coverage.evaluated}/{run.coverage.universe_size}，"
            f"返回 {run.coverage.returned}，缺失 {run.coverage.missing}"
        ),
        freshness=(
            f"数据截止 {run.coverage.data_cutoff.isoformat()}"
            if run.coverage.data_cutoff
            else "数据截止日未知"
        )
        + ("，可能陈旧" if run.coverage.stale else "，完整性检查未发现陈旧标记"),
        changes=changes,
        rows=rows,
        warnings=run.warnings,
    )
