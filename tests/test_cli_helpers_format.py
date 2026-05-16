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

    # CR-5 v0.0.4.8: 由于 cli_helpers 改用 _today() 集中 SoT (kan/_time.py) ·
    # patch path 从 "kan.cli_helpers.datetime" → "kan.cli_helpers._today" (更直接)

    def test_today_returns_time_only(self):
        """mock today=2026-05-14 · fetched=同天 → 只显示 HH:MM"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-05-14 10:30")
        assert result == "10:30", "当天应只显示时间"

    def test_same_year_different_day_returns_md_hm(self):
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-03-10 09:15")
        assert result == "03-10 09:15"

    def test_different_year_returns_full(self):
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2025-12-31 23:59")
        assert result == "2025-12-31 23:59"

    def test_unparseable_returns_as_is(self):
        result = format_fetched_at_compact("not a date")
        assert result == "not a date"

    def test_empty_string_returns_empty(self):
        result = format_fetched_at_compact("")
        # empty 走 except (ValueError) · 返原样
        assert result == ""

    # ── UX-3 (v0.0.4.8): 凌晨日界提示 ────────────────────────────
    def test_today_pre_dawn_shows_jinchen(self):
        """UX-3: 当天 00:00-04:59 → '今晨' 前缀防深夜误判"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-05-14 01:00")
        assert result == "今晨 01:00"

    def test_today_04_59_jinchen_upper_boundary(self):
        """UX-3 boundary: 04:59 仍是凌晨"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-05-14 04:59")
        assert result == "今晨 04:59"

    def test_today_05_00_no_jinchen_boundary(self):
        """UX-3 boundary: 05:00 不再是凌晨"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-05-14 05:00")
        assert result == "05:00"

    def test_today_normal_hours_no_prefix(self):
        """UX-3: 当天 05:00-21:59 → 不加前缀"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            for hour in [5, 9, 12, 17, 21]:
                t = datetime(2026, 5, 14, hour, 0)
                result = format_fetched_at_compact(t.isoformat())
                assert result == t.strftime("%H:%M"), f"{hour}h 不应加前缀"

    def test_yesterday_late_night_shows_zuowan(self):
        """UX-3: 昨天 22:00-23:59 → '昨晚' 前缀"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-05-13 23:50")
        assert result == "昨晚 23:50"

    def test_yesterday_22_00_zuowan_lower_boundary(self):
        """UX-3 boundary: 昨天 22:00 是 '昨晚'"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-05-13 22:00")
        assert result == "昨晚 22:00"

    def test_yesterday_21_59_no_zuowan(self):
        """UX-3 boundary: 昨天 21:59 不是 '昨晚' · fall through 到 md-hm"""
        with patch("kan.cli_helpers._today", return_value=date(2026, 5, 14)):
            result = format_fetched_at_compact("2026-05-13 21:59")
        assert result == "05-13 21:59"


# TestNoLegacyTextInWarnings 已删除 (CR-1 v0.0.4.8 改造)
# 原 3 个 grep-source 作弊 test 已被替换为 CliRunner runtime 真测:
# - test_trend_cli.py::test_trend_stale_warning_uses_new_phrasing
# - test_trend_cli.py::test_trend_intraday_warning_compliant_phrasing
# - test_trend_cli.py::test_trend_warnings_mutex_stale_wins
# scan/trend warning template 同源 · trend 真测覆盖 template 内容 · scan 命令完整 CliRunner coverage 推 CR-2.
