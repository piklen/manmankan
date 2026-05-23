"""kan/boards.py 的 theme 函数单元测试 · mock adata · 不走真网络。"""
import json
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from kan import boards
from kan.boards import ThemeDataUnavailableError, ThemeNotFoundError
from kan.models import Theme


@pytest.fixture(autouse=True)
def _mock_adata(monkeypatch):
    """创建 adata mock module · 防止真实网络调用。"""
    mock_adata = MagicMock()
    monkeypatch.setitem(sys.modules, "adata", mock_adata)
    monkeypatch.setitem(sys.modules, "adata.stock", MagicMock())
    monkeypatch.setitem(sys.modules, "adata.stock.info", MagicMock())
    return mock_adata


@pytest.fixture(autouse=True)
def _isolate_boards_dir(tmp_path, monkeypatch):
    """boards cache 指向 tmp · 杜绝读写真实 ~/.local/share/kan/boards/。

    同 F10a `tests/test_boards.py` 风格 · 复用 F10a tests/conftest.py 的 isolate
    若已建可省 · 若未建在此 fixture 内 monkeypatch BOARDS_DIR + paths.ensure_dirs。
    """
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    return bdir


def _fake_ths_catalog_df():
    """模拟 adata.stock.info.all_concept_code_ths() 真返回结构(2026-05-23 spike 实测)。"""
    return pd.DataFrame(
        [
            {"index_code": "886108", "name": "AI应用", "concept_code": "308767", "source": "同花顺"},
            {"index_code": "885525", "name": "白酒概念", "concept_code": "308768", "source": "同花顺"},
            {"index_code": "886109", "name": "同花顺", "concept_code": "309265", "source": "同花顺"},
        ]
    )


def test_load_theme_catalog_first_run_hits_adata(monkeypatch, _isolate_boards_dir):
    """无 cache · 第一次跑应调 adata · 返回 list[Theme]。"""
    monkeypatch.setattr(
        "adata.stock.info.all_concept_code_ths",
        lambda: _fake_ths_catalog_df(),
    )
    themes = boards.load_theme_catalog()
    assert len(themes) == 3
    assert all(isinstance(t, Theme) for t in themes)
    assert themes[0].code == "886108"
    assert themes[0].name == "AI应用"
    assert themes[0].source == "ths"


def test_load_theme_catalog_writes_cache(monkeypatch, _isolate_boards_dir):
    """跑完 catalog 应写 catalog_concept_ths.json。"""
    monkeypatch.setattr(
        "adata.stock.info.all_concept_code_ths",
        lambda: _fake_ths_catalog_df(),
    )
    boards.load_theme_catalog()
    cache = _isolate_boards_dir / "catalog_concept_ths.json"
    assert cache.exists()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[0]["code"] == "886108"


def test_load_theme_catalog_uses_cache_within_ttl(monkeypatch, _isolate_boards_dir):
    """24h 内第二次调不应再打 adata。"""
    call_count = {"n": 0}

    def counting_adata():
        call_count["n"] += 1
        return _fake_ths_catalog_df()

    monkeypatch.setattr("adata.stock.info.all_concept_code_ths", counting_adata)
    boards.load_theme_catalog()       # 第一次写 cache
    boards.load_theme_catalog()       # 第二次应读 cache
    assert call_count["n"] == 1


def test_load_theme_catalog_force_bypasses_cache(monkeypatch, _isolate_boards_dir):
    """force=True 应强制重拉。"""
    call_count = {"n": 0}

    def counting_adata():
        call_count["n"] += 1
        return _fake_ths_catalog_df()

    monkeypatch.setattr("adata.stock.info.all_concept_code_ths", counting_adata)
    boards.load_theme_catalog()
    boards.load_theme_catalog(force=True)
    assert call_count["n"] == 2


def test_load_theme_catalog_raises_when_adata_fails_and_no_cache(monkeypatch, _isolate_boards_dir):
    """adata 抛错 + 无 cache → ThemeDataUnavailableError。"""

    def raising():
        raise ConnectionError("adata down")

    monkeypatch.setattr("adata.stock.info.all_concept_code_ths", raising)
    with pytest.raises(ThemeDataUnavailableError):
        boards.load_theme_catalog()


def test_load_theme_catalog_falls_back_to_stale_cache_on_failure(monkeypatch, _isolate_boards_dir):
    """adata 挂 + cache 陈旧 → 用陈旧 cache 不抛(warn 但继续)。"""
    # 先建一个陈旧 cache(mtime 改为 25h 前)
    cache = _isolate_boards_dir / "catalog_concept_ths.json"
    cache.write_text(
        json.dumps([{"code": "886108", "name": "AI应用", "source": "ths", "size": None}], ensure_ascii=False),
        encoding="utf-8",
    )
    import os
    import time
    old = time.time() - 25 * 3600
    os.utime(cache, (old, old))

    monkeypatch.setattr(
        "adata.stock.info.all_concept_code_ths",
        lambda: (_ for _ in ()).throw(ConnectionError("adata down")),
    )

    # 捕获 debug_log 调用
    log_calls = []
    def capture_debug_log(module, op, err):
        log_calls.append((module, op, err))

    monkeypatch.setattr("kan._log.debug_log", capture_debug_log)

    themes = boards.load_theme_catalog()
    assert len(themes) == 1
    assert themes[0].code == "886108"
    # 应已记录退化警告
    assert len(log_calls) >= 1, f"expected debug_log to be called, got {len(log_calls)} calls"
    assert any("adata THS catalog" in op for _, op, _ in log_calls), \
        f"expected debug_log with 'adata THS catalog' in op, got: {log_calls}"


# ── search_theme / normalize_theme_name ──────────────────────────────

def _seed_catalog(_isolate_boards_dir):
    """写入一个完整 catalog 到 tmp · 供 search 测试用。"""
    cache = _isolate_boards_dir / "catalog_concept_ths.json"
    cache.write_text(
        json.dumps(
            [
                {"code": "886108", "name": "AI应用", "source": "ths", "size": None},
                {"code": "886112", "name": "AI智能体", "source": "ths", "size": None},
                {"code": "885525", "name": "白酒概念", "source": "ths", "size": None},
                {"code": "886058", "name": "华为昇腾", "source": "ths", "size": None},
                {"code": "886109", "name": "同花顺", "source": "ths", "size": None},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_normalize_theme_name_strips_spaces(_isolate_boards_dir):
    """'AI 应用' → 'AI应用'(去全角半角空格)。"""
    assert boards.normalize_theme_name("AI 应用") == "AI应用"
    assert boards.normalize_theme_name("AI　应用") == "AI应用"  # 全角空格
    assert boards.normalize_theme_name("白酒  概念") == "白酒概念"


def test_normalize_theme_name_idempotent(_isolate_boards_dir):
    """'AI应用' → 'AI应用'(已规范不变)。"""
    assert boards.normalize_theme_name("AI应用") == "AI应用"


def test_search_theme_exact_code(_isolate_boards_dir):
    """精确代码命中。"""
    _seed_catalog(_isolate_boards_dir)
    t = boards.search_theme("886108")
    assert t.name == "AI应用"


def test_search_theme_exact_name(_isolate_boards_dir):
    """精确题材名命中。"""
    _seed_catalog(_isolate_boards_dir)
    t = boards.search_theme("白酒概念")
    assert t.code == "885525"


def test_search_theme_fuzzy_normalized(_isolate_boards_dir):
    """模糊命中 · normalize 后含匹配 · 多命中按 catalog 顺序取第一个。"""
    _seed_catalog(_isolate_boards_dir)
    t = boards.search_theme("AI 应用")  # 带空格 → normalize → "AI应用"
    assert t.name == "AI应用"


def test_search_theme_not_found(_isolate_boards_dir):
    """完全不命中 · 抛 ThemeNotFoundError。"""
    _seed_catalog(_isolate_boards_dir)
    with pytest.raises(ThemeNotFoundError):
        boards.search_theme("不存在的题材xyz")
