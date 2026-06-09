"""scan / low-high / info 导出实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kan.storage.export_base import (
    _board_reference_kind,
    _disclaimer_quote,
    _disclaimer_text,
    md_table,
)
from kan.storage.export_find_dimensions import (
    _moneyflow_public_dict,
    _sentiment_public_dict,
    _valuation_public_dict,
)

if TYPE_CHECKING:
    from datetime import date

    from kan.core.models import (
        BoardMeta,
        BoardPositionContext,
        HotMeta,
        MoneyflowMetrics,
        PeriodResult,
        SentimentMetrics,
        StockScanResult,
        ThemeMeta,
        ValuationContext,
        ValuationMetrics,
        VolumeState,
    )
    from kan.core.scanner import TrendResult

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
        "disclaimer": _disclaimer_text(),
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
    show_context: bool = False,
) -> str:
    """kan scan --format md · 全周期(导出不做终端宽度裁剪)。"""
    headers = ["股票", "现价"]
    if show_context:
        headers += ["PE", "5日主力(万)", "10日线", "20日线", "20日低", "除权除息"]
    headers += [f"{p}日" for p in periods]
    headers.append("共振")
    rows: list[list[str]] = []
    for r in results:
        name_short = r.name.replace(" ", "")
        tag = " 涨停" if r.limit_up else (" 跌停" if r.limit_down else "")
        cells = [f"{name_short} {r.symbol}{tag}", f"{r.current_price:.2f}"]
        if show_context:
            cells += [
                _scan_num(getattr(r, "pe_ttm", None), digits=1),
                _money_wan(getattr(r, "moneyflow_5d_net_amount", None)),
                _scan_num(getattr(r, "ma_10", None)),
                _scan_num(getattr(r, "ma_20", None)),
                _scan_num(getattr(r, "recent_low_20", None)),
                _corporate_action_cell(getattr(r, "corporate_action", None)),
            ]
        for p in periods:
            pr = next((x for x in r.periods if x.period == p), None)
            cells.append("-" if pr is None else _pct_cell(pr, mode=mode))
        resonance = r.high_resonance if mode == "high" else r.low_resonance
        cells.append(f"×{resonance}" if resonance else "")
        rows.append(cells)
    return f"# {title}\n\n{md_table(headers, rows)}\n\n{_disclaimer_quote()}"


def _scan_num(value: float | None, *, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _money_wan(value: float | None) -> str:
    return "-" if value is None else f"{value:,.0f}"


def _corporate_action_cell(action) -> str:
    if action is None:
        return "-"
    text = action.ex_date.isoformat()
    if action.reference_price is not None:
        text += f" @{action.reference_price:.2f}"
    return text


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
        "disclaimer": _disclaimer_text(),
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
    from kan.core.models import ThemeMeta

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
    行为一致)。None 时退化到 results_by_period.keys()。
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
    valuation: ValuationMetrics | None = None,
    valuation_context: ValuationContext | None = None,
    moneyflow: MoneyflowMetrics | None = None,
    sentiment: SentimentMetrics | None = None,
    board_context: BoardPositionContext | None = None,
) -> dict:
    """kan info --format json 的结构化 payload。

    valuation:单股截面市场指标 · 量价 / 市值 / 估值客观裸值 · 无 token / 无数据时
    为 None (AI 消费契约仍成立)。

    valuation_context (全市场截面层):估值位置对照 · 历史分位 + 行业内分位 + 行业中位 ·
    只承载分位 + 中位参照,不重复承载个股估值裸值 · 无数据时 None。
    """
    return {
        "command": "info",
        "symbol": result.symbol,
        "name": result.name,
        "disclaimer": _disclaimer_text(),
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
        "valuation": _valuation_public_dict(valuation),
        "valuation_context": (
            valuation_context.model_dump() if valuation_context else None
        ),
        "moneyflow": _moneyflow_public_dict(moneyflow),
        "sentiment": _sentiment_public_dict(sentiment),
        "board_position_context": (
            board_context.model_dump() if board_context else None
        ),
    }


def _board_position_context_markdown(context: BoardPositionContext) -> str:
    headers = ["周期", "本股位置", "板块均值", "低到高排名"]
    rows = [
        [
            f"{row.period}日",
            f"{row.position_pct:.1f}%",
            f"{row.board_avg_pct:.1f}%",
            f"{row.rank_low_to_high}/{row.sample}",
        ]
        for row in context.periods
    ]
    heading = (
        f"板块对比 · 申万一级 {context.industry} · "
        f"本地样本 {context.cached_sample}/{context.constituent_count}"
    )
    return f"{heading}\n\n{md_table(headers, rows)}"


def info_markdown(
    result: StockScanResult,
    trend: TrendResult,
    *,
    volume: VolumeState | None,
    title: str,
    moneyflow: MoneyflowMetrics | None = None,
    sentiment: SentimentMetrics | None = None,
    board_context: BoardPositionContext | None = None,
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
    if board_context is not None:
        sections.append(_board_position_context_markdown(board_context))
    if volume is not None:
        sections.append(
            f"成交量 · 今日是近 {volume.window} 日均量的 "
            f"{volume.ratio} 倍 · {volume.label}"
        )
    if moneyflow is not None and (
        moneyflow.net_amount is not None
        or moneyflow.buy_elg_amount is not None
        or moneyflow.buy_lg_amount is not None
        or moneyflow.net_amount_5d is not None
    ):
        sections.append(
            "资金流 · "
            f"今日主力 {_scan_num(moneyflow.net_amount)} 万元 · "
            f"超大单 {_scan_num(moneyflow.buy_elg_amount)} 万元 · "
            f"大单 {_scan_num(moneyflow.buy_lg_amount)} 万元 · "
            f"连续净流入 {moneyflow.inflow_days if moneyflow.inflow_days is not None else '-'} 天 · "
            f"5日合计 {_scan_num(moneyflow.net_amount_5d)} 万元"
        )
    if sentiment is not None and (
        sentiment.first_time is not None
        or sentiment.last_time is not None
        or sentiment.open_times is not None
        or sentiment.fd_amount is not None
    ):
        sections.append(
            "涨跌停详情 · "
            f"首次封板 {sentiment.first_time or '-'} · "
            f"最后封板 {sentiment.last_time or '-'} · "
            f"开板次数 {_scan_num(sentiment.open_times, digits=0)} · "
            f"封单金额 {_scan_num(sentiment.fd_amount)}"
        )
    sections.append(_disclaimer_quote())
    return "\n\n".join(sections)


# ── trend ─────────────────────────────────────────────────────────────
