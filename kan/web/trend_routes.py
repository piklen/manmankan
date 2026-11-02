"""趋势发现薄 HTTP 适配器。"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from kan.service.trend_search import (
    SavedTrendSearch,
    SaveTrendSearchRequest,
    TrendSearchEvidence,
    TrendSearchEvidenceRequest,
    TrendSearchQuery,
    TrendSearchResult,
    delete_saved_trend,
    list_saved_trends,
    save_trend_search,
    search_trends,
    trend_search_evidence,
)
from kan.web.api_models import DeleteResponse

router = APIRouter(prefix="/api/v1/trends", tags=["trends"])


@router.post("/search", response_model=TrendSearchResult)
def trend_search(query: TrendSearchQuery) -> TrendSearchResult:
    try:
        return search_trends(query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": str(exc)}) from exc


@router.get("/search", response_model=TrendSearchResult)
def browse_trends(
    universe: Literal["all", "personal", "codes"] = "all",
    codes: Annotated[list[str] | None, Query()] = None,
    industries: Annotated[list[str] | None, Query()] = None,
    as_of: date | None = None,
) -> TrendSearchResult:
    try:
        return search_trends(TrendSearchQuery(universe=universe, codes=codes or [], industries=industries or [], as_of=as_of))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": str(exc)}) from exc


@router.post("/search/evidence", response_model=TrendSearchEvidence)
def search_evidence(request: TrendSearchEvidenceRequest) -> TrendSearchEvidence:
    try:
        return trend_search_evidence(request.query, request.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "data_unavailable", "message": str(exc)}) from exc


@router.get("/saved", response_model=list[SavedTrendSearch])
def saved_trends() -> list[SavedTrendSearch]:
    return list_saved_trends()


@router.post("/saved", response_model=SavedTrendSearch, status_code=201)
def save_trend(request: SaveTrendSearchRequest) -> SavedTrendSearch:
    return save_trend_search(request.title, request.query)


@router.delete("/saved/{saved_id}", response_model=DeleteResponse)
def delete_trend(saved_id: str) -> DeleteResponse:
    return DeleteResponse(deleted=delete_saved_trend(saved_id))
