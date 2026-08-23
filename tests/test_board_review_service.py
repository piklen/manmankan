"""每日板块趋势复看服务与持久化契约测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kan.domain.board import (
    BoardDailyChange,
    BoardKind,
    BoardTrendCoverage,
    BoardTrendQuery,
    BoardTrendRow,
    BoardTrendSnapshot,
)
from kan.domain.board_review import (
    BoardDailyReviewRequest,
    BoardReviewChangeType,
)
from kan.service import board_review_service
from kan.service.board_service import BoardTrendServiceError
from kan.storage import board_review_store, paths, workspace_db


@pytest.fixture
def isolated_review_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    return tmp_path / paths.WORKSPACE_DB_NAME


def _row(
    kind: BoardKind,
    code: str,
    name: str,
    streak: int,
    rank: int,
) -> BoardTrendRow:
    return BoardTrendRow(
        rank=rank,
        kind=kind,
        code=code,
        name=name,
        current_price=100.0,
        streak=streak,
        streak_pct=float(streak),
        direction=f"{streak}",
        latest_change_pct=1.0 if streak > 0 else -1.0,
        daily_changes=[BoardDailyChange(date="2026-08-21", change_pct=1.0)],
    )


def _snapshot(
    kind: BoardKind,
    rows: list[BoardTrendRow],
    *,
    partial: bool = False,
    cutoff: str = "2026-08-21",
) -> BoardTrendSnapshot:
    return BoardTrendSnapshot(
        query=BoardTrendQuery(kind=kind, limit=None),
        source="sw" if kind is BoardKind.INDUSTRY else "tushare",
        data_cutoff=cutoff,
        partial=partial,
        coverage=BoardTrendCoverage(
            total=len(rows),
            evaluated=len(rows),
            matched=len(rows),
            returned=len(rows),
            errors=0,
        ),
        rows=rows,
    )


def test_first_review_builds_baseline_and_identical_result_is_idempotent(
    isolated_review_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = {
        BoardKind.INDUSTRY: _snapshot(
            BoardKind.INDUSTRY,
            [_row(BoardKind.INDUSTRY, "801080", "电子", 3, 1)],
        ),
        BoardKind.THEME: _snapshot(
            BoardKind.THEME,
            [_row(BoardKind.THEME, "885781", "石墨电极", -2, 1)],
        ),
    }
    monkeypatch.setattr(
        board_review_service,
        "query_board_trends",
        lambda query: snapshots[query.kind],
    )

    first = board_review_service.create_board_review(BoardDailyReviewRequest())
    repeated = board_review_service.create_board_review(
        BoardDailyReviewRequest(force=True)
    )

    assert first.previous_review_id is None
    assert first.changes == []
    assert first.sections[0].snapshot is not None
    assert first.sections[0].snapshot.rows[0].daily_changes == []
    assert repeated.review_id == first.review_id
    assert board_review_service.get_board_review(first.review_id) == first
    summaries = board_review_service.list_board_reviews()
    assert [item.review_id for item in summaries] == [first.review_id]
    assert summaries[0].sections[0].evaluated == 1

    with sqlite3.connect(isolated_review_store) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        namespaces = {
            row[0] for row in conn.execute("SELECT namespace FROM workspace_state")
        }
    assert version == workspace_db.SCHEMA_VERSION == 3
    assert "board_reviews.v1:index" in namespaces
    assert f"board_reviews.v1:detail:{first.review_id}" in namespaces


def test_review_classifies_five_objective_change_types(
    isolated_review_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = {
        BoardKind.INDUSTRY: _snapshot(
            BoardKind.INDUSTRY,
            [
                _row(BoardKind.INDUSTRY, "A", "延长", 2, 1),
                _row(BoardKind.INDUSTRY, "B", "切换", -3, 2),
                _row(BoardKind.INDUSTRY, "C", "缩短", 4, 3),
                _row(BoardKind.INDUSTRY, "D", "缺数", 1, 4),
            ],
        ),
        BoardKind.THEME: _snapshot(
            BoardKind.THEME,
            [_row(BoardKind.THEME, "T", "不变", 2, 1)],
        ),
    }
    monkeypatch.setattr(
        board_review_service,
        "query_board_trends",
        lambda query: snapshots[query.kind],
    )
    first = board_review_service.create_board_review(BoardDailyReviewRequest())

    snapshots[BoardKind.INDUSTRY] = _snapshot(
        BoardKind.INDUSTRY,
        [
            _row(BoardKind.INDUSTRY, "A", "延长", 3, 1),
            _row(BoardKind.INDUSTRY, "B", "切换", 1, 2),
            _row(BoardKind.INDUSTRY, "C", "缩短", 2, 3),
            _row(BoardKind.INDUSTRY, "E", "新增数据", -1, 4),
        ],
        cutoff="2026-08-22",
    )
    snapshots[BoardKind.THEME] = _snapshot(
        BoardKind.THEME,
        [_row(BoardKind.THEME, "T", "不变", 2, 1)],
        cutoff="2026-08-22",
    )

    current = board_review_service.create_board_review(BoardDailyReviewRequest())

    assert current.previous_review_id == first.review_id
    assert {item.change_type for item in current.changes} == set(BoardReviewChangeType)
    assert current.change_counts.model_dump() == {
        "data_appeared": 1,
        "data_unavailable": 1,
        "direction_changed": 1,
        "streak_extended": 1,
        "streak_shortened": 1,
    }
    changed = {item.code: item for item in current.changes}
    assert changed["A"].change_type is BoardReviewChangeType.STREAK_EXTENDED
    assert changed["B"].change_type is BoardReviewChangeType.DIRECTION_CHANGED
    assert changed["C"].change_type is BoardReviewChangeType.STREAK_SHORTENED
    assert changed["D"].current_streak is None
    assert changed["E"].previous_streak is None


def test_single_source_failure_is_partial_and_does_not_fabricate_changes(
    isolated_review_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    industry = _snapshot(
        BoardKind.INDUSTRY,
        [_row(BoardKind.INDUSTRY, "801080", "电子", 3, 1)],
    )

    def one_source(query: BoardTrendQuery) -> BoardTrendSnapshot:
        if query.kind is BoardKind.THEME:
            raise BoardTrendServiceError("data_unavailable", "题材源暂不可用")
        return industry

    monkeypatch.setattr(board_review_service, "query_board_trends", one_source)

    review = board_review_service.create_board_review(BoardDailyReviewRequest())

    assert review.partial is True
    assert review.changes == []
    theme = next(item for item in review.sections if item.kind is BoardKind.THEME)
    assert theme.snapshot is None
    assert theme.error_code == "data_unavailable"
    assert review.warnings == ["题材趋势不可用: 题材源暂不可用"]

    def same_failure_with_different_detail(query: BoardTrendQuery) -> BoardTrendSnapshot:
        if query.kind is BoardKind.THEME:
            raise BoardTrendServiceError("data_unavailable", "题材网络仍不可用")
        return industry

    monkeypatch.setattr(
        board_review_service,
        "query_board_trends",
        same_failure_with_different_detail,
    )
    repeated = board_review_service.create_board_review(BoardDailyReviewRequest())
    assert repeated.review_id == review.review_id


def test_theme_provider_code_switch_uses_normalized_name_identity(
    isolated_review_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = {
        BoardKind.INDUSTRY: _snapshot(BoardKind.INDUSTRY, []),
        BoardKind.THEME: _snapshot(
            BoardKind.THEME,
            [_row(BoardKind.THEME, "885781", "石墨 电极", 2, 1)],
        ),
    }
    monkeypatch.setattr(
        board_review_service,
        "query_board_trends",
        lambda query: snapshots[query.kind],
    )
    board_review_service.create_board_review(BoardDailyReviewRequest())
    snapshots[BoardKind.THEME] = _snapshot(
        BoardKind.THEME,
        [_row(BoardKind.THEME, "307512", "石墨电极", 3, 1)],
        cutoff="2026-08-22",
    )

    current = board_review_service.create_board_review(BoardDailyReviewRequest())

    assert len(current.changes) == 1
    assert current.changes[0].change_type is BoardReviewChangeType.STREAK_EXTENDED
    assert current.changes[0].code == "307512"


def test_both_sources_failure_is_not_persisted(
    isolated_review_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        board_review_service,
        "query_board_trends",
        lambda _query: (_ for _ in ()).throw(
            BoardTrendServiceError("data_unavailable", "上游不可用")
        ),
    )

    with pytest.raises(board_review_service.BoardReviewServiceError) as exc_info:
        board_review_service.create_board_review(BoardDailyReviewRequest())

    assert exc_info.value.code == "data_unavailable"
    assert board_review_service.list_board_reviews() == []


def test_missing_review_has_stable_error(
    isolated_review_store: Path,
) -> None:
    with pytest.raises(board_review_service.BoardReviewServiceError) as exc_info:
        board_review_service.get_board_review("missing")

    assert exc_info.value.code == "review_not_found"


def test_review_detail_is_immutable(
    isolated_review_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = {
        BoardKind.INDUSTRY: _snapshot(BoardKind.INDUSTRY, []),
        BoardKind.THEME: _snapshot(BoardKind.THEME, []),
    }
    monkeypatch.setattr(
        board_review_service,
        "query_board_trends",
        lambda query: snapshots[query.kind],
    )
    review = board_review_service.create_board_review(BoardDailyReviewRequest())
    changed = review.model_copy(update={"result_hash": "changed"})

    with pytest.raises(RuntimeError, match="内容不同"):
        board_review_store.save_review(
            changed,
            board_review_service.summarize_board_review(changed),
        )


def test_store_deduplicates_same_result_hash_inside_transaction(
    isolated_review_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = {
        BoardKind.INDUSTRY: _snapshot(BoardKind.INDUSTRY, []),
        BoardKind.THEME: _snapshot(BoardKind.THEME, []),
    }
    monkeypatch.setattr(
        board_review_service,
        "query_board_trends",
        lambda query: snapshots[query.kind],
    )
    review = board_review_service.create_board_review(BoardDailyReviewRequest())
    duplicate = review.model_copy(update={"review_id": "another-id"})

    persisted = board_review_store.save_review(
        duplicate,
        board_review_service.summarize_board_review(duplicate),
    )

    assert persisted.review_id == review.review_id
    assert len(board_review_service.list_board_reviews()) == 1
