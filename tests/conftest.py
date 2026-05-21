"""测试夹具 · 全套件共享。"""

import pytest

from kan import circuit_breaker


@pytest.fixture(autouse=True)
def isolated_breaker(tmp_path, monkeypatch):
    """熔断器单例指向 tmp · 杜绝测试读写真实 ~/.local/share/kan/circuit.json。

    autouse：任何走 fetcher 真实 _fetch_* 的测试都不会碰真实熔断器状态。
    需要操作熔断器的测试把本 fixture 名加进参数即可拿到实例。
    """
    cb = circuit_breaker.CircuitBreaker(tmp_path / "circuit.json")
    monkeypatch.setattr(circuit_breaker, "_default", cb)
    return cb
