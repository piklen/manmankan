"""Web 本地访问校验。"""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi import Request

LOCAL_WEB_HOSTS = {"127.0.0.1", "localhost"}
MUTATING_METHODS = {"POST", "PUT", "DELETE"}
SESSION_QUERY_NAME = "_kan_session"
SESSION_HEADER_NAME = "x-kan-session"


def mutating_request_error(request: Request) -> str | None:
    if request.headers.get("x-kan-web") != "1":
        return "missing X-Kan-Web header"
    if not host_allowed(request.headers.get("host")):
        return "host not allowed"
    origin = request.headers.get("origin")
    scheme = getattr(getattr(request, "url", None), "scheme", "http")
    if origin and not origin_allowed(
        origin,
        expected_host=request.headers.get("host"),
        expected_scheme=scheme,
    ):
        return "origin not allowed"
    return None


def host_allowed(host: str | None) -> bool:
    if not host:
        return False
    hostname = host.rsplit(":", 1)[0].strip("[]").lower()
    return hostname in LOCAL_WEB_HOSTS


def origin_allowed(
    origin: str,
    *,
    expected_host: str | None = None,
    expected_scheme: str = "http",
) -> bool:
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.hostname.lower() not in LOCAL_WEB_HOSTS:
            return False
        if expected_host is None:
            return True
        expected = urlsplit(f"{expected_scheme}://{expected_host}")
        return (
            parsed.scheme == expected.scheme
            and parsed.hostname.lower() == (expected.hostname or "").lower()
            and parsed.port == expected.port
        )
    except ValueError:
        return False


def browser_request_error(request: Request) -> str | None:
    """阻止同一回环主机其他端口借浏览器上下文发起请求。"""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in {"same-origin", "none"}:
        return "cross-site request not allowed"
    return None


def session_allowed(request: Request, session_token: str) -> bool:
    """校验本次 kan web 进程签发的浏览器会话。"""
    header = request.headers.get(SESSION_HEADER_NAME)
    if _safe_session_equal(header, session_token):
        return True
    query = request.query_params.get(SESSION_QUERY_NAME)
    query_allowed = (
        not request.url.path.startswith("/api/")
        or request.url.path == "/api/fetch/events"
    )
    return bool(query_allowed and _safe_session_equal(query, session_token))


def _safe_session_equal(candidate: str | None, expected: str) -> bool:
    """拒绝畸形会话值，避免 compare_digest 对非 ASCII str 抛 TypeError。"""
    if candidate is None or len(candidate) != len(expected):
        return False
    try:
        return hmac.compare_digest(candidate.encode("ascii"), expected.encode("ascii"))
    except UnicodeEncodeError:
        return False
