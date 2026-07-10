"""FastAPI app factory for `kan web`."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from kan.web.routes_api import router as api_router
from kan.web.routes_pages import router as pages_router
from kan.web.security import (
    MUTATING_METHODS,
    browser_request_error,
    host_allowed,
    mutating_request_error,
    session_allowed,
)

STATIC_DIR = Path(__file__).with_name("static")


def create_app(*, session_token: str | None = None) -> FastAPI:
    """创建本地 Web 应用。"""
    active_session_token = session_token or secrets.token_urlsafe(32)
    app = FastAPI(
        title="manmankan local web",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.kan_session_token = active_session_token
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(pages_router)
    app.include_router(api_router)

    @app.middleware("http")
    async def local_access_guard(request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            return _secure_response(
                JSONResponse({"ok": False, "error": "host not allowed"}, status_code=403)
            )
        if request.url.path.startswith("/static/"):
            return _secure_response(await call_next(request))
        if not session_allowed(request, active_session_token):
            if request.url.path.startswith("/api/"):
                response: Response = JSONResponse(
                    {"ok": False, "error": "session required"}, status_code=401
                )
            else:
                response = PlainTextResponse(
                    "当前访问链接无效 · 请回到运行 kan web 的终端，打开本次访问地址。",
                    status_code=401,
                )
            return _secure_response(response)
        browser_error = browser_request_error(request)
        if browser_error is not None:
            return _secure_response(
                JSONResponse({"ok": False, "error": browser_error}, status_code=403)
            )
        if request.method in MUTATING_METHODS:
            error = mutating_request_error(request)
            if error is not None:
                return _secure_response(
                    JSONResponse({"ok": False, "error": error}, status_code=403)
                )
        return _secure_response(await call_next(request))

    return app


def _secure_response(response: Response) -> Response:
    """本地页面禁止被第三方 frame 嵌入，并避免启动凭证经 Referer 外泄。"""
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
