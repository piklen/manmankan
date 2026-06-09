"""自选股管理兼容门面 · 支持多分组 (GroupedWatchlist)。

storage schema v2:
    {
        "version": 2,
        "default": "自选",
        "groups": {
            "自选": {"stocks": [Stock, ...]},
            "持仓": {"stocks": [Stock, ...]}
        }
    }

单组操作 API (load_watchlist / save_watchlist / add / remove / clear / list_all)
不带 group 参数时走 default 组;带 group 参数时直接操作指定组。
"""
# ruff: noqa: F401

from __future__ import annotations

from kan.storage.paths import (
    NAMES_CACHE_MAX_AGE_DAYS,
    STOCK_NAMES_CACHE,
    WATCHLIST_PATH,
    is_stock_names_cache_fresh,
)
from kan.storage.watchlist_groups import (
    copy_group,
    create_group,
    delete_group,
    get_default_group,
    list_groups,
    move_stock,
    rename_group,
    set_default_group,
)
from kan.storage.watchlist_items import (
    add,
    add_stock,
    clear,
    import_csv,
    list_all,
    remove,
)
from kan.storage.watchlist_json import _atomic_write_json
from kan.storage.watchlist_models import (
    DEFAULT_GROUP_NAME,
    MAX_CSV_SIZE,
    MAX_GROUP_NAME_LEN,
    SCHEMA_VERSION,
    GroupedWatchlist,
    GroupExistsError,
    GroupNotFoundError,
    GroupProtectedError,
    Watchlist,
    WatchlistCorruptError,
    _normalize_symbol,
    _validate_group_name,
)
from kan.storage.watchlist_names import (
    _apply_cached_names,
    _fetch_names_akshare,
    _fetch_names_baostock,
    _load_stock_names,
    _lookup_name,
    load_stock_names_cache,
    preload_stock_names,
    resolve_symbol_or_name,
    search_by_name,
)
from kan.storage.watchlist_store import (
    _save_grouped_watchlist,
    _save_watchlist,
    load_grouped_watchlist,
    load_watchlist,
    save_grouped_watchlist,
    save_watchlist,
)

__all__ = [
    "DEFAULT_GROUP_NAME",
    "MAX_CSV_SIZE",
    "MAX_GROUP_NAME_LEN",
    "NAMES_CACHE_MAX_AGE_DAYS",
    "SCHEMA_VERSION",
    "STOCK_NAMES_CACHE",
    "WATCHLIST_PATH",
    "GroupExistsError",
    "GroupNotFoundError",
    "GroupProtectedError",
    "GroupedWatchlist",
    "Watchlist",
    "WatchlistCorruptError",
    "add",
    "add_stock",
    "clear",
    "copy_group",
    "create_group",
    "delete_group",
    "get_default_group",
    "import_csv",
    "is_stock_names_cache_fresh",
    "list_all",
    "list_groups",
    "load_grouped_watchlist",
    "load_stock_names_cache",
    "load_watchlist",
    "move_stock",
    "preload_stock_names",
    "remove",
    "rename_group",
    "resolve_symbol_or_name",
    "save_grouped_watchlist",
    "save_watchlist",
    "search_by_name",
    "set_default_group",
]
