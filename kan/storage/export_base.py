"""非终端导出的公共基础类型与小工具。"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta

# kan find AI 消费 JSON 的 schema 契约版本。
# 这是数据契约版本 (供外部 AI 判断字段集) · 与包版本 (__version__) 不同命名空间:
# 字段集变更时才 bump · 加字段属向后兼容演进 (AI 见到更多字段 · 不破旧消费方)。
FIND_SCHEMA_VERSION = "0.0.6.8"
HOLD_SCHEMA_VERSION = 1


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


def _hold_disclaimer_text() -> str:
    from kan.render.base import HOLD_DISCLAIMER_TEXT

    return HOLD_DISCLAIMER_TEXT


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
