"""Web 页面路由。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kan.render.base import DISCLAIMER
from kan.service.info_service import (
    InfoDataUnavailableError,
    InfoRequest,
    get_stock_info,
)
from kan.web.routes_api import default_scan_payload
from kan.web.serialize import serialize_info

router = APIRouter()
TEMPLATE_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["disclaimer"] = DISCLAIMER.strip()


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
