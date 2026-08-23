"""ManManKan Web API v1。

React、CLI 的远程调试客户端与未来 agent 适配器都只消费这里暴露的稳定领域模型；
旧 ``/api`` 路由在迁移期保留，但不进入 OpenAPI。
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import StreamingResponse

from kan import __version__
from kan.domain.board import (
    BoardKind,
    BoardTrendMode,
    BoardTrendQuery,
    BoardTrendSnapshot,
    BoardTrendSort,
)
from kan.domain.job import MarketRefreshRequest, WorkspaceJob
from kan.domain.screen import (
    Candidate,
    CandidateList,
    CompareSet,
    SavedScreen,
    ScreenRun,
    ScreenVersion,
)
from kan.service import board_service, job_service, screen_service
from kan.service.hold_service import build_hold_summary
from kan.service.info_service import InfoDataUnavailableError, InfoRequest, get_stock_info
from kan.service.market_service import get_market_sentiment, serialize_market_sentiment
from kan.service.screen_ai import ScreenRunInput
from kan.service.screen_catalog import screen_filter_groups
from kan.storage import positions, watchlist, workspace_db
from kan.web.api_models import (
    ApiMeta,
    CandidateListCreateRequest,
    CandidateListRenameRequest,
    CandidateUpsertRequest,
    CashUpdateRequest,
    CompareSetUpsertRequest,
    DeleteResponse,
    HealthResponse,
    MarketOverviewResponse,
    MarketSentimentResponse,
    PortfolioResponse,
    PositionCreateRequest,
    ScreenRunRequest,
    ScreenUpsertRequest,
    SettingsFactsResponse,
    StockResearchResponse,
)
from kan.web.serialize import empty_hold_payload, serialize_hold, serialize_info

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _service_error(exc: screen_service.ScreenServiceError) -> NoReturn:
    status = 404 if exc.code.endswith("not_found") else 400
    raise HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": exc.message, "hint": exc.hint},
    ) from exc


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
            "screens",
            "board-trends",
            "immutable-runs",
            "candidate-lists",
            "compare-sets",
            "typed-openapi",
        ],
    )


@router.get("/filters", response_model=list[dict[str, object]])
def filters() -> list[dict[str, object]]:
    return screen_filter_groups()


@router.get("/boards/trends", response_model=BoardTrendSnapshot)
def board_trends(
    kind: Annotated[BoardKind, Query()] = BoardKind.INDUSTRY,
    mode: Annotated[BoardTrendMode, Query()] = BoardTrendMode.CLOSE,
    up: Annotated[int | None, Query(ge=1, le=30)] = None,
    down: Annotated[int | None, Query(ge=1, le=30)] = None,
    min_streak: Annotated[int | None, Query(ge=1, le=30)] = None,
    sort: Annotated[BoardTrendSort, Query()] = BoardTrendSort.STREAK,
    level: Annotated[int, Query(ge=1, le=3)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 30,
    force: Annotated[bool, Query()] = False,
) -> BoardTrendSnapshot:
    """返回行业 / 题材指数的连续趋势快照。"""

    try:
        query = BoardTrendQuery(
            kind=kind,
            mode=mode,
            up=up,
            down=down,
            min_streak=min_streak,
            sort=sort,
            level=level,
            limit=limit,
            force=force,
        )
        return board_service.query_board_trends(query)
    except board_service.BoardTrendServiceError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": exc.message, "hint": exc.hint},
        ) from exc
    except ValueError as exc:
        _value_error(exc)


@router.get("/stocks/{symbol}", response_model=StockResearchResponse)
def stock_research(symbol: str) -> StockResearchResponse:
    try:
        result = get_stock_info(
            InfoRequest(
                symbol_or_name=symbol,
                allow_fetch=False,
                include_external_context=False,
                include_valuation_context=False,
                include_board_context=True,
            )
        )
    except (ValueError, InfoDataUnavailableError):
        return StockResearchResponse(
            available=False,
            message="本地暂无该股票行情；ScreenRun 证据仍可独立查看",
        )
    return StockResearchResponse(available=True, data=serialize_info(result))


@router.get("/stocks/{symbol}/history", response_model=dict[str, object])
def stock_history(symbol: str, period: Annotated[int, Query(ge=2, le=360)] = 60) -> dict:
    from kan.web.routes_api import history

    return history(symbol, period)


@router.get("/market", response_model=MarketOverviewResponse)
def market_overview() -> MarketOverviewResponse:
    from kan.web.routes_api import default_scan_payload

    message: str | None = None
    try:
        scan = default_scan_payload()
    except Exception:
        scan = None
        message = "默认股票池暂不可用；全市场截面状态仍可独立查看"
    sentiment = MarketSentimentResponse.model_validate(
        serialize_market_sentiment(get_market_sentiment())
    )
    return MarketOverviewResponse(scan=scan, sentiment=sentiment, message=message)


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
    from kan.web.routes_api import _token_status, settings_facts

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


@router.get("/screens", response_model=list[SavedScreen])
def screens() -> list[SavedScreen]:
    return screen_service.list_screens()


@router.post("/screens", response_model=SavedScreen, status_code=201)
def upsert_screen(payload: ScreenUpsertRequest) -> SavedScreen:
    return screen_service.save_screen(payload.spec, screen_id=payload.screen_id)


@router.get("/screens/{screen_id}", response_model=SavedScreen)
def screen(screen_id: str) -> SavedScreen:
    item = workspace_db.get_screen(screen_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "screen_not_found",
                "message": f"Screen 不存在: {screen_id}",
                "hint": None,
            },
        )
    return item


@router.get("/screens/{screen_id}/versions", response_model=list[ScreenVersion])
def screen_versions(screen_id: str) -> list[ScreenVersion]:
    if workspace_db.get_screen(screen_id) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "screen_not_found",
                "message": f"Screen 不存在: {screen_id}",
                "hint": None,
            },
        )
    return workspace_db.list_screen_versions(screen_id)


@router.post(
    "/screens/{screen_id}/versions/{version}/restore",
    response_model=SavedScreen,
)
def restore_screen_version(screen_id: str, version: int) -> SavedScreen:
    historical = workspace_db.get_screen_version(screen_id, version)
    if historical is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "screen_version_not_found",
                "message": f"Screen {screen_id} 不存在 v{version}",
                "hint": None,
            },
        )
    return screen_service.save_screen(historical.spec, screen_id=screen_id)


@router.delete("/screens/{screen_id}", response_model=DeleteResponse)
def delete_screen(screen_id: str) -> DeleteResponse:
    return DeleteResponse(deleted=workspace_db.delete_screen(screen_id))


@router.post("/screens/{screen_id}/runs", response_model=ScreenRun, status_code=201)
def run_saved_screen(screen_id: str) -> ScreenRun:
    try:
        return screen_service.run_saved_screen(screen_id)
    except screen_service.ScreenServiceError as exc:
        _service_error(exc)


@router.post("/runs", response_model=ScreenRun, status_code=201)
def run_screen(payload: ScreenRunRequest) -> ScreenRun:
    try:
        return screen_service.run_screen(payload.spec, persist=payload.persist)
    except screen_service.ScreenServiceError as exc:
        _service_error(exc)


@router.get("/runs", response_model=list[ScreenRun])
def runs(
    screen_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ScreenRun]:
    return workspace_db.list_runs(screen_id=screen_id, limit=limit)


@router.get("/runs/{run_id}", response_model=ScreenRun)
def run(run_id: str) -> ScreenRun:
    item = workspace_db.get_run(run_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "run_not_found",
                "message": f"ScreenRun 不存在: {run_id}",
                "hint": None,
            },
        )
    return item


@router.get("/candidate-lists", response_model=list[CandidateList])
def candidate_lists() -> list[CandidateList]:
    return workspace_db.list_candidate_lists()


@router.post("/candidate-lists", response_model=CandidateList, status_code=201)
def create_candidate_list(payload: CandidateListCreateRequest) -> CandidateList:
    try:
        return workspace_db.create_candidate_list(payload.name)
    except ValueError as exc:
        _value_error(exc)


@router.patch("/candidate-lists/{list_id}", response_model=CandidateList)
def rename_candidate_list(
    list_id: str,
    payload: CandidateListRenameRequest,
) -> CandidateList:
    try:
        return workspace_db.rename_candidate_list(list_id, payload.name)
    except ValueError as exc:
        _value_error(exc)


@router.delete("/candidate-lists/{list_id}", response_model=DeleteResponse)
def delete_candidate_list(list_id: str) -> DeleteResponse:
    try:
        return DeleteResponse(deleted=workspace_db.delete_candidate_list(list_id))
    except ValueError as exc:
        _value_error(exc)


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


@router.get("/compare-sets", response_model=list[CompareSet])
def compare_sets() -> list[CompareSet]:
    return workspace_db.list_compare_sets()


@router.post("/compare-sets", response_model=CompareSet, status_code=201)
def upsert_compare_set(payload: CompareSetUpsertRequest) -> CompareSet:
    try:
        symbols = [watchlist._normalize_symbol(item) for item in payload.symbols]
        if len(set(symbols)) != len(symbols):
            raise ValueError("对比组合不能包含重复股票")
        return workspace_db.save_compare_set(
            payload.name,
            symbols,
            compare_id=payload.compare_id,
        )
    except ValueError as exc:
        _value_error(exc)


@router.delete("/compare-sets/{compare_id}", response_model=DeleteResponse)
def delete_compare_set(compare_id: str) -> DeleteResponse:
    return DeleteResponse(deleted=workspace_db.delete_compare_set(compare_id))


@router.post("/jobs/screen-runs", response_model=WorkspaceJob, status_code=202)
def start_screen_run_job(payload: ScreenRunInput) -> WorkspaceJob:
    return job_service.start_screen_run_job(payload)


@router.post("/jobs/market-refresh", response_model=WorkspaceJob, status_code=202)
def start_market_refresh_job(payload: MarketRefreshRequest) -> WorkspaceJob:
    return job_service.start_market_refresh_job(payload)


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
