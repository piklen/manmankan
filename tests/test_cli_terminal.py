"""真实 PTY 验证输出分流与终端恢复；耗时基准由 measure_slo.py 按需测量。"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

pty = pytest.importorskip("pty")
pytestmark = pytest.mark.tty
ROOT = Path(__file__).resolve().parents[1]


def _run_in_terminal(source: str, args: list[str], state: Path) -> tuple[str, str]:
    master, slave = pty.openpty()
    try:
        result = subprocess.run(
            [sys.executable, "-c", source, *args],
            cwd=ROOT,
            env={
                **os.environ,
                "XDG_DATA_HOME": str(state / "data"),
                "XDG_CONFIG_HOME": str(state / "config"),
                "XDG_CACHE_HOME": str(state / "cache"),
                "KAN_NO_COMPLETION_AUTOINSTALL": "1",
                "KAN_NO_UPDATE_CHECK": "1",
                "KAN_NO_NAMES_BACKGROUND_REFRESH": "1",
                "KAN_NO_BOOT_BANNER": "0",
                "TERM": "xterm-256color",
            },
            stdout=subprocess.PIPE,
            stderr=slave,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=True,
        )
        # macOS 关闭最后一个 slave 时会丢弃未读输出，先排空 master 再关闭。
        chunks = []
        while select.select([master], [], [], 0)[0]:
            chunks.append(os.read(master, 4096))
        return result.stdout, b"".join(chunks).decode("utf-8")
    finally:
        os.close(slave)
        os.close(master)


def test_cli_feedback_keeps_json_stdout_parseable(tmp_path):
    stdout, terminal = _run_in_terminal(
        "from kan._entry import main; main()",
        ["find", "--codes", "600519,000858", "--format", "json", "--dry-run"],
        tmp_path,
    )
    payload = json.loads(stdout)
    assert payload["mode"] == "query_plan"
    assert payload["data_plan"]["pool_size_estimate"] == 2
    assert terminal.strip()


@pytest.mark.parametrize("finish", ["complete", "cancel"])
def test_progress_restores_terminal_on_completion_and_sigint(tmp_path, finish):
    stdout, terminal = _run_in_terminal(
        """
import json, os, signal, sys
from contextlib import suppress
from kan.infra.lifecycle import operation
from kan.infra.progress import operation_reporter
with suppress(KeyboardInterrupt):
    with operation("Processing fixture", reporter=operation_reporter(mode="cli", show_after=0)) as op:
        op.progress(1, 2)
        if sys.argv[1] == "cancel":
            os.kill(os.getpid(), signal.SIGINT)
print(json.dumps({"finish": sys.argv[1]}))
""",
        [finish],
        tmp_path,
    )
    assert json.loads(stdout) == {"finish": finish}
    assert "Processing fixture" in terminal
    assert terminal.rfind("\x1b[?25h") > terminal.find("\x1b[?25l") >= 0
