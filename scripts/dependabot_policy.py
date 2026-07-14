"""判定 Dependabot PR 是否属于可自动合并的非 major 更新。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyUpdate:
    name: str
    old: str
    new: str


_GROUP_UPDATE = re.compile(
    r"^Updates `(?P<name>[^`]+)` from (?P<old>\S+) to (?P<new>\S+)\s*$",
    re.MULTILINE,
)
_SINGLE_UPDATE = re.compile(
    r"\bbump (?P<name>.+?) from (?P<old>v?\d\S*) to (?P<new>v?\d\S*)"
    r"(?:\s+in\s+/\S+)?$",
    re.IGNORECASE,
)
_GROUP_SIZE = re.compile(r"\bwith (?P<count>\d+) updates\b", re.IGNORECASE)
_VERSION = re.compile(r"^v?(?P<release>\d+(?:\.\d+)*)(?:[-+].*)?$")


def parse_updates(title: str, body: str) -> tuple[DependencyUpdate, ...]:
    """从单依赖标题或分组 PR 正文提取所有版本变化。"""
    grouped = tuple(DependencyUpdate(*match.groups()) for match in _GROUP_UPDATE.finditer(body))
    if grouped:
        expected = _GROUP_SIZE.search(title)
        if expected is not None and len(grouped) != int(expected.group("count")):
            return ()
        return grouped

    single = _SINGLE_UPDATE.search(title)
    if single is None:
        return ()
    return (DependencyUpdate(*single.groups()),)


def _release(value: str) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.group("release").split("."))


def is_non_major_upgrade(update: DependencyUpdate) -> bool:
    """只允许可解析、向前且首个版本段不变的更新。"""
    old = _release(update.old)
    new = _release(update.new)
    if old is None or new is None or old[0] != new[0]:
        return False
    width = max(len(old), len(new))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def allows_auto_merge(title: str, body: str) -> bool:
    updates = parse_updates(title, body)
    return bool(updates) and all(is_non_major_upgrade(update) for update in updates)


if __name__ == "__main__":
    print(
        "true"
        if allows_auto_merge(os.environ.get("TITLE", ""), os.environ.get("BODY", ""))
        else "false"
    )
