"""watchlist JSON 原子写入工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from kan.storage.paths import atomic_write_json


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写：先写 .tmp 同目录文件，再 os.replace 替换目标。

    避免半截写入导致 JSON 损坏（断电/Ctrl-C/磁盘满）。

    背景: 父目录 mkdir mode=0o700 + 写完 chmod 0o600 ·
    保护用户金融持仓数据（防同机其他用户读取持仓画像）。
    """
    atomic_write_json(Path(path), data, ensure_ascii=False, indent=2)
