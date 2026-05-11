#!/usr/bin/env python3
"""Measure real CLI first-byte and Rich spinner timing through the installed kan wrapper."""

from __future__ import annotations

import os
import pty
import select
import shutil
import signal
import sys
import time
from contextlib import suppress

KAN = shutil.which("kan")
if not KAN:
    print("kan is not in PATH. Run: uv tool install --reinstall .")
    sys.exit(1)

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


def measure(args: list[str]) -> tuple[float | None, float | None]:
    pid, fd = pty.fork()
    if pid == 0:
        env = os.environ.copy()
        env["KAN_NO_COMPLETION_AUTOINSTALL"] = "1"
        env["KAN_NO_UPDATE_CHECK"] = "1"
        env["TERM"] = "xterm-256color"
        os.execvpe("kan", ["kan", *args], env)

    start = time.monotonic()
    first_byte: float | None = None
    spinner_t: float | None = None

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
                if first_byte is None:
                    first_byte = now
                if spinner_t is None and any(frame in data for frame in SPINNER_BYTES):
                    spinner_t = now
                    break

            done_pid, _ = os.waitpid(pid, os.WNOHANG)
            if done_pid:
                break
            if time.monotonic() - start > 5:
                break
    finally:
        with suppress(OSError):
            os.kill(pid, signal.SIGKILL)
        with suppress(OSError):
            os.waitpid(pid, 0)
        with suppress(OSError):
            os.close(fd)

    return first_byte, spinner_t


def main() -> None:
    cmds = [
        ["--help"],
        ["add", "600519"],
        ["scan"],
        ["low", "60"],
        ["high", "30"],
        ["info", "600519"],
        ["trend"],
    ]
    print(f"{'cmd':<22}{'TTFB(min/3)':>14}{'spinner(min/3)':>16}")
    for args in cmds:
        runs = []
        for _ in range(3):
            runs.append(measure(args))
            time.sleep(0.1)
        ttfbs = [first * 1000 for first, _ in runs if first is not None]
        spinners = [spinner * 1000 for _, spinner in runs if spinner is not None]
        ttfb = f"{min(ttfbs):.0f}ms" if ttfbs else "None"
        spinner = f"{min(spinners):.0f}ms" if spinners else "None"
        print(f"{'kan ' + ' '.join(args):<22}{ttfb:>14}{spinner:>16}")


if __name__ == "__main__":
    main()
