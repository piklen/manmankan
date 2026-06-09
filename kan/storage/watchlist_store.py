"""watchlist v2 schema 读写。"""
from __future__ import annotations

import json

from kan.core.models import Stock
from kan.storage import paths
from kan.storage.watchlist_json import _atomic_write_json
from kan.storage.watchlist_models import (
    DEFAULT_GROUP_NAME,
    SCHEMA_VERSION,
    GroupedWatchlist,
    GroupNotFoundError,
    Watchlist,
    WatchlistCorruptError,
)
from kan.storage.watchlist_names import _apply_cached_names


def load_watchlist(group: str | None = None) -> Watchlist:
    """加载指定组为单组视图 Watchlist (默认 default 组)。

    Watchlist 是单组的轻量容器 · 适合批量「读一组 → 内存改 → 写回一组」;
    需要操作多组时用 load_grouped_watchlist。
    """
    gw = load_grouped_watchlist()
    return Watchlist(stocks=list(gw.get_group(group)))


def _save_watchlist(wl: Watchlist, group: str | None = None) -> None:
    """把单组视图 wl 写回指定组 (默认 default 组)。

    实现:加载完整 GroupedWatchlist · 替换目标组的 stocks · 整体写回
    (保留其他组不被擦除)。
    """
    gw = load_grouped_watchlist()
    target = group or gw.default
    if target not in gw.groups:
        raise GroupNotFoundError(
            f"组「{target}」不存在 · 跑 `kan group create {target}` 新建"
        )
    gw.groups[target] = list(wl.stocks)
    _save_grouped_watchlist(gw)


def save_watchlist(wl: Watchlist, group: str | None = None) -> None:
    """把单组视图 wl 写回磁盘 · group=None 走 default 组。"""
    _save_watchlist(wl, group=group)


def load_grouped_watchlist() -> GroupedWatchlist:
    """加载多分组自选股 storage。

    磁盘 schema:
      {"version": 2, "default": "自选", "groups": {"自选": {"stocks": [...]}}}
    文件不存在 → 返回空的 default 组;default 指向不存在的组时降级修正(防御性)。
    """
    if not paths.WATCHLIST_PATH.exists():
        return GroupedWatchlist()
    try:
        with open(paths.WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
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

    return GroupedWatchlist(groups=groups, default=default)


def _save_grouped_watchlist(gw: GroupedWatchlist) -> None:
    """原子写 v2 schema · 保 0o600 持仓画像隐私底线。"""
    paths.ensure_dirs()
    data = {
        "version": SCHEMA_VERSION,
        "default": gw.default,
        "groups": {
            name: {"stocks": [s.model_dump(mode="json") for s in stocks]}
            for name, stocks in gw.groups.items()
        },
    }
    _atomic_write_json(paths.WATCHLIST_PATH, data)


def save_grouped_watchlist(gw: GroupedWatchlist) -> None:
    """公开 wrapper · cli/group_cmds 直接 import 调用 · 跟 save_watchlist 同形。"""
    _save_grouped_watchlist(gw)
