"""kan config 子命令组测试 · get/set/unset + token mask + env 覆盖"""

import pytest
from typer.testing import CliRunner

from kan.storage import config, paths


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
    return tmp_path


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def app():
    """触发命令注册并返回 typer app · 与既有 test_cli_registration.py 同模式"""
    import kan.cli  # noqa: F401 — 触发子模块 import 注册所有命令
    from kan.app import app
    return app


class TestConfigGet:

    def test_get_empty_shows_default_endpoint_and_unconfigured_token(self, runner, app, isolated_env):
        """未配 token 时 get 显示「未配置 · 用 kan config set ...」引导 + 默认 endpoint"""
        result = runner.invoke(app, ["config", "get"])
        assert result.exit_code == 0
        assert "tushare_endpoint" in result.stdout
        assert "默认" in result.stdout
        # 未配 token 应给散户引导(不再无声跳过)
        assert "tushare_token" in result.stdout
        assert "未配置" in result.stdout
        assert "kan config set tushare-token" in result.stdout

    def test_get_with_token_masks(self, runner, app, isolated_env):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_abcdefghij1234"})
        result = runner.invoke(app, ["config", "get"])
        assert result.exit_code == 0
        assert "tushare_token" in result.stdout
        assert "***1234" in result.stdout
        assert "tk_abcdefghij" not in result.stdout

    def test_get_with_env_override_marks_source(
        self, runner, app, isolated_env, monkeypatch,
    ):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_cfg00000000"})
        monkeypatch.setenv("TUSHARE_TOKEN", "tk_env00000000")
        result = runner.invoke(app, ["config", "get"])
        assert result.exit_code == 0
        assert "***0000" in result.stdout
        assert "env" in result.stdout.lower()

    def test_get_with_custom_endpoint(self, runner, app, isolated_env):
        config.save({**config.DEFAULT_CONFIG, "tushare_endpoint": "https://my.mirror"})
        result = runner.invoke(app, ["config", "get"])
        assert "https://my.mirror" in result.stdout


class TestConfigSet:

    def test_set_token_writes_config(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-token", "tk_new_token_1234"])
        assert result.exit_code == 0
        assert "✅" in result.stdout or "已保存" in result.stdout
        assert "tk_new_token_1234" not in result.stdout
        assert "***1234" in result.stdout
        assert config.load()["tushare_token"] == "tk_new_token_1234"

    def test_set_endpoint_writes_config(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-endpoint", "https://my.host"])
        assert result.exit_code == 0
        assert config.load()["tushare_endpoint"] == "https://my.host"

    def test_set_empty_token_rejected(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-token", "   "])
        assert result.exit_code == 2
        assert "不能为空" in result.stdout or "empty" in result.stdout.lower()

    def test_set_invalid_endpoint_rejected(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-endpoint", "not-a-url"])
        assert result.exit_code == 2
        assert "http" in result.stdout.lower()

    def test_set_unknown_key_rejected(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "no-such-key", "x"])
        assert result.exit_code != 0


class TestConfigUnset:

    def test_unset_clears_token(self, runner, app, isolated_env):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_xxxxxxxx"})
        result = runner.invoke(app, ["config", "unset", "tushare-token"])
        assert result.exit_code == 0
        assert config.load()["tushare_token"] is None

    def test_unset_already_none_is_noop_message(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "unset", "tushare-token"])
        assert result.exit_code == 0
        assert "ℹ" in result.stdout or "默认" in result.stdout or "无需" in result.stdout
