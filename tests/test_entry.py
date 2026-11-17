"""帮助命令不应加载数据源或原生执行器。"""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

from kan._entry import main


def test_find_help_skips_data_source_bootstrap():
    """单命令帮助页不应加载 mini-racer 或安装 DoH。"""
    import kan._entry as entry_module

    mock_cli = MagicMock()
    mock_cli.cli_main = MagicMock()
    with (
        patch.object(entry_module, "_maybe_print_boot_banner"),
        patch.object(entry_module, "_patch_mini_racer") as mock_patch,
        patch.object(entry_module, "_install_doh_dns") as mock_install,
        patch.dict(sys.modules, {"kan.cli": mock_cli}),
        patch.object(sys, "argv", ["kan", "find", "--help"]),
    ):
        main()

    mock_patch.assert_not_called()
    mock_install.assert_not_called()
    mock_cli.cli_main.assert_called_once()


def test_redirected_start_page_uses_utf8_with_a_western_default():
    # 模拟英文 Windows 的重定向流，在所有 CI 平台保留同一条用户路径。
    env = os.environ.copy()
    env.pop("PYTHONIOENCODING", None)
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.stdout.reconfigure(encoding='cp1252'); "
         "from kan._entry import main; main()"],
        env=env, stdout=subprocess.PIPE, check=True,
    )
    assert "慢慢看" in result.stdout.decode("utf-8")
