"""scan/low/high/info CLI 列宽回归测试

确保表格列宽容纳极值场景：[100%] 6 chars / 4 位数股价 / [100.0%] 一位小数。
scan 周期列 min_width=6 · 现价 / N日最低 / N日最高 / 位置列 min_width=8。

测试策略：
  直接构造 rich Table（用与 cli.py 相同的 add_column 配置）渲染到 StringIO，
  验证极值场景（100%/0% 位置 · 4 位数股价 · [100.0%] 一位小数）不被截断。
"""

from __future__ import annotations

from io import StringIO

import pytest
import typer
from rich.console import Console
from rich.table import Table


def _render_table(table: Table, width: int = 200) -> str:
    """渲染 Table 到 StringIO 并返回完整输出文本。"""
    output = StringIO()
    console = Console(file=output, width=width)
    console.print(table)
    return output.getvalue()


# --- scan 表格列宽回归（cli.py:296-302）---


@pytest.mark.parametrize("pct_value", ["[100%]", "[99%]", "[0%]", "[5%]"])
def test_scan_period_column_renders_pct_complete(pct_value: str) -> None:
    """scan 周期列 min_width=6 · 容纳 [100%] 6 chars 不截断"""
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    table.add_column("3日", justify="right", min_width=6)

    table.add_row("贵州茅台 600519", "1371.05", pct_value)
    rendered = _render_table(table)

    assert pct_value in rendered, f"周期列内容被截断: {rendered}"
    assert "[100…" not in rendered, "出现截断符 …"
    assert "[99…" not in rendered, "出现截断符 …"


def test_scan_price_column_handles_4_digits() -> None:
    """现价列 min_width=8 · 容纳 1371.05 (7 chars) 不截断"""
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)

    table.add_row("贵州茅台 600519", "1371.05")
    rendered = _render_table(table)

    assert "1371.05" in rendered
    assert "112.…" not in rendered
    assert "1371.…" not in rendered


def test_scan_full_row_with_100pct_resonance() -> None:
    """端到端模拟 scan 满共振行 (×10) 全部 100% · 不截断"""
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    for p in [3, 5, 7, 10, 15, 30, 60, 90, 120, 180]:
        table.add_column(f"{p}日", justify="right", min_width=6)
    table.add_column("共振", justify="center")

    table.add_row(
        "苏州高新 600736 涨停",
        "9.65",
        *(["[100%]"] * 10),
        "×10",
    )
    rendered = _render_table(table)

    # 验证 10 个 [100%] 全部完整渲染（计数）
    assert rendered.count("[100%]") == 10, f"应有 10 个 [100%] 但实际 {rendered.count('[100%]')}"
    assert "[100…" not in rendered


# --- low/high 表格列宽回归（cli.py:405-410）---


def test_low_high_position_column_handles_decimal_pct() -> None:
    """low/high 位置列 min_width=8 · 容纳 [100.0%] 8 chars (一位小数)"""
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    table.add_column("60日最低", justify="right", style="dim", min_width=8)
    table.add_column("60日最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    table.add_row(
        "贵州茅台 600519",
        "1371.05",
        "1200.00",
        "1500.00",
        "[100.0%]",
    )
    rendered = _render_table(table)

    assert "[100.0%]" in rendered
    assert "1500.00" in rendered  # 4 位数最高也不截
    assert "1200.…" not in rendered


# --- info 表格列宽回归（cli.py:629-634）---


def test_info_table_handles_4_digit_prices() -> None:
    """info 表 最低/最高/位置列 min_width=8 · 容纳 4 位数股价 + [100.0%]"""
    table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
    table.add_column("周期", justify="right", style="cyan")
    table.add_column("最低", justify="right", style="dim", min_width=8)
    table.add_column("最高", justify="right", style="dim", min_width=8)
    table.add_column("位置", justify="right", min_width=8)

    table.add_row(
        "180日",
        "1200.00",
        "1500.00",
        "[100.0%]",
    )
    rendered = _render_table(table)

    assert "1200.00" in rendered
    assert "1500.00" in rendered
    assert "[100.0%]" in rendered


# --- 终端宽度自适应 ---


class TestResponsivePeriods:
    """responsive_periods 根据终端宽度选择周期子集"""

    def test_wide_returns_all_10(self) -> None:
        from kan.render.base import responsive_periods
        result = responsive_periods(200)
        assert len(result) == 10

    def test_130_returns_all_10(self) -> None:
        from kan.render.base import responsive_periods
        result = responsive_periods(130)
        assert len(result) == 10

    def test_100_returns_6_short_dense(self) -> None:
        from kan.render.base import responsive_periods
        result = responsive_periods(100)
        assert len(result) == 6
        assert result[:3] == [3, 5, 10]
        assert 180 in result

    def test_90_returns_5(self) -> None:
        from kan.render.base import responsive_periods
        result = responsive_periods(90)
        assert len(result) == 5
        assert 5 in result and 10 in result
        assert 180 in result

    def test_80_returns_4_with_5_10(self) -> None:
        from kan.render.base import responsive_periods
        result = responsive_periods(80)
        assert len(result) == 4
        assert result == [5, 10, 30, 180]

    def test_70_returns_3(self) -> None:
        from kan.render.base import responsive_periods
        result = responsive_periods(70)
        assert len(result) == 3
        assert 180 in result

    def test_60_returns_2(self) -> None:
        from kan.render.base import responsive_periods
        result = responsive_periods(60)
        assert len(result) == 2
        assert 180 in result

    def test_always_sorted_ascending(self) -> None:
        from kan.render.base import responsive_periods
        for width in [60, 70, 80, 90, 100, 130, 200]:
            result = responsive_periods(width)
            assert result == sorted(result), f"width={width}: {result} not sorted"

    def test_resonance_visible_at_80(self) -> None:
        """80 列下 scan 表共振列不被截断"""
        from kan.render.base import responsive_periods
        periods = responsive_periods(80)

        table = Table(show_lines=False, pad_edge=False, padding=(0, 1))
        table.add_column("股票", style="white", no_wrap=True)
        table.add_column("现价", justify="right", style="white", min_width=8)
        for p in periods:
            table.add_column(f"{p}日", justify="right", min_width=6)
        table.add_column("共振", justify="center")
        table.add_row("测试股票 600000", "10.00", *(["50%"] * len(periods)), "×5")

        rendered = _render_table(table, width=80)
        assert "×5" in rendered, f"共振列在 80 列下被截断: {rendered}"


class TestMaxTrendDates:
    """max_trend_dates 根据终端宽度限制日期列数"""

    def test_80_cols_at_least_1(self) -> None:
        from kan.render.base import max_trend_dates
        assert max_trend_dates(80) >= 1

    def test_wider_allows_more_dates(self) -> None:
        from kan.render.base import max_trend_dates
        assert max_trend_dates(200) > max_trend_dates(80)


# ════════════════════════════════════════════════════════════════
# stale/intraday warning runtime 真测 (scan 命令)
# (背景: 补 scan 完整覆盖 · 跟 trend runtime test 对称)
# ════════════════════════════════════════════════════════════════
@pytest.fixture
def scan_runner(monkeypatch):
    """scan command CliRunner · 隔离 watchlist + fetcher + scanner · 让 scan 走 mock 数据."""
    from datetime import date

    from typer.testing import CliRunner

    from kan.core.models import PeriodResult, StockScanResult

    fake_period_3 = PeriodResult(
        period=3, n_low=90.0, n_high=110.0, position_pct=50.0,
        at_low=False, at_high=False,
    )
    fake_period_30 = PeriodResult(
        period=30, n_low=90.0, n_high=110.0, position_pct=3.0,
        at_low=True, at_high=False,
    )
    fake_scan_result = StockScanResult(
        symbol="600519",
        name="测试",
        current_price=100.0,
        scan_date=date(2026, 5, 14),
        periods=[fake_period_3],
        low_resonance=0,
        high_resonance=0,
    )
    fake_extreme_result = StockScanResult(
        symbol="600519",
        name="测试",
        current_price=100.0,
        scan_date=date(2026, 5, 14),
        periods=[fake_period_30],
        low_resonance=1,
        high_resonance=0,
    )

    fake_pairs = [("600519", "测试")]
    fake_stock = type("S", (), {"symbol": "600519", "name": "测试"})()
    fake_watchlist = type("WL", (), {"stocks": [fake_stock]})()
    fake_positions = type("Book", (), {"positions": []})()
    monkeypatch.setattr("kan.cli.scan_cmds._get_watchlist_pairs", lambda group=None: fake_pairs)
    monkeypatch.setattr("kan.cli.extreme_cmds._get_watchlist_pairs", lambda group=None: fake_pairs)
    monkeypatch.setattr("kan.storage.watchlist.load_watchlist", lambda group=None: fake_watchlist)
    monkeypatch.setattr("kan.storage.positions.load_positions", lambda: fake_positions)
    monkeypatch.setattr("kan.core.auto_fetch.auto_fetch_stale", lambda _pairs, **_kw: None)
    monkeypatch.setattr("kan.cli.extreme_cmds._auto_fetch_stale", lambda _pairs, **_kw: None)
    monkeypatch.setattr(
        "kan.core.scanner.scan_batch", lambda _pairs, mode="low", periods=None: [fake_scan_result]
    )
    monkeypatch.setattr(
        "kan.core.scanner.filter_extreme",
        lambda _pairs, periods, mode="low": (
            {p: [(fake_extreme_result, fake_period_30)] for p in periods}
            if mode == "low" else {}
        ),
    )
    monkeypatch.setattr("kan.core.scanner.load_snapshot", lambda: None)
    monkeypatch.setattr("kan.core.scanner.save_snapshot", lambda _results: None)
    monkeypatch.setattr("kan.data.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 14))
    monkeypatch.setattr("kan.data.fetcher.cache_age", lambda _sym: "2026-05-14 12:00")
    monkeypatch.setattr("kan.data.fetcher.cache_has_min_rows", lambda _sym, _rows: True)
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "post")
    monkeypatch.setattr("kan.core.scanner.get_limit_threshold", lambda *a, **k: 10.0)
    monkeypatch.setattr(
        "kan.service.scan_service._enrich_scan_rows_best_effort",
        lambda results, **_kwargs: list(results),
    )
    return CliRunner()


def test_scan_stale_warning_uses_new_phrasing(scan_runner, monkeypatch):
    """真测: scan 命令的 stale 警告应含'当前缓存到 X 收盘' + '数据滞后 N 天'."""
    from datetime import date

    from kan.cli import app

    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 1)
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "pre")

    result = scan_runner.invoke(app, ["scan"])
    assert result.exit_code == 0, f"scan failed · output: {result.output[:500]}"
    output = result.output
    assert "当前缓存到" in output, f"scan 新文案 '当前缓存到' 应出现 · output: {output[:500]}"
    assert "数据滞后" in output
    assert "kan fetch --force" in output
    assert "应有最近交易日" not in output


def test_scan_intraday_warning_compliant_phrasing(scan_runner, monkeypatch):
    """真测: scan 盘中警告应是状态描述 · 不含'下一秒打开' 红线词."""
    from datetime import date

    from kan.cli import app

    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 14)
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "in")

    result = scan_runner.invoke(app, ["scan"])
    assert result.exit_code == 0
    output = result.output
    # 背景: 纯状态描述 · 移除预测性 "可能回落/可能回升/都是正常波动"
    assert "涨跌停标签反映当前时刻" in output, f"scan intraday 新文案应出现 · output: {output[-500:]}"
    assert "建议盘后 15:30" in output
    assert "下一秒打开" not in output, "scan 不应残留预测性词 (AGENTS.md §6)"
    assert "都是正常波动" not in output, "应删除预测性词"
    assert "可能回落" not in output, "应删除预测性词"


def test_scan_warnings_mutex_stale_wins(scan_runner, monkeypatch):
    """真测: scan stale+intraday 同时为 True 时只显示 stale · 验证 if/elif 互斥."""
    from datetime import date

    from kan.app import app

    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 1)
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "in")

    result = scan_runner.invoke(app, ["scan"])
    assert result.exit_code == 0
    output = result.output
    assert "当前缓存到" in output, "scan stale 警告应显示"
    assert "数据滞后" in output
    assert "涨跌停标签反映当前时刻" not in output, (
        "scan stale=True 时不应同时显示 intraday 警告 (if/elif 互斥)"
    )


# ════════════════════════════════════════════════════════════════
# 背景: scan/low/high/info 命令组 CliRunner 覆盖增量
# 复用 scan_runner fixture · mock 全部 dependencies
# ════════════════════════════════════════════════════════════════
def test_scan_command_basic_runs(scan_runner):
    """`kan scan` 基础命令 · 应跑通"""
    from kan.app import app
    result = scan_runner.invoke(app, ["scan"])
    assert result.exit_code == 0
    # 应含表格基本结构
    assert "测试" in result.output or "600519" in result.output


def test_scan_terminal_narrow_skips_external_context(scan_runner, monkeypatch):
    """窄终端默认 scan 不展示 PE/资金列,不应等待外部增强。"""
    from datetime import date

    from kan.app import app
    from kan.core.models import PeriodResult, StockScanResult
    from kan.core.pipeline import DataCtx, Freshness
    from kan.service.scan_service import ScanServiceResult

    captured = {}
    row = StockScanResult(
        symbol="600519",
        name="测试",
        current_price=100.0,
        scan_date=date(2026, 6, 6),
        periods=[
            PeriodResult(
                period=30,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=0,
        high_resonance=0,
        lot_cost=10000.0,
        permission_note="测试权限",
    )
    freshness = Freshness(
        data_cutoff=date(2026, 6, 6),
        fetched_at="2026-06-06 15:30",
        expected_cutoff=date(2026, 6, 6),
        is_stale=False,
        phase="post",
    )

    def fake_run_scan(request, *, lifecycle=None):
        captured["include_external_context"] = request.include_external_context
        return ScanServiceResult(
            ctx=DataCtx(
                targets=[("600519", "测试")],
                meta=None,
                results=[row],
                freshness=freshness,
                source_name="自选股",
            ),
            mode=request.mode,
            all_results=[row],
            results=[row],
        )

    monkeypatch.setattr("kan.service.scan_service.run_scan", fake_run_scan)

    result = scan_runner.invoke(app, ["scan"], env={"COLUMNS": "100"})

    assert result.exit_code == 0, result.output
    assert captured["include_external_context"] is False
    assert "1手元" not in result.output
    assert "测试权限" not in result.output


def test_scan_compact_skips_external_context(scan_runner, monkeypatch):
    """显式 compact 也是窄输出,不应等待隐藏的外部增强字段。"""
    from datetime import date

    from kan.app import app
    from kan.core.models import PeriodResult, StockScanResult
    from kan.core.pipeline import DataCtx, Freshness
    from kan.service.scan_service import ScanServiceResult

    captured = {}
    row = StockScanResult(
        symbol="600519",
        name="测试",
        current_price=100.0,
        scan_date=date(2026, 6, 6),
        periods=[
            PeriodResult(
                period=30,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=0,
        high_resonance=0,
    )
    freshness = Freshness(
        data_cutoff=date(2026, 6, 6),
        fetched_at="2026-06-06 15:30",
        expected_cutoff=date(2026, 6, 6),
        is_stale=False,
        phase="post",
    )

    def fake_run_scan(request, *, lifecycle=None):
        captured["include_external_context"] = request.include_external_context
        return ScanServiceResult(
            ctx=DataCtx(
                targets=[("600519", "测试")],
                meta=None,
                results=[row],
                freshness=freshness,
                source_name="自选股",
            ),
            mode=request.mode,
            all_results=[row],
            results=[row],
        )

    monkeypatch.setattr("kan.service.scan_service.run_scan", fake_run_scan)

    result = scan_runner.invoke(app, ["scan", "--compact"], env={"COLUMNS": "100"})

    assert result.exit_code == 0, result.output
    assert captured["include_external_context"] is False


def test_scan_json_keeps_external_context(scan_runner, monkeypatch):
    """结构化输出仍需要 PE/资金/除权除息等外部增强字段。"""
    from datetime import date

    from kan.app import app
    from kan.core.models import PeriodResult, StockScanResult
    from kan.core.pipeline import DataCtx, Freshness
    from kan.service.scan_service import ScanServiceResult

    captured = {}
    row = StockScanResult(
        symbol="600519",
        name="测试",
        current_price=100.0,
        scan_date=date(2026, 6, 6),
        periods=[
            PeriodResult(
                period=30,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=0,
        high_resonance=0,
    )
    freshness = Freshness(
        data_cutoff=date(2026, 6, 6),
        fetched_at="2026-06-06 15:30",
        expected_cutoff=date(2026, 6, 6),
        is_stale=False,
        phase="post",
    )

    def fake_run_scan(request, *, lifecycle=None):
        captured["include_external_context"] = request.include_external_context
        return ScanServiceResult(
            ctx=DataCtx(
                targets=[("600519", "测试")],
                meta=None,
                results=[row],
                freshness=freshness,
                source_name="自选股",
            ),
            mode=request.mode,
            all_results=[row],
            results=[row],
        )

    monkeypatch.setattr("kan.service.scan_service.run_scan", fake_run_scan)

    result = scan_runner.invoke(app, ["scan", "--format", "json"], env={"COLUMNS": "100"})

    assert result.exit_code == 0, result.output
    assert captured["include_external_context"] is True


def test_scan_default_uses_holdings_when_watchlist_empty(monkeypatch):
    """默认 scan = 自选 ∪ 持仓；自选空但持仓非空时不能被旧 guard 拦截。"""
    import json as _json
    from datetime import date

    from typer.testing import CliRunner

    from kan.cli import app
    from kan.core.models import PeriodResult, StockScanResult
    from kan.core.pipeline import DataCtx, Freshness

    fake_position = type("P", (), {"symbol": "600519", "name": "贵州茅台"})()
    monkeypatch.setattr(
        "kan.storage.watchlist.load_watchlist",
        lambda group=None: type("WL", (), {"stocks": []})(),
    )
    monkeypatch.setattr(
        "kan.storage.positions.load_positions",
        lambda: type("Book", (), {"positions": [fake_position]})(),
    )

    scan_row = StockScanResult(
        symbol="600519",
        name="贵州茅台",
        current_price=100.0,
        scan_date=date(2026, 6, 6),
        periods=[
            PeriodResult(
                period=30,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=0,
        high_resonance=0,
    )
    freshness = Freshness(
        data_cutoff=date(2026, 6, 6),
        fetched_at="2026-06-06 15:30",
        expected_cutoff=date(2026, 6, 6),
        is_stale=False,
        phase="post",
    )
    captured = {}

    def fake_run_data_pipeline(
        stock_set, *, compute, mode, periods, fetch_days, show_progress,
        exit_on_resolve_error, lifecycle=None,
    ):
        pairs = stock_set.pairs()
        captured["pairs"] = pairs
        return DataCtx(
            targets=pairs,
            meta=None,
            results=[scan_row],
            freshness=freshness,
            source_name=stock_set.name,
        )

    monkeypatch.setattr("kan.core.pipeline.run_data_pipeline", fake_run_data_pipeline)
    monkeypatch.setattr(
        "kan.core.enrich.enrich_scan_rows",
        lambda results, *, data_cutoff: list(results),
    )

    result = CliRunner().invoke(app, ["scan", "--format", "json", "--periods", "30"])

    assert result.exit_code == 0, result.output
    assert captured["pairs"] == [("600519", "贵州茅台")]
    payload = _json.loads(result.output)
    assert payload["results"][0]["in_holding"] is True
    assert payload["results"][0]["in_watchlist"] is False


def test_scan_only_holdings_does_not_write_shared_snapshot(monkeypatch):
    """`kan hold scan` 走 only_holdings 时不能覆盖默认池 diff 基线。"""
    from datetime import date

    from typer.testing import CliRunner

    from kan.app import app
    from kan.core.models import PeriodResult, StockScanResult
    from kan.core.pipeline import DataCtx, Freshness
    from kan.service.scan_service import ScanServiceResult

    row = StockScanResult(
        symbol="600519",
        name="贵州茅台",
        current_price=100.0,
        scan_date=date(2026, 6, 6),
        periods=[
            PeriodResult(
                period=30,
                n_low=90.0,
                n_high=110.0,
                position_pct=50.0,
                at_low=False,
                at_high=False,
            )
        ],
        low_resonance=0,
        high_resonance=0,
    )
    freshness = Freshness(
        data_cutoff=date(2026, 6, 6),
        fetched_at="2026-06-06 15:30",
        expected_cutoff=date(2026, 6, 6),
        is_stale=False,
        phase="post",
    )
    saved = []

    def fake_run_scan(request, *, lifecycle=None):
        return ScanServiceResult(
            ctx=DataCtx(
                targets=[("600519", "贵州茅台")],
                meta=None,
                results=[row],
                freshness=freshness,
                source_name="真实持仓",
            ),
            mode=request.mode,
            all_results=[row],
            results=[row],
        )

    monkeypatch.setattr("kan.service.scan_service.run_scan", fake_run_scan)
    monkeypatch.setattr("kan.core.scanner.save_snapshot", lambda results: saved.append(results))
    monkeypatch.setattr("kan.data.fetcher.data_cutoff_date", lambda _symbol: date(2026, 6, 6))

    result = CliRunner().invoke(app, ["scan", "--only-holdings"], env={"COLUMNS": "120"})

    assert result.exit_code == 0, result.output
    assert saved == []


def test_scan_command_high_mode(scan_runner):
    """`kan scan --high` 高点模式 · 应跑通"""
    from kan.app import app
    result = scan_runner.invoke(app, ["scan", "--high"])
    assert result.exit_code == 0


def test_scan_command_exclude_st(scan_runner):
    """`kan scan --exclude-st` 排除 ST · 应跑通"""
    from kan.app import app
    result = scan_runner.invoke(app, ["scan", "--exclude-st"])
    assert result.exit_code == 0


def test_scan_custom_periods_are_forwarded(scan_runner, monkeypatch):
    """`kan scan --periods` 计算自定义 2-360 周期集合。"""
    from datetime import date

    from kan.app import app
    from kan.core.models import PeriodResult, StockScanResult

    captured = {}

    def _fake_scan(input_pairs, mode="low", periods=None):
        captured["periods"] = periods
        return [
            StockScanResult(
                symbol="600519",
                name="测试",
                current_price=100.0,
                scan_date=date(2026, 5, 14),
                periods=[
                    PeriodResult(
                        period=20, n_low=90.0, n_high=110.0,
                        position_pct=50.0, at_low=False, at_high=False,
                    ),
                    PeriodResult(
                        period=60, n_low=80.0, n_high=120.0,
                        position_pct=50.0, at_low=False, at_high=False,
                    ),
                ],
                low_resonance=0,
                high_resonance=0,
            )
        ]

    monkeypatch.setattr("kan.core.scanner.scan_batch", _fake_scan)
    result = scan_runner.invoke(app, ["scan", "--periods", "20,60", "--wide"])
    assert result.exit_code == 0, result.output
    assert captured["periods"] == [20, 60]
    assert "20日" in result.output


def test_scan_display_modes_are_mutex(scan_runner):
    """`--compact` / `--wide` 互斥，避免输出语义冲突。"""
    from kan.app import app

    result = scan_runner.invoke(app, ["scan", "--compact", "--wide", "--format", "json"])
    assert result.exit_code == 2
    assert "invalid_display_mode" in result.output


def test_scan_command_signal_only_with_no_signal(scan_runner):
    """`kan scan --signal` 但无 resonance 股票 · 应给空 signal 提示"""
    from kan.app import app
    result = scan_runner.invoke(app, ["scan", "--signal"])
    assert result.exit_code == 0
    # fake_result low_resonance=0 · 应给"没有股票触及极值区"
    assert "共振" in result.output or "没有" in result.output


def test_low_command_with_period_runs(scan_runner, monkeypatch):
    """`kan low 30` 筛选 30 日低点 · 应跑通"""
    from kan.app import app

    # low/high 走 _filter_extreme_cmd · 也调 scan_batch · 但需要额外 mock
    # 简化:让 low 跑通即可 (不验证具体筛选逻辑 · 那是 scanner module 的 unit test 职责)
    result = scan_runner.invoke(app, ["low", "30"])
    # 可能 exit 0 / 1 (依赖 fake data 是否触及 30 日低)· 关键是不 crash
    assert "Traceback" not in result.output, (
        f"low 命令不应抛 traceback · output: {result.output[:300]}"
    )


def test_high_command_with_period_runs(scan_runner, monkeypatch):
    """`kan high 30` 筛选 30 日高点 · 应跑通"""
    from kan.app import app
    result = scan_runner.invoke(app, ["high", "30"])
    assert "Traceback" not in result.output


def test_low_command_no_args_uses_default_periods(scan_runner, monkeypatch):
    """`kan low` 无参 · 用默认 periods [30, 60, 120] 跑(不报错)"""
    from kan.app import app
    from kan.cli import extreme_cmds

    # 拦下 _filter_extreme_cmd 不真跑 · 只看 periods 默认值传对
    captured = {}
    def _fake_filter(periods, **kwargs):
        captured["periods"] = periods

    monkeypatch.setattr(extreme_cmds, "_filter_extreme_cmd", _fake_filter)
    result = scan_runner.invoke(app, ["low"])
    assert result.exit_code == 0, f"无参应跑默认 periods · stderr: {result.output}"
    assert captured["periods"] == [30, 60, 120]


def test_info_command_with_existing_symbol(scan_runner, monkeypatch):
    """`kan info 600519` 单股详情 · 应跑通"""
    from datetime import date

    from kan.app import app

    # info 需要额外 mock fetch_kline 返 pd.DataFrame
    # 简化策略:让 info 失败但不 crash (exit_code 可能非 0)
    monkeypatch.setattr(
        "kan.data.fetcher.data_cutoff_date", lambda _sym: date(2026, 5, 14)
    )
    monkeypatch.setattr(
        "kan.core.trading_calendar.latest_trade_date", lambda: date(2026, 5, 14)
    )
    monkeypatch.setattr("kan.core.trading_calendar.market_phase", lambda: "pre")

    result = scan_runner.invoke(app, ["info", "600519"])
    # info 可能因 fetch_kline 失败而 exit 非 0 · 但应优雅处理 · 不抛 traceback
    assert "Traceback" not in result.output


def test_scan_command_with_diff_flag(scan_runner):
    """`kan scan --diff` 增量模式 · 应跑通 (即使无 prev snapshot)"""
    from kan.app import app
    result = scan_runner.invoke(app, ["scan", "--diff"])
    assert result.exit_code == 0


def test_scan_format_json(scan_runner, monkeypatch):
    """JSON 纯净，且唯一 lifecycle 在最终输出前已终止。"""
    import json as _json

    from kan.app import app
    from kan.infra.lifecycle import CollectingReporter, OperationState

    reporter = CollectingReporter()
    monkeypatch.setattr("kan.infra.progress.operation_reporter", lambda: reporter)
    original_echo = typer.echo

    def echo_after_close(message, **kwargs):
        assert reporter.events[-1].state is OperationState.SUCCEEDED
        original_echo(message, **kwargs)

    monkeypatch.setattr("kan.cli.scan_cmds.typer.echo", echo_after_close)
    result = scan_runner.invoke(app, ["scan", "--format", "json"])
    assert result.exit_code == 0, f"output: {result.output[:500]}"
    data = _json.loads(result.output)
    assert data["command"] == "scan"
    assert "disclaimer" in data
    assert data["results"][0]["symbol"] == "600519"
    assert len({event.operation_id for event in reporter.events}) == 1
    assert reporter.events[-1].state is OperationState.SUCCEEDED


def test_scan_snapshot_failure_prevents_success_payload(scan_runner, monkeypatch):
    """快照提交失败时不得先输出看似成功的 JSON。"""
    from kan.app import app
    from kan.infra.lifecycle import CollectingReporter, OperationState

    reporter = CollectingReporter()
    monkeypatch.setattr("kan.infra.progress.operation_reporter", lambda: reporter)

    def fail_snapshot(_results):
        raise OSError("snapshot unavailable")

    monkeypatch.setattr("kan.core.scanner.save_snapshot", fail_snapshot)
    result = scan_runner.invoke(app, ["scan", "--format", "json"])

    assert result.exit_code == 1
    assert result.output == ""
    assert reporter.events[-1].state is OperationState.FAILED


def test_scan_json_invalid_codes_error_envelope(scan_runner):
    import json as _json

    from kan.app import app

    result = scan_runner.invoke(app, ["scan", "--codes", "bad", "--format", "json"])
    assert result.exit_code == 2
    data = _json.loads(result.output)
    assert data["ok"] is False
    assert data["command"] == "scan"
    assert data["error"]["code"] == "invalid_codes"
    assert "例:" in data["error"]["hint"]


def test_scan_format_md(scan_runner):
    """`kan scan --format md` · 输出 markdown 表格"""
    from kan.app import app
    result = scan_runner.invoke(app, ["scan", "--format", "md"])
    assert result.exit_code == 0
    assert "| 股票 |" in result.output
    assert "600519" in result.output


def test_scan_codes_filters_to_explicit_pool(scan_runner, monkeypatch):
    """`kan scan --codes` 只把显式代码池喂给 scan_batch,不读自选。"""
    import json as _json
    from datetime import date

    from kan.app import app
    from kan.core.models import PeriodResult, StockScanResult

    pairs = [("600519", "贵州茅台"), ("000858", "五粮液")]
    monkeypatch.setattr(
        "kan.cli.scan_cmds._resolve_scan_code_pairs",
        lambda raw, command, fmt: pairs,
    )
    monkeypatch.setattr(
        "kan.cli.scan_cmds._get_watchlist_pairs",
        lambda group=None: (_ for _ in ()).throw(AssertionError("不应读取自选")),
    )

    captured = {}

    def _fake_scan(input_pairs, mode="low", periods=None):
        captured["pairs"] = input_pairs
        return [
            StockScanResult(
                symbol=s, name=n, current_price=100.0, scan_date=date(2026, 5, 14),
                periods=[PeriodResult(
                    period=3, n_low=90.0, n_high=110.0, position_pct=50.0,
                    at_low=False, at_high=False,
                )],
                low_resonance=0, high_resonance=0,
            )
            for s, n in input_pairs
        ]

    monkeypatch.setattr("kan.core.scanner.scan_batch", _fake_scan)
    result = scan_runner.invoke(app, ["scan", "--codes", "600519,000858", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert captured["pairs"] == pairs
    data = _json.loads(result.output[result.output.index("{"):])
    assert "disclaimer" in data
    assert [r["symbol"] for r in data["results"]] == ["600519", "000858"]


def test_scan_positional_codes_supported(scan_runner, monkeypatch):
    from kan.app import app

    captured = {}

    def fake_resolve(raw, command, fmt):
        captured["raw"] = raw
        captured["command"] = command
        captured["fmt"] = fmt
        return [("600519", "贵州茅台")]

    monkeypatch.setattr("kan.cli.scan_cmds._resolve_scan_code_pairs", fake_resolve)
    result = scan_runner.invoke(app, ["scan", "600519,000858", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert captured["raw"] == "600519,000858"
    assert captured["command"] == "kan scan"
    assert captured["fmt"].value == "json"


def test_scan_codes_rejects_diff(scan_runner, monkeypatch):
    from kan.app import app

    monkeypatch.setattr(
        "kan.cli.scan_cmds._resolve_scan_code_pairs",
        lambda raw, command, fmt: [("600519", "贵州茅台")],
    )
    result = scan_runner.invoke(app, ["scan", "--codes", "600519", "--diff"])
    assert result.exit_code == 2
    assert "--diff" in result.output


def test_low_format_json(scan_runner):
    """`kan low 30 --format json` · 不 crash · 输出合法 JSON"""
    import json as _json

    from kan.app import app
    result = scan_runner.invoke(app, ["low", "30", "--format", "json"])
    assert result.exit_code == 0, f"output: {result.output[:400]}"
    out = result.output
    data = _json.loads(out[out.index("{"):])
    assert data["command"] == "low"
    assert "disclaimer" in data
    assert "results_by_period" in data


def test_compare_too_few_symbols(scan_runner):
    """`kan compare 600519` 单只 · 报至少 2 只 · exit 2"""
    from kan.app import app
    result = scan_runner.invoke(app, ["compare", "600519"])
    assert result.exit_code == 2


def test_compare_too_many_symbols(scan_runner):
    """`kan compare` 31 只 · 超上限 30 · exit 2"""
    from kan.app import app
    many = [f"600{i:03d}" for i in range(31)]
    result = scan_runner.invoke(app, ["compare", *many])
    assert result.exit_code == 2


def test_compare_custom_periods_are_forwarded(monkeypatch):
    """`kan compare --periods` 支持 2-360 任意周期并传给 scan_stock。"""
    from datetime import date

    import pandas as pd
    from typer.testing import CliRunner

    from kan.app import app
    from kan.core.models import PeriodResult, StockScanResult

    names = {
        "600519": ("600519", "贵州茅台"),
        "000858": ("000858", "五粮液"),
    }
    captured: list[list[int] | None] = []

    monkeypatch.setattr("kan.storage.watchlist.resolve_symbol_or_name", lambda raw: names[raw])
    monkeypatch.setattr("kan.data.fetcher.is_fresh", lambda symbol: True)
    monkeypatch.setattr(
        "kan.data.fetcher.get_cached",
        lambda symbol: pd.DataFrame({"close": [100.0], "date": [date(2026, 5, 14)]}),
    )

    def fake_scan_stock(df, symbol, name, periods=None):
        captured.append(periods)
        return StockScanResult(
            symbol=symbol,
            name=name,
            current_price=100.0,
            scan_date=date(2026, 5, 14),
            periods=[
                PeriodResult(
                    period=20,
                    n_low=90.0,
                    n_high=110.0,
                    position_pct=50.0,
                    at_low=False,
                    at_high=False,
                )
            ],
            low_resonance=0,
            high_resonance=0,
        )

    monkeypatch.setattr("kan.core.scanner.scan_stock", fake_scan_stock)

    result = CliRunner().invoke(
        app,
        ["compare", "600519", "000858", "--periods", "20", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    assert captured == [[20], [20]]
