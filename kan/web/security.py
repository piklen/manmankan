"""Web 本地访问校验。"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

LOCAL_WEB_HOSTS = {"127.0.0.1", "localhost"}
MUTATING_METHODS = {"POST", "DELETE"}


def mutating_request_error(request: Request) -> str | None:
    if request.headers.get("x-kan-web") != "1":
        return "missing X-Kan-Web header"
    if not host_allowed(request.headers.get("host")):
        return "host not allowed"
    origin = request.headers.get("origin")
    if origin and not origin_allowed(origin):
        return "origin not allowed"
    return None


def host_allowed(host: str | None) -> bool:
    if not host:
        return False
    hostname = host.rsplit(":", 1)[0].strip("[]").lower()
    return hostname in LOCAL_WEB_HOSTS


def origin_allowed(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return parsed.hostname.lower() in LOCAL_WEB_HOSTS
