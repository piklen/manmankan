"""CLI integration tests for `kan find` (历史背景).

Uses subprocess (not typer.CliRunner) to avoid sys.argv shenanigans with
the root @app.callback() that checks `len(sys.argv) == 1`.
"""

import io
import json
import os
import re
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _run(args: list[str]) -> tuple[int, str]:
    """Run `kan find ARGS` via uv subprocess · returns (exit_code, combined output)."""
    env = {**os.environ, "KAN_NO_BOOT_BANNER": "1", "NO_COLOR": "1"}
    result = subprocess.run(
        ["uv", "run", "kan", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout + result.stderr


def _run_with_input(args: list[str], input_text: str) -> tuple[int, str]:
    """Run `kan find ARGS` with stdin · returns (exit_code, combined output)."""
    env = {**os.environ, "KAN_NO_BOOT_BANNER": "1", "NO_COLOR": "1"}
    result = subprocess.run(
        ["uv", "run", "kan", *args],
        cwd=REPO_ROOT,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout + result.stderr


class TestFindCli:
    def test_empty_filter_exits_one(self):
        ec, out = _run(["find"])
        assert ec == 1
        assert "terminal 模式至少需要一个 filter" in out
        assert "kan find --pos 180:lt:5" in out

    def test_bad_pos_format_exits_two(self):
        ec, out = _run(["find", "--pos", "bad:format"])
        assert ec == 2
        assert "格式错误" in out or "周期非整数" in out

    def test_bad_pos_period_exits_two(self):
        ec, out = _run(["find", "--pos", "361:lt:5"])
        assert ec == 2
        assert "周期 361 不支持" in out

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

    def test_only_watchlist_without_pool_is_watchlist_pool(self):
        ec, out = _run(["find", "--pos", "180:lt:5", "--only-watchlist"])
        assert ec in (0, 1)
        assert "需配合" not in out

    def test_help_includes_examples(self):
        ec, out = _run(["find", "--help"])
        # exit_code may be 0 (typer help)
        assert ec in (0, 2)
        assert "PERIOD:OP:VAL" in out or "kan find" in out

    def test_parse_codes_normalizes_and_dedupes(self):
        from kan.cli.helpers import _parse_codes

        codes, invalid = _parse_codes("sh600519, 000858\n600519 300750.SZ")
        assert codes == ["600519", "000858", "300750"]
        assert invalid == []

    def test_find_codes_json_uses_cached_names_only(self, monkeypatch):
        from kan.cli.find_cmds import _resolve_code_pairs_or_exit_json
        from kan.storage import export, watchlist

        def fail_preload():
            raise AssertionError("find --codes must not preload stock names")

        monkeypatch.setattr(watchlist, "preload_stock_names", fail_preload)
        monkeypatch.setattr(
            watchlist,
            "load_stock_names_cache",
            lambda *, allow_stale=False: {"600519": "贵州茅台"} if allow_stale else None,
        )

        pairs = _resolve_code_pairs_or_exit_json(
            "600519,000858", export.OutputFormat.json,
        )

        assert pairs == [("600519", "贵州茅台"), ("000858", "000858")]

    def test_resolve_codes_reads_stdin_and_fills_names(self, monkeypatch):
        from kan.cli.helpers import _resolve_code_pairs

        monkeypatch.setattr(sys, "stdin", io.StringIO("600519\n000858"))
        monkeypatch.setattr(
            "kan.storage.watchlist.preload_stock_names",
            lambda: {"600519": "贵州茅台"},
        )
        assert _resolve_code_pairs("-", command="kan find") == [
            ("600519", "贵州茅台"),
            ("000858", "000858"),
        ]

    def test_kline_snapshot_periods_only_uses_needed_windows(self):
        from kan.core.find_dsl import ConditionSet
        from kan.service.find_service import kline_snapshot_periods

        assert kline_snapshot_periods(ConditionSet.from_flags(up_days=["gte:3"])) == [3]
        assert kline_snapshot_periods(ConditionSet.from_flags(pos=["30:lt:20"])) == [30]

    def test_codes_invalid_exits_two(self):
        ec, out = _run(["find", "--codes", "600519,bad", "--pos", "180:lt:5"])
        assert ec == 2
        assert "--codes 含非法代码" in out

    def test_codes_invalid_json_returns_error_envelope(self):
        ec, out = _run([
            "find", "--codes", "600519,bad", "--pos", "180:lt:5", "--format", "json",
        ])
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["command"] == "find"
        assert payload["error"]["code"] == "invalid_codes"
        assert "--codes 含非法代码" in payload["error"]["message"]
        assert "例:" in payload["error"]["hint"]
        assert payload["schema_version"]
        assert payload["disclaimer"]

    def test_invalid_filter_json_returns_error_envelope(self):
        ec, out = _run([
            "find", "--codes", "600519", "--pos", "bad:format", "--format", "json",
        ])
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["command"] == "find"
        assert payload["error"]["code"] == "invalid_filter"
        assert "例:" in payload["error"]["hint"]

    def test_invalid_resonance_json_returns_error_envelope(self):
        ec, out = _run([
            "find", "--codes", "600519", "--resonance", "mid:gte:3", "--format", "json",
        ])
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_filter"

    def test_codes_empty_json_returns_error_envelope(self):
        ec, out = _run([
            "find", "--codes", ",,,", "--pos", "180:lt:5", "--format", "json",
        ])
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "empty_codes"
        assert payload["error"]["hint"].startswith("例:")

    def test_codes_stdin_invalid_json_returns_error_envelope(self):
        ec, out = _run_with_input([
            "find", "--codes", "-", "--pos", "180:lt:5", "--format", "json",
        ], "not-a-code\n")
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_codes"
        assert "not-a-code" in payload["error"]["message"]

    def test_codes_mutex_with_industry_exits_two(self):
        ec, out = _run([
            "find", "--codes", "600519", "--industry", "半导体", "--pos", "180:lt:5"
        ])
        assert ec == 2
        assert "互斥" in out

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

    def test_compact_requires_json_format(self):
        ec, out = _run(["find", "--pos", "180:lt:5", "--compact"])
        assert ec == 2
        assert "--compact 仅支持 --format json" in out

    def test_fields_requires_json_format(self):
        ec, out = _run(["find", "--pos", "180:lt:5", "--fields", "code,name"])
        assert ec == 2
        assert "--fields 仅支持 --format json" in out

    def test_help_includes_compact_option(self):
        from kan.core.find_registry import FILTER_SPECS

        ec, out = _run(["find", "--help"])
        assert ec in (0, 2)
        plain = _strip_ansi(out)
        assert "--compact" in plain
        assert "--no-compact-context" in plain
        assert "--fields" in plain
        assert "单维度 filter 只反映该维度" in plain
        assert "命中不等于整体位置低/高" in plain
        for spec in FILTER_SPECS.values():
            assert spec.flag in plain
        assert "@core" in plain
        assert "@valuation" in plain

    def test_find_help_survives_narrow_and_wide_terminals(self):
        for columns in ("60", "200"):
            env = {
                **os.environ,
                "KAN_NO_BOOT_BANNER": "1",
                "NO_COLOR": "1",
                "COLUMNS": columns,
            }
            result = subprocess.run(
                ["uv", "run", "kan", "find", "--help"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0
            plain = _strip_ansi(result.stdout + result.stderr)
            assert "核心层" in plain
            assert "--holders" in plain
            assert "--all 不支持" in plain

    def test_no_compact_context_requires_compact(self, tmp_path):
        ec, out, _err = _run_isolated(
            ["find", "--format", "json", "--no-compact-context"], tmp_path,
        )
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_compact_context"

    def test_dsl_errors_include_fix_hint(self):
        """DSL 错误信息必须含修复示例.

        Rich console 可能 soft-wrap "例: --pos 180:lt:5" 跨行,因此分开断言
        "例:" 和 "180:lt:5" 都在 stderr 出现就够了。
        """
        for bad_pos in ["foo:bar:baz", "361:lt:5", "180:wtf:5", "180:lt:abc", "180:lt:150"]:
            ec, out = _run(["find", "--pos", bad_pos])
            assert ec == 2, f"{bad_pos} should exit 2"
            assert "例:" in out, f"{bad_pos} missing 例: hint"
            assert "180:lt:5" in out, f"{bad_pos} missing --pos sample 180:lt:5"
        for bad_res in ["mid:gte:3", "low:wtf:3", "low:gte:abc", "low:gte:99"]:
            ec, out = _run(["find", "--resonance", bad_res])
            assert ec == 2, f"{bad_res} should exit 2"
            assert "例:" in out, f"{bad_res} missing 例: hint"
            assert "low:gte:3" in out, f"{bad_res} missing --resonance sample low:gte:3"

    def test_find_user_facing_errors_include_copyable_example(self):
        cases = [
            ["find", "--pos", "180:lt:5", "--compact"],
            ["find", "--pos", "180:lt:5", "--fields", "code"],
            ["find", "--pos", "180:lt:5", "--limit", "0"],
            ["find", "--pos", "180:lt:5", "--industry", "X", "--theme", "Y"],
            ["find", "--all", "--pe", "lt:20"],
            ["find", "--all", "--roe", "gte:15", "--format", "json"],
        ]
        for args in cases:
            ec, out = _run(args)
            assert ec in (1, 2), f"{args} should fail as user-facing error"
            assert "例:" in out, f"{args} missing copyable example"

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
        assert "terminal 模式至少需要一个 filter" in out

    def test_no_filter_json_bypasses_filter_guard(self, tmp_path):
        """无 filter + --format json = 取数模式 · 越过 filter 守卫。

        空 watchlist (隔离 XDG) → 落到 watchlist 守卫(取数无源可取 · 合理 UX)·
        关键:不再是 "至少需要一个 filter" 错误 → 证明 export 模式放开了空 filter。
        """
        _ec, out, err = _run_isolated(["find", "--format", "json"], tmp_path)
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "empty_watchlist"
        assert "terminal 模式至少需要一个 filter" not in (out + err)

    def test_codes_no_filter_json_returns_code_pool_without_kline_fetch(self, tmp_path):
        """显式代码池无 filter 是轻量取数,不应触发 K 线/交易日历网络链路。"""
        ec, out, err = _run_isolated(
            ["find", "--codes", "600519,000858", "--format", "json"], tmp_path,
        )
        assert ec == 0
        assert err == ""
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["mode"] == "code_pool"
        assert payload["rule"]["pools"] == ["codes:2"]
        assert payload["stats"]["matched"] == 2
        assert [r["code"] for r in payload["results"]] == ["600519", "000858"]
        assert all(r["name"] for r in payload["results"])

    def test_codes_no_filter_json_rejects_unavailable_fields(self, tmp_path):
        ec, out, _err = _run_isolated(
            [
                "find", "--codes", "600519,000858", "--format", "json",
                "--fields", "code,price",
            ],
            tmp_path,
        )
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_fields"
        assert "code/name" in payload["error"]["message"]

    def test_codes_no_filter_json_can_return_permission_fields(self, tmp_path):
        ec, out, err = _run_isolated(
            [
                "find", "--codes", "688981,920000", "--format", "json",
                "--fields", "code,market_board,permission_note",
            ],
            tmp_path,
        )
        assert ec == 0
        assert err == ""
        payload = json.loads(out)
        assert payload["mode"] == "code_pool"
        assert payload["results"] == [
            {"code": "688981", "market_board": "科创板", "permission_note": "需科创板权限"},
            {"code": "920000", "market_board": "北交所", "permission_note": "需北交所权限"},
        ]

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

    def test_all_with_pos_filter_no_token_friendly_error(self, tmp_path):
        ec, out, err = _run_isolated(
            ["find", "--all", "--pos", "180:lt:5", "--format", "json"], tmp_path,
        )
        combined = (out + err).lower()
        assert ec == 1
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "data_unavailable"
        assert "token" in combined or "tushare" in combined

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
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "data_unavailable"
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
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "data_unavailable"
        assert "token" in combined or "tushare" in combined

    def test_fields_unknown_json_error(self, tmp_path):
        ec, out, _err = _run_isolated(
            ["find", "--format", "json", "--fields", "code,valuation.nope"], tmp_path,
        )
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_fields"
        assert "valuation.nope" in payload["error"]["message"]
        assert "字段全集见 docs/find.md" in payload["error"]["message"]

    def test_all_fields_reject_unsupported_dimension_before_fetch(self, tmp_path):
        ec, out, _err = _run_isolated(
            ["find", "--all", "--format", "json", "--fields", "code,fundamentals.roe"],
            tmp_path,
        )
        assert ec == 2
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_fields"
        assert "fundamentals" in payload["error"]["message"]
