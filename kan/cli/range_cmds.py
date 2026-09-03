"""range · 单股历史日内上下行范围与触及后收盘事实。"""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Annotated, NoReturn

import typer

from kan.app import app
from kan.cli.helpers import _print_err, _safe_error_msg
from kan.storage import export

DEFAULT_RANGE_PERIODS = (5, 15)
DEFAULT_RANGE_LEVELS = (75.0, 85.0, 90.0, 95.0)


class RangeOutputFormat(StrEnum):
    """range 只开放人读终端与稳定 JSON 两个出口。"""

    terminal = "terminal"
    json = "json"


def _exit_range_error(
    fmt: RangeOutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> NoReturn:
    if fmt is RangeOutputFormat.json:
        typer.echo(export.to_json(export.error_payload(
            "range",
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


def _parse_periods(raw: str, fmt: RangeOutputFormat) -> tuple[int, ...]:
    parts = [part for part in raw.replace(",", " ").split() if part]
    try:
        values = [int(part) for part in parts]
    except ValueError:
        values = []
    if not values or any(value < 2 or value > 360 for value in values):
        _exit_range_error(
            fmt,
            code="invalid_periods",
            message="--periods 只接受 2-360 的整数列表",
            hint="例: kan range 600519 --periods 5,15",
            exit_code=2,
        )
    return tuple(sorted(dict.fromkeys(values)))


def _parse_levels(raw: str, fmt: RangeOutputFormat) -> tuple[float, ...]:
    parts = [part for part in raw.replace(",", " ").split() if part]
    try:
        values = [float(part) for part in parts]
    except ValueError:
        values = []
    if (
        not values
        or any(not isfinite(value) or value <= 0 or value >= 100 for value in values)
    ):
        _exit_range_error(
            fmt,
            code="invalid_levels",
            message="--levels 只接受大于 0 且小于 100 的百分比列表",
            hint="例: kan range 600519 --levels 75,85,90,95",
            exit_code=2,
        )
    return tuple(sorted(dict.fromkeys(values)))


def _validate_threshold(
    value: str | None,
    *,
    flag: str,
    maximum: float,
    fmt: RangeOutputFormat,
) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        number = float("nan")
    if not isfinite(number) or number <= 0 or number > maximum:
        _exit_range_error(
            fmt,
            code=f"invalid_{flag.removeprefix('--')}",
            message=f"{flag} 必须是大于 0 且不超过 {maximum:g} 的百分比",
            hint=f"例: kan range 600519 {flag} 3",
            exit_code=2,
        )
    return number


@app.command(name="range")
def range_command(
    symbol: Annotated[
        str,
        typer.Argument(help="股票代码或名称（如 600519 / 茅台）"),
    ],
    periods: Annotated[
        str,
        typer.Option("--periods", "-p", help="对照周期，逗号分隔（2-360）"),
    ] = "5,15",
    levels: Annotated[
        str,
        typer.Option("--levels", help="历史分位档位，逗号分隔（0-100）"),
    ] = "75,85,90,95",
    down: Annotated[
        str | None,
        typer.Option("--down", help="额外复核用户指定的下探幅度（传正数，如 3）"),
    ] = None,
    up: Annotated[
        str | None,
        typer.Option("--up", help="额外复核用户指定的上冲幅度（传正数，如 7）"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="忽略新鲜缓存并重新拉取日 K"),
    ] = False,
    fmt: Annotated[
        RangeOutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = RangeOutputFormat.terminal,
) -> None:
    """查看单股历史日内上下行范围，以及触及阈值后的收盘事实。"""

    parsed_periods = _parse_periods(periods, fmt)
    parsed_levels = _parse_levels(levels, fmt)
    parsed_down = _validate_threshold(down, flag="--down", maximum=100, fmt=fmt)
    parsed_up = _validate_threshold(up, flag="--up", maximum=1000, fmt=fmt)

    try:
        from kan.storage.watchlist import resolve_symbol_or_name

        resolved_symbol, _name = resolve_symbol_or_name(symbol)
    except ValueError as exc:
        _exit_range_error(
            fmt,
            code="invalid_symbol",
            message=str(exc),
            hint="例: kan range 600519",
            exit_code=2,
        )
    except Exception as exc:
        _exit_range_error(
            fmt,
            code="symbol_catalog_unavailable",
            message=f"股票代码表暂不可用：{_safe_error_msg(exc)}",
            hint="检查网络或稍后重试",
        )

    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter
    from kan.service.stock_range_service import (
        StockRangeRequest,
        StockRangeServiceError,
        study_stock_range,
    )

    try:
        with operation("日内范围复核", reporter=operation_reporter()) as lifecycle:
            lifecycle.phase("读取完整日 K")
            study = study_stock_range(StockRangeRequest(
                symbol=resolved_symbol,
                periods=parsed_periods,
                levels=parsed_levels,
                down_pct=parsed_down,
                up_pct=parsed_up,
                force=force,
            ))
            lifecycle.phase("准备输出")
    except StockRangeServiceError as exc:
        _exit_range_error(
            fmt,
            code=exc.code,
            message=exc.message,
            hint=exc.hint,
            exit_code=exc.exit_code,
        )
    except ValueError as exc:
        _exit_range_error(
            fmt,
            code="invalid_request",
            message=str(exc),
            hint="例: kan range 600519",
            exit_code=2,
        )
    except Exception as exc:
        _exit_range_error(
            fmt,
            code="data_unavailable",
            message=f"日 K 数据暂不可用：{_safe_error_msg(exc)}",
            hint="可重试，或运行 kan range 600519 --force",
        )

    if fmt is RangeOutputFormat.json:
        payload = export.success_envelope(
            "range",
            stats={"windows": len(study.windows)},
        )
        payload["study"] = study.model_dump(mode="json")
        typer.echo(export.to_json(payload))
        return

    from rich.console import Console

    from kan.render.terminal_range import render_stock_range

    render_stock_range(Console(), study)


__all__ = [
    "DEFAULT_RANGE_LEVELS",
    "DEFAULT_RANGE_PERIODS",
    "RangeOutputFormat",
    "range_command",
]
