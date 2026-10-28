"""趋势地图、研究实验和本机数据管理实际使用的 HTTP 入口。"""
from __future__ import annotations

from datetime import date
from typing import Annotated, NoReturn

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import StreamingResponse

from kan import __version__
from kan.domain.focus import FocusAddRequest, FocusSnapshot
from kan.domain.job import MarketRefreshRequest, MarketRefreshScope, WorkspaceJob
from kan.domain.market_study import (
    StudyEventPage,
    StudyEvidence,
    StudyQuery,
    StudyRefreshRequest,
    StudyResult,
    StudySummary,
)
from kan.domain.screen import Candidate, CandidateList
from kan.service import focus_service, job_service, market_study
from kan.service.hold_service import build_hold_summary
from kan.storage import positions, watchlist, workspace_db
from kan.web.api_models import (
    ApiMeta,
    CandidateUpsertRequest,
    CashUpdateRequest,
    DeleteResponse,
    HealthResponse,
    PortfolioResponse,
    PositionCreateRequest,
    SettingsFactsResponse,
)
from kan.web.serialize import empty_hold_payload, serialize_hold

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _value_error(exc: ValueError) -> NoReturn:
    raise HTTPException(
        status_code=400,
        detail={"code": "invalid_request", "message": str(exc), "hint": None},
    ) from exc


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@router.get("/meta", response_model=ApiMeta)
def meta() -> ApiMeta:
    return ApiMeta(
        product_version=__version__,
        capabilities=[
            "trend-map", "pattern-search", "market-studies", "frozen-evidence",
            "personal-universe", "typed-openapi",
        ],
    )


@router.get("/studies/catalog", response_model=list[dict[str, object]])
def study_catalog() -> list[dict[str, object]]:
    return market_study.FIELD_CATALOG


@router.get("/studies", response_model=list[StudySummary])
def studies() -> list[StudySummary]:
    return market_study.list_studies()


@router.post("/studies/run", response_model=StudyResult, status_code=201)
def run_study(payload: StudyQuery) -> StudyResult:
    try:
        return market_study.run_study(payload)
    except ValueError as exc:
        _value_error(exc)


@router.post("/studies/refresh", response_model=WorkspaceJob, status_code=202)
def refresh_study_data(payload: StudyRefreshRequest) -> WorkspaceJob:
    scopes = {"all": MarketRefreshScope.ALL, "personal": MarketRefreshScope.FOCUS, "codes": MarketRefreshScope.CODES}
    try:
        return job_service.start_market_refresh_job(MarketRefreshRequest(
            scope=scopes[payload.universe], codes=payload.codes, days=payload.days,
        ))
    except ValueError as exc:
        _value_error(exc)


@router.get("/studies/runs/{run_id}/events", response_model=StudyEventPage)
def study_events(run_id: str, offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> StudyEventPage:
    try:
        return market_study.study_events(run_id, offset=offset, limit=limit)
    except ValueError as exc:
        _value_error(exc)


@router.get("/studies/runs/{run_id}/evidence", response_model=StudyEvidence)
def study_evidence(run_id: str, symbol: str, date: date) -> StudyEvidence:
    try:
        return market_study.study_evidence(run_id, symbol, date)
    except ValueError as exc:
        _value_error(exc)


@router.get("/studies/{study_id}", response_model=StudyResult)
def study(study_id: str) -> StudyResult:
    try:
        return market_study.get_study(study_id)
    except ValueError as exc:
        _value_error(exc)


@router.post("/studies/{study_id}/rerun", response_model=StudyResult, status_code=201)
def rerun_study(study_id: str, latest: bool = False) -> StudyResult:
    try:
        return market_study.rerun_study(study_id, latest=latest)
    except ValueError as exc:
        _value_error(exc)


@router.get("/focus", response_model=FocusSnapshot)
def focus() -> FocusSnapshot:
    return focus_service.build_focus_snapshot()


@router.post("/focus", response_model=Candidate, status_code=201)
def add_focus(payload: FocusAddRequest) -> Candidate:
    try:
        return focus_service.add_focus(payload.symbol)
    except ValueError as exc:
        _value_error(exc)


def _portfolio_response() -> PortfolioResponse:
    try:
        payload = serialize_hold(build_hold_summary())
    except Exception:
        payload = empty_hold_payload(error="持仓数据不可用")
    return PortfolioResponse.model_validate(payload)


@router.get("/portfolio", response_model=PortfolioResponse)
def portfolio() -> PortfolioResponse:
    return _portfolio_response()


@router.put("/portfolio/cash", response_model=PortfolioResponse)
def update_portfolio_cash(payload: CashUpdateRequest) -> PortfolioResponse:
    try:
        positions.set_cash(payload.cash)
    except ValueError as exc:
        _value_error(exc)
    return _portfolio_response()


@router.post("/portfolio/positions", response_model=PortfolioResponse)
def create_portfolio_position(payload: PositionCreateRequest) -> PortfolioResponse:
    try:
        positions.add_position(
            payload.code,
            cost=payload.cost,
            shares=payload.shares,
            name=payload.name,
            merge=payload.merge,
        )
    except ValueError as exc:
        _value_error(exc)
    return _portfolio_response()


@router.delete("/portfolio/positions/{symbol}", response_model=PortfolioResponse)
def delete_portfolio_position(symbol: str) -> PortfolioResponse:
    try:
        positions.remove_position(symbol)
    except ValueError as exc:
        _value_error(exc)
    return _portfolio_response()


@router.get("/settings", response_model=SettingsFactsResponse)
def settings() -> SettingsFactsResponse:
    from kan.web.workspace_views import _token_status, settings_facts

    facts = settings_facts()
    token = _token_status()
    return SettingsFactsResponse(
        data_dir=str(facts["data_dir"]),
        workspace_db=str(workspace_db.database_path()),
        kline_cache_files=int(facts["kline_cache_files"]),
        tushare_endpoint_domain=str(facts["tushare_endpoint_domain"]),
        tushare_configured=bool(token["configured"]),
        tushare_masked=str(token["masked"]) if token["masked"] is not None else None,
        state_backend="sqlite" if workspace_db.state_backend_enabled() else "legacy",
    )


@router.get("/candidate-lists", response_model=list[CandidateList])
def candidate_lists() -> list[CandidateList]:
    return workspace_db.list_candidate_lists()


@router.put(
    "/candidate-lists/{list_id}/candidates/{symbol}",
    response_model=Candidate,
)
def upsert_candidate(
    list_id: str,
    symbol: str,
    payload: Annotated[CandidateUpsertRequest, Body()],
) -> Candidate:
    try:
        normalized = watchlist._normalize_symbol(symbol)
        names = watchlist.load_stock_names_cache(allow_stale=True) or {}
        name = payload.name or names.get(normalized, normalized)
        return workspace_db.upsert_candidate(
            list_id=list_id,
            symbol=normalized,
            name=name,
            source_run_id=payload.source_run_id,
            status=payload.status,
            note=payload.note,
        )
    except ValueError as exc:
        _value_error(exc)


@router.delete(
    "/candidate-lists/{list_id}/candidates/{symbol}",
    response_model=DeleteResponse,
)
def delete_candidate(list_id: str, symbol: str) -> DeleteResponse:
    try:
        normalized = watchlist._normalize_symbol(symbol)
    except ValueError as exc:
        _value_error(exc)
    return DeleteResponse(deleted=workspace_db.remove_candidate(list_id, normalized))


@router.get("/jobs", response_model=list[WorkspaceJob])
def jobs(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[WorkspaceJob]:
    return workspace_db.list_jobs(limit=limit)


@router.get("/jobs/{job_id}", response_model=WorkspaceJob)
def job(job_id: str) -> WorkspaceJob:
    item = workspace_db.get_job(job_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "job_not_found",
                "message": f"任务不存在: {job_id}",
                "hint": None,
            },
        )
    return item


@router.get("/jobs/{job_id}/events", response_class=StreamingResponse)
def job_events(job_id: str) -> StreamingResponse:
    if workspace_db.get_job(job_id) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "job_not_found",
                "message": f"任务不存在: {job_id}",
                "hint": None,
            },
        )
    return StreamingResponse(
        job_service.iter_job_events(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
