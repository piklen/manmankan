"""kan/config.py · 用户配置持久化测试

守护:
- 损坏自愈 (文件不存在 / JSON 损坏 / 类型不对 / 缺字段)
- atomic write (不留 .tmp)
- schema 兼容 (未知字段忽略 · 缺字段填默认值)
- load 返回独立 dict (不污染 DEFAULT_CONFIG)
"""

import json

import pytest

from kan.storage import config, paths


@pytest.fixture
def temp_config_path(tmp_path, monkeypatch):
    """每个测试用临时配置目录 · 不污染真实 ~/.local/share/kan/config.json"""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    return cfg_path


def test_load_missing_file_returns_defaults(temp_config_path):
    """文件不存在 → 默认值"""
    result = config.load()
    assert result == config.DEFAULT_CONFIG
    assert result["auto_update"] is None


def test_load_corrupted_json_returns_defaults(temp_config_path):
    """JSON 损坏 → 自愈返回默认值（不抛异常）"""
    temp_config_path.write_text("{not valid json")
    result = config.load()
    assert result == config.DEFAULT_CONFIG


def test_load_non_dict_returns_defaults(temp_config_path):
    """JSON 不是 dict（是 list）→ 自愈"""
    temp_config_path.write_text("[1, 2, 3]")
    result = config.load()
    assert result == config.DEFAULT_CONFIG


def test_load_partial_keys_merges_defaults(temp_config_path):
    """缺字段 → merge 默认值"""
    temp_config_path.write_text(json.dumps({"auto_update": True}))
    result = config.load()
    assert result["auto_update"] is True
    assert result["last_check_date"] is None
    assert result["latest_seen_version"] is None
    assert result["last_hint_date"] is None


def test_load_unknown_keys_ignored(temp_config_path):
    """未知字段忽略（向前兼容更新的 schema）"""
    temp_config_path.write_text(json.dumps({
        "auto_update": True,
        "future_field": "ignore_me",
    }))
    result = config.load()
    assert result["auto_update"] is True
    assert "future_field" not in result


def test_save_load_roundtrip(temp_config_path):
    """save 后 load 拿到一致内容"""
    cfg = config.load()
    cfg["auto_update"] = True
    cfg["last_check_date"] = "2026-05-11"
    cfg["latest_seen_version"] = "0.0.3"
    config.save(cfg)

    reloaded = config.load()
    assert reloaded["auto_update"] is True
    assert reloaded["last_check_date"] == "2026-05-11"
    assert reloaded["latest_seen_version"] == "0.0.3"


def test_save_creates_parent_directory(tmp_path, monkeypatch):
    """save 自动 mkdir 不存在的父目录"""
    nested = tmp_path / "a" / "b" / "c" / "config.json"
    monkeypatch.setattr(paths, "BASE_DIR", nested.parent)
    monkeypatch.setattr(config, "CONFIG_PATH", nested)

    cfg = dict(config.DEFAULT_CONFIG)
    cfg["auto_update"] = False
    config.save(cfg)

    assert nested.exists()
    assert json.loads(nested.read_text())["auto_update"] is False


def test_save_no_tmp_file_left(temp_config_path):
    """atomic write 完成后 .tmp 文件不应残留"""
    cfg = dict(config.DEFAULT_CONFIG)
    config.save(cfg)

    tmp_files = list(temp_config_path.parent.glob("*.tmp"))
    assert tmp_files == []


def test_load_returns_independent_dict(temp_config_path):
    """load 返回新 dict · 修改它不污染 DEFAULT_CONFIG"""
    cfg1 = config.load()
    cfg1["auto_update"] = True
    cfg2 = config.load()
    assert cfg2["auto_update"] is None  # DEFAULT 未被污染


def test_save_unicode_chinese_content(temp_config_path):
    """save 中文字符 · ensure_ascii=False 应 work"""
    cfg = dict(config.DEFAULT_CONFIG)
    cfg["latest_seen_version"] = "测试-中文版本"
    config.save(cfg)

    raw = temp_config_path.read_text(encoding="utf-8")
    assert "中文版本" in raw  # ensure_ascii=False 才能直接看到汉字（不是 \uXXXX）
    reloaded = config.load()
    assert reloaded["latest_seen_version"] == "测试-中文版本"


class TestTushareFields:
    """v0.0.5 新增 tushare_token / tushare_endpoint 字段"""

    def test_default_tushare_fields_are_none(self, temp_config_path):
        """新装用户读到 None，不打开 tushare 分支"""
        cfg = config.load()
        assert cfg["tushare_token"] is None
        assert cfg["tushare_endpoint"] is None

    def test_save_and_reload_tushare_token(self, temp_config_path):
        cfg = config.load()
        cfg["tushare_token"] = "tk_test_abcdef123456"
        config.save(cfg)
        reloaded = config.load()
        assert reloaded["tushare_token"] == "tk_test_abcdef123456"
        assert reloaded["tushare_endpoint"] is None

    def test_legacy_config_without_tushare_fields_self_heals(self, temp_config_path):
        """老 config.json 没有 tushare_* 字段也能 load → 缺字段补 None"""
        temp_config_path.write_text(json.dumps({"auto_update": True}))
        cfg = config.load()
        assert cfg["auto_update"] is True
        assert cfg["tushare_token"] is None
        assert cfg["tushare_endpoint"] is None
