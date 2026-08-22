"""确定性 AI / MCP ScreenSpec 适配器测试。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from kan.domain.screen import (
    ComparisonOperator,
    DataCoverage,
    ScreenCondition,
    ScreenEvidence,
    ScreenFilterType,
    ScreenRow,
    ScreenRun,
    ScreenSpec,
    UniverseKind,
    UniverseSpec,
)
from kan.service import screen_ai, screen_service
from kan.storage import paths, workspace_db


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))


def test_parse_explicit_thresholds_without_inventing_values() -> None:
    result = screen_ai.parse_screen_text(
        screen_ai.ScreenParseInput(
            text="全市场 pe<30 turnover>=1 排除ST",
            name="截面观察",
        )
    )

    assert result.executable is True
    assert result.confidence is screen_ai.ParseConfidence.EXACT
    assert result.spec is not None
    assert result.spec.universe.kind is UniverseKind.ALL
    assert [(item.type.value, item.value) for item in result.spec.conditions] == [
        ("pe", 30),
        ("turnover", 1),
    ]
    assert result.spec.exclude_st is True


def test_parse_requires_period_for_period_filter() -> None:
    result = screen_ai.parse_screen_text(
        screen_ai.ScreenParseInput(text="自选 pos<20")
    )

    assert result.executable is False
    assert result.spec is None
    assert result.errors


def test_plan_reports_engine_dependencies_and_unsupported_all_filter() -> None:
    spec = ScreenSpec(
        name="全市场测试",
        universe=UniverseSpec(kind=UniverseKind.ALL),
        conditions=[
            ScreenCondition(
                type=ScreenFilterType.ROE,
                operator=ComparisonOperator.GT,
                value=10,
            )
        ],
    )

    plan = screen_ai.plan_screen(spec)

    assert plan.engine_path == "cross_section"
    assert plan.required_dimensions == ["fundamentals"]
    assert plan.unsupported_filters == ["roe"]
    assert plan.executable is False


def test_get_and_explain_use_persisted_run(
    isolated_workspace: None,
) -> None:
    spec = ScreenSpec(
        name="解释测试",
        conditions=[
            ScreenCondition(
                type=ScreenFilterType.PE,
                operator=ComparisonOperator.LT,
                value=30,
            )
        ],
    )
    run = ScreenRun(
        run_id="explain-run",
        spec=spec,
        spec_hash=screen_service.content_hash(spec),
        snapshot_id="snapshot",
        result_hash="result",
        created_at=datetime.now(UTC),
        duration_ms=9,
        coverage=DataCoverage(
            universe_size=1,
            evaluated=1,
            matched=1,
            returned=1,
            ratio=1,
            data_cutoff=date(2026, 8, 21),
        ),
        rows=[
            ScreenRow(
                symbol="600519",
                name="贵州茅台",
                rank=1,
                values={"pe": 20},
                evidence=[
                    ScreenEvidence(
                        evidence_ref="run:explain-run:row:600519:condition:0",
                        filter_type=ScreenFilterType.PE,
                        field_id="pe",
                        operator=ComparisonOperator.LT,
                        threshold=30,
                        actual=20,
                        unit="倍",
                        data_date=date(2026, 8, 21),
                    )
                ],
            )
        ],
    )
    workspace_db.save_run(run)

    artifact = screen_ai.get_artifact(
        screen_ai.ScreenGetInput(run_id=run.run_id)
    )
    explanation = screen_ai.explain_run(run.run_id)

    assert artifact.kind == "run"
    assert artifact.run == run
    assert explanation.rows[0].facts == [
        "市盈率 PE TTM 低于 30倍，实际 20倍，数据日 2026-08-21"
    ]
    assert explanation.changes == "首次运行，记录 1 只符合条件股票"
