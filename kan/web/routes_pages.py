"""Web 页面路由。"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kan.render.base import DISCLAIMER, FIND_DISCLAIMER_TEXT, HOLD_DISCLAIMER_TEXT
from kan.service.hold_service import build_hold_summary
from kan.service.info_service import (
    InfoDataUnavailableError,
    InfoRequest,
    get_stock_info,
)
from kan.storage import positions
from kan.web.find_adapter import MAX_FILTERS, web_filter_groups
from kan.web.routes_api import default_scan_payload, settings_facts
from kan.web.security import SESSION_QUERY_NAME
from kan.web.serialize import empty_hold_payload, serialize_hold, serialize_info

router = APIRouter()
TEMPLATE_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["disclaimer"] = DISCLAIMER.strip()
templates.env.globals["find_disclaimer"] = FIND_DISCLAIMER_TEXT
templates.env.globals["hold_disclaimer"] = HOLD_DISCLAIMER_TEXT
templates.env.globals["session_url"] = lambda request, path: (
    f"{path}{'&' if '?' in path else '?'}"
    f"{urlencode({SESSION_QUERY_NAME: request.app.state.kan_session_token})}"
)
templates.env.globals["session_token"] = (
    lambda request: request.app.state.kan_session_token
)


def _market_phase_label() -> str:
    """返回当前市场相位的中文标签。"""
    try:
        from kan.core.trading_calendar import (
            PHASE_CLOSED_DAY,
            PHASE_INTRADAY,
            PHASE_POST,
            PHASE_PRE,
            market_phase,
        )

        phase = market_phase()
        labels = {
            PHASE_PRE: "盘前",
            PHASE_INTRADAY: "盘中",
            PHASE_POST: "已收盘",
            PHASE_CLOSED_DAY: "休市",
        }
        return labels.get(phase, "")
    except Exception:
        return ""


templates.env.globals["market_phase_label"] = _market_phase_label


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    try:
        scan = default_scan_payload()
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web index page unavailable", e)
        scan = {
            "ok": False,
            "source_name": "数据暂不可用",
            "mode": "low",
            "periods": [30, 60, 180],
            "stats": {
                "targets": 0,
                "shown": 0,
                "data_cutoff": None,
                "stale": False,
            },
            "freshness": {
                "status": "missing",
                "title": "暂时无法读取本地行情",
                "detail": "先在下方添加自选；如果已经添加，请刷新页面或到数据设置查看本地目录。",
                "action_label": "先添加自选",
            },
            "overview": {
                "data_cutoff": None,
                "expected_cutoff": None,
                "stale": False,
                "scanned_count": 0,
                "low_180_count": 0,
                "high_180_count": 0,
                "low_resonance_count": 0,
                "high_resonance_count": 0,
                "low_180": [],
                "high_180": [],
                "comparison_date": None,
                "changes": [],
                "change_count": 0,
            },
            "rows": [],
            "heatmap": [],
        }
    return templates.TemplateResponse(
        request,
        "index.html",
        {"scan": scan},
    )


@router.get("/find", response_class=HTMLResponse)
def find(request: Request):
    groups = web_filter_groups()
    options = [option for group in groups for option in group["options"]]
    return templates.TemplateResponse(
        request,
        "find.html",
        {
            "find_filter_groups": groups,
            "find_filter_options": options,
            "find_max_filters": MAX_FILTERS,
        },
    )


@router.get("/compare", response_class=HTMLResponse)
def compare(request: Request):
    return templates.TemplateResponse(request, "compare.html", {})


@router.get("/stock/{code}", response_class=HTMLResponse)
def stock(request: Request, code: str):
    try:
        result = get_stock_info(InfoRequest(
            symbol_or_name=code,
            allow_fetch=False,
            include_external_context=False,
            include_valuation_context=False,
            include_board_context=True,
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
    except positions.PositionsCorruptError as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web hold file unavailable", e)
        payload = empty_hold_payload(error="持仓文件无法读取")
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web hold page unavailable", e)
        payload = empty_hold_payload(error="持仓数据暂不可用")
    return templates.TemplateResponse(
        request,
        "hold.html",
        {"hold": payload},
    )


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    from kan.web.routes_api import _token_status

    try:
        token = _token_status()
        facts = settings_facts()
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web settings page unavailable", e)
        token = {"ok": False, "configured": False, "masked": None}
        facts = {
            "data_dir": "数据暂不可用",
            "kline_cache_files": 0,
            "tushare_endpoint_domain": "数据暂不可用",
        }
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "token": token,
            "facts": facts,
        },
    )
