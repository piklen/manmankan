"""Web 页面路由。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kan.render.base import DISCLAIMER, HOLD_DISCLAIMER_TEXT
from kan.service.hold_service import build_hold_summary
from kan.service.info_service import (
    InfoDataUnavailableError,
    InfoRequest,
    get_stock_info,
)
from kan.web.routes_api import default_scan_payload, settings_facts
from kan.web.serialize import empty_hold_payload, serialize_hold, serialize_info

router = APIRouter()
TEMPLATE_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["disclaimer"] = DISCLAIMER.strip()
templates.env.globals["hold_disclaimer"] = HOLD_DISCLAIMER_TEXT


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    scan = default_scan_payload()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"scan": scan},
    )


@router.get("/stock/{code}", response_class=HTMLResponse)
def stock(request: Request, code: str):
    try:
        result = get_stock_info(InfoRequest(
            symbol_or_name=code,
            allow_fetch=False,
            include_external_context=False,
            include_valuation_context=False,
            include_board_context=False,
        ))
    except (ValueError, InfoDataUnavailableError):
        return templates.TemplateResponse(
            request,
            "stock.html",
            {"info": None, "code": code, "not_found": True},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "stock.html",
        {"info": serialize_info(result), "code": code, "not_found": False},
    )


@router.get("/hold", response_class=HTMLResponse)
def hold(request: Request):
    try:
        payload = serialize_hold(build_hold_summary())
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web hold page unavailable", e)
        payload = empty_hold_payload(error="持仓数据不可用")
    return templates.TemplateResponse(
        request,
        "hold.html",
        {"hold": payload},
    )


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    from kan.web.routes_api import _token_status

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "token": _token_status(),
            "facts": settings_facts(),
        },
    )
