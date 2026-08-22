"""FastAPI app factory for `kan web`."""
from __future__ import annotations

import secrets
from html import escape
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from kan import __version__
from kan.service.job_service import recover_incomplete_jobs
from kan.web.api_v1 import router as api_v1_router
from kan.web.routes_api import router as api_router
from kan.web.security import (
    MUTATING_METHODS,
    browser_request_error,
    host_allowed,
    mutating_request_error,
    session_allowed,
)

SPA_DIR = Path(__file__).with_name("spa")
SPA_INDEX = SPA_DIR / "index.html"


def create_app(
    *,
    session_token: str | None = None,
    session_required: bool = True,
    recover_jobs: bool = True,
) -> FastAPI:
    """创建本地 Web 应用；``session_required=False`` 只供隔离测试 harness。"""
    active_session_token = session_token or secrets.token_urlsafe(32)
    app = FastAPI(
        title="ManManKan Local API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.kan_session_token = active_session_token
    if recover_jobs:
        recover_incomplete_jobs()
    app.mount(
        "/assets",
        StaticFiles(directory=str(SPA_DIR / "assets"), check_dir=False),
        name="spa-assets",
    )
    # 迁移期保留旧 API 兼容；默认页面和所有新调用统一走 SPA + /api/v1。
    app.include_router(api_router, include_in_schema=False)
    app.include_router(api_v1_router)

    @app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                {"detail": {"code": "not_found", "message": "API 路径不存在"}},
                status_code=404,
            )
        if not SPA_INDEX.exists():
            return PlainTextResponse(
                "Web UI 尚未构建 · 开发环境请在 webui/ 运行 npm run build。",
                status_code=503,
            )
        html = SPA_INDEX.read_text(encoding="utf-8").replace(
            "__KAN_SESSION_TOKEN__",
            escape(active_session_token, quote=True),
        )
        return HTMLResponse(html)

    @app.middleware("http")
    async def local_access_guard(request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            return _secure_response(
                JSONResponse({"ok": False, "error": "host not allowed"}, status_code=403)
            )
        if request.url.path.startswith(("/static/", "/assets/")):
            return _secure_response(await call_next(request))
        if session_required and not session_allowed(request, active_session_token):
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
