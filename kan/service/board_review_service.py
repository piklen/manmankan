"""每日板块趋势复看的入口无关 application service。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic_core import to_jsonable_python

from kan.domain.board import BoardKind, BoardTrendQuery, BoardTrendRow
from kan.domain.board_review import (
    BoardDailyReview,
    BoardDailyReviewRequest,
    BoardDailyReviewSummary,
    BoardReviewChange,
    BoardReviewChangeCounts,
    BoardReviewChangeType,
    BoardReviewSection,
    BoardReviewSectionSummary,
)
from kan.service.board_service import BoardServiceError, query_board_trends
from kan.storage import board_review_store


class BoardReviewServiceError(RuntimeError):
    """每日复看稳定失败，由 HTTP/Python 调用方统一处理。"""

    def __init__(self, code: str, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _review_section(
    kind: BoardKind,
    request: BoardDailyReviewRequest,
) -> BoardReviewSection:
    level = request.industry_level if kind is BoardKind.INDUSTRY else 1
    try:
        snapshot = query_board_trends(
            BoardTrendQuery(
                kind=kind,
                mode=request.mode,
                level=level,
                limit=None,
                force=request.force,
            )
        )
    except BoardServiceError as exc:
        return BoardReviewSection(
            kind=kind,
            error_code=exc.code,
            error_message=exc.message,
            error_hint=exc.hint,
        )
    # 每日复看只比较当前行事实，不重复保存趋势页绘图所需的日序列。
    lean_rows = [row.model_copy(update={"daily_changes": []}) for row in snapshot.rows]
    return BoardReviewSection(
        kind=kind,
        snapshot=snapshot.model_copy(update={"rows": lean_rows}),
    )


def _result_hash(
    request: BoardDailyReviewRequest,
    sections: list[BoardReviewSection],
) -> str:
    normalized_sections: list[dict[str, object]] = []
    for section in sections:
        payload = section.model_dump(mode="json")
        snapshot = payload.get("snapshot")
        if isinstance(snapshot, dict):
            query = snapshot.get("query")
            if isinstance(query, dict):
                query["force"] = False
        else:
            payload["error_message"] = None
            payload["error_hint"] = None
        normalized_sections.append(payload)
    payload = to_jsonable_python(
        {
            "mode": request.mode,
            "industry_level": request.industry_level,
            "sections": normalized_sections,
        }
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _change_type(previous: int, current: int) -> BoardReviewChangeType | None:
    previous_direction = (previous > 0) - (previous < 0)
    current_direction = (current > 0) - (current < 0)
    if previous_direction != current_direction:
        return BoardReviewChangeType.DIRECTION_CHANGED
    if abs(current) > abs(previous):
        return BoardReviewChangeType.STREAK_EXTENDED
    if abs(current) < abs(previous):
        return BoardReviewChangeType.STREAK_SHORTENED
    return None


def _row_identity(kind: BoardKind, row: BoardTrendRow) -> str:
    if kind is BoardKind.THEME:
        from kan.data.boards import normalize_theme_name

        return normalize_theme_name(row.name)
    return row.code


def _review_changes(
    sections: list[BoardReviewSection],
    previous: BoardDailyReview | None,
) -> list[BoardReviewChange]:
    if previous is None:
        return []
    previous_by_kind = {section.kind: section for section in previous.sections}
    changes: list[BoardReviewChange] = []
    for section in sections:
        previous_section = previous_by_kind.get(section.kind)
        if (
            section.snapshot is None
            or previous_section is None
            or previous_section.snapshot is None
        ):
            continue
        current_rows = {
            _row_identity(section.kind, row): row for row in section.snapshot.rows
        }
        previous_rows = {
            _row_identity(section.kind, row): row
            for row in previous_section.snapshot.rows
        }
        for identity in sorted(current_rows.keys() | previous_rows.keys()):
            current = current_rows.get(identity)
            old = previous_rows.get(identity)
            if old is None and current is not None:
                changes.append(
                    BoardReviewChange(
                        kind=section.kind,
                        code=current.code,
                        name=current.name,
                        change_type=BoardReviewChangeType.DATA_APPEARED,
                        current_streak=current.streak,
                        current_rank=current.rank,
                    )
                )
                continue
            if current is None and old is not None:
                changes.append(
                    BoardReviewChange(
                        kind=section.kind,
                        code=old.code,
                        name=old.name,
                        change_type=BoardReviewChangeType.DATA_UNAVAILABLE,
                        previous_streak=old.streak,
                        previous_rank=old.rank,
                    )
                )
                continue
            assert current is not None and old is not None
            change_type = _change_type(old.streak, current.streak)
            if change_type is None:
                continue
            changes.append(
                BoardReviewChange(
                    kind=section.kind,
                    code=current.code,
                    name=current.name,
                    change_type=change_type,
                    previous_streak=old.streak,
                    current_streak=current.streak,
                    previous_rank=old.rank,
                    current_rank=current.rank,
                )
            )

    priority = {
        BoardReviewChangeType.DIRECTION_CHANGED: 0,
        BoardReviewChangeType.STREAK_EXTENDED: 1,
        BoardReviewChangeType.STREAK_SHORTENED: 2,
        BoardReviewChangeType.DATA_APPEARED: 3,
        BoardReviewChangeType.DATA_UNAVAILABLE: 4,
    }
    return sorted(
        changes,
        key=lambda item: (
            priority[item.change_type],
            -(abs(item.current_streak or item.previous_streak or 0)),
            item.kind.value,
            item.code,
        ),
    )


def _change_counts(changes: list[BoardReviewChange]) -> BoardReviewChangeCounts:
    counts = {item.value: 0 for item in BoardReviewChangeType}
    for change in changes:
        counts[change.change_type.value] += 1
    return BoardReviewChangeCounts.model_validate(counts)


def summarize_board_review(review: BoardDailyReview) -> BoardDailyReviewSummary:
    sections: list[BoardReviewSectionSummary] = []
    for section in review.sections:
        snapshot = section.snapshot
        sections.append(
            BoardReviewSectionSummary(
                kind=section.kind,
                source=snapshot.source if snapshot is not None else None,
                data_cutoff=snapshot.data_cutoff if snapshot is not None else None,
                partial=snapshot.partial if snapshot is not None else True,
                total=snapshot.coverage.total if snapshot is not None else 0,
                evaluated=snapshot.coverage.evaluated if snapshot is not None else 0,
                error_code=section.error_code,
                error_message=section.error_message,
            )
        )
    return BoardDailyReviewSummary(
        review_id=review.review_id,
        created_at=review.created_at,
        mode=review.mode,
        industry_level=review.industry_level,
        result_hash=review.result_hash,
        previous_review_id=review.previous_review_id,
        partial=review.partial,
        sections=sections,
        change_counts=review.change_counts,
    )


def create_board_review(request: BoardDailyReviewRequest) -> BoardDailyReview:
    """读取行业/题材趋势、比较同口径上一份记录并幂等保存。"""

    sections = [
        _review_section(BoardKind.INDUSTRY, request),
        _review_section(BoardKind.THEME, request),
    ]
    if all(section.snapshot is None for section in sections):
        details = "；".join(
            section.error_message or section.error_code or section.kind.value
            for section in sections
        )
        raise BoardReviewServiceError(
            "data_unavailable",
            f"行业和题材趋势都不可用: {details}",
            hint="检查网络、数据源配置或本地缓存后重试",
        )

    result_hash = _result_hash(request, sections)
    previous = board_review_store.latest_review(
        mode=request.mode,
        industry_level=request.industry_level,
    )
    if previous is not None and previous.result_hash == result_hash:
        return previous

    changes = _review_changes(sections, previous)
    warnings: list[str] = []
    for section in sections:
        label = "行业" if section.kind is BoardKind.INDUSTRY else "题材"
        if section.snapshot is None:
            warnings.append(f"{label}趋势不可用: {section.error_message}")
        else:
            warnings.extend(
                f"{label}: {warning}"
                for warning in section.snapshot.warnings
            )
    review = BoardDailyReview(
        review_id=uuid4().hex,
        created_at=datetime.now(UTC),
        mode=request.mode,
        industry_level=request.industry_level,
        result_hash=result_hash,
        previous_review_id=previous.review_id if previous is not None else None,
        partial=any(
            section.snapshot is None or section.snapshot.partial
            for section in sections
        ),
        sections=sections,
        changes=changes,
        change_counts=_change_counts(changes),
        warnings=warnings,
    )
    return board_review_store.save_review(review, summarize_board_review(review))


def get_board_review(review_id: str) -> BoardDailyReview:
    review = board_review_store.get_review(review_id)
    if review is None:
        raise BoardReviewServiceError(
            "review_not_found",
            f"每日复看记录不存在: {review_id}",
        )
    return review


def list_board_reviews(*, limit: int = 30) -> list[BoardDailyReviewSummary]:
    return board_review_store.list_review_summaries(limit=limit)


__all__ = [
    "BoardReviewServiceError",
    "create_board_review",
    "get_board_review",
    "list_board_reviews",
    "summarize_board_review",
]
