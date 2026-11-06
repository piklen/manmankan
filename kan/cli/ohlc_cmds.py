"""显式日线条件与统一复权证据查询。"""

from typing import Annotated

import typer

from kan.app import app
from kan.storage import export


@app.command("ohlc")
def ohlc(
    market: Annotated[str, typer.Option(help="股票池，当前支持 mainboard（完整沪深主板，含 ST）")],
    as_of: Annotated[str, typer.Option(help="最近完整交易日，YYYY-MM-DD")],
    period: Annotated[int, typer.Option(min=2, max=360, help="区间交易日数")],
    low_within: Annotated[int, typer.Option(min=1, help="区间最低价须在最近多少个交易日内出现")],
    max_position: Annotated[float, typer.Option(min=0, max=100, help="区间位置上限，百分比")],
    joint_up_days: Annotated[int, typer.Option(min=2, help="连续 close>open 且 close>前收的最少天数")],
    refresh: Annotated[bool, typer.Option(help="重新获取原始日线与复权因子")] = False,
) -> None:
    """按显式参数筛选日线，JSON 返回完整候选、覆盖率和逐日证据。"""
    from kan.service.ohlc_screen_service import OhlcScreenRequest, run_ohlc_screen

    try:
        request = OhlcScreenRequest.model_validate({
            "market": market, "as_of": as_of, "period": period, "low_within": low_within,
            "max_position": max_position, "joint_up_days": joint_up_days,
        })
        result = run_ohlc_screen(request, refresh=refresh)
    except (ValueError, RuntimeError) as exc:
        typer.echo(export.to_json(export.error_payload("ohlc", code="ohlc_screen_failed", message=str(exc))))
        raise typer.Exit(1) from exc
    typer.echo(export.to_json(result))
