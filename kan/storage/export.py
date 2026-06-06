"""非终端输出格式 · markdown / json 导出。

终端渲染仍在 cli_*_cmds.py 内联 + kan/render.py;本模块只管 --format md|json
两条新输出路径,不碰终端代码(零回归风险)。数据模型(kan/models.py 的
StockScanResult / PeriodResult,Pydantic)已存在,这里只做序列化与表格化。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from kan.core.find_registry import (
    DATA_DIMENSIONS,
    DIMENSION_DATA_FIELDS,
    DIMENSIONS_UNSUPPORTED_IN_ALL,
    FIND_FIELD_SPECS,
    TRIGGER_FLAG,
    dimensions_from_filters,
)

if TYPE_CHECKING:
    from datetime import date

    from kan.core.cross_section import CrossSectionRow
    from kan.core.find_filter import FindMatch, TriggeredFilter
    from kan.core.models import (
        BoardMeta,
        BoardPositionContext,
        ChipMetrics,
        EnrichedResult,
        FundamentalMetrics,
        HotMeta,
        MoneyflowMetrics,
        PeriodResult,
        SentimentMetrics,
        ShareholderMetrics,
        StockScanResult,
        TechnicalMetrics,
        ThemeMeta,
        ValuationContext,
        ValuationMetrics,
        VolumeState,
    )
    from kan.core.pipeline import Freshness
    from kan.core.scanner import TrendResult

# kan find AI 消费 JSON 的 schema 契约版本。
# 这是数据契约版本 (供外部 AI 判断字段集) · 与包版本 (__version__) 不同命名空间:
# 字段集变更时才 bump · 加字段属向后兼容演进 (AI 见到更多字段 · 不破旧消费方)。
FIND_SCHEMA_VERSION = "0.0.6.8"


def _board_reference_kind(meta: BoardMeta | HotMeta | ThemeMeta | None) -> str:
    """meta 类型对应的 reference kind 标识 · md / json 共用。"""
    from kan.core.models import ThemeMeta

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


def _disclaimer_text() -> str:
    """通用 stock-data JSON 顶层免责声明。"""
    from kan.render.base import DISCLAIMER

    return DISCLAIMER.strip()


def error_payload(
    command: str,
    *,
    code: str,
    message: str,
    hint: str | None = None,
) -> dict:
    """机器消费错误 envelope · 避免 json 模式把业务失败落成纯文本。"""
    payload: dict = {
        "ok": False,
        "command": command,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if hint:
        payload["error"]["hint"] = hint
    if command == "find":
        from kan.render.base import FIND_DISCLAIMER_TEXT

        payload["schema_version"] = FIND_SCHEMA_VERSION
        payload["disclaimer"] = FIND_DISCLAIMER_TEXT
    else:
        payload["disclaimer"] = _disclaimer_text()
    return payload


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


# ── compare ───────────────────────────────────────────────────────────

def compare_payload(results: list[StockScanResult], *, periods: list[int]) -> dict:
    """kan compare --format json 的结构化 payload。"""
    return {
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


# ── find (AI 消费入口 · AI JSON 层) ────────────────────────────────────────

def _valuation_public_dict(v: ValuationMetrics | None) -> dict | None:
    """ValuationMetrics → 对外 JSON。

    合规 (compliance §2/§7):
    - 量价 / 市值客观事实 (close / turnover_rate / volume_ratio / total_mv / circ_mv)
      + 估值裸值 (pe_ttm / pb / ps_ttm / dv_ttm) 一并输出。
    - 放开理由:filter 由用户显式指定 (--pe 是用户主导的数据筛选 · 非工具荐股) ·
      行业分位主观性强 (回看窗口 / 行业划分皆为选择) · 裸值反而客观 (项目决策)。
    - 仍守:不评分 / 不评级 / 不判断词 (compliance §3 黑名单 · find JSON 守护测试不动)。
    """
    if v is None:
        return None
    return {
        "trade_date": v.trade_date.isoformat() if v.trade_date else None,
        "close": v.close,
        "pe_ttm": v.pe_ttm,
        "pb": v.pb,
        "ps_ttm": v.ps_ttm,
        "dv_ttm": v.dv_ttm,
        "turnover_rate": v.turnover_rate,
        "volume_ratio": v.volume_ratio,
        "total_mv": v.total_mv,
        "circ_mv": v.circ_mv,
        "source": v.source,
    }


def _fundamentals_public_dict(f: FundamentalMetrics | None) -> dict | None:
    """FundamentalMetrics → 对外 JSON (估值/质量/资金维度 · ROE/增速裸值)。

    合规 (compliance §7):ROE / 增速是单向正向因子 (无"贵/便宜"双向误导)· 原始
    指标名 · 不评分 / 不判断词 · 裸值可出 (用户主导 --roe filter)。
    """
    if f is None:
        return None
    return {
        "end_date": f.end_date.isoformat() if f.end_date else None,
        "roe": f.roe,
        "netprofit_yoy": f.netprofit_yoy,
        "or_yoy": f.or_yoy,
        "source": f.source,
    }


def _moneyflow_public_dict(m: MoneyflowMetrics | None) -> dict | None:
    """MoneyflowMetrics → 对外 JSON (估值/质量/资金维度 · 主力净额裸值)。

    合规 (compliance §2):主力净额是客观资金事实 (同 OHLCV 安全区)· 裸值可出。
    """
    if m is None:
        return None
    return {
        "trade_date": m.trade_date.isoformat() if m.trade_date else None,
        "net_amount": m.net_amount,
        "buy_elg_amount": m.buy_elg_amount,
        "buy_lg_amount": m.buy_lg_amount,
        "buy_md_amount": m.buy_md_amount,
        "buy_sm_amount": m.buy_sm_amount,
        "inflow_days": m.inflow_days,
        "outflow_days": m.outflow_days,
        "net_amount_5d": m.net_amount_5d,
        "source": m.source,
    }


def _technical_public_dict(t: TechnicalMetrics | None) -> dict | None:
    """TechnicalMetrics → 对外 JSON (技术/情绪/筹码维度 · 前复权技术指标裸值)。

    合规 (compliance §3/§7):原始指标名 (macd/kdj/rsi/ma/boll) · 不输出"超买/超卖/
    金叉/死叉"判断词 · 只出裸值。filter 阈值用户主导 (--rsi 等)。
    """
    if t is None:
        return None
    return {
        "trade_date": t.trade_date.isoformat() if t.trade_date else None,
        "close": t.close,
        "macd_dif": t.macd_dif,
        "macd_dea": t.macd_dea,
        "macd": t.macd,
        "kdj_k": t.kdj_k,
        "kdj_d": t.kdj_d,
        "kdj_j": t.kdj_j,
        "rsi_6": t.rsi_6,
        "rsi_12": t.rsi_12,
        "rsi_24": t.rsi_24,
        "ma_5": t.ma_5,
        "ma_10": t.ma_10,
        "ma_20": t.ma_20,
        "ma_60": t.ma_60,
        "atr": t.atr,
        "atr_pct": t.atr_pct(),
        "ma_bias": {
            "5": t.ma_bias(5),
            "10": t.ma_bias(10),
            "20": t.ma_bias(20),
            "60": t.ma_bias(60),
        },
        "boll_upper": t.boll_upper,
        "boll_mid": t.boll_mid,
        "boll_lower": t.boll_lower,
        "source": t.source,
    }


def _sentiment_public_dict(s: SentimentMetrics | None) -> dict | None:
    """SentimentMetrics → 对外 JSON (技术/情绪/筹码维度 · 连板/炸板裸值)。

    合规 (compliance §2/§3):连板天数 / 炸板次数是客观市场事实 · 不输出"妖股/强势"
    判断词。s 为 None = 该股当日未涨跌停 (稀疏事件型 · 见 SentimentMetrics)。
    """
    if s is None:
        return None
    return {
        "trade_date": s.trade_date.isoformat() if s.trade_date else None,
        "limit_times": s.limit_times,
        "open_times": s.open_times,
        "first_time": s.first_time,
        "last_time": s.last_time,
        "fd_amount": s.fd_amount,
        "limit": s.limit,
        "up_stat": s.up_stat,
        "source": s.source,
    }


def _chip_public_dict(c: ChipMetrics | None) -> dict | None:
    """ChipMetrics → 对外 JSON (技术/情绪/筹码维度 · 获利盘/成本分布裸值)。

    合规 (compliance §2/§7):获利盘比例 / 成本分位是客观计算值 · 不输出判断词。
    """
    if c is None:
        return None
    return {
        "trade_date": c.trade_date.isoformat() if c.trade_date else None,
        "winner_rate": c.winner_rate,
        "cost_5pct": c.cost_5pct,
        "cost_50pct": c.cost_50pct,
        "cost_95pct": c.cost_95pct,
        "weight_avg": c.weight_avg,
        "source": c.source,
    }


def _shareholder_public_dict(s: ShareholderMetrics | None) -> dict | None:
    """ShareholderMetrics → 对外 JSON (股东持股维度 · 户数环比/集中度/北向裸值)。

    合规 (compliance §7 股东持股维度 守则):户数环比 / 前十大流通集中度 / 北向占比是已披露
    客观事实衍生 · 不输出"主力建仓/洗盘/控盘/高度控盘"判断词。季度披露 · 各字段独立
    可空 (未披露 / 未进前十 → None)。北向用"香港中央结算"季度名义持有人代理。
    """
    if s is None:
        return None
    return {
        "holder_end_date": s.holder_end_date.isoformat() if s.holder_end_date else None,
        "holder_num": s.holder_num,
        "holder_chg_pct": s.holder_chg_pct,
        "top10_end_date": s.top10_end_date.isoformat() if s.top10_end_date else None,
        "top10_float_ratio": s.top10_float_ratio,
        "north_hold_ratio": s.north_hold_ratio,
        "source": s.source,
    }


def _find_disclaimer_quote() -> str:
    """find 专属免责 → markdown 引用块 (compliance §5 · 衍生不可删)。"""
    from kan.render.base import FIND_DISCLAIMER_TEXT

    return "> " + FIND_DISCLAIMER_TEXT


def _find_result_dict(match: FindMatch, enriched: EnrichedResult) -> dict:
    """单只命中 → JSON 对象 (find JSON schema · AI JSON 层扩 valuation + context)。"""
    er = enriched
    return {
        "code": er.symbol,
        "name": er.name.replace(" ", ""),
        "price": er.current_price,
        "data_time": er.scan_date.isoformat(),
        "is_st": er.is_st,
        "limit_up": er.limit_up,
        "limit_down": er.limit_down,
        "triggered_filters": [
            {
                "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
                "param": t.param,
                "value": t.value,
            }
            for t in match.triggered
        ],
        "context": {
            "low_resonance": er.low_resonance,
            "high_resonance": er.high_resonance,
            "positions": {
                str(p.period): p.position_pct
                for p in er.periods
                if not p.insufficient
            },
        },
        "valuation": _valuation_public_dict(getattr(er, "valuation", None)),
        "fundamentals": _fundamentals_public_dict(getattr(er, "fundamentals", None)),
        "moneyflow": _moneyflow_public_dict(getattr(er, "moneyflow", None)),
        "technical": _technical_public_dict(getattr(er, "technical", None)),
        "sentiment": _sentiment_public_dict(getattr(er, "sentiment", None)),
        "chip": _chip_public_dict(getattr(er, "chip", None)),
        "shareholder": _shareholder_public_dict(getattr(er, "shareholder", None)),
    }


def _triggered_filters_public(match: FindMatch) -> list[dict]:
    """TriggeredFilter tuple → JSON public audit trail."""
    return [
        {
            "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
            "param": t.param,
            "value": t.value,
        }
        for t in match.triggered
    ]


def _positions_dict(result: StockScanResult) -> dict:
    """StockScanResult.periods → compact positions dict."""
    return {
        str(p.period): p.position_pct
        for p in result.periods
        if not p.insufficient
    }


def _gains_dict(result: StockScanResult) -> dict:
    """StockScanResult.periods → compact gains dict (only populated values)."""
    return {
        str(p.period): p.gain_pct
        for p in result.periods
        if not p.insufficient and p.gain_pct is not None
    }


def _pick_non_null(data: dict | None, keys: tuple[str, ...]) -> dict | None:
    """Select keys and drop all-null dimension summaries."""
    if data is None:
        return None
    picked = {k: data.get(k) for k in keys if k in data}
    def has_value(value: object) -> bool:
        if isinstance(value, dict):
            return any(has_value(v) for v in value.values())
        return value is not None

    return picked if any(has_value(v) for v in picked.values()) else None


def _compact_dimension_summary(dim: str, obj: object | None) -> dict | None:
    """Full dimension object → compact summary used by --compact."""
    if dim == "valuation":
        return _pick_non_null(
            _valuation_public_dict(obj),  # type: ignore[arg-type]
            ("trade_date", "pe_ttm", "pb", "ps_ttm", "dv_ttm", "turnover_rate", "total_mv", "source"),
        )
    if dim == "fundamentals":
        return _pick_non_null(
            _fundamentals_public_dict(obj),  # type: ignore[arg-type]
            ("end_date", "roe", "netprofit_yoy", "or_yoy", "source"),
        )
    if dim == "moneyflow":
        return _pick_non_null(
            _moneyflow_public_dict(obj),  # type: ignore[arg-type]
            (
                "trade_date", "net_amount", "net_amount_5d", "buy_elg_amount",
                "buy_lg_amount", "inflow_days", "source",
            ),
        )
    if dim == "technical":
        return _pick_non_null(
            _technical_public_dict(obj),  # type: ignore[arg-type]
            ("trade_date", "rsi_6", "macd_dif", "macd", "kdj_j", "ma_bias", "atr_pct", "source"),
        )
    if dim == "sentiment":
        return _pick_non_null(
            _sentiment_public_dict(obj),  # type: ignore[arg-type]
            (
                "trade_date", "limit_times", "open_times", "first_time",
                "last_time", "fd_amount", "limit", "source",
            ),
        )
    if dim == "chip":
        return _pick_non_null(
            _chip_public_dict(obj),  # type: ignore[arg-type]
            ("trade_date", "winner_rate", "source"),
        )
    if dim == "shareholder":
        return _pick_non_null(
            _shareholder_public_dict(obj),  # type: ignore[arg-type]
            (
                "holder_end_date", "holder_chg_pct", "top10_end_date",
                "top10_float_ratio", "north_hold_ratio", "source",
            ),
        )
    return None


def _find_result_compact_dict(
    match: FindMatch,
    enriched: EnrichedResult,
    *,
    included_dimensions: set[str],
    include_context: bool = True,
) -> dict:
    """单只命中 → compact JSON 对象.

    compact 只保留首轮筛选常用字段:身份、价格、触发 filter、位置/共振,
    以及本次已取数维度的少量摘要。维度被请求但无数据时保留 None,让调用方
    区分“缺数据”和“未请求”。
    """
    er = enriched
    result: dict = {
        "code": er.symbol,
        "name": er.name.replace(" ", ""),
        "price": er.current_price,
        "data_time": er.scan_date.isoformat(),
        "triggered_filters": _triggered_filters_public(match),
    }
    if include_context:
        result.update({
            "positions": _positions_dict(er),
            "low_resonance": er.low_resonance,
            "high_resonance": er.high_resonance,
        })
        gains = _gains_dict(er)
        if gains:
            result["gains"] = gains
        if er.up_days:
            result["up_days"] = er.up_days
    if er.is_st:
        result["is_st"] = True
    if er.limit_up:
        result["limit_up"] = True
    if er.limit_down:
        result["limit_down"] = True
    for dim in DATA_DIMENSIONS:
        if dim in included_dimensions:
            result[dim] = _compact_dimension_summary(dim, getattr(er, dim, None))
    return result


def _object_has_dimension_data(dim: str, obj: object | None) -> bool:
    """Return True when the dimension object carries at least one useful value."""
    if obj is None:
        return False
    return any(getattr(obj, field, None) is not None for field in DIMENSION_DATA_FIELDS[dim])


def _infer_included_dimensions(items: Sequence[object]) -> set[str]:
    """Fallback for direct unit calls that do not pass included_dimensions."""
    dims: set[str] = set()
    for item in items:
        for dim in DATA_DIMENSIONS:
            if getattr(item, dim, None) is not None:
                dims.add(dim)
    return dims


def _data_availability(
    items: Sequence[object],
    *,
    included_dimensions: set[str] | None = None,
    unsupported_dimensions: set[str] | None = None,
    basis: str = "candidate_pool",
) -> dict:
    """Build top-level data_availability stats for machine consumers.

    Counts are only meaningful for dimensions attempted by this command. Dimensions
    not fetched are marked not_requested; dimensions unsupported by the current mode
    are marked not_supported instead of being mistaken for zero facts.
    """
    included = included_dimensions if included_dimensions is not None else _infer_included_dimensions(items)
    unsupported = unsupported_dimensions or set()
    total = len(items)
    out: dict = {"basis": basis, "pool_size": total}
    for dim in DATA_DIMENSIONS:
        if dim in unsupported:
            out[dim] = {"status": "not_supported", "available": None, "missing": None}
            continue
        if dim not in included:
            out[dim] = {"status": "not_requested", "available": None, "missing": None}
            continue
        available = sum(1 for item in items if _object_has_dimension_data(dim, getattr(item, dim, None)))
        out[dim] = {
            "status": "included",
            "available": available,
            "missing": total - available,
        }
    return out


def _nested_get(source: dict, path: tuple[str, ...]) -> object:
    current: object = source
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _nested_set(target: dict, path: tuple[str, ...], value: object) -> None:
    current = target
    for part in path[:-1]:
        current = current.setdefault(part, {})
    current[path[-1]] = value


def _select_find_fields(source: dict, fields: tuple[str, ...]) -> dict:
    """Select whitelisted result fields while preserving nested output paths."""
    out: dict = {}
    for field in fields:
        spec = FIND_FIELD_SPECS[field]
        _nested_set(out, spec.output_path, _nested_get(source, spec.output_path))
    return out


def _find_result_field_source(match: FindMatch, enriched: EnrichedResult) -> dict:
    """Full source dict used by --fields for normal find results."""
    source = _find_result_dict(match, enriched)
    source["context"]["gains"] = _gains_dict(enriched)
    source["context"]["up_days"] = enriched.up_days
    return source


def find_payload(
    entries: list[tuple[FindMatch, EnrichedResult]],
    *,
    query_time: str,
    pools: list[str],
    filters: list[dict],
    pool_size: int,
    matched_total: int,
    freshness: Freshness,
    compact: bool = False,
    availability_results: list[EnrichedResult] | None = None,
    included_dimensions: set[str] | None = None,
    compact_dimensions: set[str] | None = None,
    fields: tuple[str, ...] = (),
    compact_context: bool = True,
    match_mode: str = "all",
) -> dict:
    """kan find --format json 的结构化 payload (AI JSON 层 · AI 消费入口)。

    find JSON schema · 扩 context (位置/共振) + valuation (量价/市值客观事实)。

    Args:
        entries: 已 enrich + limit 后的 (FindMatch, EnrichedResult) 配对 · 顺序即输出序
        query_time: 查询发起时间 (ISO · caller 注入 · 利于测试确定性)
        pools: 候选池标识 (例 ["industry:半导体"] / ["watchlist"])
        filters: rule.filters · 每项 {"name": "--pos", "param": "180:lt:5"}
        pool_size: 池内总股票数 (筛前)
        matched_total: limit 前的总命中数 (stats.matched · len(entries)=shown)
        freshness: 数据新鲜度 (data_cutoff / stale)

    强制 disclaimer 字段 (compliance §5/§7 · 衍生不可删 · 测试守护)。
    """
    from kan.render.base import FIND_DISCLAIMER_TEXT

    availability_source = availability_results if availability_results is not None else [
        er for _, er in entries
    ]
    result_dimensions = (
        compact_dimensions
        if compact_dimensions is not None
        else dimensions_from_filters(filters)
    )
    if compact and not result_dimensions and compact_dimensions is None:
        result_dimensions = _infer_included_dimensions(availability_source)

    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "result_schema": "fields" if fields else ("compact" if compact else "full"),
        "query_time": query_time,
        "rule": {"pools": pools, "filters": filters, "match": match_mode},
        "results": [
            _select_find_fields(_find_result_field_source(m, er), fields)
            if fields
            else (
                _find_result_compact_dict(
                    m,
                    er,
                    included_dimensions=result_dimensions,
                    include_context=compact_context,
                )
                if compact else _find_result_dict(m, er)
            )
            for m, er in entries
        ],
        "disclaimer": FIND_DISCLAIMER_TEXT,
        "data_availability": _data_availability(
            availability_source,
            included_dimensions=included_dimensions,
        ),
        "stats": {
            "pool_size": pool_size,
            "matched": matched_total,
            "shown": len(entries),
            "data_cutoff": (
                freshness.data_cutoff.isoformat() if freshness.data_cutoff else None
            ),
            "stale": freshness.is_stale,
        },
    }


def code_pool_payload(
    pairs: list[tuple[str, str]],
    *,
    query_time: str,
    pools: list[str],
    fields: tuple[str, ...] = (),
) -> dict:
    """`kan find --codes ... --format json` without filters.

    Explicit code pools should be able to act as a cheap metadata provider.
    Pulling K-line data just to echo the user-supplied pool makes first-run JSON
    automation depend on slow external sources.
    """
    from kan.render.base import FIND_DISCLAIMER_TEXT

    allowed = {"code", "name"}
    selected = tuple(fields or ("code", "name"))
    unsupported = [f for f in selected if f not in allowed]
    if unsupported:
        raise ValueError(
            "外部代码池无 filter 取数只支持 code/name 字段；"
            f"不支持: {', '.join(unsupported)}"
        )

    def _row(code: str, name: str) -> dict:
        source = {"code": code, "name": name.replace(" ", "")}
        return {k: source[k] for k in selected}

    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "mode": "code_pool",
        "result_schema": "fields" if fields else "code_pool",
        "query_time": query_time,
        "rule": {"pools": pools, "filters": []},
        "results": [_row(code, name) for code, name in pairs],
        "disclaimer": FIND_DISCLAIMER_TEXT,
        "data_availability": {
            dim: {"requested": False, "available": False, "coverage": 0.0}
            for dim in DATA_DIMENSIONS
        },
        "stats": {
            "pool_size": len(pairs),
            "matched": len(pairs),
            "shown": len(pairs),
            "data_cutoff": None,
            "stale": False,
        },
    }


def code_pool_markdown(pairs: list[tuple[str, str]], *, title: str) -> str:
    """Markdown for an explicit code pool without filters."""
    rows = [[name.replace(" ", ""), code] for code, name in pairs]
    table = md_table(["股票", "代码"], rows) if rows else "无代码"
    return f"# {title}\n\n{table}\n\n{_find_disclaimer_quote()}"


def find_markdown(
    entries: list[tuple[FindMatch, EnrichedResult]],
    *,
    title: str,
    pool_size: int,
    matched_total: int,
) -> str:
    """kan find --format md · 命中股票表 + 触发 filter + disclaimer (衍生不可删)。"""
    headers = ["股票", "现价", "触发 filter", "低共振", "高共振"]
    rows: list[list[str]] = []
    for m, er in entries:
        name_short = er.name.replace(" ", "")
        tag = " 涨停" if er.limit_up else (" 跌停" if er.limit_down else "")
        st = " ST" if er.is_st else ""
        trigs = " · ".join(
            f"{TRIGGER_FLAG.get(t.filter_type, t.filter_type)}={t.param}@{t.value:g}"
            for t in m.triggered
        )
        rows.append([
            f"{name_short} {er.symbol}{tag}{st}",
            f"{er.current_price:.2f}",
            trigs or "—",
            f"×{er.low_resonance}" if er.low_resonance else "—",
            f"×{er.high_resonance}" if er.high_resonance else "—",
        ])
    head = f"# {title} · 命中 {matched_total} / {pool_size}"
    body = md_table(headers, rows) if rows else "_无股票符合您设置的所有 filter_"
    return f"{head}\n\n{body}\n\n{_find_disclaimer_quote()}"


# ── cross section (kan find --all 全市场截面取数 · 全市场截面层) ────────────────

def _scan_context_public_dict(scan: StockScanResult | None) -> dict | None:
    """`--all` K 线快照上下文 → JSON 裸值。

    只有 `kan find --all` 搭配位置 / 共振 / 涨幅 / 连阳 filter 时才会挂载 scan。
    无 K 线快照时返回 None,让调用方能区分"没请求/没数据"和"有快照但裸值为空"。
    """
    if scan is None:
        return None
    positions = {
        str(p.period): p.position_pct
        for p in scan.periods
        if not p.insufficient
    }
    gains = {
        str(p.period): p.gain_pct
        for p in scan.periods
        if not p.insufficient and p.gain_pct is not None
    }
    return {
        "low_resonance": scan.low_resonance,
        "high_resonance": scan.high_resonance,
        "up_days": scan.up_days,
        "positions": positions,
        "gains": gains,
    }


def _row_price(row: CrossSectionRow) -> float | None:
    if row.scan is not None:
        return row.scan.current_price
    return row.valuation.close if row.valuation is not None else None


def _row_data_time(row: CrossSectionRow) -> str | None:
    if row.scan is not None:
        return row.scan.scan_date.isoformat()
    for obj in (row.valuation, row.moneyflow, row.technical, row.sentiment, row.chip):
        trade_date = getattr(obj, "trade_date", None)
        if trade_date is not None:
            return trade_date.isoformat()
    return None


def _cross_section_result_compact_dict(
    row: CrossSectionRow,
    triggered: tuple[TriggeredFilter, ...] = (),
    *,
    included_dimensions: set[str],
    include_context: bool = True,
) -> dict:
    """单只截面取数结果 → compact JSON 对象."""
    result: dict = {
        "code": row.code,
        "name": row.name.replace(" ", ""),
        "price": _row_price(row),
        "data_time": _row_data_time(row),
        "triggered_filters": [
            {
                "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
                "param": t.param,
                "value": t.value,
            }
            for t in triggered
        ],
    }
    if include_context and row.scan is not None:
        result.update({
            "positions": _positions_dict(row.scan),
            "low_resonance": row.scan.low_resonance,
            "high_resonance": row.scan.high_resonance,
        })
        gains = _gains_dict(row.scan)
        if gains:
            result["gains"] = gains
        if row.scan.up_days:
            result["up_days"] = row.scan.up_days
    for dim in DATA_DIMENSIONS:
        if dim in included_dimensions and hasattr(row, dim):
            result[dim] = _compact_dimension_summary(dim, getattr(row, dim))
    return result


def _cross_section_result_field_source(
    row: CrossSectionRow,
    triggered: tuple[TriggeredFilter, ...] = (),
) -> dict:
    """Full source dict used by --fields for cross-section results."""
    source = _cross_section_result_dict(row, triggered)
    source["price"] = _row_price(row)
    source["data_time"] = _row_data_time(row)
    return source


def _cross_section_result_dict(
    row: CrossSectionRow,
    triggered: tuple[TriggeredFilter, ...] = (),
) -> dict:
    """单只截面取数结果 → JSON 对象 (估值/质量/资金维度 · 估值裸值放开 + moneyflow + triggered)。

    基础截面输出:code/name + valuation (量价/市值 + 估值裸值) + valuation_context
    (行业内分位 + 行业中位 · *_pct_rank 截面恒 None) + moneyflow + technical/
    sentiment/chip + triggered_filters。需要 K 线类 filter 时,row.scan 额外挂载
    预计算位置 / 共振 / 涨幅 / 连阳裸值到 context。
    """
    return {
        "code": row.code,
        "name": row.name.replace(" ", ""),
        "context": _scan_context_public_dict(row.scan),
        "valuation": _valuation_public_dict(row.valuation),
        "valuation_context": (
            row.valuation_context.model_dump() if row.valuation_context else None
        ),
        "moneyflow": _moneyflow_public_dict(row.moneyflow),
        "technical": _technical_public_dict(row.technical),
        "sentiment": _sentiment_public_dict(row.sentiment),
        "chip": _chip_public_dict(row.chip),
        "triggered_filters": [
            {
                "filter": TRIGGER_FLAG.get(t.filter_type, t.filter_type),
                "param": t.param,
                "value": t.value,
            }
            for t in triggered
        ],
    }


def cross_section_payload(
    entries: list[tuple[CrossSectionRow, tuple[TriggeredFilter, ...]]],
    *,
    query_time: str,
    pool_size: int,
    matched_total: int | None = None,
    data_cutoff: date | None,
    stale: bool,
    filters: list[dict] | None = None,
    compact: bool = False,
    availability_rows: list[CrossSectionRow] | None = None,
    included_dimensions: set[str] | None = None,
    compact_dimensions: set[str] | None = None,
    fields: tuple[str, ...] = (),
    compact_context: bool = True,
    match_mode: str = "all",
) -> dict:
    """kan find --all --format json 截面取数/筛选 payload (全市场截面层 + 估值/质量/资金维度 截面 filter)。

    与 find_payload 区别 (项目决策的新 schema · 不复用):全市场基础截面不逐股拉 K,
    只在请求 K 线类 filter 时挂载批量预计算 context。mode="cross_section" 标记
    形态供 AI 区分。当前契约支持截面类 filter (--pe / --moneyflow) · entries
    带 triggered · rule.filters 反映输入。

    Args:
        entries: (CrossSectionRow, triggered) 配对列表 (已筛 + limit · 顺序即输出序 ·
            无 filter 取数时 triggered 为 ())
        query_time: 查询发起时间 (ISO · caller 注入 · 利于测试确定性)
        pool_size: 池内总股票数 (筛前 · 全市场约 5500)
        data_cutoff: 截面数据交易日 (date | None)
        stale: 截面缓存是否滞后
        filters: rule.filters (--pe/--moneyflow 的 DSL · None=取数无 filter)

    强制 disclaimer 字段 (compliance §5/§7 · 衍生不可删 · 测试守护)。
    """
    from kan.render.base import FIND_DISCLAIMER_TEXT

    rows_for_availability = availability_rows if availability_rows is not None else [
        row for row, _ in entries
    ]
    result_dimensions = (
        compact_dimensions
        if compact_dimensions is not None
        else dimensions_from_filters(filters or [])
    )
    if compact and not result_dimensions and compact_dimensions is None:
        result_dimensions = _infer_included_dimensions(rows_for_availability)

    return {
        "ok": True,
        "schema_version": FIND_SCHEMA_VERSION,
        "command": "find",
        "mode": "cross_section",
        "result_schema": "fields" if fields else ("compact" if compact else "full"),
        "query_time": query_time,
        "rule": {"pools": ["all"], "filters": filters or [], "match": match_mode},
        "results": [
            _select_find_fields(_cross_section_result_field_source(r, t), fields)
            if fields
            else (
                _cross_section_result_compact_dict(
                    r,
                    t,
                    included_dimensions=result_dimensions,
                    include_context=compact_context,
                )
                if compact else _cross_section_result_dict(r, t)
            )
            for r, t in entries
        ],
        "disclaimer": FIND_DISCLAIMER_TEXT,
        "data_availability": _data_availability(
            rows_for_availability,
            included_dimensions=included_dimensions,
            unsupported_dimensions=DIMENSIONS_UNSUPPORTED_IN_ALL,
        ),
        "stats": {
            "pool_size": pool_size,
            "matched": len(entries) if matched_total is None else matched_total,
            "shown": len(entries),
            "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
            "stale": stale,
        },
    }


def cross_section_markdown(
    rows: list[CrossSectionRow],
    *,
    title: str,
    pool_size: int,
) -> str:
    """kan find --all --format md · 全市场截面简表 + disclaimer (衍生不可删)。

    列:股票 / 申万行业 / PE / PE 行业内分位 / 换手率% / 主力净额 (估值/质量/资金维度 · 裸 PE 放开
    + 换手率 + 主力净额 · PE 分位作对照 · 全字段 (PB/资金明细) 见 --format json)。
    """
    headers = ["股票", "申万行业", "PE", "PE行业分位", "换手率%", "主力净额(万)"]
    md_rows: list[list[str]] = []
    for r in rows:
        ctx = r.valuation_context
        val = r.valuation
        mf = r.moneyflow
        ind = ctx.industry if ctx and ctx.industry else "—"
        pe = f"{val.pe_ttm:.2f}" if val and val.pe_ttm is not None else "—"
        pe_pct = (
            f"{ctx.pe_industry_pct:.0f}%"
            if ctx and ctx.pe_industry_pct is not None else "—"
        )
        turnover = (
            f"{val.turnover_rate:.2f}"
            if val and val.turnover_rate is not None else "—"
        )
        net = f"{mf.net_amount:,.0f}" if mf and mf.net_amount is not None else "—"
        md_rows.append([
            f"{r.name.replace(' ', '')} {r.code}",
            ind, pe, pe_pct, turnover, net,
        ])
    head = f"# {title} · 全市场 {pool_size} 只"
    body = md_table(headers, md_rows) if md_rows else "_无截面数据_"
    return f"{head}\n\n{body}\n\n{_find_disclaimer_quote()}"


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
        "disclaimer": _disclaimer_text(),
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
