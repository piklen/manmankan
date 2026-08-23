"""trend / theme trend / compare 导出实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kan.storage.export_base import (
    _disclaimer_quote,
    _disclaimer_text,
    md_table,
    success_envelope,
)
from kan.storage.export_scan import _pct_cell

if TYPE_CHECKING:
    from datetime import date

    from kan.core.models import StockScanResult
    from kan.core.scanner import TrendResult

def _trend_dict(tr: TrendResult) -> dict:
    return {
        "symbol": tr.symbol,
        "name": tr.name,
        "current_price": tr.current_price,
        "streak": tr.streak,
        "streak_pct": tr.streak_pct,
        "direction": tr.direction,
        "daily_changes": [[d, c] for d, c in tr.daily_changes],
    }


def trend_payload(
    results: list[TrendResult],
    *,
    candle: bool,
    data_cutoff: date | None,
    fetched_at: str | None,
    stale: bool,
) -> dict:
    """kan trend --format json 的结构化 payload。"""
    return {
        "ok": True,
        "schema_version": 1,
        "command": "trend",
        "mode": "candle" if candle else "close",
        "disclaimer": _disclaimer_text(),
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "fetched_at": fetched_at or None,
        "stale": stale,
        "results": [_trend_dict(r) for r in results],
    }


def theme_leaderboard_payload(
    results: list[TrendResult],
    *,
    candle: bool,
    total_themes: int,
    errors_count: int,
    data_cutoff: date | None,
    fetched_at: str | None,
) -> dict:
    """kan theme trend --format json · 题材榜结构化输出。"""
    return {
        "command": "theme_trend",
        "mode": "candle" if candle else "close",
        "disclaimer": _disclaimer_text(),
        "total_themes": total_themes,
        "shown": len(results),
        "errors_count": errors_count,
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "fetched_at": fetched_at or None,
        "results": [
            {
                **_trend_dict(r),
                "rank": idx,
                "moneyflow_net": getattr(r, "moneyflow_net", None),
            }
            for idx, r in enumerate(results, start=1)
        ],
    }


def board_trend_payload(
    results: list[TrendResult],
    *,
    kind: str,
    level: int | None,
    candle: bool,
    total_boards: int,
    errors_count: int,
    source: str,
    data_cutoff: str | None,
    sort_by: str,
    up: int | None,
    down: int | None,
    min_streak: int | None,
) -> dict:
    """kan board trend --format json 的统一行业 / 题材输出。"""
    data_cutoffs = [
        result.daily_changes[0][0]
        for result in results
        if result.daily_changes
    ]
    payload = success_envelope(
        "board_trend",
        disclaimer=_disclaimer_text(),
        stats={
            "total": total_boards,
            "shown": len(results),
            "errors_count": errors_count,
        },
        data_availability={
            "basis": "board_index_kline",
            "source": source,
            "partial": errors_count > 0,
        },
    )
    payload.update({
        "kind": kind,
        "level": level,
        "mode": "candle" if candle else "close",
        "sort": sort_by,
        "filters": {
            "up": up,
            "down": down,
            "min_streak": min_streak,
        },
        "source": source,
        "data_cutoff": data_cutoff or (max(data_cutoffs) if data_cutoffs else None),
        "results": [
            {
                **_trend_dict(result),
                "rank": idx,
                "kind": kind,
                "code": result.symbol,
                "moneyflow_net": getattr(result, "moneyflow_net", None),
            }
            for idx, result in enumerate(results, start=1)
        ],
    })
    return payload


def board_trend_markdown(
    results: list[TrendResult],
    *,
    title: str,
    latest: int | None,
    entity_label: str,
) -> str:
    """kan board trend --format md · 行业 / 题材趋势榜。"""
    headers = ["排名", entity_label, "代码", "现价", "连续", "累计"]
    show_moneyflow = any(getattr(r, "moneyflow_net", None) is not None for r in results)
    if show_moneyflow:
        headers.append("主力净额(万)")
    n_dates = 0
    if latest and results:
        n_dates = min(latest, len(results[0].daily_changes))
        headers += [d[-5:] for d, _ in results[0].daily_changes[:n_dates]]
    rows: list[list[str]] = []
    for idx, result in enumerate(results, start=1):
        cells = [
            str(idx),
            result.name.replace(" ", ""),
            result.symbol,
            f"{result.current_price:.2f}",
            result.direction,
            f"{abs(result.streak_pct):.2f}%",
        ]
        if show_moneyflow:
            moneyflow = getattr(result, "moneyflow_net", None)
            cells.append(f"{moneyflow:,.0f}" if moneyflow is not None else "—")
        if n_dates:
            for _, change in result.daily_changes[:n_dates]:
                if change > 0:
                    cells.append(f"+{change:.2f}%")
                elif change < 0:
                    cells.append(f"{change:.2f}%")
                else:
                    cells.append("—")
            while len(cells) < len(headers):
                cells.append("-")
        rows.append(cells)
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"


def board_trend_csv(
    results: list[TrendResult],
    *,
    latest: int | None,
    entity_label: str,
) -> str:
    """kan board trend --format csv · Excel 兼容(BOM 头)。"""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["排名", entity_label, "代码", "现价", "连续", "累计%"]
    n_dates = 0
    if latest and results:
        n_dates = min(latest, len(results[0].daily_changes))
        headers += [d[-5:] for d, _ in results[0].daily_changes[:n_dates]]
    writer.writerow(headers)
    for idx, result in enumerate(results, start=1):
        cells = [
            str(idx),
            result.name.replace(" ", ""),
            result.symbol,
            f"{result.current_price:.2f}",
            result.direction,
            f"{abs(result.streak_pct):.2f}",
        ]
        if n_dates:
            cells.extend(f"{change:.2f}" for _, change in result.daily_changes[:n_dates])
            while len(cells) < len(headers):
                cells.append("")
        writer.writerow(cells)
    return "\ufeff" + output.getvalue()


def theme_leaderboard_markdown(
    results: list[TrendResult], *, title: str, latest: int | None,
) -> str:
    """kan theme trend --format md · 题材榜 · 排名列 + 可选近 N 天明细。"""
    headers = ["排名", "题材", "现价", "连续", "累计"]
    show_moneyflow = any(getattr(r, "moneyflow_net", None) is not None for r in results)
    if show_moneyflow:
        headers.append("主力净额(万)")
    n_dates = 0
    if latest and results:
        n_dates = min(latest, len(results[0].daily_changes))
        headers += [d[-5:] for d, _ in results[0].daily_changes[:n_dates]]
    rows: list[list[str]] = []
    for idx, r in enumerate(results, start=1):
        cells = [
            str(idx),
            r.name.replace(" ", ""),
            f"{r.current_price:.2f}",
            r.direction,
            f"{abs(r.streak_pct):.2f}%",
        ]
        if show_moneyflow:
            mf = getattr(r, "moneyflow_net", None)
            cells.append(f"{mf:,.0f}" if mf is not None else "—")
        if n_dates:
            for _, chg in r.daily_changes[:n_dates]:
                if chg > 0:
                    cells.append(f"+{chg:.2f}%")
                elif chg < 0:
                    cells.append(f"{chg:.2f}%")
                else:
                    cells.append("—")
            while len(cells) < len(headers):
                cells.append("-")
        rows.append(cells)
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"


def trend_markdown(
    results: list[TrendResult], *, title: str, latest: int | None,
) -> str:
    """kan trend --format md · 连续涨跌表 · --latest 时含日明细列。"""
    headers = ["股票", "现价", "连续", "累计"]
    n_dates = 0
    if latest and results:
        n_dates = min(latest, len(results[0].daily_changes))
        headers += [d[-5:] for d, _ in results[0].daily_changes[:n_dates]]
    rows: list[list[str]] = []
    for r in results:
        cells = [
            f"{r.name.replace(' ', '')} {r.symbol}",
            f"{r.current_price:.2f}",
            r.direction,
            f"{abs(r.streak_pct):.2f}%",
        ]
        if n_dates:
            for _, chg in r.daily_changes[:n_dates]:
                if chg > 0:
                    cells.append(f"+{chg:.2f}%")
                elif chg < 0:
                    cells.append(f"{chg:.2f}%")
                else:
                    cells.append("—")
            while len(cells) < len(headers):
                cells.append("-")
        rows.append(cells)
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"


def trend_csv(
    results: list[TrendResult], *, latest: int | None,
) -> str:
    """kan trend --format csv · Excel 兼容(BOM 头)。"""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["股票", "代码", "现价", "连续", "累计%"]
    n_dates = 0
    if latest and results:
        n_dates = min(latest, len(results[0].daily_changes))
        headers += [d[-5:] for d, _ in results[0].daily_changes[:n_dates]]
    writer.writerow(headers)
    for r in results:
        cells = [
            r.name.replace(" ", ""),
            r.symbol,
            f"{r.current_price:.2f}",
            r.direction,
            f"{abs(r.streak_pct):.2f}",
        ]
        if n_dates:
            for _, chg in r.daily_changes[:n_dates]:
                cells.append(f"{chg:.2f}")
            while len(cells) < len(headers):
                cells.append("")
        writer.writerow(cells)
    return "\ufeff" + output.getvalue()


# ── compare ───────────────────────────────────────────────────────────

def compare_payload(results: list[StockScanResult], *, periods: list[int]) -> dict:
    """kan compare --format json 的结构化 payload。"""
    return {
        "ok": True,
        "schema_version": 1,
        "command": "compare",
        "periods": periods,
        "disclaimer": _disclaimer_text(),
        "results": [r.model_dump(mode="json") for r in results],
    }


def compare_markdown(results: list[StockScanResult], *, periods: list[int]) -> str:
    """kan compare --format md · 转置表(指标为行 · 个股为列)。"""
    headers = ["指标", *[f"{r.name.replace(' ', '')} {r.symbol}" for r in results]]
    rows: list[list[str]] = [["现价", *[f"{r.current_price:.2f}" for r in results]]]
    for p in periods:
        cells = [f"{p}日位置"]
        for r in results:
            pr = next((x for x in r.periods if x.period == p), None)
            cells.append("-" if pr is None else _pct_cell(pr))
        rows.append(cells)
    rows.append(["低点共振", *[f"×{r.low_resonance}" for r in results]])
    rows.append(["高点共振", *[f"×{r.high_resonance}" for r in results]])
    rows.append(["ST", *["是" if r.is_st else "—" for r in results]])
    rows.append([
        "涨跌停",
        *[
            "涨停" if r.limit_up else ("跌停" if r.limit_down else "—")
            for r in results
        ],
    ])
    rows.append(["数据截止", *[r.scan_date.isoformat() for r in results]])
    return f"# 慢慢看 · 多股对比\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"


def compare_csv(results: list[StockScanResult], *, periods: list[int]) -> str:
    """kan compare --format csv · Excel 兼容(BOM 头)。"""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["指标", *[r.symbol for r in results]]
    writer.writerow(headers)
    writer.writerow(["股票", *[r.name.replace(" ", "") for r in results]])
    writer.writerow(["现价", *[f"{r.current_price:.2f}" for r in results]])
    for p in periods:
        cells = [f"{p}日位置%"]
        for r in results:
            pr = next((x for x in r.periods if x.period == p), None)
            cells.append("-" if pr is None else f"{pr.position_pct:.1f}")
        writer.writerow(cells)
    writer.writerow(["低点共振", *[str(r.low_resonance) for r in results]])
    writer.writerow(["高点共振", *[str(r.high_resonance) for r in results]])
    writer.writerow(["ST", *["是" if r.is_st else "否" for r in results]])
    writer.writerow([
        "涨跌停",
        *[
            "涨停" if r.limit_up else ("跌停" if r.limit_down else "—")
            for r in results
        ],
    ])
    writer.writerow(["数据截止", *[r.scan_date.isoformat() for r in results]])
    return "\ufeff" + output.getvalue()
