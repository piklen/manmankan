"""测试夹具 · 全套件共享。"""

import sys
from types import ModuleType

import pytest

from kan.infra import circuit_breaker


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
    cb = circuit_breaker.CircuitBreaker(tmp_path / "circuit.json")
    monkeypatch.setattr(circuit_breaker, "_default", cb)
    return cb
