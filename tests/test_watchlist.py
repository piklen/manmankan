"""watchlist 测试 · 代码校验 / 持久化 / CRUD"""

import json
from datetime import date
from unittest.mock import patch

import pytest

from kan.core.models import Stock
from kan.storage import paths, watchlist


@pytest.fixture
def temp_kan_dir(tmp_path, monkeypatch):
    """每个测试用临时目录，避免污染真实数据"""
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(paths, "STOCK_NAMES_CACHE", tmp_path / "stock_names.json")
    monkeypatch.setattr(paths, "SNAPSHOT_PATH", tmp_path / "last_scan.json")
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(watchlist, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(watchlist, "STOCK_NAMES_CACHE", tmp_path / "stock_names.json")
    return tmp_path


def test_normalize_symbol_pure_digits():
    assert watchlist._normalize_symbol("600519") == "600519"


def test_normalize_symbol_with_sh_prefix():
    assert watchlist._normalize_symbol("sh600519") == "600519"


def test_normalize_symbol_with_sz_prefix():
    assert watchlist._normalize_symbol("sz000858") == "000858"


def test_normalize_symbol_uppercase_prefix():
    assert watchlist._normalize_symbol("SH600519") == "600519"


def test_normalize_symbol_invalid_format():
    with pytest.raises(ValueError, match="不是 6 位股票代码"):
        watchlist._normalize_symbol("abc")


def test_normalize_symbol_too_short():
    with pytest.raises(ValueError, match="不是 6 位股票代码"):
        watchlist._normalize_symbol("12345")


# ── resolve_symbol_or_name · 6 位代码 / 名称 / 多匹配 / 零匹配 / 空输入 ──────────
# 背景 · info / compare 共用入口 · 让"用户给名称"在所有 verb 一致 work。


def _stub_names(monkeypatch, mapping):
    """让 _load_stock_names 直接返回测试用 mapping · 跳过 baostock/akshare 真网络。"""
    monkeypatch.setattr(watchlist, "_load_stock_names", lambda: mapping)


def test_resolve_symbol_or_name_pure_code(monkeypatch):
    _stub_names(monkeypatch, {"600519": "贵州茅台"})
    assert watchlist.resolve_symbol_or_name("600519") == ("600519", "贵州茅台")


def test_resolve_symbol_or_name_with_prefix(monkeypatch):
    _stub_names(monkeypatch, {"600519": "贵州茅台"})
    assert watchlist.resolve_symbol_or_name("sh600519") == ("600519", "贵州茅台")


def test_resolve_symbol_or_name_single_match(monkeypatch):
    _stub_names(monkeypatch, {"600519": "贵州茅台"})
    assert watchlist.resolve_symbol_or_name("茅台") == ("600519", "贵州茅台")


def test_resolve_symbol_or_name_multi_match_lists_candidates(monkeypatch):
    _stub_names(monkeypatch, {
        "601318": "中国平安",
        "000001": "平安银行",
        "001359": "平安电工",
    })
    with pytest.raises(ValueError, match="匹配到 3 只"):
        watchlist.resolve_symbol_or_name("平安")


def test_resolve_symbol_or_name_zero_match(monkeypatch):
    _stub_names(monkeypatch, {"600519": "贵州茅台"})
    with pytest.raises(ValueError, match="未找到包含"):
        watchlist.resolve_symbol_or_name("xxxxx")


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_resolve_symbol_or_name_blank_rejected(monkeypatch, bad):
    _stub_names(monkeypatch, {"600519": "贵州茅台"})
    with pytest.raises(ValueError, match="空字符串不是有效"):
        watchlist.resolve_symbol_or_name(bad)


def test_resolve_symbol_or_name_unknown_code(monkeypatch):
    _stub_names(monkeypatch, {"600519": "贵州茅台"})
    with pytest.raises(ValueError, match="未找到股票"):
        watchlist.resolve_symbol_or_name("999999")


def test_search_by_name_blank_returns_empty(monkeypatch):
    """search_by_name 同样不能让 `'' in name` 短路命中全部 · 否则 add/info 多匹配 spam。"""
    _stub_names(monkeypatch, {"600519": "贵州茅台", "000858": "五粮液"})
    assert watchlist.search_by_name("") == []
    assert watchlist.search_by_name("   ") == []


def test_load_empty_watchlist(temp_kan_dir):
    wl = watchlist.load_watchlist()
    assert wl.stocks == []


def test_save_and_load_watchlist(temp_kan_dir):
    wl = watchlist.Watchlist([
        Stock(symbol="600519", name="贵州茅台", added_at=date(2026, 5, 5)),
    ])
    watchlist._save_watchlist(wl)

    loaded = watchlist.load_watchlist()
    assert len(loaded.stocks) == 1
    assert loaded.stocks[0].symbol == "600519"
    assert loaded.stocks[0].name == "贵州茅台"


def test_add_stock(temp_kan_dir):
    with patch("kan.storage.watchlist._lookup_name", return_value="贵州茅台"):
        ok, msg = watchlist.add("600519")
    assert ok
    assert "600519" in msg
    assert len(watchlist.list_all()) == 1


def test_add_duplicate(temp_kan_dir):
    with patch("kan.storage.watchlist._lookup_name", return_value="贵州茅台"):
        watchlist.add("600519")
        ok, msg = watchlist.add("600519")
    assert not ok
    assert "已在自选列表" in msg


def test_add_with_prefix_normalizes(temp_kan_dir):
    with patch("kan.storage.watchlist._lookup_name", return_value="贵州茅台"):
        watchlist.add("sh600519")
    stocks = watchlist.list_all()
    assert stocks[0].symbol == "600519"


def test_remove_stock(temp_kan_dir):
    with patch("kan.storage.watchlist._lookup_name", return_value="贵州茅台"):
        watchlist.add("600519")
    ok, msg = watchlist.remove("600519")
    assert ok
    assert "已移除" in msg
    assert len(watchlist.list_all()) == 0


def test_remove_nonexistent(temp_kan_dir):
    ok, msg = watchlist.remove("600519")
    assert not ok
    assert "不在自选列表" in msg


def test_clear_watchlist(temp_kan_dir):
    with patch("kan.storage.watchlist._lookup_name", return_value="贵州茅台"):
        watchlist.add("600519")
        watchlist.add("000858")
    count = watchlist.clear()
    assert count == 2
    assert len(watchlist.list_all()) == 0


def test_import_csv(temp_kan_dir, tmp_path):
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text("600519\n000858\n")

    with patch("kan.storage.watchlist._lookup_name", return_value="测试股"):
        success, skipped, errors = watchlist.import_csv(str(csv_path))

    assert success == 2
    assert skipped == 0
    assert len(errors) == 0


def test_stock_names_cache_used(temp_kan_dir):
    """二次查询应命中本地缓存，不调用 AKShare"""
    cache_data = {"600519": "贵州茅台"}
    watchlist.STOCK_NAMES_CACHE.write_text(json.dumps(cache_data, ensure_ascii=False))

    with patch("akshare.stock_info_a_code_name") as mock_ak:
        names = watchlist._load_stock_names()
        mock_ak.assert_not_called()
        assert names["600519"] == "贵州茅台"


def test_load_watchlist_resolves_code_placeholder_from_cache(temp_kan_dir):
    """后台名称表建好后,占位 name==symbol 的自选应显示真实名称。"""
    watchlist.STOCK_NAMES_CACHE.write_text(
        json.dumps({"600519": "贵州茅台"}, ensure_ascii=False),
        encoding="utf-8",
    )
    watchlist.save_watchlist(
        watchlist.Watchlist(
            stocks=[Stock(symbol="600519", name="600519", added_at=date(2026, 6, 4))]
        )
    )

    wl = watchlist.load_watchlist()

    assert wl.stocks[0].name == "贵州茅台"


# --- 名称搜索 ---


class TestSearchByName:
    """search_by_name 按名称模糊搜索"""

    def test_exact_match(self, temp_kan_dir):
        cache = {"600519": "贵州茅台", "000858": "五粮液", "000001": "平安银行"}
        watchlist.STOCK_NAMES_CACHE.write_text(json.dumps(cache, ensure_ascii=False))

        results = watchlist.search_by_name("茅台")
        assert len(results) == 1
        assert results[0] == ("600519", "贵州茅台")

    def test_multiple_matches(self, temp_kan_dir):
        cache = {"000001": "平安银行", "601988": "中国银行", "601398": "工商银行"}
        watchlist.STOCK_NAMES_CACHE.write_text(json.dumps(cache, ensure_ascii=False))

        results = watchlist.search_by_name("银行")
        assert len(results) == 3

    def test_no_match(self, temp_kan_dir):
        cache = {"600519": "贵州茅台"}
        watchlist.STOCK_NAMES_CACHE.write_text(json.dumps(cache, ensure_ascii=False))

        results = watchlist.search_by_name("不存在")
        assert len(results) == 0

    def test_partial_match(self, temp_kan_dir):
        cache = {"600519": "贵州茅台", "600999": "招商证券"}
        watchlist.STOCK_NAMES_CACHE.write_text(json.dumps(cache, ensure_ascii=False))

        results = watchlist.search_by_name("贵州")
        assert len(results) == 1
        assert results[0][0] == "600519"


# --- import_csv 入口校验 (路径 / 后缀 / 大小) ---


class TestImportCsvValidation:
    """import_csv 入口三道校验 · 防 path traversal / 误读敏感文件 / OOM"""

    def test_reject_non_csv_suffix(self, temp_kan_dir, tmp_path):
        """非 .csv 后缀应抛 ValueError (防误传 ~/.ssh/id_rsa 等敏感文件)"""
        bad_path = tmp_path / "stocks.txt"
        bad_path.write_text("600519\n")

        with pytest.raises(ValueError, match=r"必须是 \.csv 后缀"):
            watchlist.import_csv(str(bad_path))

    def test_reject_nonexistent_file(self, temp_kan_dir, tmp_path):
        """不存在的文件应抛 FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="文件不存在"):
            watchlist.import_csv(str(tmp_path / "no-such-file.csv"))

    def test_reject_directory(self, temp_kan_dir, tmp_path):
        """传入目录应抛 FileNotFoundError (不是普通文件)"""
        sub_dir = tmp_path / "subdir.csv"
        sub_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="不是普通文件"):
            watchlist.import_csv(str(sub_dir))

    def test_reject_oversized_file(self, temp_kan_dir, tmp_path, monkeypatch):
        """大于 MAX_CSV_SIZE 的文件应抛 ValueError (防 OOM)"""
        monkeypatch.setattr(watchlist, "MAX_CSV_SIZE", 100)  # 临时把上限调小到 100 字节
        big_path = tmp_path / "big.csv"
        big_path.write_text("600519\n" * 50)  # ~350 字节 > 100

        with pytest.raises(ValueError, match="文件过大"):
            watchlist.import_csv(str(big_path))


# --- add_stock() 批量添加接口 ---


class TestAddStock:
    def test_add_stock_normal(self, temp_kan_dir):
        wl = watchlist.Watchlist()
        ok = watchlist.add_stock(wl, "600519", "贵州茅台")
        assert ok
        assert len(wl.stocks) == 1
        assert wl.stocks[0].symbol == "600519"

    def test_add_stock_duplicate(self, temp_kan_dir):
        wl = watchlist.Watchlist()
        watchlist.add_stock(wl, "600519", "贵州茅台")
        ok = watchlist.add_stock(wl, "600519", "贵州茅台")
        assert not ok
        assert len(wl.stocks) == 1

    def test_add_stock_sets_today(self, temp_kan_dir):
        wl = watchlist.Watchlist()
        watchlist.add_stock(wl, "600519", "贵州茅台")
        assert wl.stocks[0].added_at == date.today()


# --- Stock.groups 兼容性 ---


class TestStockGroups:
    def test_groups_default_empty(self):
        s = Stock(symbol="600519", name="贵州茅台", added_at=date.today())
        assert s.groups == {}

    def test_old_json_without_groups(self):
        """旧 JSON（无 groups 字段）反序列化应兼容"""
        old_data = {"symbol": "600519", "name": "贵州茅台", "added_at": "2026-05-10"}
        s = Stock(**old_data)
        assert s.groups == {}

    def test_groups_with_data(self):
        s = Stock(
            symbol="002371", name="北方华创", added_at=date.today(),
            groups={
                "industry_l1": "电子",
                "industry_l2": "半导体设备",
                "concepts": ["芯片", "光刻机"],
                "custom": ["重仓"],
            },
        )
        assert s.groups["industry_l1"] == "电子"
        assert "芯片" in s.groups["concepts"]

    def test_groups_roundtrip_json(self):
        """groups 序列化/反序列化 roundtrip"""
        s = Stock(
            symbol="002371", name="北方华创", added_at=date.today(),
            groups={"board": "主板", "concepts": ["AI"]},
        )
        data = s.model_dump(mode="json")
        s2 = Stock(**data)
        assert s2.groups == s.groups


# --- 冷启动延迟回归保护 (背景 · akshare lazy import) ---


class TestColdStartInvariants:
    """守护 akshare 不在 kan.storage.watchlist 顶层被 import · 防冷启动 启动反馈回归。

    早期实测：watchlist.py 顶层 `import akshare as ak` 把 pandas/numpy/bs4/requests
    整窝拖入启动路径，单 akshare 占 watchlist 加载成本 85%（热启动 229ms / 冷启动约 8s）。
    """

    def test_watchlist_top_level_does_not_load_akshare(self):
        """import kan.storage.watchlist 时 akshare 不应出现在 sys.modules（子进程隔离）。

        sys.modules 是 process-global · 单进程 pytest 内可能被其他测试污染，
        必须用 subprocess 隔离才能可靠检查"watchlist 自己有没有 import akshare"。
        """
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable, "-c",
                "import kan.storage.watchlist as w; "
                "import sys; "
                "leaked = [m for m in sys.modules if 'akshare' in m.lower()]; "
                "assert not leaked, f'akshare leaked: {leaked}'",
            ],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"akshare leaked into top-level imports of kan.storage.watchlist\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_scanner_top_level_does_not_load_pandas(self):
        """import kan.core.scanner 时 pandas/numpy 不应出现在 sys.modules（历史背景）。

        早期版本安装后导入失败的成因之一：scanner.py 顶层 `import pandas as pd`
        触发 numpy C-extension load · macOS Gatekeeper 拒载老 .so cache。
        已改为 `if TYPE_CHECKING: import pandas` + 函数体 lazy。
        """
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable, "-c",
                "import kan.core.scanner as s; "
                "import sys; "
                "leaked = [m for m in sys.modules if any(x in m.lower() for x in ('pandas', 'numpy'))]; "
                "assert not leaked, f'pandas/numpy leaked: {leaked}'",
            ],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"pandas/numpy leaked into top-level imports of kan.core.scanner\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_baostock_success_does_not_call_akshare_fallback(self, temp_kan_dir, monkeypatch):
        """baostock 主路径成功 → akshare fallback 不应被调用（避免无谓 import 成本）。"""
        fallback_called: list[bool] = []

        def sentinel() -> None:
            fallback_called.append(True)
            raise AssertionError(
                "akshare fallback should NOT be called when baostock succeeds"
            )

        monkeypatch.setattr(watchlist, "_fetch_names_akshare", sentinel)
        monkeypatch.setattr(
            watchlist, "_fetch_names_baostock",
            lambda: {"600519": "贵州茅台", "000858": "五粮液"},
        )

        names = watchlist._load_stock_names()

        assert names == {"600519": "贵州茅台", "000858": "五粮液"}
        assert not fallback_called, "akshare fallback unexpectedly invoked"
