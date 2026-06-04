"""atexit hook 在 shell completion 调用中必须完全静默。

历史背景回归 case: `kan upd<Tab>` 触发 zsh completion 时，atexit 弹
`typer.prompt("是否启用「以后自动升级」 [y/n/skip]", ...)`，prompt 文本
默认写到 stdout，被 zsh `eval $(env _KAN_COMPLETE=complete_zsh kan)` 抓走
当 spec 解析，报 `_arguments:comparguments:327: invalid argument`。

修复护栏（双重）:
  1. `_is_shell_completion_run()` 检测 `_KAN_COMPLETE` / `_TYPER_COMPLETE_ARGS`
     任一被设置 → 两个 hook 立即 return
  2. isatty 检查从 `or` 改为 `and` (stdout 被 pipe 即跳过,更严格)
"""

from __future__ import annotations

import io
import sys

import pytest


class _FakeStream:
    """模拟 stdout/stderr · 可控 isatty + 抓 write 内容。"""

    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty
        self._buf = io.StringIO()

    def isatty(self) -> bool:
        return self._is_tty

    def write(self, s: str) -> int:
        self._buf.write(s)
        return len(s)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self._buf.getvalue()


@pytest.fixture
def completion_streams(monkeypatch):
    """模拟 zsh completion 真实场景: stdout 被 eval 抓 (非 tty) · stderr 仍是 tty。"""
    out = _FakeStream(is_tty=False)
    err = _FakeStream(is_tty=True)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    return out, err


@pytest.fixture
def block_network(monkeypatch):
    """禁止任何 PyPI / config 写入 · hermetic 测试。"""
    monkeypatch.setattr(
        "kan.data.updater.fetch_latest_version_from_pypi",
        lambda: pytest.fail("hook 不该在 completion 时打 PyPI"),
    )


# ── _is_shell_completion_run 单测 ─────────────────────────────────────


def test_is_shell_completion_run_detects_KAN_COMPLETE(monkeypatch):
    monkeypatch.setenv("_KAN_COMPLETE", "complete_zsh")
    monkeypatch.delenv("_TYPER_COMPLETE_ARGS", raising=False)
    from kan.cli.atexit import _is_shell_completion_run
    assert _is_shell_completion_run() is True


def test_is_shell_completion_run_detects_TYPER_COMPLETE_ARGS(monkeypatch):
    monkeypatch.delenv("_KAN_COMPLETE", raising=False)
    monkeypatch.setenv("_TYPER_COMPLETE_ARGS", "kan upd")
    from kan.cli.atexit import _is_shell_completion_run
    assert _is_shell_completion_run() is True


def test_is_shell_completion_run_false_when_neither_set(monkeypatch):
    monkeypatch.delenv("_KAN_COMPLETE", raising=False)
    monkeypatch.delenv("_TYPER_COMPLETE_ARGS", raising=False)
    from kan.cli.atexit import _is_shell_completion_run
    assert _is_shell_completion_run() is False


# ── _check_updates_atexit 在 completion 流程必须静默 ──────────────────


def test_check_updates_skipped_when_KAN_COMPLETE_set(
    monkeypatch, completion_streams, block_network
):
    """关键回归: zsh completion 触发时 hook 不得写任何字符到 stdout/stderr。"""
    monkeypatch.setenv("_KAN_COMPLETE", "complete_zsh")
    monkeypatch.setenv("_TYPER_COMPLETE_ARGS", "kan upd")
    from kan.cli.atexit import _check_updates_atexit

    _check_updates_atexit()

    out, err = completion_streams
    assert out.getvalue() == ""
    assert err.getvalue() == ""


def test_check_updates_skipped_when_TYPER_COMPLETE_ARGS_only(
    monkeypatch, completion_streams, block_network
):
    """单独 _TYPER_COMPLETE_ARGS 也应跳过 (双护栏冗余)。"""
    monkeypatch.delenv("_KAN_COMPLETE", raising=False)
    monkeypatch.setenv("_TYPER_COMPLETE_ARGS", "kan upd")
    from kan.cli.atexit import _check_updates_atexit

    _check_updates_atexit()

    out, err = completion_streams
    assert out.getvalue() == ""
    assert err.getvalue() == ""


def test_check_updates_skipped_when_stdout_piped(
    monkeypatch, completion_streams, block_network
):
    """stdout 被 pipe (非 tty) 即跳过 · 不再依赖 stderr.isatty 兜底。

    防 or → and bug 回归: completion 之外的 pipe 场景 (kan info | grep) 同样
    不该弹 prompt。
    """
    monkeypatch.delenv("_KAN_COMPLETE", raising=False)
    monkeypatch.delenv("_TYPER_COMPLETE_ARGS", raising=False)
    from kan.cli.atexit import _check_updates_atexit

    _check_updates_atexit()

    out, err = completion_streams
    assert out.getvalue() == ""
    assert err.getvalue() == ""


# ── _auto_install_completion 同样需要在 completion 流程内静默 ─────────


def test_auto_install_completion_skipped_when_KAN_COMPLETE_set(
    monkeypatch, completion_streams
):
    """completion 触发时不得调 typer.completion.install (会写 shell rc 文件)。"""
    monkeypatch.setenv("_KAN_COMPLETE", "complete_zsh")
    monkeypatch.setenv("_TYPER_COMPLETE_ARGS", "kan upd")

    install_called = {"n": 0}

    def fake_install(shell: str, prog_name: str):  # pragma: no cover
        install_called["n"] += 1
        return shell, "/tmp/never"

    monkeypatch.setattr("typer.completion.install", fake_install)

    from kan.cli.atexit import _auto_install_completion
    _auto_install_completion()

    out, err = completion_streams
    assert install_called["n"] == 0
    assert out.getvalue() == ""
    assert err.getvalue() == ""
