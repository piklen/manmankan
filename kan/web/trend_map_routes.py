"""趋势发现薄 HTTP 适配器。"""

from fastapi import APIRouter, HTTPException

from kan.service.trend_map import (
    TrendMapQuery,
    TrendMapSnapshot,
    TrendStockQuery,
    TrendStockSnapshot,
    build_trend_map,
    get_trend_stock,
)

router = APIRouter(prefix="/api/v1/trends", tags=["trends"])


@router.post("/map", response_model=TrendMapSnapshot)
def trend_map(query: TrendMapQuery) -> TrendMapSnapshot:
    try:
        return build_trend_map(query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": str(exc)}) from exc


@router.post("/stock", response_model=TrendStockSnapshot)
def trend_stock(query: TrendStockQuery) -> TrendStockSnapshot:
    try:
        return get_trend_stock(query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "data_unavailable", "message": str(exc)}) from exc
