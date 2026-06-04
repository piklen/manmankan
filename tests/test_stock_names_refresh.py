"""Background stock-name refresh startup behavior."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kan.storage import paths, stock_names_refresh


class _FakeStderr:
    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


@pytest.fixture
def temp_kan_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(paths, "STOCK_NAMES_CACHE", tmp_path / "stock_names.json")
    monkeypatch.setattr(paths, "SNAPSHOT_PATH", tmp_path / "last_scan.json")
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "BOARDS_DIR", tmp_path / "boards")
    monkeypatch.setattr(paths, "HOT_DIR", tmp_path / "hot")
    return tmp_path


def test_maybe_start_spawns_detached_worker_when_cache_missing(
    temp_kan_paths, monkeypatch
):
    monkeypatch.delenv("KAN_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("KAN_NO_NAMES_BACKGROUND_REFRESH", raising=False)
    monkeypatch.delenv("_KAN_COMPLETE", raising=False)
    monkeypatch.delenv("_TYPER_COMPLETE_ARGS", raising=False)
    calls: list[tuple[list[str], dict]] = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(stock_names_refresh.sys, "stderr", _FakeStderr(is_tty=True))
    monkeypatch.setattr(stock_names_refresh.subprocess, "Popen", fake_popen)

    stock_names_refresh.maybe_start_stock_names_refresh()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[1:] == ["-m", "kan.storage.stock_names_refresh", "--worker"]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["env"]["KAN_STOCK_NAMES_REFRESH_WORKER"] == "1"
    assert (temp_kan_paths / ".stock_names_refresh.lock").exists()


def test_maybe_start_skips_when_update_checks_disabled(temp_kan_paths, monkeypatch):
    monkeypatch.setattr(stock_names_refresh.sys, "stderr", _FakeStderr(is_tty=True))
    monkeypatch.setenv("KAN_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(
        stock_names_refresh.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("should not spawn worker"),
    )

    stock_names_refresh.maybe_start_stock_names_refresh()

    assert not (temp_kan_paths / ".stock_names_refresh.lock").exists()


def test_maybe_start_skips_shell_completion(temp_kan_paths, monkeypatch):
    monkeypatch.delenv("KAN_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setenv("_KAN_COMPLETE", "complete_zsh")
    monkeypatch.setattr(stock_names_refresh.sys, "stderr", _FakeStderr(is_tty=True))
    monkeypatch.setattr(
        stock_names_refresh.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("should not spawn worker"),
    )

    stock_names_refresh.maybe_start_stock_names_refresh()

    assert not (temp_kan_paths / ".stock_names_refresh.lock").exists()


def test_maybe_start_skips_non_interactive_startup(temp_kan_paths, monkeypatch):
    monkeypatch.delenv("KAN_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("_KAN_COMPLETE", raising=False)
    monkeypatch.delenv("_TYPER_COMPLETE_ARGS", raising=False)
    monkeypatch.setattr(stock_names_refresh.sys, "stderr", _FakeStderr(is_tty=False))
    monkeypatch.setattr(
        stock_names_refresh.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("should not spawn worker"),
    )

    stock_names_refresh.maybe_start_stock_names_refresh()

    assert not (temp_kan_paths / ".stock_names_refresh.lock").exists()


def test_worker_releases_lock(temp_kan_paths, monkeypatch):
    lock = temp_kan_paths / ".stock_names_refresh.lock"
    lock.write_text("pid=1\n", encoding="utf-8")
    calls: list[bool] = []

    def fake_preload():
        calls.append(True)
        return {"600519": "贵州茅台"}

    monkeypatch.setenv("KAN_STOCK_NAMES_REFRESH_WORKER", "1")
    monkeypatch.setattr("kan.storage.watchlist.preload_stock_names", fake_preload)

    assert stock_names_refresh.main(["--worker"]) == 0
    assert calls == [True]
    assert not lock.exists()
