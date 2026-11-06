"""市场观察 CLI：从群体事实进入精确查询。"""

from datetime import date
from typing import Annotated

import typer

from kan.app import app
from kan.cli.trend_cmds import TrendFormat, TrendUniverse
from kan.domain.discovery import DiscoveryQuery
from kan.service.discovery import discover_market


@app.command()
def discover(
    universe: Annotated[TrendUniverse, typer.Option("--universe", help="观察完整范围：all / personal / codes")] = TrendUniverse.all,
    codes: Annotated[str | None, typer.Option("--codes", help="逗号分隔的明确股票范围")] = None,
    industry: Annotated[list[str] | None, typer.Option("--industry", help="仅观察指定行业，可重复")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of", help="完整收盘日 YYYY-MM-DD，默认最近收盘")] = None,
    window: Annotated[int, typer.Option("--window", min=2, max=120, help="每段观察的市场交易日数；比较两个相邻等长窗口")] = 20,
    format: Annotated[TrendFormat, typer.Option("--format")] = TrendFormat.terminal,
) -> None:
    """观察群体分布、行业差异与参与范围变化，不预置股票筛选策略。"""
    try:
        result = discover_market(DiscoveryQuery(
            universe="codes" if codes else universe.value, codes=codes.split(",") if codes else [],
            industries=industry or [], as_of=date.fromisoformat(as_of) if as_of else None, window=window,
        ))
    except (ValueError, OSError) as exc:
        if format is TrendFormat.json:
            import json

            typer.echo(json.dumps({"error": {"message": str(exc)}}, ensure_ascii=False))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if format is TrendFormat.json:
        typer.echo(result.model_dump_json())
        return
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print(f"慢慢看 · 市场观察 · {result.as_of} · 每段 {window} 个交易日")
    console.print(f"本段 {result.current_start or '起点不足'} → {result.as_of}；前段 {result.previous_start or '起点不足'} → {result.previous_as_of or '终点不足'}")
    for observation in result.market.observations:
        console.print(f"\n[bold]{observation.title}[/bold]\n{observation.detail}")
    if not result.market.current.available and result.common_data_date:
        console.print(f"\n本地主要数据日 {result.common_data_date}（{result.common_data_count} 只）；可显式 --as-of {result.common_data_date}，未自动改用旧行情。")
    table = Table("行业", "覆盖", "上涨", "中位涨跌", "同组占比变化")
    for group in result.industries:
        stats, comparison = group.current, group.comparison
        table.add_row(
            group.name, f"{stats.available}/{stats.total}", f"{stats.up}/{stats.available}",
            f"{stats.median_return:+.2f}%" if stats.median_return is not None else "—",
            f"{comparison.breadth_delta_pp:+.1f}pp ({comparison.available}只)" if comparison.breadth_delta_pp is not None else "—",
        )
    console.print(table)
    console.print("当前成员与行业归属回溯；中位数不是行业指数。历史价格不预示未来，仅供参考，不构成投资建议。")
