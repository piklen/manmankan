"""Web 页面路由。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kan.render.base import DISCLAIMER
from kan.web.routes_api import default_scan_payload

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
