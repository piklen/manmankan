"""入口模块 _install_doh_dns 覆盖。"""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from unittest.mock import MagicMock, patch

from kan._entry import _install_doh_dns, _is_shell_completion_run, main


class TestInstallDohDns:
    def test_skips_when_shell_completion(self):
        """_KAN_COMPLETE=1 时直接返回，不 import doh_dns。"""
        with patch.dict(os.environ, {"_KAN_COMPLETE": "1"}):
            # _is_shell_completion_run 返回 True，函数提前 return
            _install_doh_dns()
            # 不抛异常 = 正确跳过

    def test_installs_when_not_completion(self):
        """正常模式下调 doh_dns.install()。"""
        # 确保 _KAN_COMPLETE 未设置
        with patch.dict(os.environ, {}, clear=True), \
             patch("kan.infra.doh_dns.install") as mock_install:
            _install_doh_dns()
            mock_install.assert_called_once()

    def test_exception_silently_passes(self):
        """doh_dns 模块抛异常不阻塞启动（except Exception: pass）。"""
        with patch.dict(os.environ, {}, clear=True), \
             patch("kan.infra.doh_dns.install", side_effect=RuntimeError("boom")):
            # 不抛异常
            _install_doh_dns()


class TestIsShellCompletionRun:
    def test_env_var_triggers_completion(self):
        assert _is_shell_completion_run() is False
        with patch.dict(os.environ, {"_KAN_COMPLETE": "1"}):
            assert _is_shell_completion_run() is True

    def test_typer_complete_args_triggers_completion(self):
        with patch.dict(os.environ, {"_TYPER_COMPLETE_ARGS": "some_args"}):
            assert _is_shell_completion_run() is True


class TestMainCallsInstallDohDns:
    def test_main_reaches_install_doh_dns(self):
        """main() 在正常路径中调 _install_doh_dns（第 109 行调用点覆盖）。
        用 sys.modules mock 替代 kan.cli 整树导入，避免测试耗时。"""
        import kan._entry as entry_module

        # 预置 sys.modules mock，让 main() 的 local import 走 mock
        mock_cli = MagicMock()
        mock_cli.cli_main = MagicMock(side_effect=SystemExit(0))
        with (
            patch.object(entry_module, "_maybe_print_boot_banner"),
            patch.object(entry_module, "_install_doh_dns") as mock_install,
            patch.dict(sys.modules, {"kan.cli": mock_cli}),
            patch.object(sys, "argv", ["kan", "info", "600519"]),
        ):
            with suppress(SystemExit):
                main()
            mock_install.assert_called_once()
