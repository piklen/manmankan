"""manmankan 用户配置持久化 · ~/.local/share/kan/config.json

设计要点:
- 仅依赖标准库 · 极轻 import · 让 cli 能在重模块加载前先决策 auto_update 偏好
- 损坏自愈: 文件不存在 / JSON 损坏 / 类型不对 / 缺字段都返回默认值不抛异常
- atomic write: 先写 .tmp · os.replace 替换目标 · 防半截写入 (Ctrl-C / 断电 / 磁盘满)
- schema 向后/向前兼容: 未知字段忽略 · 缺字段填默认值
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from kan.paths import BASE_DIR

CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "auto_update": None,          # null=未设过 · True=自动升级 · False=仅 hint 不升级
    "last_check_date": None,      # ISO date "YYYY-MM-DD" · daily cache 命中
    "latest_seen_version": None,  # 上次发现的最新版本号字符串
    "last_hint_date": None,       # 选 False 后 hint 限流 (每周一次)
}


def _atomic_write_json(path: Path, data: Any) -> None:
    """先写 .tmp 再 os.replace · 防半截写入。

    v0.0.4.4: 父目录 mode=0o700 + 写完 chmod 0o600 · 保护用户配置。
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def load() -> dict[str, Any]:
    """加载配置 · 文件不存在 / 损坏 / 类型不对 / 缺字段都自愈返回默认值。

    返回值是新 dict · 修改它不影响 DEFAULT_CONFIG。
    """
    config = dict(DEFAULT_CONFIG)
    if not CONFIG_PATH.exists():
        return config
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError):
        return config  # 损坏自愈
    if not isinstance(loaded, dict):
        return config  # 类型损坏自愈
    for key in DEFAULT_CONFIG:
        if key in loaded:
            config[key] = loaded[key]
    return config


def save(config: dict[str, Any]) -> None:
    """原子写入 · 自动 mkdir · 防半截写入。"""
    _atomic_write_json(CONFIG_PATH, config)
