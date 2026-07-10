"""运行时依赖互斥关系回归测试。"""
from importlib.metadata import packages_distributions


def test_py_mini_racer_has_single_distribution_owner() -> None:
    """同名顶层包被两个发行包覆盖会形成 Python/动态库 ABI 混装。"""
    owners = {name.lower().replace("_", "-") for name in (
        packages_distributions().get("py_mini_racer") or []
    )}
    assert not {"mini-racer", "py-mini-racer"} <= owners
