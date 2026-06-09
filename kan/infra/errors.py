"""用户面错误消息整理 helper。"""
from __future__ import annotations

import os
import re as _re

_HOME_PREFIX = os.path.expanduser("~")
_ABS_PATH_PATTERN = _re.compile(r"/[\w/.\-]+/([\w.\-]+)")
_NETWORK_ERR_KEYWORDS = (
    "Max retries",
    "Timeout",
    "HTTPSConnection",
    "HTTPConnection",
    "ConnectionError",
    "ConnectionResetError",
    "Read timed out",
    "URLError",
    "RemoteDisconnected",
    "Failed to establish",
)


def safe_error_msg(e: Exception, max_len: int = 200) -> str:
    """脱敏异常消息：替换 home 路径为 ~ · 隐藏绝对路径前缀 · 截断超长消息。"""
    msg = str(e)
    if _HOME_PREFIX and _HOME_PREFIX != "/":
        msg = msg.replace(_HOME_PREFIX, "~")
    msg = _ABS_PATH_PATTERN.sub(r"<...>/\1", msg)
    if len(msg) > max_len:
        msg = msg[: max_len - 3] + "..."
    return msg


def network_error_msg(err: str) -> str:
    """把网络异常 traceback 简化为用户友好提示。"""
    if any(k in err for k in _NETWORK_ERR_KEYWORDS):
        return "网络异常 · 请检查连接或稍后重试"
    if "无效股票代码或无数据" in err:
        return "无数据（可能停牌 / 退市）"
    return safe_error_msg(ValueError(err), max_len=60)
