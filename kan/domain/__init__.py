"""ManManKan 稳定领域契约。"""

from kan.domain.board_history import (
    BoardHistoryCoverage,
    BoardHistoryEvent,
    BoardHistoryStudy,
    BoardHistoryStudyQuery,
    BoardStudyDirection,
    BoardStudySamplePolicy,
    PointInTimeAudit,
    ReturnDistribution,
)
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
from kan.domain.job import (
    JobStatus,
    MarketRefreshRequest,
    MarketRefreshScope,
    WorkspaceJob,
)
from kan.domain.workspace import Candidate, CandidateList, CandidateStatus

__all__ = [
    "BoardDailyReview",
    "BoardDailyReviewRequest",
    "BoardDailyReviewSummary",
    "BoardHistoryCoverage",
    "BoardHistoryEvent",
    "BoardHistoryStudy",
    "BoardHistoryStudyQuery",
    "BoardReviewChange",
    "BoardReviewChangeCounts",
    "BoardReviewChangeType",
    "BoardReviewSection",
    "BoardReviewSectionSummary",
    "BoardStudyDirection",
    "BoardStudySamplePolicy",
    "Candidate",
    "CandidateList",
    "CandidateStatus",
    "JobStatus",
    "MarketRefreshRequest",
    "MarketRefreshScope",
    "PointInTimeAudit",
    "ReturnDistribution",
    "WorkspaceJob",
]
