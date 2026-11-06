"""测试夹具 · 全套件共享。"""

import os
import sys
from tempfile import TemporaryDirectory
from types import ModuleType

import pytest

# 在任何 kan 导入前隔离会话路径，漏掉局部 stub 也不能触碰用户状态。
_test_home = TemporaryDirectory(prefix="manmankan-pytest-")
for _kind in ("DATA", "CONFIG", "CACHE"):
    _key = f"XDG_{_kind}_HOME"
    os.environ[_key] = os.environ.get(_key) or f"{_test_home.name}/{_kind.lower()}"


def _akshare_test_double() -> ModuleType:
    """Return a lightweight akshare module for offline tests.

    Several unit tests patch attributes such as ``akshare.stock_zh_a_hist`` by
    dotted string. Without a preinstalled module, Python imports real akshare
    during patch setup, which can load network/native dependencies before the
    test double is applied.
    """
    mod = ModuleType("akshare")
    mod.__manmankan_test_double__ = True

    def unmocked(*_args, **_kwargs):
        raise AssertionError("offline test attempted to call unmocked akshare")

    for name in (
        "index_component_sw",
        "index_hist_sw",
        "stock_board_concept_cons_em",
        "stock_board_concept_hist_em",
        "stock_board_concept_name_em",
        "stock_board_concept_name_ths",
        "stock_hot_rank_em",
        "stock_hot_up_em",
        "stock_info_a_code_name",
        "stock_zh_a_daily",
        "stock_zh_a_hist",
        "stock_zh_a_hist_tx",
        "sw_index_first_info",
        "sw_index_second_info",
        "sw_index_third_info",
        "tool_trade_date_hist_sina",
    ):
        setattr(mod, name, unmocked)
    return mod


@pytest.fixture(autouse=True)
def offline_akshare_test_double(request, monkeypatch):
    """Use a lightweight akshare test double for non-network tests."""
    if request.node.get_closest_marker("network"):
        return
    monkeypatch.setitem(sys.modules, "akshare", _akshare_test_double())


@pytest.fixture(autouse=True)
def isolated_breaker(tmp_path, monkeypatch):
    """熔断器单例指向 tmp · 杜绝测试读写真实 ~/.local/share/kan/circuit.json。

    autouse：任何走 fetcher 真实 _fetch_* 的测试都不会碰真实熔断器状态。
    需要操作熔断器的测试把本 fixture 名加进参数即可拿到实例。
    """
    from kan.infra import circuit_breaker

    cb = circuit_breaker.CircuitBreaker(tmp_path / "circuit.json")
    monkeypatch.setattr(circuit_breaker, "_default", cb)
    return cb
