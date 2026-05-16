"""时间 SoT helper (CR-5 v0.0.4.8: 集中 datetime.now().date()).

放在独立 module 防 circular import:
- cli_helpers (上层) + trading_calendar (下层) 都需要 `今天的日期`
- cli_helpers 已 import trading_calendar · 反向不可行
- 放 _time.py · 0 上游依赖 · 任何 module 都可 import

替代 3 处独立 `datetime.now().date()` (cli_helpers 2 + trading_calendar 1) ·
方便 test 时 monkeypatch 单点 mock 控制"今天是哪天"。
"""
from __future__ import annotations

from datetime import date, datetime


def today() -> date:
    """返回今天的日期 (datetime.now().date() 的单点 entry).

    跨时区用户:datetime.now() 受系统 TZ 影响 · 默认 Asia/Shanghai.
    """
    return datetime.now().date()
