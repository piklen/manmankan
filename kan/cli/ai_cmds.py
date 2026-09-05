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
        "kan find --codes 600519,000858 --format json --dry-run",
        "只返回查询计划；确认 CLI、JSON envelope、退出码和免责声明正常。",
    ),
    (
        "代码池字段补全",
        "kan find --codes 600519,000858 --fields @core,@valuation,@moneyflow,@technical --format json",
        "显式代码池无 filter 也会按字段补客观数据，不需要伪造永真 filter。",
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
        "复核单股日内范围",
        "kan range 600519 --format json",
        "默认返回近 5/15 日的 75/85/90/95 四档上下行范围及触及后收盘事实。",
    ),
    (
        "板块连续涨跌",
        "kan board trend --kind industry --up 3 --format json",
        "把申万行业指数当作 OHLC 序列，返回连续上涨不少于 3 天的客观结果。",
    ),
    (
        "预览 MCP 注册",
        "kan mcp install --dry-run",
        "预览写入哪些本机 AI 客户端配置；确认后再去掉 --dry-run。",
    ),
    (
        "Agent schema 发现",
        "kan schema --format json --section find --compact",
        "低上下文查看 CLI JSON、find DSL、MCP tools 和错误 envelope 契约。",
    ),
    (
        "个股研究证据包",
        "kan research 600519 --format json",
        "按请求维度整理市场、估值、财务等事实，保留来源、各自日期、单位和缺口；不调用模型。",
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
    examples: list[dict[str, str]] = [
        {"title": title, "command": command, "detail": detail}
        for title, command, detail in _EXAMPLES
    ]
    payload = {
        "command": "examples",
        "examples": examples,
    }
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    if fmt is export.OutputFormat.md:
        lines = ["# manmankan 工作流示例", ""]
        for i, item in enumerate(examples, 1):
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
    for i, item in enumerate(examples, 1):
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
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """注册 manmankan MCP 到本机常见 AI 客户端的用户级配置。"""
    from kan.mcp.install import SUPPORTED_CLIENTS, install_clients, install_results_payload

    selected = clients or list(SUPPORTED_CLIENTS)
    unknown = [c for c in selected if c not in SUPPORTED_CLIENTS]
    if unknown:
        _exit_ai_error(
            "mcp install",
            fmt,
            code="invalid_mcp_client",
            message="不支持的 MCP client: " + ", ".join(unknown),
            hint=f"支持: {', '.join(SUPPORTED_CLIENTS)}",
            exit_code=2,
        )
    results = install_clients(selected, dry_run=dry_run)
    if not dry_run and results and all(r.status != "failed" for r in results):
        from kan.cli.setup_helpers import mark_mcp_setup

        mark_mcp_setup(True)
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(install_results_payload(
            results,
            selected_clients=selected,
            dry_run=dry_run,
        )))
        return
    if fmt is export.OutputFormat.md:
        rows = [[r.client, r.status, r.target, r.detail] for r in results]
        typer.echo(
            "# manmankan MCP 注册结果\n\n"
            + export.md_table(["client", "status", "target", "detail"], rows)
            + "\n\n> 重启对应客户端后生效；若已安装对应 CLI，会优先用 user scope 注册。"
        )
        return
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
def schema(
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
    section: Annotated[
        str,
        typer.Option("--section", help="只输出局部 schema：all / commands / find / mcp / errors"),
    ] = "all",
    compact: Annotated[
        bool,
        typer.Option("--compact", help="低上下文输出；省略长说明和完整 inputSchema"),
    ] = False,
) -> None:
    """发现 CLI JSON / find DSL / MCP / error envelope 契约。"""
    from kan.service.schema_service import (
        VALID_SCHEMA_SECTIONS,
        build_schema_payload,
        render_schema_markdown,
        render_schema_terminal,
    )

    try:
        payload = build_schema_payload(section=section, compact=compact)
    except ValueError as e:
        _exit_ai_error(
            "schema",
            fmt,
            code="invalid_schema_section",
            message=str(e),
            hint="支持: " + " / ".join(VALID_SCHEMA_SECTIONS),
            exit_code=2,
        )
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(payload))
        return
    if fmt is export.OutputFormat.md:
        typer.echo(render_schema_markdown(payload))
        return
    typer.echo(render_schema_terminal(payload))


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
    from kan.render.base import DISCLAIMER
    from kan.service.index_service import (
        IndexRequest,
        IndexServiceError,
        get_index_reference,
        index_row_payload,
    )

    try:
        result = get_index_reference(IndexRequest(
            codes=codes,
            periods=[period],
            days=days,
        ))
    except IndexServiceError as e:
        _exit_ai_error(
            "index",
            fmt,
            code=e.code,
            message=e.message,
            hint=e.hint,
            exit_code=e.exit_code,
        )
    rows = [index_row_payload(row) for row in result.rows]

    payload = {
        **export.success_envelope(
            "index",
            disclaimer=DISCLAIMER.strip(),
            stats={"shown": len(rows), "period": period},
            data_availability={
                "basis": "index_daily",
                "pool_size": len(rows),
                "available": sum(1 for row in rows if row["data_available"]),
                "missing": sum(1 for row in rows if not row["data_available"]),
            },
        ),
        "period": period,
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
    if fmt is export.OutputFormat.csv:
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["指数", "代码", "收盘", "位置%", "涨幅%", "数据日"])
        for r in rows:
            writer.writerow([
                r["name"],
                r["code"],
                "-" if r["close"] is None else f"{r['close']:.2f}",
                "-" if r["position_pct"] is None else f"{r['position_pct']:.1f}",
                "-" if r["gain_pct"] is None else f"{r['gain_pct']:.2f}",
                r["data_date"] or "-",
            ])
        typer.echo("\ufeff" + output.getvalue())
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
