"""FastAPI app factory for `kan web`."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from kan.web.routes_api import router as api_router
from kan.web.routes_pages import router as pages_router

STATIC_DIR = Path(__file__).with_name("static")
LOCAL_WEB_HOSTS = {"127.0.0.1", "localhost"}
MUTATING_METHODS = {"POST", "DELETE"}


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
        if request.method in MUTATING_METHODS:
            error = _mutating_request_error(request)
            if error is not None:
                return JSONResponse({"ok": False, "error": error}, status_code=403)
        return await call_next(request)

    return app


def _mutating_request_error(request: Request) -> str | None:
    if request.headers.get("x-kan-web") != "1":
        return "missing X-Kan-Web header"
    if not _host_allowed(request.headers.get("host")):
        return "host not allowed"
    origin = request.headers.get("origin")
    if origin and not _origin_allowed(origin):
        return "origin not allowed"
    return None


def _host_allowed(host: str | None) -> bool:
    if not host:
        return False
    hostname = host.rsplit(":", 1)[0].strip("[]").lower()
    return hostname in LOCAL_WEB_HOSTS


def _origin_allowed(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return parsed.hostname.lower() in LOCAL_WEB_HOSTS
