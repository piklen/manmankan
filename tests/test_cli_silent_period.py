"""PTY 真终端回归：CLI 重路径按回车后必须快速出现可见反馈。"""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

pytestmark = pytest.mark.tty

ROOT = Path(__file__).resolve().parents[1]
SLO_MS = 200.0
HELP_TTFB_SLO_MS = 100.0
CLI_BOOTSTRAP = (
    "import sys; "
    "sys.argv = ['kan', *sys.argv[1:]]; "
    "from kan.cli import cli_main; "
    "cli_main()"
)
SPINNER_BYTES = (
    b"\xe2\xa0\x8b",
    b"\xe2\xa0\x99",
    b"\xe2\xa0\xb9",
    b"\xe2\xa0\xb8",
    b"\xe2\xa0\xbc",
    b"\xe2\xa0\xb4",
    b"\xe2\xa0\xa6",
    b"\xe2\xa0\xa7",
    b"\xe2\xa0\x87",
    b"\xe2\xa0\x8f",
)


def _seed_watchlist(xdg_home: Path) -> None:
    base = xdg_home / "kan"
    base.mkdir(parents=True, exist_ok=True)
    (base / "watchlist.json").write_text(
        json.dumps({
            "stocks": [
                {"symbol": "600519", "name": "贵州茅台", "added_at": "2026-05-11"},
            ],
        }),
        encoding="utf-8",
    )
    (base / "stock_names.json").write_text(
        json.dumps({"600519": "贵州茅台"}, ensure_ascii=False),
        encoding="utf-8",
    )


def _measure_cli(
    args: list[str],
    xdg_home: Path,
    *,
    timeout_s: float = 5.0,
    stop_on_spinner: bool = True,
) -> dict[str, float | int | str | None]:
    pid, fd = pty.fork()
    if pid == 0:
        env = os.environ.copy()
        env.update({
            "XDG_DATA_HOME": str(xdg_home),
            "KAN_NO_COMPLETION_AUTOINSTALL": "1",
            "KAN_NO_UPDATE_CHECK": "1",
            "TERM": "xterm-256color",
        })
        os.chdir(ROOT)
        os.execve(sys.executable, [sys.executable, "-c", CLI_BOOTSTRAP, *args], env)

    start = time.monotonic()
    first_byte_t: float | None = None
    spinner_t: float | None = None
    chunks = 0
    killed = False

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0.02)
            if ready:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                now = time.monotonic() - start
                chunks += 1
                if first_byte_t is None:
                    first_byte_t = now
                if spinner_t is None and any(frame in data for frame in SPINNER_BYTES):
                    spinner_t = now
                    if stop_on_spinner:
                        os.kill(pid, signal.SIGKILL)
                        killed = True
                        break

            done_pid, _ = os.waitpid(pid, os.WNOHANG)
            if done_pid:
                break
            if time.monotonic() - start > timeout_s:
                os.kill(pid, signal.SIGKILL)
                killed = True
                break
    finally:
        try:
            if killed:
                os.waitpid(pid, 0)
            else:
                os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        with suppress(OSError):
            os.close(fd)

    return {
        "cmd": "kan " + " ".join(args),
        "ttfb_ms": first_byte_t * 1000 if first_byte_t is not None else None,
        "spinner_first_frame_ms": spinner_t * 1000 if spinner_t is not None else None,
        "total_chunks": chunks,
    }


def test_help_ttfb_stays_fast(tmp_path: Path) -> None:
    result = _measure_cli(["--help"], tmp_path / "help", timeout_s=2.0, stop_on_spinner=False)
    assert result["ttfb_ms"] is not None, result
    assert result["ttfb_ms"] <= HELP_TTFB_SLO_MS, result


@pytest.mark.parametrize(
    "args,needs_watchlist",
    [
        (["add", "600519"], False),
        (["scan"], True),
    ],
)
def test_heavy_commands_show_spinner_within_slo(
    tmp_path: Path,
    args: list[str],
    needs_watchlist: bool,
) -> None:
    xdg_home = tmp_path / ("-".join(args).replace("/", "_"))
    if needs_watchlist:
        _seed_watchlist(xdg_home)

    result = _measure_cli(args, xdg_home)
    assert result["spinner_first_frame_ms"] is not None, result
    assert result["spinner_first_frame_ms"] <= SLO_MS, result
