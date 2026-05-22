"""路径管理 · XDG Base Directory 规范

数据存放在 $XDG_DATA_HOME/kan/（默认 ~/.local/share/kan/），符合 XDG 规范。
首次运行如检测到旧路径 ~/.kan/，自动迁移到新位置。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_LEGACY_DIR = Path.home() / ".kan"


def _get_base_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "kan"
    return Path.home() / ".local" / "share" / "kan"


BASE_DIR = _get_base_dir()
DATA_DIR = BASE_DIR / "data"
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
STOCK_NAMES_CACHE = BASE_DIR / "stock_names.json"
SNAPSHOT_PATH = BASE_DIR / "last_scan.json"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
CIRCUIT_PATH = BASE_DIR / "circuit.json"
BOARDS_DIR = BASE_DIR / "boards"
HOT_DIR = BASE_DIR / "hot"

NAMES_CACHE_MAX_AGE_DAYS = 7


def is_stock_names_cache_fresh() -> bool:
    """A 股代码表本地缓存是否新鲜（< NAMES_CACHE_MAX_AGE_DAYS 天）。

    只看 mtime · 不读文件内容 · 保持极轻 (~370μs import 成本)。
    放在 paths.py 而非 watchlist.py：让 CLI 在 import 重模块（akshare/pandas）
    之前就能决策是否需要拉取，spinner 可以提前到重模块 import 之前显示。
    """
    if not STOCK_NAMES_CACHE.exists():
        return False
    from datetime import datetime
    mtime = datetime.fromtimestamp(STOCK_NAMES_CACHE.stat().st_mtime)
    return (datetime.now() - mtime).days < NAMES_CACHE_MAX_AGE_DAYS


def ensure_dirs() -> None:
    """确保数据目录存在。

    v0.0.4.4: mode=0o700 保护用户金融持仓画像（防同机其他用户/容器逃逸/SSH 多用户跳板机）。
    """
    BASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    BOARDS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    HOT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def atomic_write_parquet(df, path: Path) -> None:
    """atomic 写入 parquet · 防中断损坏旧文件。

    实现：写 path.tmp 再 os.replace(tmp, path) · POSIX + Windows atomic
    guarantee (Python 3.3+)。所有 parquet 写入统一走此 helper · 保持
    paths.py 轻量 (df 不加 pd.DataFrame 注解 · 不顶层 import pandas)。
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def migrate_legacy() -> None:
    """从 ~/.kan/ 自动迁移到 XDG 路径 · 仅首次运行时触发。"""
    if not _LEGACY_DIR.exists():
        return
    if WATCHLIST_PATH.exists():
        return

    ensure_dirs()
    for item in _LEGACY_DIR.iterdir():
        dest = BASE_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    readme = _LEGACY_DIR / "_MIGRATED.txt"
    readme.write_text(
        f"数据已迁移到 {BASE_DIR}\n"
        "此目录可安全删除。\n"
    )

    import typer
    # P1-9: migration message 走 stderr · 不污染 stdout
    # (kan --version 等 nullary 命令保持干净 · 脚本可 2>/dev/null 过滤)
    typer.echo(f"📦 数据已从 ~/.kan/ 迁移到 {BASE_DIR}", err=True)
    typer.echo("   旧目录可安全删除（rm -rf ~/.kan/）", err=True)
