"""Web JSON API 路由。"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from kan.core.models import Stock
from kan.core.pipeline import StockSetResolveError
from kan.core.stock_set import from_flags
from kan.service.history_service import HistoryRequest, HistoryServiceError, get_symbol_history
from kan.service.hold_service import build_hold_summary
from kan.service.index_service import IndexRequest, get_index_reference
from kan.service.info_service import (
    InfoDataUnavailableError,
    InfoRequest,
    get_stock_info,
)
from kan.service.scan_service import ScanRequest, run_scan
from kan.storage import config, watchlist
from kan.storage.watchlist_names import _lookup_name
from kan.storage.watchlist_store import watchlist_lock
from kan.web.fetch_jobs import get_fetch_job, iter_sse, start_fetch_job
from kan.web.find_adapter import run_web_find
from kan.web.security import host_allowed
from kan.web.serialize import (
    empty_hold_payload,
    serialize_history,
    serialize_hold,
    serialize_index,
    serialize_info,
    serialize_scan,
)

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


@router.post("/find")
def find(payload: Annotated[dict[str, Any], Body()]) -> dict:
    return run_web_find(payload)


@router.post("/watchlist")
def add_watchlist(payload: Annotated[dict[str, Any], Body()]) -> dict:
    raw = payload.get("codes")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="请填写股票代码")
    tokens = [part for part in raw.replace(",", " ").replace("，", " ").split() if part]
    if not tokens:
        raise HTTPException(status_code=400, detail="请填写股票代码")
    try:
        symbols = [watchlist._normalize_symbol(token) for token in tokens]
        repeated = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
        if repeated:
            raise ValueError(f"重复代码: {', '.join(repeated)}")
        # 锁包住 load→mutate→save 整段:防 web 多 tab / web 与 CLI 并发写丢更新。
        with watchlist_lock():
            gw = watchlist.load_grouped_watchlist()
            target = gw.default
            if target not in gw.groups:
                raise watchlist.GroupNotFoundError(
                    f"组「{target}」不存在 · 跑 `kan group create {target}` 新建"
                )
            existing = {stock.symbol for stock in gw.groups[target]}
            duplicates = [symbol for symbol in symbols if symbol in existing]
            if duplicates:
                raise ValueError(f"代码已在自选列表中: {', '.join(duplicates)}")
            names = {symbol: _lookup_name(symbol) for symbol in symbols}
            for symbol in symbols:
                gw.groups[target].append(Stock(
                    symbol=symbol,
                    name=names[symbol],
                    added_at=date.today(),
                ))
            watchlist.save_grouped_watchlist(gw)
            messages = [f"✅ 已添加 {names[symbol]} ({symbol})" for symbol in symbols]
    except (ValueError, watchlist.GroupNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "messages": messages}


@router.delete("/watchlist/{code}")
def remove_watchlist(code: str) -> dict:
    try:
        removed, msg = watchlist.remove(code)
    except (ValueError, watchlist.GroupNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    status = 200 if removed else 404
    if not removed:
        raise HTTPException(status_code=status, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/fetch")
def fetch() -> dict:
    job = start_fetch_job()
    return {"ok": True, "job": job.id, "status": job.status}


@router.get("/fetch/events")
def fetch_events(request: Request, job: str = Query(..., min_length=1)) -> StreamingResponse:
    if not host_allowed(request.headers.get("host")):
        raise HTTPException(status_code=403, detail="host not allowed")
    fetch_job = get_fetch_job(job)
    if fetch_job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return StreamingResponse(
        iter_sse(fetch_job),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
    # 不在 Query 层夹 ge/le:交给 service 的 MIN_PERIOD/MAX_PERIOD 校验,
    # 让 web 与 CLI 的越界报错文案一致(带范围 hint),而非 FastAPI 通用 422。
    period: int = Query(60),
) -> dict:
    try:
        result = get_symbol_history(HistoryRequest(symbol_or_name=code, period=period))
    except HistoryServiceError as e:
        status = 400 if e.exit_code == 2 else 404
        detail = f"{e.message} · {e.hint}" if e.hint else e.message
        raise HTTPException(status_code=status, detail=detail) from e
    return serialize_history(result)


@router.get("/hold")
def hold() -> dict:
    try:
        return serialize_hold(build_hold_summary())
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web hold unavailable", e)
        return empty_hold_payload(error="持仓数据不可用")


@router.get("/index")
def index_reference() -> dict:
    try:
        result = get_index_reference(IndexRequest(periods=[30, 60, 180]))
        payload = serialize_index(result)
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web index unavailable", e)
        payload = {"ok": False, "periods": [30, 60, 180], "rows": [], "stats": {"shown": 0}}
    if not payload["ok"]:
        payload["message"] = "指数数据不可用"
    return payload


@router.get("/config/token")
def config_token() -> dict:
    return _token_status()


@router.post("/config/token")
def set_config_token(payload: Annotated[dict[str, Any], Body()]) -> dict:
    raw = payload.get("token")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="token 无效")
    cfg = config.load()
    cfg["tushare_token"] = raw.strip()
    config.save(cfg)
    return _token_status()


@router.delete("/config/token")
def delete_config_token() -> dict:
    cfg = config.load()
    cfg["tushare_token"] = None
    config.save(cfg)
    return _token_status()


def _token_status() -> dict[str, Any]:
    token = config.load().get("tushare_token")
    token_text = token.strip() if isinstance(token, str) else ""
    configured = bool(token_text)
    return {
        "ok": True,
        "configured": configured,
        "masked": config.mask_token(token_text) if configured else None,
    }


def settings_facts() -> dict[str, Any]:
    """设置页只读事实。"""
    import os

    from kan.data.tushare import DEFAULT_ENDPOINT
    from kan.storage import paths

    cfg = config.load()
    endpoint_raw = os.environ.get("TUSHARE_ENDPOINT") or cfg.get("tushare_endpoint") or DEFAULT_ENDPOINT
    endpoint = endpoint_raw.strip() if isinstance(endpoint_raw, str) else DEFAULT_ENDPOINT
    if not endpoint.startswith(("http://", "https://")):
        endpoint = DEFAULT_ENDPOINT
    return {
        "data_dir": str(paths.DATA_DIR),
        "kline_cache_files": _kline_cache_count(paths.DATA_DIR),
        "tushare_endpoint_domain": _endpoint_domain(endpoint),
    }


def _kline_cache_count(data_dir) -> int:
    try:
        return sum(
            1 for path in data_dir.glob("*.parquet")
            if path.stem.isdigit() and len(path.stem) == 6
        )
    except OSError:
        return 0


def _endpoint_domain(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return ""
    return parsed.hostname or ""
