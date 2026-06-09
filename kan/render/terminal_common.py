"""终端渲染共用 helper。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta


# ── 共用 reference label ──────────────────────────────────────────────


def _board_reference_label(
    name: str, meta: BoardMeta | HotMeta | ThemeMeta | None,
) -> str:
    """板块 / 题材指数 reference 行的名称单元格 · scan / low / high 共用。

    industry 模式 → 「🏛️ X 板块指数」 · theme 模式 → 「🎯 X 题材指数」
    单 SOT 化以前 scan_table 内硬编码 🏛️ 的写法,避免 scan 与 low/high 视觉漂移。
    """
    from kan.core.models import ThemeMeta

    if isinstance(meta, ThemeMeta):
        return f"🎯 {name} 题材指数"
    return f"🏛️ {name} 板块指数"
