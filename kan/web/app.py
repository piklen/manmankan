"""FastAPI app factory for `kan web`."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from kan.web.routes_api import router as api_router
from kan.web.routes_pages import router as pages_router
from kan.web.security import MUTATING_METHODS, host_allowed, mutating_request_error

STATIC_DIR = Path(__file__).with_name("static")


def create_app() -> FastAPI:
    """创建本地 Web 应用。"""
    app = FastAPI(
        title="manmankan local web",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(pages_router)
    app.include_router(api_router)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            return JSONResponse({"ok": False, "error": "host not allowed"}, status_code=403)
        if request.method in MUTATING_METHODS:
            error = mutating_request_error(request)
            if error is not None:
                return JSONResponse({"ok": False, "error": error}, status_code=403)
        return await call_next(request)

    return app
