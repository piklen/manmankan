"""非终端导出的公共基础类型与小工具。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta

# kan find AI 消费 JSON 的 schema 契约版本。
# 这是数据契约版本 (供外部 AI 判断字段集) · 与包版本 (__version__) 不同命名空间:
# 字段集变更时才 bump · 加字段属向后兼容演进 (AI 见到更多字段 · 不破旧消费方)。
FIND_SCHEMA_VERSION = "0.0.6.8"
HOLD_SCHEMA_VERSION = 1
JSON_SCHEMA_VERSION = 1
_JSON_ENCODING_PROBE = "候选 ≠ 买入信号 · 贵州茅台"


def _board_reference_kind(meta: BoardMeta | HotMeta | ThemeMeta | None) -> str:
    """meta 类型对应的 reference kind 标识 · md / json 共用。"""
    from kan.core.models import ThemeMeta

    return "theme" if isinstance(meta, ThemeMeta) else "industry"


class OutputFormat(StrEnum):
    """--format 选项 · terminal 默认(现有行为) · md/json 为导出。"""

    terminal = "terminal"
    md = "md"
    json = "json"


def _stdout_needs_ascii_json() -> bool:
    """stdout 编码承载不了中文/符号时，JSON 自动退回 ASCII escape。"""
    encoding = getattr(sys.stdout, "encoding", None)
    if not encoding:
        return False
    try:
        _JSON_ENCODING_PROBE.encode(encoding)
    except LookupError:
        return False
    except UnicodeEncodeError:
        return True
    return False


def to_json(payload: dict) -> str:
    """统一 json 序列化 · UTF-8 终端保留中文 · 非 UTF stdout 可安全输出。"""
    return json.dumps(payload, ensure_ascii=_stdout_needs_ascii_json(), indent=2)


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


def query_time_now() -> str:
    """统一 JSON 查询时间戳 · 只表示本机命令生成响应的时间。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def success_envelope(
    command: str,
    *,
    query_time: str | None = None,
    schema_version: str | int = JSON_SCHEMA_VERSION,
    disclaimer: str | None = None,
    stats: dict | None = None,
    data_availability: dict | None = None,
) -> dict:
    """所有 JSON 成功响应共用的最小机器 envelope。

    旧命令仍保留自己的业务字段；这个 helper 只补齐 agent parser 需要的
    ok/schema_version/command/query_time/stats/data_availability 基础层。
    """
    payload: dict = {
        "ok": True,
        "schema_version": schema_version,
        "command": command,
        "query_time": query_time or query_time_now(),
    }
    if stats is not None:
        payload["stats"] = stats
    if data_availability is not None:
        payload["data_availability"] = data_availability
    payload["disclaimer"] = disclaimer if disclaimer is not None else _disclaimer_text()
    return payload


def _next_command_from_hint(hint: str | None) -> str | None:
    if not hint or "例:" not in hint:
        return None
    tail = hint.split("例:", 1)[1].strip()
    for sep in ("；", "\n"):
        if sep in tail:
            tail = tail.split(sep, 1)[0].strip()
    return tail or None


def error_payload(
    command: str,
    *,
    code: str,
    message: str,
    hint: str | None = None,
) -> dict:
    """机器消费错误 envelope · 避免 json 模式把业务失败落成纯文本。"""
    next_command = _next_command_from_hint(hint)
    payload: dict = {
        "ok": False,
        "command": command,
        "error": {
            "code": code,
            "reason": code,
            "message": message,
        },
    }
    if hint:
        payload["error"]["hint"] = hint
    if next_command:
        payload["error"]["next_command"] = next_command
    if command == "find":
        from kan.render.base import FIND_DISCLAIMER_TEXT

        payload["schema_version"] = FIND_SCHEMA_VERSION
        payload["disclaimer"] = FIND_DISCLAIMER_TEXT
    else:
        payload["schema_version"] = JSON_SCHEMA_VERSION
        payload["disclaimer"] = _disclaimer_text()
    return payload
