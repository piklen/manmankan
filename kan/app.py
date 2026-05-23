"""typer.Typer 单例 + root callbacks。

子模块和 cli.py 都从这里 import `app`，避免循环 import：
子模块需要 `@app.command()` 装饰器引用 `app`，如果 `app` 在 cli.py，子模块
要 `from kan.cli import app` → cli.py 又要 import 子模块触发命令注册 → 循环。
"""
from typing import Annotated

import typer

from kan import __version__

app = typer.Typer(
    name="kan",
    help="慢慢看 · A 股自选股位置感工具",
    invoke_without_command=True,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"kan {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True, help="显示版本号"),
    ] = None,
) -> None:
    """慢慢看 · 看清你的股票正站在历史价格的哪个位置"""
    import sys
    if len(sys.argv) == 1:
        # lazy import 避免循环 · help_cmd 装饰在 app 上但位于 cli_help
        from kan.cli_help import help_cmd
        help_cmd()
        raise typer.Exit()
