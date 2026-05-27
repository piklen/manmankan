"""统一 debug logging · 通过 KAN_DEBUG env var 控制可见.

合并实施:
- v0.0.4.8: fetcher.py 4 处 hot-path broad except 加 debug log
- 统一 debug 通道 helper

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


_HANDLER_INSTALLED = False


def _ensure_kan_handler() -> None:
    """KAN_DEBUG=1 时，给 `kan` namespace logger 装 StreamHandler(stderr)。

    Python logging 默认 root level=WARNING + 无 handler · DEBUG 永远被吞 ·
    没这步用户开 KAN_DEBUG=1 也看不到任何 debug_log 输出(P0 嫌疑修复)。
    幂等 · 模块级 flag 防多次安装重复输出。
    propagate 保留默认 True · pytest caplog 通过 root 拦截 · 也兼容用户
    自配 root handler;CLI 进程通常没有 root handler · 不会双输出。
    """
    global _HANDLER_INSTALLED
    if _HANDLER_INSTALLED:
        return
    logger = logging.getLogger("kan")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()  # stderr by default
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(handler)
    _HANDLER_INSTALLED = True


# v0.0.4.8 finalize: path/token redact 防 issue 截图 leak
# 用户开 KAN_DEBUG=1 后截图发 issue 会暴露 username / 本地路径 / API token
# 这里 best-effort 替换常见 PII pattern · 不保证 100% 覆盖 · 仍提醒 docstring
_REDACT_PATTERNS = [
    # mac/linux home dir: /Users/xiao / /home/xiao → /Users/<user> / /home/<user>
    (re.compile(r"(/(?:Users|home))/[^/\s]+"), r"\1/<user>"),
    # token=xxx 或 ?key=xxx in URL → <redacted>
    (re.compile(r"([?&](?:token|key|api_key|secret|auth)=)[^&\s]+"), r"\1<redacted>"),
    # Windows path C:\Users\xiao → C:\Users\<user>
    (re.compile(r"([A-Z]:\\Users\\)[^\\\s]+"), r"\1<user>"),
    # v0.0.5.0: body 文本里的裸 token 兜底
    # 防 TuShare 服务端返回 msg 含 "token xxxxx invalid" 直接进日志
    (re.compile(r"\btoken[\s=:]+[A-Za-z0-9_\-]{8,}", re.I), "token <redacted>"),
]


def redact_text(text: str) -> str:
    """对任何用户可见文本做 best-effort path/token redact (public · 跨模块可用)。

    用例:
    - debug_log 内部 sanitize 异常文本(原有用法)
    - tushare server msg 透传给用户前 sanitize (v0.0.6.5 后 · _post_tushare_api)
    - 任何要打印给用户的含 PII 文本

    覆盖: home dir / URL token 参数 / Windows path / body 文本里裸 token
    """
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
        from kan.infra.log import debug_log

        try:
            risky_op()
        except Exception as e:
            debug_log(__name__, "fetch eastmoney", e)
            return None

    用户开 KAN_DEBUG=1 后 stderr 显示:
        DEBUG:kan.data.fetcher:fetch eastmoney: ConnectionError: HTTPSConnectionPool ...

    v0.0.4.8 finalize · str(err) 经 redact_text 处理:
        - /Users/<真名> → /Users/<user>
        - token=xxx → token=<redacted>
    截图发 issue 时 best-effort 防 PII leak · 但**不保证 100% 覆盖** (e.g. IP / 内部 hostname 未 redact)
    用户应在公网共享 debug log 前自查。
    """
    if _debug_enabled():
        _ensure_kan_handler()
        msg = redact_text(f"{op}: {type(err).__name__}: {err}")
        logging.getLogger(module).debug("%s", msg)
