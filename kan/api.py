"""Python 查询入口：股票池、事实扫描、趋势条件与历史研究共用确定性服务。

示例：
    >>> from kan.api import TrendSearchQuery, search_trends
    >>> query = TrendSearchQuery(universe="codes", codes=["600519"])
    >>> result = search_trends(query)
"""
from __future__ import annotations

# Re-export · 集合抽象 + 4 实现 + factory
from kan.core.stock_set import (
    HoldingsSet,
    HotRankSet,
    IndustrySet,
    StockSet,
    ThemeSet,
    WatchlistHoldingsSet,
    WatchlistSet,
    from_flags,
)

# Re-export · 5 个 verb
from kan.core.verbs import (
    fetch,
    high,
    low,
    scan,
    trend,
)

# 背景 · 数据源扩展 API (KlineSource + ThemeConstituentSource Protocol + register/inspect)
from kan.data._builtin_sources import (
    clear_user_kline_sources,
    register_kline_source,
)
from kan.data.protocols import KlineSource
from kan.data.source_chain import default_kline_chain as kline_chain
from kan.data.theme_constituents import (
    ThemeConstituentSource,
    clear_user_theme_constituent_sources,
    register_theme_constituent_source,
)
from kan.data.theme_constituents import (
    default_theme_constituent_chain as theme_constituent_chain,
)
from kan.domain.board import (
    BoardDailyChange,
    BoardKind,
    BoardPulseCoverage,
    BoardPulseMember,
    BoardPulseQuery,
    BoardPulseSnapshot,
    BoardTrendCoverage,
    BoardTrendFailure,
    BoardTrendMode,
    BoardTrendQuery,
    BoardTrendRow,
    BoardTrendSnapshot,
    BoardTrendSort,
)
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
from kan.domain.discovery import DiscoveryQuery, DiscoveryResult
from kan.domain.focus import FocusRow, FocusSnapshot
from kan.domain.market_study import StudyCondition, StudyQuery, StudyResult
from kan.domain.observation import (
    ObservationRecord,
    ObservationReviewResult,
    ObservationSaveRequest,
)
from kan.domain.research import ResearchBundle, ResearchRequest
from kan.domain.workspace import CandidateList
from kan.service.board_history_service import (
    BoardHistoryServiceError,
    study_board_history,
)
from kan.service.board_review_service import (
    BoardReviewServiceError,
    create_board_review,
    get_board_review,
    list_board_reviews,
)
from kan.service.board_service import (
    BoardPulseServiceError,
    BoardServiceError,
    BoardTrendServiceError,
    query_board_pulse,
    query_board_trends,
)
from kan.service.discovery import discover_market
from kan.service.focus_service import (
    add_focus,
    build_focus_snapshot,
    update_focus_note,
)
from kan.service.market_study import (
    get_study,
    list_studies,
    rerun_study,
    run_study,
    study_events,
    study_evidence,
)
from kan.service.observation import (
    get_observation,
    list_observations,
    review_observation,
    save_observation,
)
from kan.service.research_service import build_research_bundle
from kan.service.trend_search import (
    SavedTrendSearch,
    TrendSearchEvidence,
    TrendSearchQuery,
    TrendSearchResult,
    delete_saved_trend,
    list_saved_trends,
    save_trend_search,
    search_trends,
    trend_search_evidence,
)
from kan.storage.workspace_db import list_candidate_lists

__all__ = [
    "BoardDailyChange",
    "BoardDailyReview",
    "BoardDailyReviewRequest",
    "BoardDailyReviewSummary",
    "BoardHistoryCoverage",
    "BoardHistoryEvent",
    "BoardHistoryServiceError",
    "BoardHistoryStudy",
    "BoardHistoryStudyQuery",
    "BoardKind",
    "BoardPulseCoverage",
    "BoardPulseMember",
    "BoardPulseQuery",
    "BoardPulseServiceError",
    "BoardPulseSnapshot",
    "BoardReviewChange",
    "BoardReviewChangeCounts",
    "BoardReviewChangeType",
    "BoardReviewSection",
    "BoardReviewSectionSummary",
    "BoardReviewServiceError",
    "BoardServiceError",
    "BoardStudyDirection",
    "BoardStudySamplePolicy",
    "BoardTrendCoverage",
    "BoardTrendFailure",
    "BoardTrendMode",
    "BoardTrendQuery",
    "BoardTrendRow",
    "BoardTrendServiceError",
    "BoardTrendSnapshot",
    "BoardTrendSort",
    "CandidateList",
    "DiscoveryQuery",
    "DiscoveryResult",
    "FocusRow",
    "FocusSnapshot",
    "HoldingsSet",
    "HotRankSet",
    "IndustrySet",
    "KlineSource",
    "ObservationRecord",
    "ObservationReviewResult",
    "ObservationSaveRequest",
    "PointInTimeAudit",
    "ResearchBundle",
    "ResearchRequest",
    "ReturnDistribution",
    "SavedTrendSearch",
    "StockSet",
    "StudyCondition",
    "StudyQuery",
    "StudyResult",
    "ThemeConstituentSource",
    "ThemeSet",
    "TrendSearchEvidence",
    "TrendSearchQuery",
    "TrendSearchResult",
    "WatchlistHoldingsSet",
    "WatchlistSet",
    "add_focus",
    "build_focus_snapshot",
    "build_research_bundle",
    "clear_user_kline_sources",
    "clear_user_theme_constituent_sources",
    "create_board_review",
    "delete_saved_trend",
    "discover_market",
    "fetch",
    "from_flags",
    "get_board_review",
    "get_observation",
    "get_study",
    "high",
    "kline_chain",
    "list_board_reviews",
    "list_candidate_lists",
    "list_observations",
    "list_saved_trends",
    "list_studies",
    "low",
    "query_board_pulse",
    "query_board_trends",
    "register_kline_source",
    "register_theme_constituent_source",
    "rerun_study",
    "review_observation",
    "run_study",
    "save_observation",
    "save_trend_search",
    "scan",
    "search_trends",
    "study_board_history",
    "study_events",
    "study_evidence",
    "theme_constituent_chain",
    "trend",
    "trend_search_evidence",
    "update_focus_note",
]
