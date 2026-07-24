"""路径管理 · XDG Base Directory 规范

数据存放在 $XDG_DATA_HOME/kan/（默认 ~/.local/share/kan/），符合 XDG 规范。
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def _get_base_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "kan"
    return Path.home() / ".local" / "share" / "kan"


BASE_DIR = _get_base_dir()
DATA_DIR = BASE_DIR / "data"
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
POSITIONS_PATH = BASE_DIR / "positions.json"
STOCK_NAMES_CACHE = BASE_DIR / "stock_names.json"
SNAPSHOT_PATH = BASE_DIR / "last_scan.json"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
WEB_SNAPSHOTS_DIR = BASE_DIR / "web_snapshots"
AGENT_SNAPSHOTS_DIR = BASE_DIR / "agent_snapshots"
CIRCUIT_PATH = BASE_DIR / "circuit.json"
BOARDS_DIR = BASE_DIR / "boards"
HOT_DIR = BASE_DIR / "hot"

NAMES_CACHE_MAX_AGE_DAYS = 1
"""代码表缓存新鲜窗口(天) · 1 天:新上市股票 24h 内可 kan add。

刷新走启动期后台 worker(baostock ~5s · 不占前台),每日一次的代价
可忽略;7 天窗口会让打新用户最长一周无法添加新股。"""


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

    背景: mode=0o700 保护用户金融持仓画像（防同机其他用户/容器逃逸/SSH 多用户跳板机）。
    """
    directories = (
        BASE_DIR,
        DATA_DIR,
        SNAPSHOTS_DIR,
        WEB_SNAPSHOTS_DIR,
        AGENT_SNAPSHOTS_DIR,
        BOARDS_DIR,
        HOT_DIR,
    )
    for directory in directories:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # mkdir(exist_ok=True) 不会收紧升级前已经存在的宽松权限。
        with contextlib.suppress(OSError):
            os.chmod(directory, 0o700)


def atomic_write_parquet(
    df,
    path: Path,
    *,
    metadata: dict[str, str] | None = None,
) -> None:
    """atomic 写入 parquet · 防中断损坏旧文件。

    实现：同目录唯一临时文件写完后 os.replace(tmp, path) · POSIX + Windows
    atomic guarantee (Python 3.3+)。所有 parquet 写入统一走此 helper · 保持
    paths.py 轻量 (df 不加 pd.DataFrame 注解 · 不顶层 import pandas)。

    加 chmod 0o600 防持仓画像跨备份(Time Machine / iCloud)/
    跨容器逃逸 / 跨 FS(SMB/NFS)被同机其他用户读。父目录 0o700 是中度防御 ·
    0o600 是最后一道线。
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp = Path(handle.name)
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
        if metadata:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pandas(df, preserve_index=False)
            schema_metadata = dict(table.schema.metadata or {})
            schema_metadata.update({
                key.encode("utf-8"): value.encode("utf-8")
                for key, value in metadata.items()
            })
            pq.write_table(table.replace_schema_metadata(schema_metadata), tmp)
        else:
            df.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink()
    # Windows / 异常 FS chmod 失败容错(不致命)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def atomic_write_json(path: Path, data: object, **dumps_kw) -> None:
    """atomic 写入 JSON + chmod 0o600(持仓画像保护)。

    替代 path.write_text(json.dumps(...)) · 所有 cache/snapshot 写入应走此 helper:
    - boards.py / hot.py / circuit_breaker.py 等 cache 文件
    - 自动 atomic(tmp + os.replace)+ 0o600

    json.dumps 参数(ensure_ascii / indent 等)通过 **dumps_kw 透传。

    Examples:
        atomic_write_json(cache, [b.model_dump() for b in boards], ensure_ascii=False)
    """
    import json

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp = Path(handle.name)
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            handle.write(json.dumps(data, **dumps_kw))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink()
    # Windows / 异常 FS chmod 失败容错(不致命)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
