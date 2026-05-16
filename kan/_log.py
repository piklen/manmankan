"""统一 debug logging · 通过 KAN_DEBUG env var 控制可见.

合并实施:
- CR-4 (v0.0.4.8): fetcher.py 4 处 hot-path broad except 加 debug log
- P2 backlog A.2: 统一 debug 通道 helper

设计:
- 默认 no-op (KAN_DEBUG 不设) · 不打扰
- KAN_DEBUG=1/true/yes/on → 写 logging.getLogger(module).debug
- caller 用 __name__ 做 module · 自然 logger 隔离
"""
from __future__ import annotations

import logging
import os


def _debug_enabled() -> bool:
    """KAN_DEBUG 是 truthy 值时返 True."""
    return os.environ.get("KAN_DEBUG", "").lower() in ("1", "true", "yes", "on")


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
    """
    if _debug_enabled():
        logging.getLogger(module).debug("%s: %s: %s", op, type(err).__name__, err)
