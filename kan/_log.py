"""统一 debug logging · 通过 KAN_DEBUG env var 控制可见.

合并实施:
- ***REMOVED*** (v0.0.4.8): fetcher.py 4 处 hot-path broad except 加 debug log
- P2 backlog A.2: 统一 debug 通道 helper

设计:
- 默认 no-op (KAN_DEBUG 不设) · 不打扰
- KAN_DEBUG=1/true/yes/on → 写 logging.getLogger(module).debug
- caller 用 __name__ 做 module · 自然 logger 隔离
"""
from __future__ import annotations

import logging
import os
import re


def _debug_enabled() -> bool:
    """KAN_DEBUG 是 truthy 值时返 True."""
    return os.environ.get("KAN_DEBUG", "").lower() in ("1", "true", "yes", "on")


# ***REMOVED*** (v0.0.4.8 finalize): path/token redact 防 issue 截图 leak
# 用户开 KAN_DEBUG=1 后截图发 issue 会暴露 username / 本地路径 / API token
# 这里 best-effort 替换常见 PII pattern · 不保证 100% 覆盖 · 仍提醒 docstring
_REDACT_PATTERNS = [
    # mac/linux home dir: /Users/xiao / /home/xiao → /Users/<user> / /home/<user>
    (re.compile(r"(/(?:Users|home))/[^/\s]+"), r"\1/<user>"),
    # token=xxx 或 ?key=xxx in URL → <redacted>
    (re.compile(r"([?&](?:token|key|api_key|secret|auth)=)[^&\s]+"), r"\1<redacted>"),
    # Windows path C:\Users\xiao → C:\Users\<user>
    (re.compile(r"([A-Z]:\\Users\\)[^\\\s]+"), r"\1<user>"),
]


def _redact(text: str) -> str:
    """对 debug log 文本做 best-effort path/token redact (***REMOVED***)."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def debug_log(module: str, op: str, err: BaseException) -> None:
    """单点 debug log entry · 走 logging.getLogger(module) · KAN_DEBUG env var 控制可见.

    Args:
        module: caller __name__ (用于 logger 隔离 · 让用户能按模块过滤)
        op: 操作描述 (e.g. "fetch eastmoney", "read parquet cutoff")
        err: 捕获的异常对象 (含 type + str · 不暴露 traceback)

    Examples:
        from kan._log import debug_log

        try:
            risky_op()
        except Exception as e:
            debug_log(__name__, "fetch eastmoney", e)
            return None

    用户开 KAN_DEBUG=1 后 stderr 显示:
        DEBUG:kan.fetcher:fetch eastmoney: ConnectionError: HTTPSConnectionPool ...

    ***REMOVED*** (v0.0.4.8 finalize): str(err) 经 _redact 处理:
        - /Users/<真名> → /Users/<user>
        - token=xxx → token=<redacted>
    截图发 issue 时 best-effort 防 PII leak · 但**不保证 100% 覆盖** (e.g. IP / 内部 hostname 未 redact)
    用户应在公网共享 debug log 前自查。
    """
    if _debug_enabled():
        msg = _redact(f"{op}: {type(err).__name__}: {err}")
        logging.getLogger(module).debug("%s", msg)
