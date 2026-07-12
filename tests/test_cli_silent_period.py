"""PTY 真终端回归：CLI 重路径按回车后必须快速出现可见反馈。"""

from __future__ import annotations

import json
import os
import pty
import select
import shutil
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

pytestmark = pytest.mark.tty

ROOT = Path(__file__).resolve().parents[1]


def _is_github_macos() -> bool:
    """GitHub-hosted macOS TTY timing jitters more than local terminals."""
    return sys.platform == "darwin" and os.environ.get("GITHUB_ACTIONS") == "true"


def _is_github_linux() -> bool:
    """Self-hosted Linux runner 会和并行测试共享 CPU，TTY timing 只做回归兜底。"""
    return sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true"


# 200ms 是理想目标；真实 `uv tool install` wrapper 还要承担 Python startup +
# entry point import 的物理开销。当前架构下以真实 wrapper 取 400ms 作为回归 SLO。
SLO_MS = 1200.0 if _is_github_linux() else (550.0 if _is_github_macos() else 400.0)
# B.8 (历史背景macOS flake hotfix): macOS GitHub runner I/O 抖动严重 · 100ms 太严
# macOS 真测 ttfb 经常落在 150-200ms · 加 platform-aware 阈值
# 详见 [[project_manmankan_macos_slo_flake_session_2026_05_13]] · 历史背景改用 best-of-N 或异常重试
HELP_TTFB_SLO_MS = 1500.0 if _is_github_linux() else (600.0 if _is_github_macos() else (250.0 if sys.platform == "darwin" else 100.0))
# Rich status 会先写出 message/control bytes，再按 refresh tick 输出动画帧。
# 这里把"按回车后有可见反馈"和"spinner 帧最终开始转动"分开守门：
# - ttfb 仍用 SLO_MS 抓真正沉默；
# - spinner 帧只做硬上限，避免 self-hosted runner 负载抖动把 main 打红。
LIFECYCLE_DISPLAY_HARD_CAP_MS = 2500.0 if _is_github_linux() else (1400.0 if _is_github_macos() else 1200.0)
# 新生命周期系统 Rich Live.start() 写 \x1b[?25l 隐藏光标，是可靠的第一帧信号。
# 旧版 Rich SpinnerColumn（⠋ ⠙ ⠹ …）已随 _with_heavy_imports_spinner 移除，不再检测。
LIFECYCLE_BYTES = (b"\x1b[?25l",)


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
    stop_on_lifecycle: bool = True,
) -> dict[str, float | int | str | None]:
    if shutil.which("kan") is None:
        pytest.skip("kan is not in PATH. Run: uv tool install --reinstall .")

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
        os.execvpe("kan", ["kan", *args], env)

    start = time.monotonic()
    first_byte_t: float | None = None
    lifecycle_t: float | None = None
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
                if lifecycle_t is None and any(frame in data for frame in LIFECYCLE_BYTES):
                    lifecycle_t = now
                    if stop_on_lifecycle:
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
        "lifecycle_first_frame_ms": lifecycle_t * 1000 if lifecycle_t is not None else None,
        "total_chunks": chunks,
    }


def _measure_best_of_three(
    args: list[str],
    xdg_home: Path,
    *,
    timeout_s: float = 5.0,
    stop_on_lifecycle: bool = True,
) -> dict[str, float | int | str | None]:
    results = [
        _measure_cli(
            args,
            xdg_home,
            timeout_s=timeout_s,
            stop_on_lifecycle=stop_on_lifecycle,
        )
        for _ in range(3)
    ]
    ttfbs = [r["ttfb_ms"] for r in results if r["ttfb_ms"] is not None]
    lifecycles = [
        r["lifecycle_first_frame_ms"]
        for r in results
        if r["lifecycle_first_frame_ms"] is not None
    ]
    best = dict(results[0])
    best["ttfb_ms"] = min(ttfbs) if ttfbs else None
    best["lifecycle_first_frame_ms"] = min(lifecycles) if lifecycles else None
    best["attempts_json"] = json.dumps(results, ensure_ascii=False)
    return best


def test_help_ttfb_stays_fast(tmp_path: Path) -> None:
    result = _measure_best_of_three(
        ["--help"],
        tmp_path / "help",
        timeout_s=2.0,
        stop_on_lifecycle=False,
    )
    assert result["ttfb_ms"] is not None, result
    assert result["ttfb_ms"] <= HELP_TTFB_SLO_MS, result


def test_find_help_ttfb_stays_fast(tmp_path: Path) -> None:
    result = _measure_best_of_three(
        ["find", "--help"],
        tmp_path / "find-help",
        timeout_s=2.0,
        stop_on_lifecycle=False,
    )
    assert result["ttfb_ms"] is not None, result
    assert result["ttfb_ms"] <= HELP_TTFB_SLO_MS, result


def test_add_code_fast_path_ttfb_stays_fast(tmp_path: Path) -> None:
    result = _measure_best_of_three(
        ["add", "600519"],
        tmp_path / "add-fast-path",
        timeout_s=2.0,
        stop_on_lifecycle=False,
    )
    assert result["ttfb_ms"] is not None, result
    assert result["ttfb_ms"] <= SLO_MS, result


@pytest.mark.parametrize(
    "args,needs_watchlist",
    [
        (["scan"], True),
        (["fetch", "600519", "--force"], False),
        (["info", "600519"], True),
    ],
)
def test_heavy_commands_show_lifecycle_within_slo(
    tmp_path: Path,
    args: list[str],
    needs_watchlist: bool,
) -> None:
    """重命令（有网络 I/O）必须在新生命周期的 show_after 延迟后显示 Live。"""
    xdg_home = tmp_path / ("-".join(args).replace("/", "_"))
    if needs_watchlist:
        _seed_watchlist(xdg_home)

    result = _measure_best_of_three(args, xdg_home)
    assert result["ttfb_ms"] is not None, result
    assert result["ttfb_ms"] <= SLO_MS, result
    assert result["lifecycle_first_frame_ms"] is not None, result
    assert result["lifecycle_first_frame_ms"] <= LIFECYCLE_DISPLAY_HARD_CAP_MS, result


@pytest.mark.parametrize(
    "args,needs_watchlist",
    [
        (["low", "60"], True),
        (["high", "60"], True),
        (["trend"], True),
    ],
)
def test_fast_commands_ttfb_within_slo(
    tmp_path: Path,
    args: list[str],
    needs_watchlist: bool,
) -> None:
    """轻命令在 150ms show_after 内完成时不强制显示生命周期（零感停顿设计）。"""
    xdg_home = tmp_path / ("-".join(args).replace("/", "_"))
    if needs_watchlist:
        _seed_watchlist(xdg_home)

    result = _measure_best_of_three(args, xdg_home)
    assert result["ttfb_ms"] is not None, result
    assert result["ttfb_ms"] <= SLO_MS, result
