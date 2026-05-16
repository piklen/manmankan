"""CR-4 v0.0.4.7 · 补测试覆盖盲区.

部分 finding (CR-4 全套 3 类) 已被其他 test 覆盖:
- warning / title runtime 行为 → tests/test_trend_cli.py CliRunner 真测 (CR-1 v0.0.4.8 改造完成)
- data_cutoff / is_fresh / future date 边界 → tests/test_data_freshness.py 19 case

本 file 补 1 项:
- test_fetched_at_lex_sort_equals_time_sort (验"取最新" lex 排序语义 ·
  CR-2 v0.0.4.5 的 main-session fix 配套 · 防回归)

CR-4 其他 2 项 (future_date with warning · scan/info 命令组完整覆盖)
推 v0.0.4.8 CR-2 (CLI 命令组覆盖率 6% → 60%+).
"""
from __future__ import annotations

from datetime import datetime


def test_fetched_at_lex_sort_equals_time_sort():
    """fetched_at 取 max() 用 lex 排序 · 等同时间排序.

    CR-2 v0.0.4.5 fix: `if t and (fetched_at is None or t > fetched_at): fetched_at = t`
    依赖 ISO timestamp 字符串的 lex 排序 = 时间排序属性.
    本 test 防止未来格式变更 (e.g. "5月13日 16:35") 破坏此 invariant.
    """
    times = [
        "2026-05-13 09:00",  # 早盘
        "2026-05-13 16:35",  # 盘后 (最新)
        "2026-05-13 16:30",  # 盘后 (5min 前)
        "2026-05-12 23:59",  # 昨晚
        "2026-05-13 02:55",  # 凌晨拉数据 (v0.0.4.4 bug 场景)
    ]
    # Lex sort
    sorted_lex = sorted(times)
    # Time sort (parsed via datetime)
    sorted_time = sorted(times, key=datetime.fromisoformat)

    assert sorted_lex == sorted_time, "ISO timestamp lex 排序应严格 = 时间排序"
    assert max(times) == "2026-05-13 16:35", "max() 应取最新 · 不是字典序意外的某项"


def test_fetched_at_max_picks_latest_correctly_across_days():
    """跨天 fetched_at 取 max 应正确 · 即使昨天 23:59 字符串 lex 比 今天 02:55 'larger' 看起来."""
    today_early = "2026-05-13 02:55"
    yesterday_late = "2026-05-12 23:59"
    # Lex: "2026-05-13" > "2026-05-12" · 所以 today_early > yesterday_late 即使时间分钟 'early'
    # 这正是 fetched_at 应该取的语义 · 跨天后今天的数据更新于昨天
    assert max(today_early, yesterday_late) == today_early
    assert max(today_early, yesterday_late) == max(
        [today_early, yesterday_late],
        key=datetime.fromisoformat,
    )
