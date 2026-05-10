"""kan completion 子命令测试 · 跨 shell（mac/linux/windows）"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from kan.cli import _detect_shell_fallback, app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── _detect_shell_fallback 单测 ────────────────────────────────────


def test_detect_shell_shellingham_zsh(monkeypatch):
    """shellingham 检测到 zsh 时优先返回。"""
    monkeypatch.setattr(
        "shellingham.detect_shell",
        lambda: ("zsh", "/bin/zsh"),
    )
    assert _detect_shell_fallback() == "zsh"


def test_detect_shell_shellingham_fail_fallback_env(monkeypatch):
    """shellingham 失败时 fallback 读 $SHELL。"""
    monkeypatch.setattr(
        "shellingham.detect_shell",
        lambda: (_ for _ in ()).throw(Exception("ShellDetectionFailure")),
    )
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    assert _detect_shell_fallback() == "bash"


def test_detect_shell_fish_via_env(monkeypatch):
    """$SHELL 路径含 fish 时识别。"""
    monkeypatch.setattr(
        "shellingham.detect_shell",
        lambda: (_ for _ in ()).throw(Exception()),
    )
    monkeypatch.setenv("SHELL", "/usr/local/bin/fish")
    assert _detect_shell_fallback() == "fish"


def test_detect_shell_windows_powershell(monkeypatch):
    """Windows 环境（os.name=nt 或 PSModulePath）兜底 powershell。"""
    monkeypatch.setattr(
        "shellingham.detect_shell",
        lambda: (_ for _ in ()).throw(Exception()),
    )
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setenv("PSModulePath", "C:\\WindowsPowerShell")
    assert _detect_shell_fallback() == "powershell"


def test_detect_shell_unknown_returns_none(monkeypatch):
    """所有检测都失败时返回 None。"""
    monkeypatch.setattr(
        "shellingham.detect_shell",
        lambda: (_ for _ in ()).throw(Exception()),
    )
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setattr("os.name", "posix")  # 装作 mac/linux 但无 SHELL
    assert _detect_shell_fallback() is None


# ── 错误路径 ──────────────────────────────────────────────────────


def test_invalid_shell_rejects(runner: CliRunner):
    """不支持的 shell 应给出友好错误 + 列出支持列表。"""
    result = runner.invoke(app, ["completion", "install", "csh"])
    assert result.exit_code == 1
    out = (result.output or "") + (result.stderr if hasattr(result, "stderr") else "")
    assert "不支持的 shell" in out or "csh" in out


def test_unknown_action_rejects(runner: CliRunner):
    """未知 action（不是 install）应报错。"""
    result = runner.invoke(app, ["completion", "uninstall", "zsh"])
    assert result.exit_code == 1


def test_install_without_shell_no_detection(runner: CliRunner, monkeypatch):
    """无法自动检测时给出明确 instruction。"""
    monkeypatch.setattr(
        "shellingham.detect_shell",
        lambda: (_ for _ in ()).throw(Exception()),
    )
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setattr("os.name", "posix")
    result = runner.invoke(app, ["completion", "install"])
    assert result.exit_code == 1


# ── install 路径（mock 真实写文件）───────────────────────────────


def test_install_zsh_calls_typer(runner: CliRunner, tmp_path, monkeypatch):
    """install zsh 应调用 typer.completion.install 且传 shell=zsh。"""
    called: dict = {}

    def fake_install(shell: str, prog_name: str):
        called["shell"] = shell
        called["prog_name"] = prog_name
        return shell, str(tmp_path / "_kan")

    monkeypatch.setattr("typer.completion.install", fake_install)

    result = runner.invoke(app, ["completion", "install", "zsh"])
    assert result.exit_code == 0
    assert called["shell"] == "zsh"
    assert called["prog_name"] == "kan"
    assert "已安装到" in result.output
