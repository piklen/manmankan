"""kan/updater.py · PyPI 查询 + 版本对比 + 包管理器派发测试

守护:
- 网络失败 / timeout / 解析失败 → 静默 fallback (atexit hook 不破坏主命令)
- daily cache 命中不发请求 (隐私 + 性能)
- 版本号比较 (packaging + fallback)
- 安装方式检测 (uv tool / pipx / pip)
- 升级派发 (返回码 / timeout / 命令找不到)
"""

import json
import subprocess
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from kan.data import updater
from kan.storage import config, paths


class _FakeUrlResponse:
    """模拟 urllib.request.urlopen 返回的 context manager"""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> BytesIO:
        return BytesIO(self.body)

    def __exit__(self, *args) -> bool:
        return False


@pytest.fixture
def temp_config_path(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    return cfg_path


# --- fetch_latest_version_from_pypi ---


class TestFetchPypi:
    def test_success_returns_version(self):
        body = json.dumps({"info": {"version": "0.0.5"}}).encode()
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            return_value=_FakeUrlResponse(body),
        ):
            assert updater.fetch_latest_version_from_pypi() == "0.0.5"

    def test_url_error_returns_none(self):
        import urllib.error
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            assert updater.fetch_latest_version_from_pypi() is None

    def test_timeout_returns_none(self):
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            side_effect=TimeoutError("timeout"),
        ):
            assert updater.fetch_latest_version_from_pypi() is None

    def test_oserror_returns_none(self):
        """DNS / 路由 / socket 错误 → None"""
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            side_effect=OSError("network unreachable"),
        ):
            assert updater.fetch_latest_version_from_pypi() is None

    def test_non_dict_response_returns_none(self):
        body = json.dumps([1, 2, 3]).encode()
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            return_value=_FakeUrlResponse(body),
        ):
            assert updater.fetch_latest_version_from_pypi() is None

    def test_missing_info_returns_none(self):
        body = json.dumps({"other": {}}).encode()
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            return_value=_FakeUrlResponse(body),
        ):
            assert updater.fetch_latest_version_from_pypi() is None

    def test_missing_version_returns_none(self):
        body = json.dumps({"info": {"name": "manmankan"}}).encode()
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            return_value=_FakeUrlResponse(body),
        ):
            assert updater.fetch_latest_version_from_pypi() is None

    def test_invalid_json_returns_none(self):
        body = b"not valid json at all"
        with patch(
            "kan.data.updater.urllib.request.urlopen",
            return_value=_FakeUrlResponse(body),
        ):
            assert updater.fetch_latest_version_from_pypi() is None


# --- is_newer ---


class TestIsNewer:
    def test_strictly_newer(self):
        assert updater.is_newer("0.0.3", "0.0.2") is True

    def test_strictly_older(self):
        assert updater.is_newer("0.0.1", "0.0.2") is False

    def test_equal(self):
        assert updater.is_newer("0.0.2", "0.0.2") is False

    def test_minor_version_jump(self):
        assert updater.is_newer("0.1.0", "0.0.9") is True

    def test_major_version_jump(self):
        assert updater.is_newer("1.0.0", "0.99.0") is True


# --- check_for_updates ---


class TestCheckForUpdates:
    def test_cache_hit_does_not_call_pypi(self, temp_config_path):
        """daily cache 命中 · 不发网络请求 (隐私 + 性能 invariant)"""
        cfg = config.load()
        cfg["last_check_date"] = date.today().isoformat()
        cfg["latest_seen_version"] = "0.0.5"
        config.save(cfg)

        sentinel = MagicMock(side_effect=AssertionError("PyPI fetch should NOT be called"))
        with patch.object(updater, "fetch_latest_version_from_pypi", sentinel):
            info = updater.check_for_updates(force=False)

        assert info.latest == "0.0.5"
        assert info.from_cache is True
        sentinel.assert_not_called()

    def test_force_skips_cache(self, temp_config_path):
        """force=True 跳过 cache 强制查 (kan update 命令用)"""
        cfg = config.load()
        cfg["last_check_date"] = date.today().isoformat()
        cfg["latest_seen_version"] = "0.0.5"
        config.save(cfg)

        with patch.object(updater, "fetch_latest_version_from_pypi", return_value="0.0.7"):
            info = updater.check_for_updates(force=True)

        assert info.latest == "0.0.7"
        assert info.from_cache is False

    def test_cache_miss_writes_cache(self, temp_config_path):
        """cache miss 后写 cache · 下次命中"""
        with patch.object(updater, "fetch_latest_version_from_pypi", return_value="0.0.5"):
            info = updater.check_for_updates(force=False)

        assert info.from_cache is False
        cfg = config.load()
        assert cfg["last_check_date"] == date.today().isoformat()
        assert cfg["latest_seen_version"] == "0.0.5"

    def test_network_failure_returns_no_latest(self, temp_config_path):
        """网络失败 · latest=None · 不写 cache"""
        with patch.object(updater, "fetch_latest_version_from_pypi", return_value=None):
            info = updater.check_for_updates(force=False)

        assert info.latest is None
        assert info.has_update is False
        cfg = config.load()
        assert cfg["last_check_date"] is None  # 没写 cache

    def test_yesterday_cache_misses(self, temp_config_path):
        """昨天的 cache 不算命中 · 重新查"""
        cfg = config.load()
        cfg["last_check_date"] = (date.today() - timedelta(days=1)).isoformat()
        cfg["latest_seen_version"] = "0.0.5"
        config.save(cfg)

        with patch.object(updater, "fetch_latest_version_from_pypi", return_value="0.0.6"):
            info = updater.check_for_updates(force=False)

        assert info.latest == "0.0.6"
        assert info.from_cache is False


# --- detect_install_method ---


class TestDetectInstallMethod:
    # 背景: 升级命令全改为 force-reinstall 模式
    # 防 partial state 升级 (老 .so cache 不重链触发 macOS Gatekeeper 拒载)

    def test_uv_tool(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        result = updater.detect_install_method()
        assert result.name == "uv tool"
        assert result.upgrade_cmd == ["uv", "tool", "install", "--reinstall", "manmankan"]

    def test_pipx(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/pipx/venvs/manmankan/bin/python",
        )
        result = updater.detect_install_method()
        assert result.name == "pipx"
        assert result.upgrade_cmd == ["pipx", "install", "--force", "manmankan"]

    def test_pip_venv(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/projects/manmankan/.venv/bin/python",
        )
        result = updater.detect_install_method()
        assert result.name == "pip / venv"
        assert "manmankan" in result.upgrade_cmd
        assert "--force-reinstall" in result.upgrade_cmd

    def test_unknown_falls_back_to_uv_tool_guess(self, monkeypatch):
        """完全无法识别 · 兜底用 uv tool（最常见）"""
        monkeypatch.setattr("sys.executable", "/usr/bin/python3")
        result = updater.detect_install_method()
        assert "uv tool" in result.name

    def test_package_spec_can_pin_target_version(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        result = updater.detect_install_method("manmankan==0.0.6.8")
        assert result.upgrade_cmd == [
            "uv", "tool", "install", "--reinstall", "manmankan==0.0.6.8",
        ]


# --- run_upgrade ---


class TestRunUpgrade:
    def _make_completed(self, returncode: int, stdout: str = "", stderr: str = ""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_success_returncode_zero(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        with patch(
            "kan.data.updater.subprocess.run",
            return_value=self._make_completed(0, "Upgraded successfully"),
        ):
            status, msg = updater.run_upgrade()
        assert status == "success"
        assert msg == "uv tool"

    def test_target_version_pins_install_and_smoke(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return self._make_completed(0)

        with patch("kan.data.updater.subprocess.run", side_effect=fake_run):
            status, msg = updater.run_upgrade(target_version="0.0.6.8")

        assert status == "success"
        assert msg == "uv tool"
        assert calls[0] == [
            "uv", "tool", "install", "--reinstall", "manmankan==0.0.6.8",
        ]
        assert "from kan.api import WatchlistSet, fetch, from_flags, scan" in calls[1][2]
        assert "importlib.metadata.version('manmankan') == kan.__version__" in calls[1][2]
        assert "assert kan.__version__ == '0.0.6.8'" in calls[1][2]
        assert "from kan import scanner" not in calls[1][2]
        assert "from kan.core import scanner" not in calls[1][2]

    def test_failed_nonzero_returncode(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        with patch(
            "kan.data.updater.subprocess.run",
            return_value=self._make_completed(1, "", "Permission denied"),
        ):
            status, msg = updater.run_upgrade()
        assert status == "failed"
        assert "Permission denied" in msg

    def test_timeout(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        with patch(
            "kan.data.updater.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="uv", timeout=120),
        ):
            status, msg = updater.run_upgrade()
        assert status == "failed"
        assert "超时" in msg

    def test_command_not_found(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        with patch(
            "kan.data.updater.subprocess.run",
            side_effect=FileNotFoundError("uv not found"),
        ):
            status, msg = updater.run_upgrade()
        assert status == "failed"
        assert "未找到" in msg

    def test_unexpected_exception_swallowed(self, monkeypatch):
        """RuntimeError / 其他异常都吞掉返回 failed"""
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        with patch(
            "kan.data.updater.subprocess.run",
            side_effect=RuntimeError("unexpected"),
        ):
            status, _msg = updater.run_upgrade()
        assert status == "failed"


# --- spinner UX (历史背景) ---


class TestRunUpgradeSpinner:
    """背景: run_upgrade 用 rich.Console.status 显示进度 spinner

    根因守护:capture_output=True 吞掉 uv/pipx 原生输出 · 用户感知"卡死"
    修复后:主升级阶段 + smoke 阶段各一段 spinner · 非 TTY 自动退化静默
    """

    def _make_completed(self, returncode: int, stdout: str = "", stderr: str = ""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_uses_passed_console_status(self, monkeypatch):
        """caller (cli_atexit / cli_meta_cmds) 传入的 console 必须被用于 spinner

        防回归:避免 updater 自建 console · 与 caller 输出风格不一致
        """
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        fake_console = MagicMock()
        fake_console.status.return_value.__enter__ = MagicMock()
        fake_console.status.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "kan.data.updater.subprocess.run",
            return_value=self._make_completed(0),
        ):
            status, _msg = updater.run_upgrade(console=fake_console)

        assert status == "success"
        # 主升级 + smoke 两段 spinner = 2 次 status 调用
        assert fake_console.status.call_count == 2
        # 第一段必含"安装" · 第二段必含"验证"
        call_texts = [str(c.args[0]) for c in fake_console.status.call_args_list]
        assert any("安装" in t for t in call_texts)
        assert any("验证" in t for t in call_texts)

    def test_no_spinner_on_failed_install_skips_smoke(self, monkeypatch):
        """主升级失败 (returncode != 0) · smoke 不该跑 · 只 1 段 spinner"""
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        fake_console = MagicMock()
        fake_console.status.return_value.__enter__ = MagicMock()
        fake_console.status.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "kan.data.updater.subprocess.run",
            return_value=self._make_completed(1, "", "boom"),
        ):
            status, _msg = updater.run_upgrade(console=fake_console)

        assert status == "failed"
        # 只跑了主升级阶段 · smoke 因 returncode != 0 跳过
        assert fake_console.status.call_count == 1

    def test_no_console_arg_does_not_break(self, monkeypatch):
        """console=None 时 updater 自建 stderr console · 行为不破

        守护:非 TTY (pytest 默认) Console.status 退化为静默 · 不抛错
        """
        monkeypatch.setattr(
            "sys.executable",
            "/Users/x/.local/share/uv/tools/manmankan/bin/python",
        )
        with patch(
            "kan.data.updater.subprocess.run",
            return_value=self._make_completed(0),
        ):
            status, msg = updater.run_upgrade()  # 不传 console
        assert status == "success"
        assert msg == "uv tool"
