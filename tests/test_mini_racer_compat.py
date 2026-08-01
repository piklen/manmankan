"""mini-racer 兼容 shim 与 finalizer 噪音抑制测试。

覆盖合并引入的 macOS mini-racer 0.14+ 兼容路径:
- kan.data.concepts._get_mini_racer_cls 三段导入 fallback
- kan.data.concepts._ths_headers 的 racer eval/call 主路径
- kan.infra.finalizer_guard.patch_mini_racer_import 各分支
- kan.infra.finalizer_guard.defuse_mini_racer_finalizer 的 _mini_racer 子模块路径
- kan._entry._patch_mini_racer 的异常静默分支
"""
from __future__ import annotations

import builtins
import importlib
import sys
import types

import pytest


def _block_import(monkeypatch: pytest.MonkeyPatch, blocked: set[str]) -> None:
    """让指定模块名 import 时抛 ImportError，其余走真实导入。"""
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in blocked:
            raise ImportError(f"blocked: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


# ── concepts._get_mini_racer_cls ───────────────────────────────────────


def test_get_mini_racer_cls_normal_import() -> None:
    from kan.data.concepts import _get_mini_racer_cls

    cls = _get_mini_racer_cls()
    assert cls.__name__ == "MiniRacer"


def test_get_mini_racer_cls_namespace_package_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """py_mini_racer 无 __init__(命名空间包) → 从 _mini_racer 子模块导入。"""
    from kan.data import concepts

    monkeypatch.delitem(sys.modules, "py_mini_racer", raising=False)
    monkeypatch.delitem(sys.modules, "py_mini_racer._mini_racer", raising=False)

    fake_sub = types.ModuleType("py_mini_racer._mini_racer")
    sentinel = type("MiniRacer", (), {})
    fake_sub.MiniRacer = sentinel  # type: ignore[attr-defined]
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "py_mini_racer":
            raise ImportError("no __init__.py")
        if name == "py_mini_racer._mini_racer":
            return fake_sub
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert concepts._get_mini_racer_cls() is sentinel


def test_get_mini_racer_cls_all_imports_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.data import concepts

    _block_import(monkeypatch, {"py_mini_racer", "py_mini_racer._mini_racer"})
    with pytest.raises(ImportError, match="无法导入 MiniRacer"):
        concepts._get_mini_racer_cls()


def test_ths_headers_uses_racer_eval_and_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_ths_headers 主路径:固定脚本 eval + call('v') 拼 Cookie。

    conftest 的 akshare test double 不是包 · 预置子模块进 sys.modules 绕过。
    """
    from kan.data import concepts

    ths_mod = types.ModuleType("akshare.stock_feature.stock_board_concept_ths")
    ths_mod._get_file_content_ths = lambda _name: "fake-js-source"  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "akshare.stock_feature", types.ModuleType("akshare.stock_feature"),
    )
    monkeypatch.setitem(
        sys.modules, "akshare.stock_feature.stock_board_concept_ths", ths_mod,
    )

    calls: dict[str, str] = {}

    class FakeRacer:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def eval(self, script: str) -> None:
            calls["script"] = script

        def call(self, fn: str) -> str:
            calls["fn"] = fn
            return "fake-cookie-value"

    monkeypatch.setattr(concepts, "_get_mini_racer_cls", lambda: FakeRacer)
    concepts._ths_headers.cache_clear()
    try:
        headers = concepts._ths_headers()
    finally:
        concepts._ths_headers.cache_clear()

    assert calls == {"script": "fake-js-source", "fn": "v"}
    assert headers["Cookie"] == "v=fake-cookie-value"
    assert headers["Referer"] == "https://q.10jqka.com.cn/gn/"
    assert "Mozilla/5.0" in headers["User-Agent"]


# ── finalizer_guard.patch_mini_racer_import ─────────────────────────────


def test_patch_mini_racer_import_early_return_when_loaded() -> None:
    from kan.infra.finalizer_guard import patch_mini_racer_import

    before = importlib.import_module("py_mini_racer")  # 确保已在 sys.modules
    patch_mini_racer_import()
    assert sys.modules["py_mini_racer"] is before


def test_patch_mini_racer_import_real_package_has_attr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.infra.finalizer_guard import patch_mini_racer_import

    monkeypatch.delitem(sys.modules, "py_mini_racer", raising=False)
    patch_mini_racer_import()
    package = sys.modules["py_mini_racer"]
    assert hasattr(package, "MiniRacer")
    assert package.__spec__ is not None
    assert package.__path__


def test_patch_mini_racer_import_preserves_loaded_namespace_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已加载的命名空间包要原地补属性，且测试不依赖平台安装形态。"""
    from kan.infra.finalizer_guard import patch_mini_racer_import

    package = types.ModuleType("py_mini_racer")
    package.__spec__ = importlib.machinery.ModuleSpec(
        "py_mini_racer", loader=None, is_package=True,
    )
    package.__path__ = ["/fake/py_mini_racer"]
    submodule = types.ModuleType("py_mini_racer._mini_racer")
    sentinel = type("MiniRacer", (), {})
    submodule.MiniRacer = sentinel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "py_mini_racer", package)
    monkeypatch.setitem(sys.modules, "py_mini_racer._mini_racer", submodule)
    original_spec = package.__spec__
    original_path = package.__path__

    patch_mini_racer_import()

    assert sys.modules["py_mini_racer"] is package
    assert package.__spec__ is original_spec
    assert package.__path__ is original_path
    assert package.MiniRacer is sentinel  # type: ignore[attr-defined]


def test_patch_mini_racer_import_shims_namespace_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常导入失败 → 从 _mini_racer 抢救并注入兼容模块到 sys.modules。"""
    from kan.infra.finalizer_guard import patch_mini_racer_import

    monkeypatch.delitem(sys.modules, "py_mini_racer", raising=False)
    monkeypatch.delitem(sys.modules, "py_mini_racer._mini_racer", raising=False)

    fake_sub = types.ModuleType("py_mini_racer._mini_racer")
    sentinel = type("MiniRacer", (), {})
    fake_sub.MiniRacer = sentinel  # type: ignore[attr-defined]
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "py_mini_racer":
            raise ImportError("no __init__.py")
        if name == "py_mini_racer._mini_racer":
            return fake_sub
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    patch_mini_racer_import()

    compat = sys.modules["py_mini_racer"]
    assert isinstance(compat, types.ModuleType)
    assert compat.MiniRacer is sentinel  # type: ignore[attr-defined]


def test_patch_mini_racer_import_all_fail_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kan.infra.finalizer_guard import patch_mini_racer_import

    monkeypatch.delitem(sys.modules, "py_mini_racer", raising=False)
    monkeypatch.delitem(sys.modules, "py_mini_racer._mini_racer", raising=False)
    _block_import(monkeypatch, {"py_mini_racer", "py_mini_racer._mini_racer"})

    patch_mini_racer_import()  # 不抛异常
    assert "py_mini_racer" not in sys.modules


def test_patch_mini_racer_import_native_load_failure_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """原生扩展加载错误不能让不依赖 AkShare 的 kan.data 导入失败。"""
    from kan.infra.finalizer_guard import patch_mini_racer_import

    monkeypatch.delitem(sys.modules, "py_mini_racer", raising=False)
    monkeypatch.delitem(sys.modules, "py_mini_racer._mini_racer", raising=False)
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"py_mini_racer", "py_mini_racer._mini_racer"}:
            raise OSError("native library has incompatible architecture")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    patch_mini_racer_import()  # 不抛异常
    assert "py_mini_racer" not in sys.modules


# ── finalizer_guard.defuse_mini_racer_finalizer ──────────────────────────


def test_defuse_via_mini_racer_submodule(monkeypatch: pytest.MonkeyPatch) -> None:
    """包无 MiniRacer 属性 → 从 _mini_racer 子模块取类并包装 __del__。"""
    from kan.infra import finalizer_guard

    monkeypatch.setattr(finalizer_guard, "_defused", False)

    fake_parent = types.ModuleType("py_mini_racer")  # 无 MiniRacer 属性
    fake_sub = types.ModuleType("py_mini_racer._mini_racer")

    class FakeRacer:
        def __del__(self) -> None:
            pass

    original_del = FakeRacer.__del__
    fake_sub.MiniRacer = FakeRacer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "py_mini_racer", fake_parent)
    monkeypatch.setitem(sys.modules, "py_mini_racer._mini_racer", fake_sub)

    finalizer_guard.defuse_mini_racer_finalizer()

    assert finalizer_guard._defused is True
    assert FakeRacer.__del__ is not original_del
    # 包装后的 __del__ 仍调用原实现(异常被静默)
    FakeRacer().__del__()


def test_defuse_wraps_del_and_suppresses_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """包装后的 __del__ 调用原实现并静默异常。"""
    from kan.infra import finalizer_guard

    monkeypatch.setattr(finalizer_guard, "_defused", False)

    class FakeRacer:
        def __del__(self) -> None:
            raise AttributeError("half-initialized")

    fake_parent = types.ModuleType("py_mini_racer")
    fake_parent.MiniRacer = FakeRacer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "py_mini_racer", fake_parent)

    finalizer_guard.defuse_mini_racer_finalizer()

    # 不抛异常 = 噪音被 suppress
    FakeRacer().__del__()


# ── _entry._patch_mini_racer ────────────────────────────────────────────


def test_entry_patch_mini_racer_failure_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补丁失败不阻塞启动(except Exception: pass)。"""
    import kan._entry as entry

    def _boom() -> None:
        raise RuntimeError("patch failed")

    monkeypatch.setattr(
        "kan.infra.finalizer_guard.patch_mini_racer_import", _boom,
    )
    entry._patch_mini_racer()  # 不抛异常


def test_entry_patch_mini_racer_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import kan._entry as entry

    called = []
    monkeypatch.setattr(
        "kan.infra.finalizer_guard.patch_mini_racer_import",
        lambda: called.append(True),
    )
    entry._patch_mini_racer()
    assert called == [True]


def test_defuse_submodule_import_also_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """包无 MiniRacer 且 _mini_racer 子模块也导入失败 → ImportError 被静默。"""
    from kan.infra import finalizer_guard

    monkeypatch.setattr(finalizer_guard, "_defused", False)

    fake_parent = types.ModuleType("py_mini_racer")  # 无 MiniRacer / py_mini_racer 属性
    monkeypatch.setitem(sys.modules, "py_mini_racer", fake_parent)
    monkeypatch.delitem(sys.modules, "py_mini_racer._mini_racer", raising=False)
    _block_import(monkeypatch, {"py_mini_racer._mini_racer"})

    finalizer_guard.defuse_mini_racer_finalizer()  # 不抛异常
    assert finalizer_guard._defused is True
