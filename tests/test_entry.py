"""帮助命令不应加载数据源或原生执行器。"""

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
