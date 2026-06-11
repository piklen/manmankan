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
    # -h 作 --help short flag · Unix 通用约定 (F2 修)
    context_settings={"help_option_names": ["-h", "--help"]},
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"kan {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True, help="显示版本号"),
    ] = None,
) -> None:
    """慢慢看 · 看清你的股票正站在历史价格的哪个位置"""
    # 用 Click 解析结果判断"没敲子命令" · 不读进程全局 sys.argv：
    # MCP server(kan-mcp 进程)用 CliRunner 在进程内 invoke 子命令时,
    # sys.argv 恒为 ['kan-mcp'](长度 1),旧的 len(sys.argv)==1 会误判成
    # 无子命令 → 打印命令速记并 raise Exit → 子命令永远不执行(所有 MCP 工具
    # 都塌缩成同一段 help)。ctx.invoked_subcommand 读 Click 解析后的子命令名,
    # 对真 CLI 和 in-process invoke 都正确。
    if ctx.invoked_subcommand is None:
        # lazy import 避免循环 · help_cmd 装饰在 app 上但位于 cli_help
        from kan.cli.help import help_cmd
        help_cmd()
        raise typer.Exit()
