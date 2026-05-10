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
        from kan.render import responsive_periods
        result = responsive_periods(200)
        assert len(result) == 10

    def test_130_returns_all_10(self) -> None:
        from kan.render import responsive_periods
        result = responsive_periods(130)
        assert len(result) == 10

    def test_100_returns_6_short_dense(self) -> None:
        from kan.render import responsive_periods
        result = responsive_periods(100)
        assert len(result) == 6
        assert result[:3] == [3, 5, 10]
        assert 180 in result

    def test_90_returns_5(self) -> None:
        from kan.render import responsive_periods
        result = responsive_periods(90)
        assert len(result) == 5
        assert 5 in result and 10 in result
        assert 180 in result

    def test_80_returns_4_with_5_10(self) -> None:
        from kan.render import responsive_periods
        result = responsive_periods(80)
        assert len(result) == 4
        assert result == [5, 10, 30, 180]

    def test_70_returns_3(self) -> None:
        from kan.render import responsive_periods
        result = responsive_periods(70)
        assert len(result) == 3
        assert 180 in result

    def test_60_returns_2(self) -> None:
        from kan.render import responsive_periods
        result = responsive_periods(60)
        assert len(result) == 2
        assert 180 in result

    def test_always_sorted_ascending(self) -> None:
        from kan.render import responsive_periods
        for width in [60, 70, 80, 90, 100, 130, 200]:
            result = responsive_periods(width)
            assert result == sorted(result), f"width={width}: {result} not sorted"

    def test_resonance_visible_at_80(self) -> None:
        """80 列下 scan 表共振列不被截断"""
        from kan.render import responsive_periods
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
        from kan.render import max_trend_dates
        assert max_trend_dates(80) >= 1

    def test_wider_allows_more_dates(self) -> None:
        from kan.render import max_trend_dates
        assert max_trend_dates(200) > max_trend_dates(80)
