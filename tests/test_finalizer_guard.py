"""finalizer_guard 单测: 半初始化 MiniRacer 析构不再抛裸 traceback。"""
from __future__ import annotations

import sys
import types

import kan.infra.finalizer_guard as guard


def _install_fake_mini_racer(monkeypatch) -> type:
    """向 sys.modules 注入带脆弱 __del__ 的假 py_mini_racer。"""

    class FakeMiniRacer:
        def __del__(self) -> None:
            raise AttributeError("'NoneType' object has no attribute 'mr_free_context'")

    module = types.ModuleType("py_mini_racer")
    module.MiniRacer = FakeMiniRacer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "py_mini_racer", module)
    return FakeMiniRacer


def test_defuse_wraps_fragile_del(monkeypatch) -> None:
    fake_cls = _install_fake_mini_racer(monkeypatch)
    monkeypatch.setattr(guard, "_defused", False)

    guard.defuse_mini_racer_finalizer()

    instance = fake_cls()
    # 包裹后直接调用析构不再抛异常(等价于 GC 路径不再产生 unraisable)
    instance.__del__()


def test_defuse_idempotent(monkeypatch) -> None:
    fake_cls = _install_fake_mini_racer(monkeypatch)
    monkeypatch.setattr(guard, "_defused", False)

    guard.defuse_mini_racer_finalizer()
    wrapped = fake_cls.__del__
    guard.defuse_mini_racer_finalizer()

    assert fake_cls.__del__ is wrapped


def test_defuse_survives_missing_module(monkeypatch) -> None:
    monkeypatch.setattr(guard, "_defused", False)
    monkeypatch.setitem(sys.modules, "py_mini_racer", None)

    # import 失败时静默返回,不影响调用方
    guard.defuse_mini_racer_finalizer()
