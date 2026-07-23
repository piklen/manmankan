"""`kan status` · 本地数据状态一览(纯本地 · 零网络)。

散户价值:数据可不可信一眼看清 — 缓存多少只、新不新、凭证配没配、
数据源有没有被熔断。全部读本地状态,不做任何网络探测(本地优先原则:
状态页自己绝不能变成新的故障点)。
"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.app import app
from kan.storage import export

_STATUS_SCHEMA_VERSION = "0.1"


def _collect_status() -> dict:
    """汇总本地状态 · 所有读取 fail-open(单项失败记 error 字段,不拖垮整页)。"""
    from datetime import datetime

    from kan.core.pipeline import freshness_of
    from kan.infra.circuit_breaker import DOWN_TTL, CircuitBreaker
    from kan.storage import config, watchlist
    from kan.storage.paths import (
        BASE_DIR,
        CIRCUIT_PATH,
        DATA_DIR,
        SNAPSHOTS_DIR,
        STOCK_NAMES_CACHE,
    )
    from kan.storage.positions import load_positions

    _sentinel = object()

    def _safe(fn, default=_sentinel):
        try:
            return fn()
        except Exception as e:  # 状态页 fail-open
            if default is _sentinel:
                return {"error": f"{type(e).__name__}: {e}"}
            return default

    # K 线缓存:parquet 文件名即代码 · 排除 chip_* 等非股票缓存文件
    symbols = sorted(
        p.stem
        for p in DATA_DIR.glob("*.parquet")
        if len(p.stem) == 6 and p.stem.isdigit()
    )
    freshness = _safe(lambda: freshness_of(symbols), default=None)

    stock_names = _safe(
        lambda: {
            "count": len(watchlist.load_stock_names_cache(allow_stale=True) or {}),
            "mtime": (
                datetime.fromtimestamp(STOCK_NAMES_CACHE.stat().st_mtime).isoformat(
                    timespec="seconds"
                )
                if STOCK_NAMES_CACHE.exists() else None
            ),
        }
    )

    cfg = config.load()
    token = str(cfg.get("tushare_token") or "").strip()

    circuit = CircuitBreaker(CIRCUIT_PATH)
    down_sources = _safe(
        lambda: sorted(
            s for s in ("baostock", "sina", "eastmoney", "tencent") if circuit.is_down(s)
        ),
        default=[],
    )

    disk_bytes = _safe(
        lambda: sum(f.stat().st_size for f in BASE_DIR.rglob("*") if f.is_file()),
        default=0,
    )

    wl_count = _safe(lambda: len(watchlist.load_watchlist().stocks), default=0)
    book = _safe(load_positions, default=None)

    snapshots = len(list(SNAPSHOTS_DIR.glob("*.json"))) if SNAPSHOTS_DIR.exists() else 0

    return {
        "data_dir": str(BASE_DIR),
        "disk_bytes": disk_bytes if isinstance(disk_bytes, int) else 0,
        "kline_cached_count": len(symbols),
        "freshness": (
            {
                "data_cutoff": (
                    freshness.data_cutoff.isoformat() if freshness.data_cutoff else None
                ),
                "expected_cutoff": freshness.expected_cutoff.isoformat(),
                "is_stale": freshness.is_stale,
                "current_count": freshness.current_count,
                "target_count": freshness.target_count,
            }
            if freshness is not None and not isinstance(freshness, dict)
            else freshness
        ),
        "snapshots_days": snapshots,
        "stock_names": stock_names,
        "watchlist_count": wl_count if isinstance(wl_count, int) else 0,
        "holding_count": len(book.positions) if book is not None else 0,
        "cash_configured": bool(book is not None and book.cash > 0),
        "tushare": {
            "token_configured": bool(token),
            "token_masked": config.mask_token(token) if token else None,
            "endpoint": cfg.get("tushare_endpoint") or None,
        },
        "circuit_down_sources": down_sources,
        "circuit_down_ttl_seconds": int(DOWN_TTL.total_seconds()),
    }


@app.command()
def status(
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """本地数据状态一览（缓存 / 新鲜度 / 凭证 / 熔断 · 纯本地不联网）。"""
    import kan
    from kan.cli.helpers import format_date_compact

    s = _collect_status()
    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json({
            "ok": True,
            "schema_version": _STATUS_SCHEMA_VERSION,
            "command": "status",
            "version": kan.__version__,
            **s,
        }))
        return

    from rich.console import Console

    console = Console()
    console.print(f"\n[bold]慢慢看 · 本地数据状态[/bold] · v{kan.__version__}")
    console.print(f"  数据目录 [cyan]{s['data_dir']}[/cyan] · 占用 {_fmt_bytes(s['disk_bytes'])}")
    freshness = s["freshness"]
    if isinstance(freshness, dict) and freshness.get("data_cutoff"):
        from datetime import date as _date

        cutoff = format_date_compact(_date.fromisoformat(freshness["data_cutoff"]))
        stale_note = ""
        if freshness["is_stale"]:
            lag = freshness["target_count"] - freshness["current_count"]
            stale_note = f" · [yellow]{lag}/{freshness['target_count']} 只滞后[/yellow]"
        console.print(
            f"  K线缓存 [bold]{s['kline_cached_count']}[/bold] 只 · "
            f"最新截止 [cyan]{cutoff}[/cyan]{stale_note}"
        )
    else:
        console.print(f"  K线缓存 [bold]{s['kline_cached_count']}[/bold] 只 · [dim]无有效截止日[/dim]")
    names = s["stock_names"]
    if isinstance(names, dict) and "count" in names:
        console.print(f"  代码表 {names['count']} 只 · 快照 {s['snapshots_days']} 天")
    console.print(
        f"  自选 {s['watchlist_count']} 只 · 持仓 {s['holding_count']} 只 · "
        f"现金 {'已配置' if s['cash_configured'] else '未配置'}"
    )
    tushare = s["tushare"]
    if tushare["token_configured"]:
        endpoint = tushare["endpoint"] or "官方默认"
        console.print(f"  tushare 凭证 [green]已配置[/green]（{tushare['token_masked']}）· endpoint {endpoint}")
    else:
        console.print("  tushare 凭证 [yellow]未配置[/yellow] · 全市场截面/估值维度不可用 · kan config set tushare-token <YOUR_TOKEN>")
    if s["circuit_down_sources"]:
        console.print(f"  数据源熔断中: [yellow]{', '.join(s['circuit_down_sources'])}[/yellow] · 5 分钟内自动重试")
    else:
        console.print("  数据源熔断器 [green]正常[/green]（baostock / sina / eastmoney / tencent 均可探测）")
    console.print()


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"
