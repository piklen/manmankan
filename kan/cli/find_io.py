"""`kan find` CLI 输入解析和错误出口。"""
from __future__ import annotations

import typer

from kan.cli.helpers import _parse_codes, _print_err
from kan.service.find_service import FindServiceError
from kan.storage import export


def _resolve_code_pairs_or_exit_json(
    raw: str,
    fmt: export.OutputFormat,
) -> list[tuple[str, str]]:
    """解析 `kan find --codes`，并在 json 模式保持错误 envelope。"""
    import sys

    from kan.infra.log import debug_log

    text = sys.stdin.read() if raw == "-" else raw
    codes, invalid = _parse_codes(text)
    if invalid:
        preview = ", ".join(invalid[:5])
        suffix = "..." if len(invalid) > 5 else ""
        _exit_find_error(
            fmt,
            code="invalid_codes",
            message=f"--codes 含非法代码: {preview}{suffix} · 需 6 位 A 股代码",
            hint="例: kan find --codes 600519,000858 --pos 180:lt:20",
            exit_code=2,
        )
    if not codes:
        _exit_find_error(
            fmt,
            code="empty_codes",
            message="--codes 为空",
            hint="例: kan find --codes 600519,000858 --pos 180:lt:20",
            exit_code=2,
        )
    try:
        from kan.storage.watchlist import load_stock_names_cache

        names = load_stock_names_cache(allow_stale=True) or {}
    except Exception as e:
        debug_log(__name__, "load cached stock names for find --codes", e)
        names = {}
    return [(code, names.get(code, code)) for code in codes]


def _exit_find_error(
    fmt: export.OutputFormat,
    *,
    code: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 1,
) -> None:
    """find 专用错误出口 · json 模式输出机器可读 envelope。"""
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.error_payload(
            "find",
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


def _exit_find_service_error(fmt: export.OutputFormat, error: FindServiceError) -> None:
    _exit_find_error(
        fmt,
        code=error.code,
        message=error.message,
        hint=error.hint,
        exit_code=error.exit_code,
    )
