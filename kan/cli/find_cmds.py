"""kan find · 用户主导的选股 DSL (v0.0.6.4 MVP · 地基-2 加 AI 消费 JSON)

按用户输入条件 · 在自选/行业/题材/热榜池里筛符合的股票。
"工具仅返回数据 · 不替你判断"

地基-2 (AI 消费入口):
- `--format json`:命中股票带全维度 metadata (triggered_filters + context + valuation)
- `--format md`:markdown 表格
- 无 filter + `--format json|md`:整池全维度 (= AI 取数环节 · 不带 filter = 数据 provider)
- 强制 disclaimer 字段 (compliance §5/§7 · 衍生不可删 · 测试守护)

合规(manmankan/docs/compliance.md §7):
- 用户显式指定 filter · 不内置 preset
- 输出 "符合条件的股票" · 不"推荐"
- 估值/质量/资金/技术/股东等裸值可按用户 filter 输出
"""
from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING, Annotated

import typer

from kan.app import app
from kan.cli.helpers import (
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _with_heavy_imports_spinner,
)
from kan.cli.helpers import (
    _parse_codes as _shared_parse_codes,
)
from kan.cli.helpers import (
    _resolve_code_pairs as _shared_resolve_code_pairs,
)
from kan.core.find_registry import (
    DIMENSIONS_UNSUPPORTED_IN_ALL,
    dimensions_from_fields,
    fields_need_kline,
    parse_find_fields,
)
from kan.data.hot import HotList
from kan.storage import export

if TYPE_CHECKING:
    from kan.core.find_dsl import ConditionSet
    from kan.core.models import EnrichedResult


def _parse_codes(raw: str) -> tuple[list[str], list[str]]:
    """兼容旧测试 import path · 实现移到 cli.helpers 供 scan/find 共用。"""
    return _shared_parse_codes(raw)


def _resolve_code_pairs(raw: str) -> list[tuple[str, str]]:
    """兼容旧测试 import path · 实现移到 cli.helpers 供 scan/find 共用。"""
    return _shared_resolve_code_pairs(
        raw,
        command="kan find",
    )


def _find_pools(
    industry: str | None,
    hot: HotList | None,
    theme: str | None,
    group: str | None,
    code_pairs: list[tuple[str, str]] | None = None,
) -> list[str]:
    """构造 rule.pools 机器标识 (JSON 输出 · 例 ["industry:半导体"] / ["watchlist"])。"""
    if code_pairs is not None:
        return [f"codes:{len(code_pairs)}"]
    if industry is not None:
        return [f"industry:{industry}"]
    if hot is not None:
        return [f"hot:{getattr(hot, 'value', hot)}"]
    if theme is not None:
        return [f"theme:{theme}"]
    return [f"watchlist:{group}"] if group else ["watchlist"]


def _find_filters(conditions: ConditionSet) -> list[dict]:
    """构造 rule.filters (JSON 输出 · 复刻用户输入的 DSL · 利于 AI 审计)。"""
    out: list[dict] = []
    for p in conditions.pos_filters:
        out.append({"name": "--pos", "param": f"{p.period}:{p.op}:{p.value:g}"})
    for r in conditions.resonance_filters:
        out.append({"name": "--resonance", "param": f"{r.level}:{r.op}:{r.value}"})
    for pe in conditions.pe_filters:
        out.append({"name": "--pe", "param": f"{pe.op}:{pe.value:g}"})
    for roe in conditions.roe_filters:
        out.append({"name": "--roe", "param": f"{roe.op}:{roe.value:g}"})
    for mf in conditions.moneyflow_filters:
        out.append({"name": "--moneyflow", "param": f"{mf.op}:{mf.value:g}"})
    for rsi in conditions.rsi_filters:
        out.append({"name": "--rsi", "param": f"{rsi.op}:{rsi.value:g}"})
    for md in conditions.macd_dif_filters:
        out.append({"name": "--macd-dif", "param": f"{md.op}:{md.value:g}"})
    for mc in conditions.macd_filters:
        out.append({"name": "--macd", "param": f"{mc.op}:{mc.value:g}"})
    for kj in conditions.kdj_j_filters:
        out.append({"name": "--kdj-j", "param": f"{kj.op}:{kj.value:g}"})
    for stk in conditions.streak_filters:
        out.append({"name": "--streak", "param": f"{stk.op}:{stk.value:g}"})
    for wn in conditions.winner_filters:
        out.append({"name": "--winner", "param": f"{wn.op}:{wn.value:g}"})
    for mb in conditions.ma_bias_filters:
        out.append({"name": "--ma-bias", "param": f"{mb.period}:{mb.op}:{mb.value:g}"})
    for gn in conditions.gain_filters:
        out.append({"name": "--gain", "param": f"{gn.period}:{gn.op}:{gn.value:g}"})
    for ap in conditions.atr_pct_filters:
        out.append({"name": "--atr-pct", "param": f"{ap.op}:{ap.value:g}"})
    for ud in conditions.up_days_filters:
        out.append({"name": "--up-days", "param": f"{ud.op}:{ud.value:g}"})
    for hd in conditions.holders_filters:
        out.append({"name": "--holders", "param": f"{hd.op}:{hd.value:g}"})
    for tt in conditions.top10_filters:
        out.append({"name": "--top10", "param": f"{tt.op}:{tt.value:g}"})
    for nt in conditions.north_filters:
        out.append({"name": "--north", "param": f"{nt.op}:{nt.value:g}"})
    if conditions.exclude_st:
        out.append({"name": "--exclude-st"})
    return out


def _kline_snapshot_periods(conditions: ConditionSet) -> list[int] | None:
    """`--all` K 线快照只取 filter 需要的周期,避免轻量条件拉 181 天。"""
    if not conditions.has_kline_filters():
        return None

    from kan.core.scanner import PERIODS

    periods: set[int] = set()
    periods.update(f.period for f in conditions.pos_filters)
    periods.update(f.period for f in conditions.gain_filters)
    if conditions.resonance_filters:
        periods.update(PERIODS)
    if conditions.up_days_filters:
        max_days = max(1, max(ceil(f.value) for f in conditions.up_days_filters))
        periods.add(min(max_days, max(PERIODS)))
    return sorted(periods or PERIODS)


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


def _any_metric(results: list[EnrichedResult], attr: str, fields: tuple[str, ...]) -> bool:
    """任一股票有目标子对象字段值即视为该维度可用。"""
    for r in results:
        obj = getattr(r, attr, None)
        if obj is None:
            continue
        if any(getattr(obj, field, None) is not None for field in fields):
            return True
    return False


def _any_technical_for_filters(
    results: list[EnrichedResult],
    conditions: ConditionSet,
) -> bool:
    """按请求的技术 filter 判断 technical 数据是否真的可用。"""
    for r in results:
        t = getattr(r, "technical", None)
        if t is None:
            continue
        if conditions.rsi_filters and getattr(t, "rsi_6", None) is not None:
            return True
        if conditions.macd_dif_filters and getattr(t, "macd_dif", None) is not None:
            return True
        if conditions.macd_filters and getattr(t, "macd", None) is not None:
            return True
        if conditions.kdj_j_filters and getattr(t, "kdj_j", None) is not None:
            return True
        if conditions.atr_pct_filters and t.atr_pct() is not None:
            return True
        if any(t.ma_bias(f.period) is not None for f in conditions.ma_bias_filters):
            return True
    return False


def _find_data_gap(
    conditions: ConditionSet,
    results: list[EnrichedResult],
) -> tuple[str, str, str] | None:
    """识别“上游数据不可用”而不是让 filter 静默变成 0 命中。"""
    if not results:
        return None
    token_hint = "配置 tushare token 后重试，或去掉对应 filter"
    if conditions.pe_filters and not _any_metric(results, "valuation", ("pe_ttm",)):
        return ("data_unavailable", "当前候选池缺少估值数据，无法执行 --pe filter", token_hint)
    if conditions.moneyflow_filters and not _any_metric(results, "moneyflow", ("net_amount",)):
        return ("data_unavailable", "当前候选池缺少资金流数据，无法执行 --moneyflow filter", token_hint)
    if conditions.roe_filters and not _any_metric(results, "fundamentals", ("roe",)):
        return ("data_unavailable", "当前候选池缺少财务数据，无法执行 --roe filter", token_hint)
    if conditions.needs_technical() and not _any_technical_for_filters(results, conditions):
        return ("data_unavailable", "当前候选池缺少技术指标数据，无法执行技术 filter", token_hint)
    if conditions.winner_filters and not _any_metric(results, "chip", ("winner_rate",)):
        return ("data_unavailable", "当前候选池缺少筹码数据，无法执行 --winner filter", token_hint)
    if conditions.needs_shareholder() and not _any_metric(
        results,
        "shareholder",
        ("holder_chg_pct", "top10_float_ratio", "north_hold_ratio"),
    ):
        return ("data_unavailable", "当前候选池缺少股东持股结构数据，无法执行股东 filter", token_hint)
    return None


def _condition_dimensions(conditions: ConditionSet) -> set[str]:
    dims: set[str] = set()
    if conditions.pe_filters:
        dims.add("valuation")
    if conditions.needs_fundamentals():
        dims.add("fundamentals")
    if conditions.needs_moneyflow():
        dims.add("moneyflow")
    if conditions.needs_technical():
        dims.add("technical")
    if conditions.needs_sentiment():
        dims.add("sentiment")
    if conditions.needs_chip():
        dims.add("chip")
    if conditions.needs_shareholder():
        dims.add("shareholder")
    return dims


def _availability_dimensions(
    conditions: ConditionSet,
    *,
    is_export: bool,
    field_dimensions: set[str] | None = None,
    fields_mode: bool = False,
) -> set[str]:
    """本次 find 实际尝试取数的维度,用于 data_availability 统计。"""
    dims = _condition_dimensions(conditions)
    dims.update(field_dimensions or set())
    if fields_mode:
        return dims
    if is_export:
        dims.add("valuation")
    if conditions.needs_moneyflow() or (is_export and conditions.is_empty()):
        dims.add("moneyflow")
    if conditions.needs_technical() or (is_export and conditions.is_empty()):
        dims.add("technical")
    if conditions.needs_sentiment() or (is_export and conditions.is_empty()):
        dims.add("sentiment")
    if conditions.needs_chip() or (is_export and conditions.is_empty()):
        dims.add("chip")
    if conditions.needs_shareholder():
        dims.add("shareholder")
    return dims


def _compact_dimensions(conditions: ConditionSet, *, is_export: bool) -> set[str]:
    """compact 结果里应该内联摘要的维度。"""
    if is_export and conditions.is_empty():
        return {"valuation", "moneyflow", "technical", "sentiment", "chip"}
    return _condition_dimensions(conditions)


@app.command()
def find(
    pos: Annotated[
        list[str],
        typer.Option(
            "--pos",
            help="位置 filter PERIOD:OP:VAL 例 180:lt:5 (180 日位置 < 5%) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    resonance: Annotated[
        list[str],
        typer.Option(
            "--resonance",
            help="共振 filter LEVEL:OP:VAL 例 low:gte:3 (低点共振 ≥ 3 周期) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    exclude_st: Annotated[
        bool,
        typer.Option("--exclude-st", help="排除 ST/*ST 股票"),
    ] = False,
    pe: Annotated[
        list[str],
        typer.Option(
            "--pe",
            help="估值 filter OP:VAL 例 lt:20 (PE TTM < 20 · 裸值筛) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    roe: Annotated[
        list[str],
        typer.Option(
            "--roe",
            help="质量 filter OP:VAL 例 gte:15 (ROE ≥ 15%) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    moneyflow: Annotated[
        list[str],
        typer.Option(
            "--moneyflow",
            help="主力资金 filter OP:VAL 例 gt:0 (主力净流入 · 单位万元) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rsi: Annotated[
        list[str],
        typer.Option(
            "--rsi",
            help="技术 filter OP:VAL 例 lt:30 (RSI 6 日 · 前复权裸值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    macd_dif: Annotated[
        list[str],
        typer.Option(
            "--macd-dif",
            help="技术 filter OP:VAL 例 gt:0 (MACD DIF 快线) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    macd: Annotated[
        list[str],
        typer.Option(
            "--macd",
            help="技术 filter OP:VAL 例 gt:0 (MACD 柱 · 柱>0=DIF 在 DEA 上方) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    kdj_j: Annotated[
        list[str],
        typer.Option(
            "--kdj-j",
            help="技术 filter OP:VAL 例 lt:20 (KDJ J 值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    streak: Annotated[
        list[str],
        typer.Option(
            "--streak",
            help="情绪 filter OP:VAL 例 gte:3 (连板天数 ≥ 3 · 不含 ST) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    winner: Annotated[
        list[str],
        typer.Option(
            "--winner",
            help="筹码 filter OP:VAL 例 gte:50 (获利盘 ≥ 50%) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    ma_bias: Annotated[
        list[str],
        typer.Option(
            "--ma-bias",
            help="乖离率 filter PERIOD:OP:VAL 例 20:gt:0 (收盘距 20 日线 % · 裸值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    gain: Annotated[
        list[str],
        typer.Option(
            "--gain",
            help="涨幅 filter PERIOD:OP:VAL 例 30:gt:20 (近 30 日涨幅 % · K 线池) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    atr_pct: Annotated[
        list[str],
        typer.Option(
            "--atr-pct",
            help="波动率 filter OP:VAL 例 lt:5 (ATR/close % · 裸值) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    up_days: Annotated[
        list[str],
        typer.Option(
            "--up-days",
            help="连阳天数 filter OP:VAL 例 gte:3 (连续阳线数 · K 线池) · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    holders: Annotated[
        list[str],
        typer.Option(
            "--holders",
            help="股东 filter OP:VAL 例 lt:0 (户数环比减少) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    top10: Annotated[
        list[str],
        typer.Option(
            "--top10",
            help="股东 filter OP:VAL 例 gte:50 (前十大流通集中度%) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    north: Annotated[
        list[str],
        typer.Option(
            "--north",
            help="股东 filter OP:VAL 例 gte:3 (北向持股% · 香港中央结算季度代理) · 逐股 · --all 不支持 · 可多次",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="池: 申万行业 (例 半导体)"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="池: 东财热榜 rank|surge"),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="池: 题材成分股 (例 AI应用)"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option(
            "--only-watchlist",
            help="池仅自选 ∩ industry/hot/theme · 需配合 pool flag",
        ),
    ] = False,
    group: Annotated[
        str | None,
        typer.Option("--group", "-g", help="自选股分组 (默认 default 组)"),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            help="输出条数上限 (默认 K 线模式 50 · --all 截面模式全量)",
        ),
    ] = None,
    all_stocks: Annotated[
        bool,
        typer.Option(
            "--all",
            help="全市场截面取数 ~5500 只 (估值/资金/技术/位置/涨幅/连阳 · 需 token)",
        ),
    ] = False,
    codes: Annotated[
        str | None,
        typer.Option(
            "--codes",
            help="池: 自定义代码列表 (逗号/空格/换行分隔；传 - 从 stdin 读)",
        ),
    ] = None,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式:terminal(默认)/ md / json(AI 消费)"),
    ] = export.OutputFormat.terminal,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help="仅用于 --format json:输出低字段量结果 + data_availability",
        ),
    ] = False,
    fields: Annotated[
        list[str],
        typer.Option(
            "--fields",
            help="仅用于 --format json:字段白名单,例 code,name,price,context.positions,valuation.pe_ttm",
        ),
    ] = [],  # noqa: B006 · typer multi-option 需要 list 默认值
) -> None:
    """按你的规则筛股 · 不替你定规则 (v0.0.6.4 MVP · 地基-2 加 JSON)

    示例:
      kan find --pos 180:lt:5                          # 180 日位置 < 5%
      kan find --resonance low:gte:3                   # 低点共振 ≥ 3 周期
      kan find --pos 60:lt:10 --resonance low:gte:2    # 多条件 AND
      kan find --industry 半导体 --pos 180:lt:10       # 半导体里 180 日位置 < 10%
      kan find --exclude-st --pos 180:lt:5             # 排 ST + 位置 filter
      kan find --industry 半导体 --format json         # 整池全维度 JSON(AI 取数)
      kan find --industry 半导体 --pe lt:30 --moneyflow gt:0  # 估值+资金组合
      kan find --all --pe lt:20 --format json          # 全市场 PE<20 截面筛
      kan find --codes 600519,000858 --pos 180:lt:20   # 自定义代码池里筛位置
      printf "600519\n000858\n" | kan find --codes - --gain 30:gt:10
      kan find --all --rsi lt:30 --streak gte:3 --format json  # 全市场 RSI<30 + 连板≥3
      kan find --industry 半导体 --top10 gte:50 --format json  # 半导体里前十大流通集中度≥50%

    Filter:
      --pos PERIOD:OP:VAL    PERIOD 取 3/5/7/10/15/30/60/90/120/180 · OP 取 lt/lte/gt/gte/eq/ne
      --resonance LEVEL:OP:VAL   LEVEL 取 low/high · OP 同上 · VAL 取 [0, 10]
      --pe OP:VAL            PE TTM 裸值筛 · 例 lt:20 (整合-1)
      --roe OP:VAL           ROE % 裸值筛 · 例 gte:15 · 逐股 · --all 不支持 (整合-1)
      --moneyflow OP:VAL     主力净额(万元) · 例 gt:0 净流入 (整合-1)
      --rsi/--macd-dif/--macd/--kdj-j OP:VAL  技术裸值筛 · 前复权 · 例 --rsi lt:30 (整合-2)
      --streak OP:VAL        连板天数 · 例 gte:3 · 不含 ST (整合-2)
      --winner OP:VAL        获利盘% · 例 gte:50 (整合-2)
      --ma-bias PERIOD:OP:VAL  乖离率 · PERIOD 取 5/10/20/60 · 例 20:gt:0 (收盘距 20 日线)
      --gain PERIOD:OP:VAL   近 N 日涨幅% · 例 30:gt:20 · K 线池/--all 预计算快照
      --atr-pct OP:VAL       ATR 波动率% · 例 lt:5 (atr/close · 裸值)
      --up-days OP:VAL       连阳天数 · 例 gte:3 · K 线池/--all 预计算快照
      --holders OP:VAL       股东户数环比% · 例 lt:0 (户数减少) · 逐股 · --all 不支持 (整合-3)
      --top10 OP:VAL         前十大流通集中度% · 例 gte:50 · 逐股 · --all 不支持 (整合-3)
      --north OP:VAL         北向持股% · 例 gte:3 (香港中央结算季度代理) · 逐股 · --all 不支持 (整合-3)
      --exclude-st           排 ST (quiet · 不记 triggered)

    输出 (地基-2):
      --format terminal  默认 · Rich 表格 (需至少一个 filter)
      --format json      AI 友好 · 命中带 metadata · 无 filter = 整池取数
      --compact          json 低字段量输出 · 适合脚本/外部模型首轮筛选
      --fields LIST      json 字段白名单 · 例 code,name,price,context.positions,valuation.pe_ttm
      --format md        markdown 表格

    池 selector (跟 kan scan 一致 · 三者互斥):
      --industry NAME / --hot rank|surge / --theme NAME (不指定默认自选)
      --codes LIST (逗号/空格/换行分隔 · `--codes -` 从 stdin 读)
      --only-watchlist (需配合 pool · 取交集)
      --group GROUP (选自选股具名组)
    """
    from datetime import datetime

    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from kan.core.enrich import enrich_results
        from kan.core.find_dsl import ConditionSet, FilterParseError
        from kan.core.find_filter import apply_conditions, apply_cross_section_conditions
        from kan.core.pipeline import render_freshness_warning, run_data_pipeline
        from kan.core.scanner import scan_batch
        from kan.core.stock_set import from_flags
        from kan.render import terminal
        from kan.render.base import FIND_DISCLAIMER_TEXT, responsive_periods

    console = Console()
    find_disclaimer = f"[bold dim]{FIND_DISCLAIMER_TEXT}[/bold dim]"
    is_export = fmt is not export.OutputFormat.terminal
    if compact and fmt is not export.OutputFormat.json:
        _print_err("❌ --compact 仅支持 --format json")
        raise typer.Exit(2)
    if fields and fmt is not export.OutputFormat.json:
        _print_err("❌ --fields 仅支持 --format json")
        raise typer.Exit(2)
    if compact and fields:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message="--fields 与 --compact 不能同时使用",
            hint="二者都定义结果字段形态；需要显式字段时只用 --fields",
            exit_code=2,
        )
    try:
        field_paths = parse_find_fields(fields)
    except ValueError as e:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message=str(e),
            hint="例: --fields code,name,price,context.positions,valuation.pe_ttm",
            exit_code=2,
        )
    field_dimensions = dimensions_from_fields(field_paths)

    # 0. Validate --limit · 防 Python 负切片导致的 silent data loss
    # limit=None 哨兵:K 线模式后续解析为 50 · 截面模式 (--all) 为全量。
    if limit is not None and limit <= 0:
        _print_err("❌ --limit 必须为正整数 (例 --limit 20)")
        raise typer.Exit(2)

    # 1. Parse DSL flags
    try:
        conditions = ConditionSet.from_flags(
            pos=pos,
            resonance=resonance,
            pe=pe,
            roe=roe,
            moneyflow=moneyflow,
            rsi=rsi,
            macd_dif=macd_dif,
            macd=macd,
            kdj_j=kdj_j,
            streak=streak,
            winner=winner,
            ma_bias=ma_bias,
            gain=gain,
            atr_pct=atr_pct,
            up_days=up_days,
            holders=holders,
            top10=top10,
            north=north,
            exclude_st=exclude_st,
        )
    except FilterParseError as e:
        _print_err(f"❌ {e}")
        raise typer.Exit(2) from e

    # 无 filter:terminal 默认报错引导 (人类 UX 不变 · 测试守护);
    # json/md 放开 = AI 取数环节 (整池全维度 · PRD §5 "不带 filter = 数据 provider")。
    if conditions.is_empty() and not is_export and not all_stocks:
        _print_err(
            "❌ 至少需要一个 filter (--pos / --resonance / --exclude-st)\n"
            "💡 例: kan find --pos 180:lt:5 (找 180 日位置 < 5% 的股票)\n"
            "💡 取数模式: kan find --industry 半导体 --format json (整池全维度)"
        )
        raise typer.Exit(1)

    # 2. Validate pool flags (复用 scan 互斥校验)
    if sum(1 for x in (industry, hot, theme, codes) if x is not None) > 1:
        _print_err("❌ --industry / --hot / --theme / --codes 四者互斥")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None or theme is not None or codes is not None
    if codes is not None and only_watchlist:
        _print_err("❌ --codes 与 --only-watchlist 不能同时使用")
        raise typer.Exit(2)
    if codes is not None and group is not None:
        _print_err("❌ --codes 已显式指定候选池 · 不再叠加 --group")
        raise typer.Exit(2)
    code_pairs = _resolve_code_pairs(codes) if codes is not None else None

    # 2.5 全市场截面取数 (--all) · 不走 K 线管线 (截面专用路径 · PRD §3.2) · 早返回不读自选
    if all_stocks:
        if source_mode:
            _print_err("❌ --all 与 --industry / --hot / --theme / --codes 互斥")
            raise typer.Exit(2)
        if conditions.needs_fundamentals():
            _print_err(
                "❌ --all 全市场截面不支持 --roe (fina_indicator 逐股 · 全市场 ~5500 只代价高)\n"
                "   质量筛请缩小池 · 例 kan find --industry 半导体 --roe gte:15"
            )
            raise typer.Exit(2)
        if conditions.needs_shareholder():
            _print_err(
                "❌ --all 全市场截面不支持 --holders/--top10/--north (股东数据逐股 · 全市场 ~5500 只代价高)\n"
                "   持股结构筛请缩小池 · 例 kan find --industry 半导体 --top10 gte:50"
            )
            raise typer.Exit(2)
        unsupported_fields = field_dimensions & DIMENSIONS_UNSUPPORTED_IN_ALL
        if unsupported_fields:
            _exit_find_error(
                fmt,
                code="invalid_fields",
                message=(
                    "--all 全市场截面不支持这些 --fields 维度: "
                    + ", ".join(sorted(unsupported_fields))
                ),
                hint="去掉逐股维度字段,或缩小候选池后再查",
                exit_code=2,
            )
        if not is_export:
            _print_err(
                "❌ --all 截面取数请配 --format json 或 --format md\n"
                "   (全市场 ~5500 只 · terminal 表格不适合 · json 供 AI 消费)"
            )
            raise typer.Exit(2)
        from kan.core.cross_section import run_cross_section
        from kan.core.stock_set import AllStocksSet

        cs = run_cross_section(
            AllStocksSet(),
            need_kline=conditions.has_kline_filters() or compact or fields_need_kline(field_paths),
            kline_periods=_kline_snapshot_periods(conditions),
        )
        if not cs.rows:
            _exit_find_error(
                fmt,
                code="data_unavailable",
                message="全市场截面无数据",
                hint=(
                    "估值/量价/资金/行业分位依赖 tushare；"
                    "设 TUSHARE_TOKEN 或运行 kan config set tushare-token <你的_token>"
                ),
            )
        # 截面类 filter (pe / moneyflow) · 无 filter → 全量返回 (取数语义)
        cs_matched = apply_cross_section_conditions(cs.rows, conditions)
        cs_limited = cs_matched if limit is None else cs_matched[:limit]
        query_time = datetime.now().astimezone().isoformat(timespec="seconds")
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.cross_section_payload(
                cs_limited,
                query_time=query_time,
                pool_size=cs.pool_size,
                data_cutoff=cs.data_cutoff,
                stale=cs.stale,
                filters=_find_filters(conditions),
                compact=compact,
                availability_rows=cs.rows,
                included_dimensions={"valuation", "moneyflow", "technical", "sentiment", "chip"},
                compact_dimensions=_compact_dimensions(conditions, is_export=is_export),
                fields=field_paths,
            )))
        else:  # md
            typer.echo(export.cross_section_markdown(
                [r for r, _ in cs_limited],
                title="慢慢看 · kan find · A股全市场截面",
                pool_size=cs.pool_size,
            ))
        return

    watchlist_pairs = (
        [] if code_pairs is not None else (
            _load_watchlist_pairs(group) if source_mode else _get_watchlist_pairs(group)
        )
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry/--hot/--theme")
        raise typer.Exit(1)

    # 3. Build StockSet · 复用 from_flags
    if code_pairs is not None:
        from kan.core.stock_set import CodeListSet

        stock_set = CodeListSet(code_pairs)
    else:
        stock_set = from_flags(
            industry=industry,
            hot=hot,
            theme=theme,
            watchlist_pairs=watchlist_pairs,
            only_watchlist=only_watchlist,
            watchlist_group=group,
        )

    # 4. Fetch + scan (复用 pipeline · low mode 算位置 + 共振)
    ctx = run_data_pipeline(stock_set, compute=scan_batch, mode="low")
    if not ctx.targets and only_watchlist:
        _exit_find_error(
            fmt,
            code="empty_intersection",
            message="自选股与当前候选池没有交集",
            hint="去掉 --only-watchlist，或先把目标股票加进自选",
        )
    if not ctx.results and not is_export:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    # 5. Enrich (按需 · 截面/财务 filter 依赖数据 → filter 前 enrich) + apply conditions
    # valuation/moneyflow 截面廉价 (全池=命中 同一次 HTTP) · fundamentals 逐股 (仅 --roe)。
    # limit 哨兵:K 线模式 None → 50 (截面 --all 已在 step 2.5 早返回)。
    effective_limit = limit if limit is not None else 50
    need_enrich = (
        (is_export and not field_paths)
        or conditions.has_cross_section_filters()
        or conditions.needs_fundamentals()
        or conditions.needs_shareholder()
        or bool(field_dimensions)
    )
    if need_enrich:
        pool_results = enrich_results(
            ctx.results,
            need_fundamentals=conditions.needs_fundamentals()
            or ("fundamentals" in field_dimensions),
            need_moneyflow=conditions.needs_moneyflow()
            or (is_export and conditions.is_empty() and not field_paths)
            or ("moneyflow" in field_dimensions),
            need_technical=conditions.needs_technical()
            or (is_export and conditions.is_empty() and not field_paths)
            or ("technical" in field_dimensions),
            need_sentiment=conditions.needs_sentiment()
            or (is_export and conditions.is_empty() and not field_paths)
            or ("sentiment" in field_dimensions),
            need_chip=conditions.needs_chip()
            or (is_export and conditions.is_empty() and not field_paths)
            or ("chip" in field_dimensions),
            need_shareholder=conditions.needs_shareholder()
            or ("shareholder" in field_dimensions),
        )
    else:
        pool_results = ctx.results
    gap = _find_data_gap(conditions, pool_results)
    if gap is not None:
        code, message, hint = gap
        _exit_find_error(fmt, code=code, message=message, hint=hint)
    matches = apply_conditions(pool_results, conditions)
    matches_limited = matches[:effective_limit]

    # 6. Export 分发 (json/md) · m.result 已按需 enrich (is_export → need_enrich) → 全维度
    if is_export:
        entries = [(m, m.result) for m in matches_limited]
        pools = _find_pools(industry, hot, theme, group, code_pairs)
        filters = _find_filters(conditions)
        query_time = datetime.now().astimezone().isoformat(timespec="seconds")
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.find_payload(
                entries,
                query_time=query_time,
                pools=pools,
                filters=filters,
                pool_size=len(ctx.results),
                matched_total=len(matches),
                freshness=ctx.freshness,
                compact=compact,
                availability_results=pool_results,
                included_dimensions=_availability_dimensions(
                    conditions,
                    is_export=is_export,
                    field_dimensions=field_dimensions,
                    fields_mode=bool(field_paths),
                ),
                compact_dimensions=_compact_dimensions(conditions, is_export=is_export),
                fields=field_paths,
            )))
        else:  # md
            typer.echo(export.find_markdown(
                entries,
                title=f"慢慢看 · kan find · {stock_set.name}",
                pool_size=len(ctx.results),
                matched_total=len(matches),
            ))
        return

    # 7. Terminal 渲染 (默认 · 复用 scan_table 视觉一致)
    console.print(
        f"\n[bold]🔍 kan find · {stock_set.name} · "
        f"命中 {len(matches)} / {len(ctx.results)} 只"
        f"{f' · 限 {effective_limit} 显示' if len(matches) > effective_limit else ''}[/bold]"
    )

    if not matches_limited:
        console.print("\n[yellow]  无股票符合您设置的所有 filter[/yellow]")
        console.print(
            "[dim]  💡 尝试放宽条件 · 例 --pos 180:lt:10 替代 --pos 180:lt:5[/dim]"
        )
        render_freshness_warning(ctx.freshness, console)
        console.print()
        console.print(find_disclaimer)
        return

    results_only = [m.result for m in matches_limited]
    display_periods = responsive_periods(console.width)
    table = terminal.scan_table(
        ctx,
        results_only,
        display_periods=display_periods,
        high_mode=False,
        signal_only=False,
        board_index_result=None,
    )
    console.print("[dim]💡 慢慢看是观察工具 · 不预测涨跌 · 详见底部免责[/dim]")
    console.print(table)

    # Triggered filters audit trail
    console.print()
    console.print("[bold]📋 触发的 filter:[/bold]")
    shown = 0
    for m in matches_limited:
        if not m.triggered:
            continue
        if shown >= 20:
            remaining = sum(1 for x in matches_limited[shown:] if x.triggered)
            if remaining > 0:
                console.print(
                    f"  [dim](还有 {remaining} 只命中 · 调小 filter 或减 --limit 看完整)[/dim]"
                )
            break
        trigs = " · ".join(
            f"{t.filter_type}={t.param}@{t.value:.1f}" for t in m.triggered
        )
        console.print(f"  [dim]{m.result.symbol} {m.result.name}[/dim] · {trigs}")
        shown += 1

    render_freshness_warning(ctx.freshness, console)
    console.print()
    console.print(find_disclaimer)
