"""`kan web` 本地服务启动器。"""
from __future__ import annotations

import logging
import secrets
import socket
import webbrowser
from urllib.parse import urlencode

from kan.web.app import create_app
from kan.web.security import SESSION_QUERY_NAME

WEB_HOST = "127.0.0.1"


def run_server(port: int, open_browser: bool) -> None:
    """启动本地 Web 服务。"""
    _ensure_port_available(port)
    session_token = secrets.token_urlsafe(32)
    query = urlencode({SESSION_QUERY_NAME: session_token})
    url = f"http://{WEB_HOST}:{port}/?{query}"
    print("本地私有服务 · 仅监听 127.0.0.1 · 数据不出本机")
    print(f"访问地址（本次启动有效）: {url}")
    if open_browser:
        webbrowser.open(url)
    logging.getLogger(__name__).info("Starting kan web server")

    import uvicorn

    uvicorn.run(
        create_app(session_token=session_token),
        host=WEB_HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )


def _ensure_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((WEB_HOST, port))
        except OSError as e:
            raise RuntimeError(
                f"端口 {port} 已被占用 · 请换一个 --port，或先关闭占用该端口的本地程序"
            ) from e
