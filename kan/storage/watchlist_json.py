"""watchlist JSON 原子写入工具。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写：先写 .tmp 同目录文件，再 os.replace 替换目标。

    避免半截写入导致 JSON 损坏（断电/Ctrl-C/磁盘满）。

    背景: 父目录 mkdir mode=0o700 + 写完 chmod 0o600 ·
    保护用户金融持仓数据（防同机其他用户读取持仓画像）。
    """
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    # 收紧权限到 0o600 (umask 默认 022 会留 0644 · 同机其他用户能读)
    os.chmod(path, 0o600)
