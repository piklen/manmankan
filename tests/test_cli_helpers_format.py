"""cli_helpers 日期格式化 helper 测试 (UX-1 · 散户友好压缩 · v0.0.4.7).

覆盖:
- format_date_compact: 同年省 year · 跨年完整 ISO
- format_fetched_at_compact: 当天只时间 · 同年 mm-dd HH:MM · 跨年完整
- 边界: 不可解析输入 · None · 空字符串
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from kan.cli_helpers import format_date_compact, format_fetched_at_compact


class TestFormatDateCompact:
    """UX-1: 同年 date 省 year."""

    def test_same_year_omits_year(self):
        today = datetime.now().date()
        same_year = date(today.year, 3, 15)
        result = format_date_compact(same_year)
        assert result == "03-15"
        assert str(today.year) not in result, "同年应省 year"

    def test_different_year_keeps_full_iso(self):
        today = datetime.now().date()
        last_year = date(today.year - 1, 12, 31)
        result = format_date_compact(last_year)
        assert result == f"{today.year - 1}-12-31"

    def test_future_year_keeps_full_iso(self):
        today = datetime.now().date()
        next_year = date(today.year + 1, 1, 1)
        result = format_date_compact(next_year)
        assert result == f"{today.year + 1}-01-01"


class TestFormatFetchedAtCompact:
    """UX-1: 当天只时间 · 同年 mm-dd HH:MM · 跨年完整."""

    def test_today_returns_time_only(self):
        # mock now() to fixed 2026-05-14 17:00
        with patch("kan.cli_helpers.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 14, 17, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            result = format_fetched_at_compact("2026-05-14 10:30")
        assert result == "10:30", "当天应只显示时间"

    def test_same_year_different_day_returns_md_hm(self):
        with patch("kan.cli_helpers.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 14, 17, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            result = format_fetched_at_compact("2026-03-10 09:15")
        assert result == "03-10 09:15"

    def test_different_year_returns_full(self):
        with patch("kan.cli_helpers.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 14, 17, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            result = format_fetched_at_compact("2025-12-31 23:59")
        assert result == "2025-12-31 23:59"

    def test_unparseable_returns_as_is(self):
        result = format_fetched_at_compact("not a date")
        assert result == "not a date"

    def test_empty_string_returns_empty(self):
        result = format_fetched_at_compact("")
        # empty 走 except (ValueError) · 返原样
        assert result == ""


class TestNoLegacyTextInWarnings:
    """UX-2 + U-5: 验证 stale 警告新文案 + 删除旧"应有最近交易日"."""

    def test_stale_warning_uses_new_phrasing(self):
        """scan/trend stale 警告应含"缓存到 X 收盘" + "数据滞后 N 天" · 不再含"应有最近交易日"."""
        from pathlib import Path
        scan_src = Path("kan/cli_scan_cmds.py").read_text(encoding="utf-8")
        trend_src = Path("kan/cli_trend_cmds.py").read_text(encoding="utf-8")
        for src, name in [(scan_src, "scan"), (trend_src, "trend")]:
            assert "应有最近交易日" not in src, f"{name}: 旧术语 '应有最近交易日' 应删除 (UX-2)"
            assert "当前缓存到" in src, f"{name}: 新文案 '当前缓存到' 应出现 (UX-2)"
            assert "数据滞后" in src, f"{name}: 新文案 '数据滞后' 应出现 (UX-2)"

    def test_intraday_warning_uses_new_phrasing(self):
        """UX-3: 盘中警告改为'每秒变动 · 涨停可能下一秒打开'."""
        from pathlib import Path
        scan_src = Path("kan/cli_scan_cmds.py").read_text(encoding="utf-8")
        trend_src = Path("kan/cli_trend_cmds.py").read_text(encoding="utf-8")
        for src, name in [(scan_src, "scan"), (trend_src, "trend")]:
            assert "数据每秒变动" in src, f"{name}: 新文案 '数据每秒变动' 应出现 (UX-3)"
            assert "可能下一秒打开" in src, f"{name}: 新文案 '可能下一秒打开' 应出现 (UX-3)"
            assert "建议盘后 15:30" in src, f"{name}: 新文案 '建议盘后 15:30' 应出现 (UX-3)"

    def test_warnings_use_elif_not_if_if(self):
        """UX-4: 双警告应 if/elif 互斥 · 不再 if/if."""
        from pathlib import Path
        for fp in ["kan/cli_scan_cmds.py", "kan/cli_trend_cmds.py"]:
            src = Path(fp).read_text(encoding="utf-8")
            # 找 "if is_stale" 后紧跟的 "elif phase == PHASE_INTRADAY"
            assert "if is_stale:" in src
            assert "elif phase == PHASE_INTRADAY:" in src, (
                f"{fp}: 双警告应改为 if/elif 互斥 (UX-4)"
            )
            # 反例: "if phase == PHASE_INTRADAY:" 独立 if (不接 elif) 应消失
            # 注: 用 "    if phase ==" (前 4 空格 · 表 stale 之外的独立 if) 检测
            assert "\n    if phase == PHASE_INTRADAY:" not in src, (
                f"{fp}: 残留独立 'if phase == INTRADAY' (应改 elif · UX-4)"
            )
