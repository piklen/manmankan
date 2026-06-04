"""Background stock-name cache refresh for CLI startup.

The foreground command must stay fast: this module only decides whether to
spawn a detached worker. The worker performs the slow network fetch and writes
``stock_names.json`` through the existing watchlist cache path.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from kan.infra.log import debug_log
from kan.storage import paths

_LOCK_MAX_AGE_SECONDS = 30 * 60
_LOCK_FILE = ".stock_names_refresh.lock"
_WORKER_ENV = "KAN_STOCK_NAMES_REFRESH_WORKER"
_DISABLE_ENV = "KAN_NO_NAMES_BACKGROUND_REFRESH"


def _is_shell_completion_run() -> bool:
    return bool(os.environ.get("_KAN_COMPLETE") or os.environ.get("_TYPER_COMPLETE_ARGS"))


def _is_interactive_startup() -> bool:
    return sys.stderr.isatty()


def _lock_path() -> Path:
    return paths.BASE_DIR / _LOCK_FILE


def _acquire_lock(lock: Path) -> bool:
    now = time.time()
    if lock.exists():
        try:
            age = now - lock.stat().st_mtime
        except OSError:
            return False
        if age < _LOCK_MAX_AGE_SECONDS:
            return False
        try:
            lock.unlink()
        except OSError:
            return False

    try:
        paths.ensure_dirs()
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        return False

    try:
        payload = f"pid={os.getpid()} started_at={int(now)}\n"
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _release_lock() -> None:
    try:
        _lock_path().unlink()
    except FileNotFoundError:
        return
    except OSError as e:
        debug_log(__name__, "release stock names refresh lock", e)


def maybe_start_stock_names_refresh() -> None:
    """Start a detached stock-name refresh worker when cache is missing/stale.

    This function is intentionally silent and best-effort. It must never affect
    the foreground command's output, exit code, or latency profile.
    """
    if os.environ.get(_WORKER_ENV) == "1":
        return
    if os.environ.get(_DISABLE_ENV) == "1":
        return
    # Existing test/CI knob for startup network background work.
    if os.environ.get("KAN_NO_UPDATE_CHECK") == "1":
        return
    if _is_shell_completion_run():
        return
    if not _is_interactive_startup():
        return

    try:
        if paths.is_stock_names_cache_fresh():
            return
        lock = _lock_path()
        if not _acquire_lock(lock):
            return

        env = os.environ.copy()
        env[_WORKER_ENV] = "1"
        env["KAN_NO_UPDATE_CHECK"] = "1"
        env["KAN_NO_COMPLETION_AUTOINSTALL"] = "1"
        env["KAN_NO_BOOT_BANNER"] = "1"
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": env,
            "close_fds": True,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        subprocess.Popen(
            [sys.executable, "-m", "kan.storage.stock_names_refresh", "--worker"],
            **kwargs,
        )
    except Exception as e:
        _release_lock()
        debug_log(__name__, "start stock names background refresh", e)


def _run_worker() -> int:
    try:
        from kan.storage.watchlist import preload_stock_names

        preload_stock_names()
        return 0
    except Exception as e:
        debug_log(__name__, "stock names background refresh worker", e)
        return 1
    finally:
        _release_lock()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--worker"]:
        return 2
    if os.environ.get(_WORKER_ENV) != "1":
        return 2
    return _run_worker()


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess/unit entry
    raise SystemExit(main())
