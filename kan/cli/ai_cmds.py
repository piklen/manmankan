"""AI consumption helpers: examples, fields, MCP, and index references."""
from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from kan.app import app
from kan.cli.helpers import _print_err
from kan.storage import export

fields_app = typer.Typer(
    name="fields",
    help="查看 find JSON 字段白名单",
    no_args_is_help=True,
)
app.add_typer(fields_app, name="fields")

mcp_app = typer.Typer(
    name="mcp",
    help="manmankan MCP server / 客户端注册",
    no_args_is_help=True,
)
app.add_typer(mcp_app, name="mcp")


_EXAMPLES = [
    (
        "首次结构 smoke",
        "kan find --codes 600519,000858 --format json",
        "不拉行情；确认 CLI、JSON envelope、退出码和免责声明正常。",
    ),
    (
        "真实行情坐标 JSON",
        "kan scan --codes 600519,000858 --periods 5,20,60,180 --format json",
        "拉公开日 K；输出多周期位置、区间涨跌、共振和数据截止日。",
    ),
    (
        "按代码池筛选位置",
        "kan find --codes 600519,000858 --pos 180:lt:30 --fields @core,@context --format json",
        "只在显式代码池内筛选；输出触发条件和位置上下文字段。",
    ),
    (
        "全市场估值筛选",
        "kan find --all --pe lt:20 --turnover gt:1 --limit 20 --fields @core,@valuation --format json",
        "走截面数据，不依赖自选股；TuShare 不可用时返回缺数提示。",
    ),
    (
        "小代码池 ROE 取数",
        "kan find --codes 600519,000858 --roe gt:10 --fields @core,@fundamentals --format json",
        "ROE 是逐股报告期数据；全市场模式不支持，先缩小代码池。",
    ),
    (
        "查看单股详情",
        "kan info 600519 --format json",
        "返回多周期位置、今日资金流拆分、连续净流入天数、涨跌停详情等事实。",
    ),
    (
        "预览 MCP 注册",
        "kan mcp install --dry-run",
        "预览写入哪些本机 AI 客户端配置；确认后再去掉 --dry-run。",
    ),
]


@app.command()
def examples(
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """查看端到端工作流示例。"""
    payload = {
        "command": "examples",
        "examples": [
            {"title": title, "command": command, "detail": detail}
            for title, command, detail in _EXAMPLES
        ],
    }
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    if fmt is export.OutputFormat.md:
        lines = ["# manmankan 工作流示例", ""]
        for i, item in enumerate(payload["examples"], 1):
            lines.extend([
                f"## {i}. {item['title']}",
                "",
                "```bash",
                str(item["command"]),
                "```",
                "",
                str(item["detail"]),
                "",
            ])
        typer.echo("\n".join(lines).rstrip() + "\n")
        return

    lines = ["慢慢看 · 工作流示例", ""]
    for i, item in enumerate(payload["examples"], 1):
        lines.extend([
            f"{i}. {item['title']}",
            f"   {item['command']}",
            f"   {item['detail']}",
            "",
        ])
    lines.append("复制命令时只复制缩进后的 kan ... 行。")
    typer.echo("\n".join(lines))


@fields_app.command("list")
def fields_list(
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """列出 kan find --format json 的字段 preset 和字段白名单。"""
    from kan.core.find_registry import FIND_FIELD_PRESETS, FIND_FIELD_SPECS

    payload: dict[str, Any] = {
        "command": "fields list",
        "presets": {k: list(v) for k, v in FIND_FIELD_PRESETS.items()},
        "fields": [
            {
                "path": path,
                "dimension": spec.dimension,
                "needs_kline": spec.needs_kline,
                "needs_valuation_context": spec.needs_valuation_context,
            }
            for path, spec in FIND_FIELD_SPECS.items()
        ],
    }
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    if fmt is export.OutputFormat.md:
        rows = [
            [
                field["path"],
                field["dimension"] or "-",
                "yes" if field["needs_kline"] else "",
                "yes" if field["needs_valuation_context"] else "",
            ]
            for field in payload["fields"]
        ]
        typer.echo(
            "# kan find 字段白名单\n\n"
            "## Presets\n\n"
            + "\n".join(f"- `{k}`: `{', '.join(v)}`" for k, v in payload["presets"].items())
            + "\n\n## Fields\n\n"
            + export.md_table(["字段", "维度", "K线", "估值上下文"], rows)
        )
        return

    table = Table(title="kan find 字段白名单")
    table.add_column("字段", style="cyan")
    table.add_column("维度")
    table.add_column("K线", justify="center")
    table.add_column("估值上下文", justify="center")
    for field in payload["fields"]:
        table.add_row(
            str(field["path"]),
            str(field["dimension"] or "-"),
            "✓" if field["needs_kline"] else "",
            "✓" if field["needs_valuation_context"] else "",
        )
    console = Console()
    console.print(table)
    console.print("[dim]presets: " + " / ".join(payload["presets"]) + "[/dim]")


@mcp_app.command("serve")
def mcp_serve() -> None:
    """启动 stdio MCP server。"""
    from kan.mcp.server import serve

    serve()


@mcp_app.command("http")
def mcp_http(
    host: Annotated[
        str,
        typer.Option("--host", help="监听地址；默认仅绑定本机 127.0.0.1"),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", min=1, max=65535, help="监听端口"),
    ] = 8765,
    path: Annotated[
        str,
        typer.Option("--path", help="MCP HTTP endpoint 路径"),
    ] = "/mcp",
    allow_origin: Annotated[
        list[str] | None,
        typer.Option("--allow-origin", help="额外允许的浏览器 Origin，可重复"),
    ] = None,
    allow_non_localhost: Annotated[
        bool,
        typer.Option(
            "--allow-non-localhost",
            help="允许绑定非本机地址；只在可信内网或反向代理后使用",
        ),
    ] = False,
) -> None:
    """启动本机 Streamable HTTP MCP server。"""
    from kan.mcp.server import is_local_http_host, serve_http

    if not allow_non_localhost and not is_local_http_host(host):
        _print_err(
            "❌ 默认只允许绑定 127.0.0.1 / localhost / ::1\n"
            "   若你确认在可信内网或本机反向代理后使用，例: "
            f"kan mcp http --host {host} --allow-non-localhost"
        )
        raise typer.Exit(2)
    typer.echo(
        f"manmankan MCP HTTP server: http://{host}:{port}{path} · Ctrl+C 停止",
        err=True,
    )
    serve_http(host=host, port=port, path=path, allow_origins=allow_origin)


@mcp_app.command("install")
def mcp_install(
    clients: Annotated[
        list[str] | None,
        typer.Option(
            "--client",
            help=(
                "只注册指定客户端，可重复；支持: codex / claude-code / claude-desktop / "
                "cursor / vscode / windsurf / cline / gemini-cli / opencode / "
                "zed / openclaw / amazon-q"
            ),
        ),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只预览，不写配置")] = False,
) -> None:
    """注册 manmankan MCP 到本机常见 AI 客户端的用户级配置。"""
    from kan.mcp.install import SUPPORTED_CLIENTS, install_clients

    selected = clients or list(SUPPORTED_CLIENTS)
    unknown = [c for c in selected if c not in SUPPORTED_CLIENTS]
    if unknown:
        _print_err(
            "❌ 不支持的 MCP client: "
            + ", ".join(unknown)
            + f" · 支持: {', '.join(SUPPORTED_CLIENTS)}"
        )
        raise typer.Exit(2)
    results = install_clients(selected, dry_run=dry_run)
    table = Table(title="manmankan MCP 注册结果")
    table.add_column("client", style="cyan")
    table.add_column("status")
    table.add_column("target", overflow="fold")
    table.add_column("detail", overflow="fold")
    for r in results:
        table.add_row(r.client, r.status, r.target, r.detail)
    console = Console()
    console.print(table)
    console.print("[dim]重启对应客户端后生效；若已安装对应 CLI，会优先用 user scope 注册。[/dim]")
    if not dry_run and results and all(r.status != "failed" for r in results):
        from kan.cli.setup_helpers import mark_mcp_setup

        mark_mcp_setup(True)


def _index_row_payload(scan, *, code: str, name: str, data_available: bool) -> dict[str, Any]:
    if scan is None:
        return {
            "code": code,
            "name": name,
            "data_available": data_available,
            "data_date": None,
            "close": None,
            "position_pct": None,
            "gain_pct": None,
        }
    period = scan.periods[0] if scan.periods else None
    return {
        "code": code,
        "name": name,
        "data_available": data_available,
        "data_date": scan.scan_date.isoformat(),
        "close": scan.current_price,
        "position_pct": None if period is None or period.insufficient else period.position_pct,
        "gain_pct": None if period is None else period.gain_pct,
    }


def _exit_ai_error(
    command: str,
    fmt: export.OutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> None:
    """AI-facing commands keep JSON error envelopes when JSON was requested."""
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.error_payload(
            command,
            code=code,
            message=message,
            hint=hint,
        )))
    else:
        text = f"❌ {message}"
        if hint:
            text += f"\n   {hint}"
        _print_err(text)
    raise typer.Exit(exit_code)


@app.command()
def index(
    codes: Annotated[
        list[str] | None,
        typer.Argument(help="指数代码或别名：sh / sz / cyb / hs300；无参默认四个常用指数"),
    ] = None,
    period: Annotated[int, typer.Option("--period", help="位置周期（2-360）")] = 60,
    days: Annotated[int, typer.Option("--days", help="拉取日线条数（默认自动覆盖周期）")] = 420,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """查看常用 A 股指数日线位置参照（TuShare index_daily）。"""
    from kan.core.scanner import MAX_PERIOD, MIN_PERIOD, scan_stock
    from kan.data.index import DEFAULT_INDEXES, fetch_index_daily, index_name, normalize_index_code
    from kan.render.base import DISCLAIMER

    if period < MIN_PERIOD or period > MAX_PERIOD:
        _exit_ai_error(
            "index",
            fmt,
            code="invalid_period",
            message=f"周期 {period} 无效（范围 {MIN_PERIOD}-{MAX_PERIOD}）",
            hint="例: kan index sh --period 60 --format json",
            exit_code=2,
        )
    raw_codes = codes or [spec.code for spec in DEFAULT_INDEXES]
    rows: list[dict[str, Any]] = []
    for raw in raw_codes:
        try:
            code = normalize_index_code(raw)
        except ValueError as e:
            _exit_ai_error(
                "index",
                fmt,
                code="invalid_index",
                message=str(e),
                hint="支持: sh / sz / cyb / hs300 · 例: kan index sh --format json",
                exit_code=2,
            )
        name = index_name(code)
        df = fetch_index_daily(code, days=max(days, period + 40))
        if df is None or len(df) < period:
            rows.append(_index_row_payload(None, code=code, name=name, data_available=False))
            continue
        scan = scan_stock(df, code, name, periods=[period])
        rows.append(_index_row_payload(scan, code=code, name=name, data_available=True))

    payload = {
        "command": "index",
        "period": period,
        "disclaimer": DISCLAIMER.strip(),
        "results": rows,
    }
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    md_rows = [
        [
            f"{r['name']} {r['code']}",
            "-" if r["close"] is None else f"{r['close']:.2f}",
            "-" if r["position_pct"] is None else f"{r['position_pct']:.1f}%",
            "-" if r["gain_pct"] is None else f"{r['gain_pct']:.2f}%",
            r["data_date"] or "-",
        ]
        for r in rows
    ]
    if fmt is export.OutputFormat.md:
        typer.echo(
            f"# A 股指数位置参照（{period}日）\n\n"
            + export.md_table(["指数", "收盘", "位置", "涨幅", "数据日"], md_rows)
            + f"\n\n> {DISCLAIMER.strip()}"
        )
        return

    table = Table(title=f"A 股指数位置参照 · {period}日")
    table.add_column("指数", style="cyan")
    table.add_column("收盘", justify="right")
    table.add_column("位置", justify="right")
    table.add_column("涨幅", justify="right")
    table.add_column("数据日", justify="right")
    for row in md_rows:
        table.add_row(*row)
    console = Console()
    console.print(table)
    console.print(DISCLAIMER, style="dim")
