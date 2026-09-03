"""range · 单股或明确代码池的历史日内上下行范围。"""

from __future__ import annotations

import re
from enum import StrEnum
from math import isfinite
from typing import Annotated, NoReturn, TypedDict

import typer

from kan.app import app
from kan.cli.helpers import _print_err, _safe_error_msg
from kan.storage import export

DEFAULT_RANGE_PERIODS = (5, 15)
DEFAULT_RANGE_LEVELS = (75.0, 85.0, 90.0, 95.0)
MAX_RANGE_CODES = 20


class RangeOutputFormat(StrEnum):
    """range 只开放人读终端与稳定 JSON 两个出口。"""

    terminal = "terminal"
    json = "json"


class _RangeErrorDetail(TypedDict):
    code: str
    message: str
    hint: str | None
    exit_code: int


class RangeBatchFailure(TypedDict):
    symbol: str
    error: _RangeErrorDetail


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
    if not isfinite(number) or number < 0 or number > maximum:
        _exit_range_error(
            fmt,
            code=f"invalid_{flag.removeprefix('--')}",
            message=f"{flag} 必须是大于等于 0 且不超过 {maximum:g} 的百分比",
            hint=f"例: kan range 600519 {flag} 3",
            exit_code=2,
        )
    return number


def _parse_range_codes(raw: str, fmt: RangeOutputFormat) -> tuple[str, ...]:
    """解析明确的批量代码池；重复代码是输入错误，不静默去重。"""

    text = raw.strip()
    if not text:
        _exit_range_error(
            fmt,
            code="empty_codes",
            message="--codes 不能为空",
            hint="例: kan range --codes 600519,000858",
            exit_code=2,
        )
    prefix_re = re.compile(r"^(SH|SZ|BJ)[.:]?", re.I)
    suffix_re = re.compile(r"[.:]?(SH|SZ|BJ)$", re.I)
    codes: list[str] = []
    invalid: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,，;；]+", text):
        if not token:
            continue
        code = prefix_re.sub("", token.strip())
        code = suffix_re.sub("", code)
        if not re.fullmatch(r"\d{6}", code):
            invalid.append(token)
            continue
        if code in seen:
            duplicates.append(code)
            continue
        seen.add(code)
        codes.append(code)
    if invalid:
        _exit_range_error(
            fmt,
            code="invalid_codes",
            message=f"--codes 含非法代码: {', '.join(invalid[:5])}",
            hint="只接受逗号分隔的 6 位 A 股代码",
            exit_code=2,
        )
    if duplicates:
        _exit_range_error(
            fmt,
            code="duplicate_codes",
            message=f"--codes 含重复代码: {', '.join(dict.fromkeys(duplicates))}",
            hint="每只股票只保留一次后重试",
            exit_code=2,
        )
    if not codes:
        _exit_range_error(
            fmt,
            code="empty_codes",
            message="--codes 不能为空",
            hint="例: kan range --codes 600519,000858",
            exit_code=2,
        )
    if len(codes) > MAX_RANGE_CODES:
        _exit_range_error(
            fmt,
            code="too_many_codes",
            message=f"--codes 最多接受 {MAX_RANGE_CODES} 只股票，当前 {len(codes)} 只",
            hint="拆成多个批次后重试",
            exit_code=2,
        )
    return tuple(codes)


def _batch_failure(
    symbol: str,
    *,
    code: str,
    message: str,
    hint: str | None,
    exit_code: int,
) -> RangeBatchFailure:
    return {
        "symbol": symbol,
        "error": {
            "code": code,
            "message": message,
            "hint": hint,
            "exit_code": exit_code,
        },
    }


@app.command(name="range")
def range_command(
    symbol: Annotated[
        str | None,
        typer.Argument(help="单只股票代码或名称（如 600519 / 茅台）"),
    ] = None,
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="批量股票代码，逗号分隔（最多 20 只）"),
    ] = None,
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
        typer.Option("--down", help="复核下探幅度（非负，如 0/3）"),
    ] = None,
    up: Annotated[
        str | None,
        typer.Option("--up", help="复核上冲幅度（非负，如 0/7）"),
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
    """查看单股或明确代码池的历史日内范围与触及后收盘事实。"""

    parsed_periods = _parse_periods(periods, fmt)
    parsed_levels = _parse_levels(levels, fmt)
    parsed_down = _validate_threshold(down, flag="--down", maximum=100, fmt=fmt)
    parsed_up = _validate_threshold(up, flag="--up", maximum=1000, fmt=fmt)
    if (symbol is None) == (codes is None):
        _exit_range_error(
            fmt,
            code="invalid_target",
            message="请在单只股票参数与 --codes 之间选择一种",
            hint="例: kan range 600519；或 kan range --codes 600519,000858",
            exit_code=2,
        )

    from kan.infra.lifecycle import operation
    from kan.infra.progress import operation_reporter
    from kan.service.stock_range_service import (
        StockRangeRequest,
        StockRangeServiceError,
        study_stock_range,
    )

    if symbol is not None:
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
        return

    batch_codes = _parse_range_codes(codes or "", fmt)
    studies = []
    failures: list[RangeBatchFailure] = []
    with operation("批量日内范围复核", reporter=operation_reporter()) as lifecycle:
        for index, code in enumerate(batch_codes, start=1):
            lifecycle.phase(f"读取 {index}/{len(batch_codes)} · {code} 完整日 K")
            try:
                studies.append(study_stock_range(StockRangeRequest(
                    symbol=code,
                    periods=parsed_periods,
                    levels=parsed_levels,
                    down_pct=parsed_down,
                    up_pct=parsed_up,
                    force=force,
                )))
            except StockRangeServiceError as exc:
                failures.append(_batch_failure(
                    code,
                    code=exc.code,
                    message=exc.message,
                    hint=exc.hint,
                    exit_code=exc.exit_code,
                ))
            except ValueError as exc:
                failures.append(_batch_failure(
                    code,
                    code="invalid_request",
                    message=str(exc),
                    hint="检查批量代码和查询参数后重试",
                    exit_code=2,
                ))
            except Exception as exc:
                failures.append(_batch_failure(
                    code,
                    code="data_unavailable",
                    message=f"日 K 数据暂不可用：{_safe_error_msg(exc)}",
                    hint="可重试，或加 --force 重新拉取",
                    exit_code=1,
                ))
        lifecycle.phase("准备批量输出")

    partial = bool(studies and failures)
    if fmt is RangeOutputFormat.json:
        payload = export.success_envelope(
            "range",
            stats={
                "requested": len(batch_codes),
                "succeeded": len(studies),
                "failed": len(failures),
                "windows": sum(len(study.windows) for study in studies),
            },
        )
        payload.update({
            "ok": not failures,
            "partial": partial,
            "studies": [study.model_dump(mode="json") for study in studies],
            "errors": failures,
        })
        if failures:
            error_code = "batch_partial" if partial else "batch_failed"
            message = (
                f"{len(failures)} 只股票未取得日内范围，"
                f"已保留 {len(studies)} 只成功结果"
                if partial
                else f"{len(failures)} 只股票均未取得日内范围"
            )
            payload["error"] = export.error_payload(
                "range",
                code=error_code,
                message=message,
                hint="查看 errors 获取逐股失败原因",
            )["error"]
        typer.echo(export.to_json(payload))
    else:
        from rich.console import Console

        from kan.render.terminal_range import render_stock_range_batch

        render_stock_range_batch(
            Console(),
            studies,
            failures=[
                (failure["symbol"], failure["error"]["message"])
                for failure in failures
            ],
        )
    if failures:
        raise typer.Exit(max(
            failure["error"]["exit_code"]
            for failure in failures
        ))


__all__ = [
    "DEFAULT_RANGE_LEVELS",
    "DEFAULT_RANGE_PERIODS",
    "MAX_RANGE_CODES",
    "RangeOutputFormat",
    "range_command",
]
