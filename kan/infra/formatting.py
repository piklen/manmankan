"""面向展示层的轻量格式化 helper。

CLI / render / core 警告文案都需要同一套日期压缩规则，放在 infra 层可以避免
低层模块为了展示文案反向依赖 `kan.cli.helpers`。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from kan.infra._time import today as _today


def format_date_compact(d: date) -> str:
    """同年时省 year (`05-12`) · 跨年才显示完整 ISO (`2025-12-31`)。"""
    today = _today()
    if d.year == today.year:
        return d.strftime("%m-%d")
    return d.isoformat()


def format_fetched_at_compact(fetched_str: str) -> str:
    """从 ISO datetime string 提取最 compact 表示。"""
    try:
        dt = datetime.fromisoformat(fetched_str)
    except (ValueError, TypeError):
        return fetched_str
    today = _today()
    if dt.date() == today:
        hour = dt.hour
        time_str = dt.strftime("%H:%M")
        if 0 <= hour < 5:
            return f"今晨 {time_str}"
        return time_str
    if dt.date() == today - timedelta(days=1) and dt.hour >= 22:
        return f"昨晚 {dt.strftime('%H:%M')}"
    if dt.year == today.year:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")
