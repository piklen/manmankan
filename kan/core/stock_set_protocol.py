"""StockSet 协议定义。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from kan.core.models import BoardMeta, HotMeta, ThemeMeta


@runtime_checkable
class StockSet(Protocol):
    """股票集合抽象 · 任何"一组股票"对象都可以扮演这个 role。

    必需:
    - `name` (property 或 attr): 集合显示名 (CLI 输出 / 日志 / 错误提示)
    - `codes()`: 6 位纯数字代码列表
    - `pairs()`: (代码, 名称) 元组列表 (名称缺失时可为空字符串)
    - `meta()`: 返回 BoardMeta / HotMeta / ThemeMeta / None (method · 不是 property)
      - WatchlistSet → None
      - HotRankSet → HotMeta
      - ThemeSet → ThemeMeta
      - IndustrySet → BoardMeta
      meta() 触发 lazy resolve · 调用前可先 .pairs() 触发 (两者共享 cache)
      用 method 不用 @property:让 `isinstance(x, StockSet)` 的 hasattr 探测不会
      触发 IO (lazy fetch 推迟到实际 .meta() 调用)

    可选:
    - `__len__`: 元素个数 (默认走 len(codes()))
    """

    @property
    def name(self) -> str: ...

    def codes(self) -> list[str]: ...
    def pairs(self) -> list[tuple[str, str]]: ...
    def meta(self) -> BoardMeta | HotMeta | ThemeMeta | None: ...
