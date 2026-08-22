"""ManManKan Web API v1。

React、CLI 的远程调试客户端与未来 agent 适配器都只消费这里暴露的稳定领域模型；
旧 ``/api`` 路由在迁移期保留，但不进入 OpenAPI。
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Body, HTTPException, Query

from kan import __version__
from kan.domain.screen import (
    Candidate,
    CandidateList,
    CompareSet,
    SavedScreen,
    ScreenRun,
)
from kan.service import screen_service
from kan.service.screen_catalog import screen_filter_groups
from kan.storage import watchlist, workspace_db
from kan.web.api_models import (
    ApiMeta,
    CandidateListCreateRequest,
    CandidateUpsertRequest,
    CompareSetUpsertRequest,
    DeleteResponse,
    HealthResponse,
    ScreenRunRequest,
    ScreenUpsertRequest,
)

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
            "immutable-runs",
            "candidate-lists",
            "compare-sets",
            "typed-openapi",
        ],
    )


@router.get("/filters", response_model=list[dict[str, object]])
def filters() -> list[dict[str, object]]:
    return screen_filter_groups()


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
