"""题材扫描渲染层 helper · 三层信息架构。

层 1:题材指数本身位置(1 行 metadata · 由 cli_scan_cmds 的 board_index_result 复用渲染)
层 2:成分股 N 行表(共用 scan 现有 render_scan_table)
层 3:散户警示 4 行强 disclaimer
"""
from __future__ import annotations

import typer

# 题材 disclaimer 3 个关键短语 SOT · 所有调用点 import 同一份(防 4 处不一致漂移)
# scan/info 用全 4 行 · add/remove 二次确认 + theme list 用其中部分
THEME_CLASSIFICATION = "题材分类各家口径不同(本工具用同花顺口径)"
THEME_RISK = "题材跟风风险高于行业"
THEME_VS_INDUSTRY = "题材是标签 · 一只股可能在多个题材中"
# 历史背景`kan theme trend` 专属 · 连涨连跌榜诱导追高/抄底风险
THEME_TREND_DISCLAIMER = "连涨 ≠ 还会涨 · 连跌 ≠ 还会跌 · 题材方向变化比个股快"


def render_theme_disclaimer() -> None:
    """4 行强 disclaimer(AGENTS.md §6 · 不省一行)。

    题材线 disclaimer 比 --industry 多一档:加 "题材跟风风险高于行业"。
    """
    typer.echo("")
    typer.echo("💡 数据源:同花顺 catalog/成分股 · 东方财富 K 线/反查")
    typer.echo("⚠️  位置 ≠ 买卖信号  ·  共振低位区间 ≠ 买入建议")
    typer.echo(f"⚠️  {THEME_CLASSIFICATION} · 同名题材成分股可能差异  ·  {THEME_RISK}")
    typer.echo("ℹ️  manmankan 是观察工具 · 不预测涨跌 · 不荐股")


def render_theme_trend_disclaimer(*, source: str = "em") -> None:
    """`kan theme trend` 专属 disclaimer · 比 scan 题材多一行连涨连跌 anti-FOMO。

    沿用 render_theme_disclaimer 4 行 + 多 1 行 THEME_TREND_DISCLAIMER。
    数据源行根据实际运行路径动态:
    - source='tushare' → "TuShare Pro ths_daily 批量"
    - source='em'(默认)→ "同花顺 catalog · 东方财富题材 K 线"
    """
    if source == "tushare":
        data_source_line = "💡 数据源:TuShare Pro ths_daily 批量 · 12h cache"
    else:
        data_source_line = "💡 数据源:同花顺 catalog · 东方财富题材 K 线 · 24h cache"
    typer.echo("")
    typer.echo(data_source_line)
    typer.echo("⚠️  位置 ≠ 买卖信号  ·  共振低位区间 ≠ 买入建议")
    typer.echo(f"⚠️  {THEME_CLASSIFICATION} · 同名题材成分股可能差异  ·  {THEME_RISK}")
    typer.echo(f"⚠️  {THEME_TREND_DISCLAIMER}")
    typer.echo("ℹ️  manmankan 是观察工具 · 不预测涨跌 · 不荐股")
