"""A 股交易日历 + 市场相位判定 · 数据时效性的真相源。

为什么需要本模块：
v0.0.4.4 前缓存新鲜度只看 mtime ·凌晨 02:55 拉了昨日数据后 mtime 日期 = 今天，
被误判为"今日数据齐了"整天不刷新，scan 结果停留在昨日（包括错误涨停标签）。
本模块提供"应有最近交易日"作为缓存判定的真相基准（替代 mtime）。

设计要点：
- 交易日列表：akshare ak.tool_trade_date_hist_sina() · 本地 JSON 缓存 7 天
- 市场相位：本地时间判 pre / intraday / post / closed_day
- "应有最近交易日"：盘后 ≥ 15:30 当日已 final；否则回退到最近交易日
- 不引入 pytz / zoneinfo · 假设系统时区为本地（Asia/Shanghai 用户主体）
- 跨时区用户可通过 TZ 环境变量影响 datetime.now()
"""
from __future__ import annotations

import contextlib
import json
from datetime import date, datetime, time, timedelta

from kan.paths import BASE_DIR

# 北京时间 A 股交易时段
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(15, 0)
# 留 30min 给收盘清算 · 保守 · 避免 15:00:01 就判 final 但接口尚未推数据
DATA_AVAILABLE_AFTER = time(15, 30)

# 相位常量
PHASE_PRE = "pre"
PHASE_INTRADAY = "in"
PHASE_POST = "post"
PHASE_CLOSED_DAY = "closed"

# 交易日历本地缓存
TRADE_DATES_CACHE = BASE_DIR / "trade_dates.json"
TRADE_DATES_TTL_DAYS = 7

# 模块级 memo · 单 CLI 进程内只解析一次 · 测试用 clear_memo() 重置
_trade_dates_memo: set[date] | None = None


def _read_cache() -> set[date] | None:
    if not TRADE_DATES_CACHE.exists():
        return None
    mtime = datetime.fromtimestamp(TRADE_DATES_CACHE.stat().st_mtime)
    if (datetime.now() - mtime).days >= TRADE_DATES_TTL_DAYS:
        return None
    try:
        data = json.loads(TRADE_DATES_CACHE.read_text(encoding="utf-8"))
        return {date.fromisoformat(d) for d in data}
    except Exception:
        return None


def _write_cache(dates: set[date]) -> None:
    from kan.paths import ensure_dirs
    ensure_dirs()
    payload = sorted(d.isoformat() for d in dates)
    TRADE_DATES_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    # 沿用 paths.ensure_dirs 的 0o700 权限策略 · 文件级也保险
    # 某些 FS (SMB / 容器 mount) 不支持 chmod · 静默忽略
    with contextlib.suppress(OSError):
        TRADE_DATES_CACHE.chmod(0o600)


def _fetch_from_akshare() -> set[date]:
    """从 akshare 拉全部 A 股交易日历（历史 + 当年 + 次年早期）。

    数据 ~10000 行 · 序列化后 JSON ~100KB · in-memory set ~1MB。
    """
    import akshare as ak
    import pandas as pd

    df = ak.tool_trade_date_hist_sina()
    col = df["trade_date"]
    return {pd.to_datetime(v).date() for v in col}


def get_trade_dates() -> set[date]:
    """返回交易日集合 · 7 天 TTL 缓存 · 进程内 memo。"""
    global _trade_dates_memo
    if _trade_dates_memo is not None:
        return _trade_dates_memo
    cached = _read_cache()
    if cached is not None:
        _trade_dates_memo = cached
        return cached
    dates = _fetch_from_akshare()
    _write_cache(dates)
    _trade_dates_memo = dates
    return dates


def is_trading_day(d: date) -> bool:
    return d in get_trade_dates()


def latest_trade_date(as_of: datetime | None = None) -> date:
    """返回截至 as_of 时刻 "应有" 数据的最近交易日（已 final 收盘）。

    判定规则：
    - as_of 是交易日 且 时间 ≥ DATA_AVAILABLE_AFTER(15:30) → 当日
    - 否则向前回找最近交易日（最多 14 天保护）

    示例（假设系统 TZ=Asia/Shanghai）：
    - 周一 16:00       → 周一
    - 周二 10:00 (盘中) → 周一
    - 周二 09:00 (盘前) → 周一
    - 周六任何时间      → 周五
    - 长假后第一天 09:00 → 节前最后一个交易日
    """
    if as_of is None:
        as_of = datetime.now()

    trade_days = get_trade_dates()
    today = as_of.date()

    if today in trade_days and as_of.time() >= DATA_AVAILABLE_AFTER:
        return today

    cursor = today
    for _ in range(14):
        cursor = cursor - timedelta(days=1)
        if cursor in trade_days:
            return cursor
    raise RuntimeError(
        f"找不到 {today} 之前 14 天内的交易日 · "
        "可能交易日历缓存损坏 · 试 `kan fetch --force`"
    )


def market_phase(as_of: datetime | None = None) -> str:
    """返回当前市场相位 · 返回值 = PHASE_* 之一。

    PHASE_PRE        非交易日前 / 交易日 < 9:30
    PHASE_INTRADAY   交易日 9:30 ≤ t < 15:00（实时变动 · 涨跌停可能瞬时反转）
    PHASE_POST       交易日 ≥ 15:00（含数据延迟未 final 的 15:00-15:30 窗口）
    PHASE_CLOSED_DAY 非交易日（周末 / 节假日）
    """
    if as_of is None:
        as_of = datetime.now()
    if as_of.date() not in get_trade_dates():
        return PHASE_CLOSED_DAY
    t = as_of.time()
    if t < MARKET_OPEN:
        return PHASE_PRE
    if t < MARKET_CLOSE:
        return PHASE_INTRADAY
    return PHASE_POST


def clear_memo() -> None:
    """测试用：清除 module-level memo 让 monkeypatch 生效。"""
    global _trade_dates_memo
    _trade_dates_memo = None
