"""第三方库 finalizer 噪音抑制。

py_mini_racer 在部分机器上 dylib 加载失败(如架构不匹配)时,半初始化实例被 GC
会经 unraisablehook 向 stderr 打出 "Exception ignored in MiniRacer.__del__" 的
裸 traceback,污染 CLI/Web 输出。akshare 的部分接口会间接 import 它。
这里把它的 __del__ 包一层 try/except:只清噪音,不改变正常释放路径。
"""
from __future__ import annotations

import contextlib
import sys

_defused = False


def patch_mini_racer_import() -> None:
    """修复 mini-racer 0.14+ 在 macOS 上缺少 __init__.py 的问题。

    mini-racer 0.14+ 在 macOS 上安装为 py_mini_racer 命名空间包，
    没有 __init__.py，导致 `from py_mini_racer import MiniRacer` 失败。
    此函数在 sys.modules 中注入一个兼容的 py_mini_racer 模块。
    """
    if "py_mini_racer" in sys.modules:
        return
    try:
        # 先尝试正常导入
        import py_mini_racer
        if hasattr(py_mini_racer, "MiniRacer"):
            return
    except ImportError:
        pass
    # 尝试从 _mini_racer 子模块导入
    try:
        import types

        from py_mini_racer._mini_racer import MiniRacer

        # 创建一个兼容的模块对象
        compat_module = types.ModuleType("py_mini_racer")
        compat_module.MiniRacer = MiniRacer
        compat_module.__file__ = getattr(sys.modules.get("py_mini_racer._mini_racer"), "__file__", None)
        sys.modules["py_mini_racer"] = compat_module
    except ImportError:
        pass


def defuse_mini_racer_finalizer() -> None:
    """让 py_mini_racer 半初始化实例的析构不再向 stderr 抛裸 traceback。幂等。"""
    global _defused
    if _defused:
        return
    _defused = True
    racer_cls = None
    try:
        import py_mini_racer

        racer_cls = getattr(py_mini_racer, "MiniRacer", None)
        if racer_cls is None:
            # mini-racer 0.14+ 在 macOS 上是命名空间包，没有 __init__.py
            try:
                from py_mini_racer._mini_racer import MiniRacer

                racer_cls = MiniRacer
            except ImportError:
                pass
        if racer_cls is None:
            from py_mini_racer import py_mini_racer as _impl  # type: ignore[attr-defined]

            racer_cls = getattr(_impl, "MiniRacer", None)
    except Exception:
        # 未安装/导入即崩 → 没有可修补的对象
        return
    if racer_cls is None:
        return
    original = getattr(racer_cls, "__del__", None)
    if original is None:
        return

    def _quiet_del(self: object) -> None:
        # 半初始化实例(dylib 加载失败)析构时的属性错误 · 静默丢弃
        with contextlib.suppress(Exception):
            original(self)

    racer_cls.__del__ = _quiet_del
