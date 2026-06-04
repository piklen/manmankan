"""kan/log.py debug_log helper 测试 (历史背景).

设计要求:
- KAN_DEBUG 不设 / 不是 truthy → no-op (默认静默 · 不打扰)
- KAN_DEBUG=1/true/yes/on → 写 logging.getLogger(module).debug
- caller __name__ 做 logger 隔离
"""
from __future__ import annotations

import logging

from kan.infra.log import _debug_enabled, debug_log


class TestDebugEnabled:
    """_debug_enabled 解析 KAN_DEBUG env var."""

    def test_unset_returns_false(self, monkeypatch):
        """env var 未设 → False"""
        monkeypatch.delenv("KAN_DEBUG", raising=False)
        assert _debug_enabled() is False

    def test_empty_returns_false(self, monkeypatch):
        """env var = '' → False"""
        monkeypatch.setenv("KAN_DEBUG", "")
        assert _debug_enabled() is False

    def test_zero_returns_false(self, monkeypatch):
        """env var = '0' → False (不是 truthy 值)"""
        monkeypatch.setenv("KAN_DEBUG", "0")
        assert _debug_enabled() is False

    def test_false_returns_false(self, monkeypatch):
        """env var = 'false' → False"""
        monkeypatch.setenv("KAN_DEBUG", "false")
        assert _debug_enabled() is False

    def test_one_returns_true(self, monkeypatch):
        """env var = '1' → True"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        assert _debug_enabled() is True

    def test_true_returns_true(self, monkeypatch):
        """env var = 'true' → True"""
        monkeypatch.setenv("KAN_DEBUG", "true")
        assert _debug_enabled() is True

    def test_yes_returns_true(self, monkeypatch):
        """env var = 'yes' → True"""
        monkeypatch.setenv("KAN_DEBUG", "yes")
        assert _debug_enabled() is True

    def test_on_returns_true(self, monkeypatch):
        """env var = 'on' → True"""
        monkeypatch.setenv("KAN_DEBUG", "on")
        assert _debug_enabled() is True

    def test_uppercase_true_returns_true(self, monkeypatch):
        """env var = 'TRUE' (大小写不敏感) → True"""
        monkeypatch.setenv("KAN_DEBUG", "TRUE")
        assert _debug_enabled() is True


class TestDebugLog:
    """debug_log 函数 · KAN_DEBUG 控制 logging.debug 调用."""

    def test_kan_debug_unset_no_log(self, monkeypatch, caplog):
        """KAN_DEBUG 未设 → 不调 logging.debug"""
        monkeypatch.delenv("KAN_DEBUG", raising=False)
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log("test.module", "test_op", ValueError("test error"))
        assert caplog.records == [], "KAN_DEBUG 未设时应静默 · 不写 log"

    def test_kan_debug_1_writes_log(self, monkeypatch, caplog):
        """KAN_DEBUG=1 → 写 debug log 含 op + exception type + message"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log("test.module", "fetch eastmoney", ValueError("HTTP 503"))
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "fetch eastmoney" in record.getMessage()
        assert "ValueError" in record.getMessage()
        assert "HTTP 503" in record.getMessage()

    def test_kan_debug_zero_no_log(self, monkeypatch, caplog):
        """KAN_DEBUG='0' → 静默 (0 不是 truthy 值)"""
        monkeypatch.setenv("KAN_DEBUG", "0")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log("test.module", "test_op", RuntimeError("test"))
        assert caplog.records == []

    def test_logger_module_isolation(self, monkeypatch, caplog):
        """不同 module 名走不同 logger · 用户可按模块过滤"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="kan.data.fetcher"):
            debug_log("kan.data.fetcher", "fetch_baostock", ConnectionError("timeout"))
        with caplog.at_level(logging.DEBUG, logger="kan.data.updater"):
            debug_log("kan.data.updater", "check_version", TimeoutError("rate limit"))
        # 两条 log 应该 isolated 到对应 logger name
        loggers = {r.name for r in caplog.records}
        assert "kan.data.fetcher" in loggers
        assert "kan.data.updater" in loggers

    def test_exception_message_preserved(self, monkeypatch, caplog):
        """exception 的 str 完整保留 · 不截断"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        long_msg = "x" * 500
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log("test.module", "op", ValueError(long_msg))
        assert long_msg in caplog.records[0].getMessage()


class TestRedact:
    """背景: debug_log path/token redact 防 issue 截图 PII leak"""

    def test_redact_home_dir_unix(self, monkeypatch, caplog):
        """mac/linux home dir 替换 · /Users/xiaobao → /Users/<user>"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log(
                "test.module",
                "read parquet",
                FileNotFoundError("/Users/realname/.local/share/kan/test.parquet"),
            )
        msg = caplog.records[0].getMessage()
        assert "/Users/<user>" in msg
        assert "realname" not in msg, "真名应被 redact 掉"

    def test_redact_home_dir_linux(self, monkeypatch, caplog):
        """/home/user 替换"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log("test.module", "op", OSError("Error at /home/realuser/data.json"))
        msg = caplog.records[0].getMessage()
        assert "/home/<user>" in msg
        assert "realuser" not in msg

    def test_redact_token_in_url(self, monkeypatch, caplog):
        """URL ?token=xxx 替换"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log(
                "test.module",
                "fetch api",
                ValueError("URL: https://api.example.com/v1/data?token=secret123&user=x"),
            )
        msg = caplog.records[0].getMessage()
        assert "token=<redacted>" in msg
        assert "secret123" not in msg

    def test_redact_token_in_json_body(self, monkeypatch, caplog):
        """JSON body/header token variants must not leak in debug output."""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log(
                "test.module",
                "post api",
                ValueError('body={"token":"SECRET_TK_123456","Authorization":"Bearer abc.def"}'),
            )
        msg = caplog.records[0].getMessage()
        assert '"token":"<redacted>"' in msg
        assert '"Authorization":"<redacted>"' in msg
        assert "SECRET_TK_123456" not in msg
        assert "abc.def" not in msg

    def test_redact_bearer_token(self, monkeypatch, caplog):
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log("test.module", "auth", ValueError("Authorization: Bearer abc.def-ghi"))
        msg = caplog.records[0].getMessage()
        assert "Bearer <redacted>" in msg
        assert "abc.def-ghi" not in msg

    def test_redact_windows_path(self, monkeypatch, caplog):
        r"""Windows path C:\Users\realname → C:\Users\<user>"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log(
                "test.module",
                "win op",
                OSError(r"Cannot access C:\Users\realname\AppData\file.json"),
            )
        msg = caplog.records[0].getMessage()
        assert r"C:\Users\<user>" in msg
        assert "realname" not in msg

    def test_redact_no_pii_keeps_msg_intact(self, monkeypatch, caplog):
        """无 PII 的 message 不被 redact · 完整保留"""
        monkeypatch.setenv("KAN_DEBUG", "1")
        with caplog.at_level(logging.DEBUG, logger="test.module"):
            debug_log(
                "test.module",
                "no pii",
                ValueError("simple error without paths or tokens"),
            )
        msg = caplog.records[0].getMessage()
        assert "simple error without paths or tokens" in msg
