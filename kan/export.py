"""非终端输出格式 · markdown / json 导出。

终端渲染仍在 cli_*_cmds.py 内联 + kan/render.py;本模块只管 --format md|json
两条新输出路径,不碰终端代码(零回归风险)。数据模型(kan/models.py 的
StockScanResult / PeriodResult,Pydantic)已存在,这里只做序列化与表格化。
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from kan.models import PeriodResult, StockScanResult
    from kan.scanner import TrendResult


class OutputFormat(StrEnum):
    """--format 选项 · terminal 默认(现有行为) · md/json 为导出。"""

    terminal = "terminal"
    md = "md"
    json = "json"


def to_json(payload: dict) -> str:
    """统一 json 序列化 · 中文不转义 · 缩进 2。"""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """GitHub-flavored markdown 表格。"""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _disclaimer_quote() -> str:
    """免责声明 → markdown 引用块。"""
    from kan.render import DISCLAIMER

    return "> " + DISCLAIMER.strip()


# ── scan ──────────────────────────────────────────────────────────────

def _pct_cell(pr: PeriodResult, *, decimals: int = 0) -> str:
    """位置百分比 → md 单元格 · 触及极值保留方括号语义(无颜色)。"""
    if pr.insufficient:
        return "-"
    text = f"{pr.position_pct:.{decimals}f}%"
    return f"[{text}]" if (pr.at_low or pr.at_high) else text


def scan_payload(
    results: list[StockScanResult],
    *,
    mode: str,
    data_cutoff: date | None,
    fetched_at: str | None,
    stale: bool,
) -> dict:
    """kan scan --format json 的结构化 payload。"""
    return {
        "command": "scan",
        "mode": mode,
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "fetched_at": fetched_at or None,
        "stale": stale,
        "results": [r.model_dump(mode="json") for r in results],
    }


def scan_markdown(
    results: list[StockScanResult],
    *,
    periods: list[int],
    mode: str,
    title: str,
) -> str:
    """kan scan --format md · 全周期(导出不做终端宽度裁剪)。"""
    headers = ["股票", "现价", *[f"{p}日" for p in periods], "共振"]
    rows: list[list[str]] = []
    for r in results:
        name_short = r.name.replace(" ", "")
        tag = " 涨停" if r.limit_up else (" 跌停" if r.limit_down else "")
        cells = [f"{name_short} {r.symbol}{tag}", f"{r.current_price:.2f}"]
        for p in periods:
            pr = next((x for x in r.periods if x.period == p), None)
            cells.append("-" if pr is None else _pct_cell(pr))
        resonance = r.high_resonance if mode == "high" else r.low_resonance
        cells.append(f"×{resonance}" if resonance else "")
        rows.append(cells)
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"


# ── low / high ────────────────────────────────────────────────────────

def extreme_payload(results_by_period: dict[int, list], *, mode: str) -> dict:
    """kan low / high --format json 的结构化 payload。"""
    return {
        "command": mode,  # "low" / "high"
        "results_by_period": {
            str(n): [r.model_dump(mode="json") for r, _ in hits]
            for n, hits in results_by_period.items()
        },
    }


def extreme_markdown(results_by_period: dict[int, list], *, mode: str) -> str:
    """kan low / high --format md · 每周期一张表。"""
    label = "低点" if mode == "low" else "高点"
    parts = [f"# 慢慢看 · {label}筛选"]
    for n, hits in results_by_period.items():
        headers = ["股票", "现价", f"{n}日最低", f"{n}日最高", "位置"]
        rows = [
            [
                f"{r.name.replace(' ', '')} {r.symbol}",
                f"{r.current_price:.2f}",
                f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}",
                f"[{pr.position_pct:.1f}%]",
            ]
            for r, pr in hits
        ]
        parts.append(
            f"## {n} 日{label} · {len(hits)} 只触及\n\n{md_table(headers, rows)}"
        )
    parts.append(_disclaimer_quote())
    return "\n\n".join(parts)


# ── info ──────────────────────────────────────────────────────────────

def info_payload(
    result: StockScanResult,
    trend: TrendResult,
    *,
    data_cutoff: date | None,
    fetched_at: str | None,
    stale: bool,
) -> dict:
    """kan info --format json 的结构化 payload。"""
    return {
        "command": "info",
        "symbol": result.symbol,
        "name": result.name,
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "fetched_at": fetched_at or None,
        "stale": stale,
        "result": result.model_dump(mode="json"),
        "trend": {
            "streak": trend.streak,
            "streak_pct": trend.streak_pct,
            "direction": trend.direction,
        },
    }


def info_markdown(result: StockScanResult, trend: TrendResult, *, title: str) -> str:
    """kan info --format md · 标题 + 全周期位置表。"""
    tags = []
    if result.is_st:
        tags.append("ST")
    if result.limit_up:
        tags.append("涨停")
    elif result.limit_down:
        tags.append("跌停")
    tag_str = (" · " + " ".join(tags)) if tags else ""
    headers = ["周期", "最低", "最高", "位置"]
    rows: list[list[str]] = []
    for pr in result.periods:
        if pr.insufficient:
            rows.append([f"{pr.period}日", "-", "-", "-"])
        else:
            rows.append([
                f"{pr.period}日",
                f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}",
                _pct_cell(pr),
            ])
    return "\n\n".join([
        f"# {title}{tag_str}",
        f"现价 {result.current_price:.2f} · {trend.direction} · "
        f"累计 {abs(trend.streak_pct):.2f}%",
        md_table(headers, rows),
        f"低点共振 ×{result.low_resonance} · 高点共振 ×{result.high_resonance}",
        _disclaimer_quote(),
    ])
