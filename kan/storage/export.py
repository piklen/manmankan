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

    from kan.core.models import (
        BoardMeta,
        HotMeta,
        PeriodResult,
        StockScanResult,
        ThemeMeta,
        VolumeState,
    )
    from kan.core.scanner import TrendResult


def _board_reference_kind(meta: BoardMeta | HotMeta | ThemeMeta | None) -> str:
    """meta 类型对应的 reference kind 标识 · md / json 共用。"""
    from kan.core.scan_targets import ThemeMeta

    return "theme" if isinstance(meta, ThemeMeta) else "industry"


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
    from kan.render.base import DISCLAIMER

    return "> " + DISCLAIMER.strip()


# ── scan ──────────────────────────────────────────────────────────────

def _pct_cell(
    pr: PeriodResult, *, decimals: int = 0, mode: str | None = None
) -> str:
    """位置百分比 → md 单元格 · 触及极值保留方括号语义(无颜色)。

    mode="high" → 只 at_high 加 [%] · mode="low" → 只 at_low 加 [%]。
    mode=None (info / compare 等双模显示) → 沿用旧行为(任一极值都 mark)。
    """
    if pr.insufficient:
        return "-"
    text = f"{pr.position_pct:.{decimals}f}%"
    if mode == "high":
        return f"[{text}]" if pr.at_high else text
    if mode == "low":
        return f"[{text}]" if pr.at_low else text
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
            cells.append("-" if pr is None else _pct_cell(pr, mode=mode))
        resonance = r.high_resonance if mode == "high" else r.low_resonance
        cells.append(f"×{resonance}" if resonance else "")
        rows.append(cells)
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"


# ── low / high ────────────────────────────────────────────────────────

def extreme_payload(
    results_by_period: dict[int, list],
    *,
    mode: str,
    board_index_result: StockScanResult | None = None,
    board_meta: BoardMeta | HotMeta | ThemeMeta | None = None,
) -> dict:
    """kan low / high --format json 的结构化 payload。

    industry / theme 模式带 board_index_result 时 payload 顶层增加 `reference`
    字段(板块 / 题材指数 K 线 scan 结果 + kind 标识)· 用户脚本侧可直接读
    `payload['reference']['periods']` 跟成分股 hits 对照。
    """
    payload: dict = {
        "command": mode,  # "low" / "high"
        "results_by_period": {
            str(n): [r.model_dump(mode="json") for r, _ in hits]
            for n, hits in results_by_period.items()
        },
    }
    if board_index_result is not None:
        payload["reference"] = {
            "kind": _board_reference_kind(board_meta),
            **board_index_result.model_dump(mode="json"),
        }
    return payload


def _extreme_reference_row(
    board_index_result: StockScanResult,
    board_meta: BoardMeta | HotMeta | ThemeMeta | None,
    period: int,
) -> list[str] | None:
    """构造单周期 md 表格的 reference 首行 · period 不在 board.periods 时返回 None。"""
    from kan.core.scan_targets import ThemeMeta

    board_pr = next(
        (p for p in board_index_result.periods if p.period == period), None,
    )
    if board_pr is None or board_pr.insufficient:
        return None
    if isinstance(board_meta, ThemeMeta):
        label = f"🎯 {board_index_result.name} 题材指数"
    else:
        label = f"🏛️ {board_index_result.name} 板块指数"
    return [
        label,
        f"{board_index_result.current_price:.2f}",
        f"{board_pr.n_low:.2f}",
        f"{board_pr.n_high:.2f}",
        f"{board_pr.position_pct:.1f}%",
    ]


def extreme_markdown(
    results_by_period: dict[int, list],
    *,
    mode: str,
    board_index_result: StockScanResult | None = None,
    board_meta: BoardMeta | HotMeta | ThemeMeta | None = None,
    periods: list[int] | None = None,
) -> str:
    """kan low / high --format md · 每周期一张表。

    industry / theme 模式带 board_index_result 时 · 每张表首行注入板块 /
    题材指数 reference (跟终端 reference 行视觉对齐 · 阅读器侧也能直接看到
    「板块整体当前位置」对照)。

    `periods`:caller 原始周期 list · 用于空 hits 仍画 reference 表(与终端
    行为一致)。None 时退化到 results_by_period.keys() · 跟 v0.0.5.x 一致。
    """
    label = "低点" if mode == "low" else "高点"
    parts = [f"# 慢慢看 · {label}筛选"]
    target_periods = periods if periods is not None else list(results_by_period.keys())
    for n in target_periods:
        hits = results_by_period.get(n, [])
        headers = ["股票", "现价", f"{n}日最低", f"{n}日最高", "位置"]
        rows: list[list[str]] = []
        if board_index_result is not None:
            ref = _extreme_reference_row(board_index_result, board_meta, n)
            if ref is not None:
                rows.append(ref)
        rows += [
            [
                f"{r.name.replace(' ', '')} {r.symbol}",
                f"{r.current_price:.2f}",
                f"{pr.n_low:.2f}",
                f"{pr.n_high:.2f}",
                f"[{pr.position_pct:.1f}%]",
            ]
            for r, pr in hits
        ]
        if not rows:  # 既无 reference 也无 hits · 跳过该周期(不画空表)
            continue
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
    volume: VolumeState | None,
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
        "volume": volume.model_dump() if volume else None,
    }


def info_markdown(
    result: StockScanResult,
    trend: TrendResult,
    *,
    volume: VolumeState | None,
    title: str,
) -> str:
    """kan info --format md · 标题 + 全周期位置表 + 成交量状态。"""
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
    sections = [
        f"# {title}{tag_str}",
        f"现价 {result.current_price:.2f} · {trend.direction} · "
        f"累计 {abs(trend.streak_pct):.2f}%",
        md_table(headers, rows),
        f"低点共振 ×{result.low_resonance} · 高点共振 ×{result.high_resonance}",
    ]
    if volume is not None:
        sections.append(
            f"成交量 · 今日是近 {volume.window} 日均量的 "
            f"{volume.ratio} 倍 · {volume.label}"
        )
    sections.append(_disclaimer_quote())
    return "\n\n".join(sections)


# ── trend ─────────────────────────────────────────────────────────────

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
        "command": "trend",
        "mode": "candle" if candle else "close",
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
    """kan theme trend --format json · 题材榜结构化输出 · v0.0.5.7。"""
    return {
        "command": "theme_trend",
        "mode": "candle" if candle else "close",
        "total_themes": total_themes,
        "shown": len(results),
        "errors_count": errors_count,
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "fetched_at": fetched_at or None,
        "results": [
            {**_trend_dict(r), "rank": idx}
            for idx, r in enumerate(results, start=1)
        ],
    }


def theme_leaderboard_markdown(
    results: list[TrendResult], *, title: str, latest: int | None,
) -> str:
    """kan theme trend --format md · 题材榜 · 排名列 + 可选近 N 天明细 · v0.0.5.7。"""
    headers = ["排名", "题材", "现价", "连续", "累计"]
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


# ── compare ───────────────────────────────────────────────────────────

def compare_payload(results: list[StockScanResult], *, periods: list[int]) -> dict:
    """kan compare --format json 的结构化 payload。"""
    return {
        "command": "compare",
        "periods": periods,
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


# ── history ───────────────────────────────────────────────────────────

def _history_mark_label(res: int, direction: str) -> str:
    """共振方向 → md/json 共用的中文标记 · 1-2 只方向词 · ≥3 加"多周期"。"""
    if res == 0 or not direction:
        return "—"
    word = "低位" if direction == "low" else "高位"
    return f"多周期{word}" if res >= 3 else word


def history_payload(
    symbol: str,
    name: str,
    entries: list,
    *,
    period: int,
) -> dict:
    """kan history --format json 的结构化 payload(新→旧)。"""
    from kan.core.scanner import history_mark, history_resonance

    series = []
    for e in entries:
        cell = e.periods.get(period)
        low_res, high_res = history_resonance(e.periods)
        res, direction = history_mark(e.periods)
        series.append({
            "date": e.snapshot_date.isoformat(),
            "name": e.name,
            "position_pct": cell["pct"] if cell else None,
            "at_low": bool(cell["at_low"]) if cell else None,
            "at_high": bool(cell["at_high"]) if cell else None,
            "low_resonance": low_res,
            "high_resonance": high_res,
            "resonance": res,
            "direction": direction or None,
        })
    return {
        "command": "history",
        "symbol": symbol,
        "name": name,
        "period": period,
        "series": series,
    }


def history_markdown(
    entries: list,
    *,
    period: int,
    title: str,
) -> str:
    """kan history --format md · 单周期纵向时间线(新→旧)。"""
    from kan.core.scanner import history_mark

    headers = ["日期", f"{period}日位置", "共振", "标记"]
    rows: list[list[str]] = []
    for e in entries:
        cell = e.periods.get(period)
        if cell is None:
            pct_str = "-"
        else:
            text = f"{cell['pct']:.0f}%"
            pct_str = f"[{text}]" if (cell.get("at_low") or cell.get("at_high")) else text
        res, direction = history_mark(e.periods)
        rows.append([
            e.snapshot_date.isoformat(),
            pct_str,
            f"×{res}" if res else "—",
            _history_mark_label(res, direction),
        ])
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"
