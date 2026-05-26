"""CLI integration tests for `kan find` (v0.0.6.4).

Uses subprocess (not typer.CliRunner) to avoid sys.argv shenanigans with
the root @app.callback() that checks `len(sys.argv) == 1`.
"""

import os
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args: list[str]) -> tuple[int, str]:
    """Run `kan find ARGS` via uv subprocess · returns (exit_code, combined output)."""
    env = {**os.environ, "KAN_NO_BOOT_BANNER": "1"}
    result = subprocess.run(
        ["uv", "run", "kan", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout + result.stderr


class TestFindCli:
    def test_empty_filter_exits_one(self):
        ec, out = _run(["find"])
        assert ec == 1
        assert "至少需要一个 filter" in out
        assert "kan find --pos 180:lt:5" in out

    def test_bad_pos_format_exits_two(self):
        ec, out = _run(["find", "--pos", "bad:format"])
        assert ec == 2
        assert "格式错误" in out or "周期非整数" in out

    def test_bad_pos_period_exits_two(self):
        ec, out = _run(["find", "--pos", "200:lt:5"])
        assert ec == 2
        assert "周期 200 不支持" in out

    def test_bad_pos_value_exits_two(self):
        ec, out = _run(["find", "--pos", "180:lt:150"])
        assert ec == 2
        assert "数值 150" in out or "越界" in out

    def test_bad_resonance_level_exits_two(self):
        ec, out = _run(["find", "--resonance", "mid:gte:3"])
        assert ec == 2
        assert "级别" in out and "不支持" in out

    def test_mutex_pools_exit_two(self):
        ec, out = _run(["find", "--pos", "180:lt:5", "--industry", "X", "--theme", "Y"])
        assert ec == 2
        assert "互斥" in out

    def test_only_watchlist_without_pool_exits_one(self):
        ec, out = _run(["find", "--pos", "180:lt:5", "--only-watchlist"])
        assert ec == 1
        assert "--only-watchlist" in out

    def test_help_includes_examples(self):
        ec, out = _run(["find", "--help"])
        # exit_code may be 0 (typer help)
        assert ec in (0, 2)
        assert "PERIOD:OP:VAL" in out or "kan find" in out

    @pytest.mark.skipif(
        not os.environ.get("KAN_RUN_FIND_DATA_TEST"),
        reason="needs watchlist data · set KAN_RUN_FIND_DATA_TEST=1 to run",
    )
    def test_with_data_renders_table_and_disclaimer(self):
        """Optional: needs actual watchlist + kline cache."""
        ec, out = _run(["find", "--pos", "180:lte:100"])  # match everything
        assert ec == 0
        assert "kan find" in out
        # Compliance disclaimer must always appear
        assert "候选 ≠ 买入信号" in out
        assert "不构成任何形式的推荐或建议" in out


class TestFindCompliance:
    """Compliance-driven tests · §7 hard rules · enforce 命名 + disclaimer."""

    def test_help_does_not_contain_banned_words(self):
        _ec, out = _run(["find", "--help"])
        # Skip if help fell back to banner · only check if help worked
        if "PERIOD:OP:VAL" not in out and "kan find" not in out:
            pytest.skip("help fell back to banner · cannot verify")
        # Compliance §3 §4: forbidden terms in user-facing output
        banned = ["推荐", "优选", "黑马", "建议买入", "建议关注", "强推", "值得关注"]
        for word in banned:
            assert word not in out, f"compliance §3 violated: '{word}' in find help"

    def test_error_messages_use_neutral_phrasing(self):
        ec, out = _run(["find"])
        assert ec == 1
        # error messages should reference "filter" not "推荐 / 建议"
        banned = ["推荐", "建议买入", "值得关注"]
        for word in banned:
            assert word not in out, f"compliance §3 violated in empty-filter error: '{word}'"
