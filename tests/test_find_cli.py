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

    def test_limit_negative_exits_two(self):
        """防 Python 负切片 silent drop."""
        ec, out = _run(["find", "--pos", "180:lt:5", "--limit", "-1"])
        assert ec == 2
        assert "--limit 必须为正整数" in out

    def test_limit_zero_exits_two(self):
        """--limit 0 不能跟 '无命中' 分支混淆."""
        ec, out = _run(["find", "--pos", "180:lt:5", "--limit", "0"])
        assert ec == 2
        assert "--limit 必须为正整数" in out

    def test_dsl_errors_include_fix_hint(self):
        """DSL 错误信息必须含修复示例.

        Rich console 可能 soft-wrap "例: --pos 180:lt:5" 跨行,因此分开断言
        "例:" 和 "180:lt:5" 都在 stderr 出现就够了。
        """
        for bad_pos in ["foo:bar:baz", "200:lt:5", "180:wtf:5", "180:lt:abc", "180:lt:150"]:
            ec, out = _run(["find", "--pos", bad_pos])
            assert ec == 2, f"{bad_pos} should exit 2"
            assert "例:" in out, f"{bad_pos} missing 例: hint"
            assert "180:lt:5" in out, f"{bad_pos} missing --pos sample 180:lt:5"
        for bad_res in ["mid:gte:3", "low:wtf:3", "low:gte:abc", "low:gte:99"]:
            ec, out = _run(["find", "--resonance", bad_res])
            assert ec == 2, f"{bad_res} should exit 2"
            assert "例:" in out, f"{bad_res} missing 例: hint"
            assert "low:gte:3" in out, f"{bad_res} missing --resonance sample low:gte:3"

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


def _run_isolated(args: list[str], tmp) -> tuple[int, str, str]:
    """Run `kan ARGS` with isolated XDG (空 watchlist) + no token · 确定性 JSON 输出。"""
    env = {
        **os.environ,
        "KAN_NO_BOOT_BANNER": "1",
        "XDG_DATA_HOME": str(tmp),
        "TUSHARE_TOKEN": "",
    }
    result = subprocess.run(
        ["uv", "run", "kan", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=90,
    )
    return result.returncode, result.stdout, result.stderr


class TestFindJsonOutput:
    """地基-2 · --format json/md AI 消费入口 wiring (隔离 XDG 保证确定性)。"""

    def test_no_filter_terminal_still_errors(self):
        """无 filter + terminal(默认)→ exit 1 "至少需要一个 filter" · 人类 UX 不变。"""
        ec, out = _run(["find"])
        assert ec == 1
        assert "至少需要一个 filter" in out

    def test_no_filter_json_bypasses_filter_guard(self, tmp_path):
        """无 filter + --format json = 取数模式 · 越过 filter 守卫。

        空 watchlist (隔离 XDG) → 落到 watchlist 守卫(取数无源可取 · 合理 UX)·
        关键:不再是 "至少需要一个 filter" 错误 → 证明 export 模式放开了空 filter。
        """
        _ec, out, err = _run_isolated(["find", "--format", "json"], tmp_path)
        combined = out + err
        assert "至少需要一个 filter" not in combined  # filter 守卫已对 export 放开
        assert "自选列表为空" in combined  # 落到 watchlist 守卫 (空池无数可取)

    @pytest.mark.skipif(
        not os.environ.get("KAN_RUN_FIND_DATA_TEST"),
        reason="needs watchlist + kline cache · set KAN_RUN_FIND_DATA_TEST=1 to run",
    )
    def test_json_emits_valid_schema_with_data(self):
        """真数据 opt-in:--format json 出完整 schema + 强制 disclaimer + 估值裸值不出。"""
        import json
        result = subprocess.run(
            ["uv", "run", "kan", "find", "--pos", "180:lte:100", "--format", "json"],
            cwd=REPO_ROOT, env={**os.environ, "KAN_NO_BOOT_BANNER": "1"},
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["command"] == "find"
        assert payload["schema_version"]
        assert "候选 ≠ 买入信号" in payload["disclaimer"]
        # 整合-1 拍板:估值裸值现在对外输出 (推翻旧"裸值不出")
        assert '"pe_ttm"' in result.stdout


class TestFindAllCrossSection:
    """kan find --all 全市场截面取数 CLI wiring (地基-3) · 校验均先于截面 fetch。"""

    def test_all_with_pos_filter_exits_two(self):
        ec, out = _run(["find", "--all", "--pos", "180:lt:5", "--format", "json"])
        assert ec == 2
        assert "不支持" in out

    def test_all_with_industry_exits_two(self):
        ec, out = _run(["find", "--all", "--industry", "半导体", "--format", "json"])
        assert ec == 2
        assert "互斥" in out

    def test_all_terminal_exits_two(self):
        ec, out = _run(["find", "--all"])
        assert ec == 2
        assert "json" in out

    def test_all_no_token_friendly_error(self, tmp_path):
        """--all + json + 无 token (隔离 XDG) → 友好报错 exit 1 · 不静默空。"""
        ec, out, err = _run_isolated(["find", "--all", "--format", "json"], tmp_path)
        combined = (out + err).lower()
        assert ec == 1
        assert "token" in combined or "tushare" in combined

    def test_all_with_roe_exits_two(self):
        """整合-1 · --all + --roe → exit 2 (fina 逐股 · 全市场太贵 · 引导缩小池)。"""
        ec, out = _run(["find", "--all", "--roe", "gte:15", "--format", "json"])
        assert ec == 2
        assert "roe" in out.lower() or "缩小池" in out

    def test_all_with_pe_no_token_friendly_error(self, tmp_path):
        """整合-1 · --all + --pe (截面 filter 放开) + 无 token → 友好报错 exit 1。"""
        ec, out, err = _run_isolated(
            ["find", "--all", "--pe", "lt:20", "--format", "json"], tmp_path,
        )
        combined = (out + err).lower()
        assert ec == 1
        assert "token" in combined or "tushare" in combined
