"""web · 本地选股研究工作台。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.cli.helpers import _print_err

DEFAULT_WEB_PORT = 8876


@app.command()
def web(
    port: Annotated[
        int,
        typer.Option("--port", min=1, max=65535, help="本地端口（默认 8876）"),
    ] = DEFAULT_WEB_PORT,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="启动后不自动打开浏览器"),
    ] = False,
) -> None:
    """启动本地私有选股研究工作台。"""
    from kan.web.server import run_server

    try:
        run_server(port=port, open_browser=not no_open)
    except RuntimeError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(1) from e
