"""manmankan 用户配置持久化 · ~/.local/share/kan/config.json

设计要点:
- 仅依赖标准库 · 极轻 import · 让 cli 能在重模块加载前先决策 auto_update 偏好
- 损坏自愈: 文件不存在 / JSON 损坏 / 类型不对 / 缺字段都返回默认值不抛异常
- atomic write: 先写 .tmp · os.replace 替换目标 · 防半截写入 (Ctrl-C / 断电 / 磁盘满)
- schema 向后/向前兼容: 未知字段忽略 · 缺字段填默认值
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from kan.storage.paths import BASE_DIR, atomic_write_json

CONFIG_PATH = BASE_DIR / "config.json"
_CONFIG_THREAD_LOCK = threading.RLock()

DEFAULT_CONFIG: dict[str, Any] = {
    "auto_update": None,          # null=未设过 · True=自动升级 · False=仅 hint 不升级
    "last_check_date": None,      # ISO date "YYYY-MM-DD" · daily cache 命中
    "latest_seen_version": None,  # 上次发现的最新版本号字符串
    "last_hint_date": None,       # 选 False 后 hint 限流 (每周一次)
    "completion_setup": None,     # null=未询问 · True=已安装/确认 · False=不再提示
    "mcp_setup": None,            # null=未询问 · True=已安装/确认 · False=不再提示
    "env_setup_last_skip_date": None,  # ISO date · setup prompt skip 限流
    "tushare_token": None,        # 背景: TuShare Pro API token (None=未配置 → 跳过 TS 分支)
    "tushare_endpoint": None,     # 背景: TuShare Pro 端点 (None=用 https://api.tushare.pro 默认)
}


def _atomic_write_json(path: Path, data: Any) -> None:
    """唯一临时文件原子写入，写入期间也保持 0600。"""
    atomic_write_json(path, data, ensure_ascii=False, indent=2)


@contextlib.contextmanager
def config_lock() -> Iterator[None]:
    """串行化配置的 load→修改→save；文件锁不可重入，调用方不得嵌套。"""
    with _CONFIG_THREAD_LOCK:
        CONFIG_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(CONFIG_PATH.parent, 0o700)
        lock_path = CONFIG_PATH.with_suffix(".lock")
        with open(lock_path, "a+b") as handle:
            with contextlib.suppress(OSError):
                os.chmod(lock_path, 0o600)
            try:
                import fcntl
            except ImportError:
                yield from _windows_config_lock(handle)
            else:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def _windows_config_lock(handle) -> Iterator[None]:
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
    with config_lock():
        _atomic_write_json(CONFIG_PATH, config)


def update(**changes: Any) -> dict[str, Any]:
    """在同一锁事务中更新指定字段，避免并发覆盖其他配置。"""
    unknown = changes.keys() - DEFAULT_CONFIG.keys()
    if unknown:
        raise KeyError(f"未知配置项: {', '.join(sorted(unknown))}")
    with config_lock():
        current = load()
        current.update(changes)
        _atomic_write_json(CONFIG_PATH, current)
        return current


def mask_token(token: str | None) -> str:
    """末 4 位显形 · 前面 *** · 少于 4 位 / None / 空串全返 '***'。

    所有 token 出 CLI / 日志 / 错误消息一律走此函数 · 永不直传原 token。
    """
    if not token or len(token) < 4:
        return "***"
    return f"***{token[-4:]}"
