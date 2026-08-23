"""每日板块复看在既有 workspace_state 上的事务存储。"""

from __future__ import annotations

from kan.domain.board import BoardTrendMode
from kan.domain.board_review import BoardDailyReview, BoardDailyReviewSummary
from kan.storage import workspace_db

_INDEX_NAMESPACE = "board_reviews.v1:index"
_DETAIL_PREFIX = "board_reviews.v1:detail:"


def _detail_namespace(review_id: str) -> str:
    return f"{_DETAIL_PREFIX}{review_id}"


def save_review(
    review: BoardDailyReview,
    summary: BoardDailyReviewSummary,
) -> BoardDailyReview:
    """在一个事务内写不可变 detail 与可枚举 summary index。"""

    with workspace_db.transaction() as conn:
        existing_detail = workspace_db.get_state(
            _detail_namespace(review.review_id),
            conn=conn,
        )
        if existing_detail is not None:
            if BoardDailyReview.model_validate(existing_detail) != review:
                raise RuntimeError(f"每日复看 {review.review_id} 已存在且内容不同")
            return review
        current = workspace_db.get_state(_INDEX_NAMESPACE, conn=conn) or {"items": []}
        raw_items = current.get("items", [])
        if not isinstance(raw_items, list):
            raise RuntimeError("每日复看索引不是 JSON array")
        items = [
            BoardDailyReviewSummary.model_validate(item)
            for item in raw_items
        ]
        duplicate = next(
            (
                item
                for item in items
                if item.mode is summary.mode
                and item.industry_level == summary.industry_level
                and item.result_hash == summary.result_hash
            ),
            None,
        )
        if duplicate is not None:
            existing = workspace_db.get_state(
                _detail_namespace(duplicate.review_id),
                conn=conn,
            )
            if existing is None:
                raise RuntimeError(f"每日复看索引缺少 detail: {duplicate.review_id}")
            return BoardDailyReview.model_validate(existing)
        items = [item for item in items if item.review_id != review.review_id]
        items.insert(0, summary)
        workspace_db.put_state(
            _detail_namespace(review.review_id),
            review.model_dump(mode="json"),
            source_hash=review.result_hash,
            conn=conn,
        )
        workspace_db.put_state(
            _INDEX_NAMESPACE,
            {"items": [item.model_dump(mode="json") for item in items]},
            conn=conn,
        )
        return review


def get_review(review_id: str) -> BoardDailyReview | None:
    payload = workspace_db.get_state(_detail_namespace(review_id))
    return None if payload is None else BoardDailyReview.model_validate(payload)


def list_review_summaries(*, limit: int = 30) -> list[BoardDailyReviewSummary]:
    payload = workspace_db.get_state(_INDEX_NAMESPACE) or {"items": []}
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        raise RuntimeError("每日复看索引不是 JSON array")
    return [
        BoardDailyReviewSummary.model_validate(item)
        for item in raw_items[:limit]
    ]


def latest_review(
    *,
    mode: BoardTrendMode,
    industry_level: int,
) -> BoardDailyReview | None:
    for summary in list_review_summaries(limit=10_000):
        if summary.mode is mode and summary.industry_level == industry_level:
            return get_review(summary.review_id)
    return None


__all__ = [
    "get_review",
    "latest_review",
    "list_review_summaries",
    "save_review",
]
