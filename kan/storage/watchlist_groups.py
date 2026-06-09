"""watchlist 多分组 CRUD 操作。"""
from __future__ import annotations

from kan.core.models import Stock
from kan.storage.watchlist_models import (
    GroupExistsError,
    GroupNotFoundError,
    GroupProtectedError,
    _normalize_symbol,
    _validate_group_name,
)
from kan.storage.watchlist_store import (
    _save_grouped_watchlist,
    load_grouped_watchlist,
)


def list_groups() -> list[tuple[str, int, bool]]:
    """返回 [(组名, 股数, 是否 default), ...] 按插入顺序。"""
    gw = load_grouped_watchlist()
    return [
        (name, len(stocks), name == gw.default)
        for name, stocks in gw.groups.items()
    ]


def create_group(name: str) -> str:
    """创建新组 · 返回规范化后的组名。重名抛 GroupExistsError。"""
    name = _validate_group_name(name)
    gw = load_grouped_watchlist()
    if name in gw.groups:
        raise GroupExistsError(f"组「{name}」已存在 · 跑 `kan group list` 查看")
    gw.groups[name] = []
    _save_grouped_watchlist(gw)
    return name


def rename_group(old: str, new: str) -> str:
    """重命名组 · 同时更新 default 指针 (如指向 old)。返回新组名。"""
    new = _validate_group_name(new)
    gw = load_grouped_watchlist()
    if old not in gw.groups:
        raise GroupNotFoundError(f"组「{old}」不存在")
    if new == old:
        return new  # noop
    if new in gw.groups:
        raise GroupExistsError(
            f"组「{new}」已存在 · 拒绝合并 · 想合并跑 `kan group copy {old} {new}` 再 `kan group delete {old}`"
        )
    # 保插入顺序:重建 dict (Python 3.7+ insertion-ordered)
    gw.groups = {(new if k == old else k): v for k, v in gw.groups.items()}
    if gw.default == old:
        gw.default = new
    _save_grouped_watchlist(gw)
    return new


def delete_group(name: str) -> int:
    """删除组 · 不能删 default (先切换 default 再删) · 返回被删股数。"""
    gw = load_grouped_watchlist()
    if name not in gw.groups:
        raise GroupNotFoundError(f"组「{name}」不存在")
    if name == gw.default:
        raise GroupProtectedError(
            f"组「{name}」是默认组 · 不能删除 · 先 `kan group default <其他组>` 切换"
        )
    count = len(gw.groups[name])
    del gw.groups[name]
    _save_grouped_watchlist(gw)
    return count


def set_default_group(name: str) -> str:
    """切换 default 组 · 返回旧 default 组名。"""
    gw = load_grouped_watchlist()
    if name not in gw.groups:
        raise GroupNotFoundError(f"组「{name}」不存在")
    old = gw.default
    gw.default = name
    _save_grouped_watchlist(gw)
    return old


def get_default_group() -> str:
    """获取当前 default 组名。"""
    return load_grouped_watchlist().default


def copy_group(src: str, dst: str) -> int:
    """复制 src 整组到 dst (dst 必须不存在 · 防误覆盖) · 返回复制的股数。"""
    dst = _validate_group_name(dst)
    gw = load_grouped_watchlist()
    if src not in gw.groups:
        raise GroupNotFoundError(f"源组「{src}」不存在")
    if dst in gw.groups:
        raise GroupExistsError(
            f"目标组「{dst}」已存在 · 拒绝覆盖 · 想覆盖先 `kan group delete {dst}`"
        )
    gw.groups[dst] = [s.model_copy() for s in gw.groups[src]]
    _save_grouped_watchlist(gw)
    return len(gw.groups[dst])


def move_stock(symbol: str, src: str, dst: str) -> tuple[Stock, bool]:
    """跨组移动单股 · src/dst 都必须存在 (不自动建组 · 防 typo 灾难)。

    返回 (移动的 Stock, dst_already_had) ·
    dst_already_had=True 表示目标组已有该股 (只从 src 删除 · 不重复添加)。
    """
    symbol = _normalize_symbol(symbol)
    gw = load_grouped_watchlist()
    if src not in gw.groups:
        raise GroupNotFoundError(f"源组「{src}」不存在")
    if dst not in gw.groups:
        raise GroupNotFoundError(
            f"目标组「{dst}」不存在 · 跑 `kan group create {dst}` 新建 · 不自动建组防 typo"
        )
    src_stocks = gw.groups[src]
    found = next((s for s in src_stocks if s.symbol == symbol), None)
    if found is None:
        raise ValueError(f"{symbol} 不在「{src}」组中")
    dst_existed = any(s.symbol == symbol for s in gw.groups[dst])
    gw.groups[src] = [s for s in src_stocks if s.symbol != symbol]
    if not dst_existed:
        gw.groups[dst].append(found)
    _save_grouped_watchlist(gw)
    return found, dst_existed
