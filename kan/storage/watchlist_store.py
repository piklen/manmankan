"""watchlist v2 schema 读写。"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterator
from typing import ParamSpec, TypeVar

from kan.core.models import Stock
from kan.storage import paths
from kan.storage.watchlist_json import _atomic_write_json
from kan.storage.watchlist_models import (
    DEFAULT_GROUP_NAME,
    SCHEMA_VERSION,
    GroupedWatchlist,
    GroupNotFoundError,
    Watchlist,
    WatchlistConflictError,
    WatchlistCorruptError,
)
from kan.storage.watchlist_names import _apply_cached_names

_WATCHLIST_THREAD_LOCK = threading.RLock()
_MISSING_SOURCE_TOKEN = "<missing>"


def load_watchlist(group: str | None = None) -> Watchlist:
    """加载指定组为单组视图 Watchlist (默认 default 组)。

    Watchlist 是单组的轻量容器 · 适合批量「读一组 → 内存改 → 写回一组」;
    需要操作多组时用 load_grouped_watchlist。
    """
    gw = load_grouped_watchlist()
    return Watchlist(
        stocks=list(gw.get_group(group)),
        source_token=gw._source_token,
    )


def _save_watchlist(wl: Watchlist, group: str | None = None) -> None:
    """把单组视图 wl 写回指定组 (默认 default 组)。

    实现:加载完整 GroupedWatchlist · 替换目标组的 stocks · 整体写回
    (保留其他组不被擦除)。
    """
    gw = load_grouped_watchlist()
    if wl._source_token is not None and wl._source_token != gw._source_token:
        raise WatchlistConflictError("自选数据已被其他窗口修改 · 请重新打开后再试")
    target = group or gw.default
    if target not in gw.groups:
        raise GroupNotFoundError(
            f"组「{target}」不存在 · 跑 `kan group create {target}` 新建"
        )
    gw.groups[target] = list(wl.stocks)
    _save_grouped_watchlist(gw)
    wl._source_token = gw._source_token


def save_watchlist(wl: Watchlist, group: str | None = None) -> None:
    """把单组视图 wl 写回磁盘 · group=None 走 default 组。"""
    with watchlist_lock():
        _save_watchlist(wl, group=group)


def load_grouped_watchlist() -> GroupedWatchlist:
    """加载多分组自选股 storage。

    磁盘 schema:
      {"version": 2, "default": "自选", "groups": {"自选": {"stocks": [...]}}}
    文件不存在 → 返回空的 default 组;default 指向不存在的组时降级修正(防御性)。
    """
    if not paths.WATCHLIST_PATH.exists():
        return GroupedWatchlist(source_token=_MISSING_SOURCE_TOKEN)
    try:
        raw = paths.WATCHLIST_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise WatchlistCorruptError(
            f"自选股文件损坏（{paths.WATCHLIST_PATH.name}）· "
            f"错误: {e.msg} (行 {e.lineno} 列 {e.colno})"
        ) from e

    raw_groups = data.get("groups", {})
    groups: dict[str, list[Stock]] = {}
    for name, payload in raw_groups.items():
        stock_list = payload.get("stocks", []) if isinstance(payload, dict) else []
        groups[name] = _apply_cached_names([Stock(**s) for s in stock_list])

    default = data.get("default", DEFAULT_GROUP_NAME)
    # default 指向不存在组时降级 (理论不发生 · 防御性):
    # 1. 有任意组 → 取第一个为 default 并写回
    # 2. 完全空 → 重建 default 组
    if default not in groups:
        if groups:
            default = next(iter(groups.keys()))
        else:
            groups[DEFAULT_GROUP_NAME] = []
            default = DEFAULT_GROUP_NAME

    return GroupedWatchlist(
        groups=groups,
        default=default,
        source_token=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _save_grouped_watchlist(gw: GroupedWatchlist) -> None:
    """原子写 v2 schema · 保 0o600 持仓画像隐私底线。"""
    paths.ensure_dirs()
    if gw._source_token is not None and gw._source_token != _current_source_token():
        raise WatchlistConflictError("自选数据已被其他窗口修改 · 请重新打开后再试")
    data = {
        "version": SCHEMA_VERSION,
        "default": gw.default,
        "groups": {
            name: {"stocks": [s.model_dump(mode="json") for s in stocks]}
            for name, stocks in gw.groups.items()
        },
    }
    _atomic_write_json(paths.WATCHLIST_PATH, data)
    gw._source_token = _current_source_token()


def _current_source_token() -> str:
    if not paths.WATCHLIST_PATH.exists():
        return _MISSING_SOURCE_TOKEN
    return hashlib.sha256(paths.WATCHLIST_PATH.read_bytes()).hexdigest()


def save_grouped_watchlist(gw: GroupedWatchlist) -> None:
    """公开 wrapper · cli/group_cmds 直接 import 调用 · 跟 save_watchlist 同形。"""
    with watchlist_lock():
        _save_grouped_watchlist(gw)


_P = ParamSpec("_P")
_R = TypeVar("_R")


@contextlib.contextmanager
def watchlist_lock() -> Iterator[None]:
    """跨进程串行化 watchlist 写事务(load→mutate→save),防 web/CLI 并发丢更新。

    原子写只保证单次写不损坏,挡不住「A 读→B 读→A 写→B 写覆盖 A」的丢更新;
    这里用进程内锁 + 平台文件锁把整段读改写事务串起来。POSIX 使用 flock，
    Windows 使用 msvcrt.locking；文件锁不可用时仍保留进程内互斥。

    注意:flock 是 per-fd 建议锁,同进程嵌套两个 fd 锁同一文件会自锁死,
    因此只在叶子写事务(add/remove/clear)加锁,别在批量外层(import_csv)再套。
    """
    with _WATCHLIST_THREAD_LOCK:
        paths.ensure_dirs()
        lock_path = paths.WATCHLIST_PATH.with_suffix(".lock")
        with open(lock_path, "a+b") as handle:
            with contextlib.suppress(OSError):
                os.chmod(lock_path, 0o600)
            try:
                import fcntl
            except ImportError:
                yield from _windows_watchlist_lock(handle)
            else:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def _windows_watchlist_lock(handle) -> Iterator[None]:
    """Windows 锁定 lock 文件首字节；不可用时仍由进程内锁兜底。"""
    try:
        import msvcrt
    except ImportError:
        yield
        return
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    try:
        yield
    finally:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def with_watchlist_lock(fn: Callable[_P, _R]) -> Callable[_P, _R]:
    """把整段写事务纳入 watchlist_lock 的装饰器 · 保留原签名。"""

    @functools.wraps(fn)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with watchlist_lock():
            return fn(*args, **kwargs)

    return wrapper
