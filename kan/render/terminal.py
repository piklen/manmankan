"""终端 rich.Table 构建层公共入口。

实现按命令族拆在 terminal_* 模块；本模块保留历史 import path：
`from kan.render import terminal`。
"""
from __future__ import annotations

from kan.render.terminal_common import _board_reference_label
from kan.render.terminal_compare import compare_table
from kan.render.terminal_extreme import extreme_table
from kan.render.terminal_history import history_table
from kan.render.terminal_hold import hold_table, render_hold_footer
from kan.render.terminal_info import board_position_table, info_table
from kan.render.terminal_range import downside_table, render_stock_range, upside_table
from kan.render.terminal_scan import scan_table, scan_title
from kan.render.terminal_trend import (
    theme_leaderboard_table,
    theme_leaderboard_title,
    trend_table,
    trend_title,
)

__all__ = [
    "_board_reference_label",
    "board_position_table",
    "compare_table",
    "downside_table",
    "extreme_table",
    "history_table",
    "hold_table",
    "info_table",
    "render_hold_footer",
    "render_stock_range",
    "scan_table",
    "scan_title",
    "theme_leaderboard_table",
    "theme_leaderboard_title",
    "trend_table",
    "trend_title",
    "upside_table",
]
