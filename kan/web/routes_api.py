"""Web JSON API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from kan.core.pipeline import StockSetResolveError
from kan.core.stock_set import from_flags
from kan.service.history_service import HistoryRequest, HistoryServiceError, get_symbol_history
from kan.service.info_service import (
    InfoDataUnavailableError,
    InfoRequest,
    get_stock_info,
)
from kan.service.scan_service import ScanRequest, run_scan
from kan.web.serialize import serialize_history, serialize_info, serialize_scan

router = APIRouter(prefix="/api")


def default_scan_payload() -> dict:
    """默认池 scan · 只读本地缓存。"""
    try:
        result = run_scan(ScanRequest(
            stock_set=from_flags(),
            show_progress=False,
            allow_auto_fetch=False,
            include_external_context=False,
        ))
    except StockSetResolveError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    return serialize_scan(result)


@router.get("/scan")
def scan() -> dict:
    return default_scan_payload()


@router.get("/info/{code}")
def info(code: str) -> dict:
    try:
        result = get_stock_info(InfoRequest(
            symbol_or_name=code,
            allow_fetch=False,
            include_external_context=False,
            include_valuation_context=False,
            include_board_context=False,
        ))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InfoDataUnavailableError as e:
        raise HTTPException(status_code=404, detail="本地缓存没有该股票数据") from e
    return serialize_info(result)


@router.get("/history/{code}")
def history(
    code: str,
    period: int = Query(60, ge=2, le=360),
) -> dict:
    try:
        result = get_symbol_history(HistoryRequest(symbol_or_name=code, period=period))
    except HistoryServiceError as e:
        status = 400 if e.exit_code == 2 else 404
        raise HTTPException(status_code=status, detail=e.message) from e
    return serialize_history(result)
