"""题材扫描渲染层 helper · 三层信息架构(spec §10)。

层 1:题材指数本身位置(1 行 metadata · 由 cli_scan_cmds 的 board_index_result 复用渲染)
层 2:成分股 N 行表(共用 scan 现有 render_scan_table)
层 3:散户警示 4 行强 disclaimer(spec §12.1 LOCKED)
"""
from __future__ import annotations

import typer


def render_theme_disclaimer() -> None:
    """4 行强 disclaimer(AGENTS.md §6 · spec §12.1 LOCKED · 不省一行)。

    题材线 disclaimer 比 --industry 多一档:加 "题材跟风风险高于行业"。
    """
    typer.echo("")
    typer.echo("💡 数据源:同花顺 catalog/成分股 · 东方财富 K 线/反查")
    typer.echo("⚠️  位置 ≠ 买卖信号  ·  共振低位区间 ≠ 买入建议")
    typer.echo("⚠️  题材分类各家口径不同 · 同名题材成分股可能差异  ·  题材跟风风险高于行业")
    typer.echo("ℹ️  manmankan 是观察工具 · 不预测涨跌 · 不荐股")
