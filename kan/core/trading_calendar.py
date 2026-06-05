"""A 股交易日历 + 市场相位判定 · 数据时效性的真相源 + 防御纵深。

为什么需要本模块:
早期实现缓存新鲜度只看 mtime · 凌晨 02:55 拉了昨日数据后 mtime 日期 = 今天,
被误判为"今日数据齐了"整天不刷新, scan 结果停留在昨日(包括错误涨停标签)。
本模块提供"应有最近交易日"作为缓存判定的真相基准(替代 mtime)。

设计要点:
- 交易日列表: akshare ak.tool_trade_date_hist_sina() · 本地 JSON 缓存 7 天
- 市场相位: 本地时间判 pre / intraday / post / closed_day
- "应有最近交易日": 盘后 ≥ 15:30 当日已 final; 否则回退到最近交易日
- 不引入 pytz / zoneinfo · 假设系统时区为本地(Asia/Shanghai 用户主体)
- 跨时区用户可通过 TZ 环境变量影响 datetime.now() · 或设 KAN_DATA_AVAIL_OFFSET_MIN

防御纵深:
- akshare 失败 / 返脏 / cache 损坏 → 不抛 RuntimeError · 退化 weekday 启发式 + stderr warning
- 缓存内容三 invariant sanity check (count > 5000 · min year < 2010 · max date > today-30)
- chmod 0o600 后真校验 · 失败 stderr warn (不再静默 suppress)
- _trade_dates_memo 加锁 (double-checked) · 防多线程并发首调 akshare
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import date, datetime, time, timedelta

from kan.infra._time import today as _today
from kan.storage.paths import BASE_DIR

# 北京时间 A 股交易时段
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(15, 0)


def _resolve_data_available_after() -> time:
    """计算 DATA_AVAILABLE_AFTER · 支持 env var KAN_DATA_AVAIL_OFFSET_MIN 覆盖.

    背景: 跨时区 / WSL2 默认 UTC / Docker 容器用户能自救.

    默认 15:30 北京时间 (= 15:00 收盘 + 30min 数据延迟 final).
    Override: KAN_DATA_AVAIL_OFFSET_MIN=N (整数 minutes) · 变为 15:00 + N min.

    场景示例:
    - WSL2 系统时区 UTC: 设 KAN_DATA_AVAIL_OFFSET_MIN=510 (中国 23:30 = UTC 15:30)
    - 美东 (UTC-5): KAN_DATA_AVAIL_OFFSET_MIN=-270 (东 8 区比美东早 13 小时 → 02:30 美东)
    - 严格盘后 (16:00 才算 final): KAN_DATA_AVAIL_OFFSET_MIN=60

    解析失败 (非整数 / 越界) → 静默回退默认 15:30 · 不抛.
    """
    import os
    raw = os.environ.get("KAN_DATA_AVAIL_OFFSET_MIN")
    if raw:
        try:
            n = int(raw)
            # 从 15:00 base + n min
            base_minutes = 15 * 60 + n
            if 0 <= base_minutes < 24 * 60:
                return time(base_minutes // 60, base_minutes % 60)
        except ValueError:
            pass
    # 留 30min 给收盘清算 · 保守 · 避免 15:00:01 就判 final 但接口尚未推数据
    return time(15, 30)


DATA_AVAILABLE_AFTER = _resolve_data_available_after()

# 相位常量
PHASE_PRE = "pre"
PHASE_INTRADAY = "in"
PHASE_POST = "post"
PHASE_CLOSED_DAY = "closed"

# 交易日历本地缓存
TRADE_DATES_CACHE = BASE_DIR / "trade_dates.json"
TRADE_DATES_TTL_DAYS = 7

# Sanity check 阈值
SANITY_MIN_COUNT = 5000             # akshare 至少给 5000+ trade_dates(历史 2000-2027 约 6500 天)
SANITY_MAX_YEAR_MIN = 2010          # 最早 date.year 必须 < 2010(确保有历史回溯)
SANITY_MAX_DAYS_OLD = 30            # 最大 date 至少在 today - 30 之内(确保近期数据)

# 模块级 memo + 锁 (double-checked locking)
_trade_dates_memo: set[date] | None = None
_memo_lock = threading.Lock()


def _sanity_check_dates(dates: set[date], context: str = "") -> bool:
    """三 invariant sanity check.

    任一 fail → return False · 触发 cache miss / 重拉。
    用于 cache 内容校验 + akshare 返回值校验。
    """
    if not dates or len(dates) < SANITY_MIN_COUNT:
        print(
            f"[kan] ⚠️  {context} sanity 失败 · count={len(dates) if dates else 0} 太少",
            file=sys.stderr,
        )
        return False
    min_d = min(dates)
    if min_d.year >= SANITY_MAX_YEAR_MIN:
        print(
            f"[kan] ⚠️  {context} sanity 失败 · 最早日期 {min_d} 太新(应早于 {SANITY_MAX_YEAR_MIN})",
            file=sys.stderr,
        )
        return False
    today = _today()  # 背景: 用 kan.infra._time.today() 集中(单一来源)
    max_d = max(dates)
    if max_d < today - timedelta(days=SANITY_MAX_DAYS_OLD):
        print(
            f"[kan] ⚠️  {context} sanity 失败 · 最新日期 {max_d} 距今 {(today - max_d).days} 天 "
            f"(超 {SANITY_MAX_DAYS_OLD})",
            file=sys.stderr,
        )
        return False
    return True


def _read_cache() -> set[date] | None:
    """读 trade_dates.json 缓存 · TTL + sanity check 全通过才返回。

    加 sanity check 三 invariant · 失败返 None 触发重拉。
    except 缩窄到 (JSONDecodeError | ValueError | OSError) + stderr warn。
    """
    if not TRADE_DATES_CACHE.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(TRADE_DATES_CACHE.stat().st_mtime)
        if (datetime.now() - mtime).days >= TRADE_DATES_TTL_DAYS:
            return None
        data = json.loads(TRADE_DATES_CACHE.read_text(encoding="utf-8"))
        dates = {date.fromisoformat(d) for d in data}
        if not _sanity_check_dates(dates, context="trade_dates.json cache"):
            return None
        return dates
    except (json.JSONDecodeError, ValueError, OSError) as e:
        # 缩 except 范围 + stderr warn
        print(
            f"[kan] ⚠️  trade_dates.json 读取失败 ({type(e).__name__}: {e}) · 重新拉取",
            file=sys.stderr,
        )
        return None


def _write_cache(dates: set[date]) -> None:
    """写 trade_dates.json + chmod 0600 真校验。

    chmod 失败不再静默 contextlib.suppress · 改 stderr warn。
    """
    from kan.storage.paths import ensure_dirs
    ensure_dirs()
    payload = sorted(d.isoformat() for d in dates)
    TRADE_DATES_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    # chmod 0o600 后真校验 · 失败 stderr warn
    try:
        TRADE_DATES_CACHE.chmod(0o600)
        actual_mode = TRADE_DATES_CACHE.stat().st_mode & 0o777
        if actual_mode != 0o600:
            print(
                f"[kan] ⚠️  trade_dates.json 权限设置失败 "
                f"(目标 0o600 · 实际 0o{actual_mode:o}) · "
                "可能跨 FS (SMB / 容器 mount) 不支持精确 chmod",
                file=sys.stderr,
            )
    except OSError as e:
        # 背景: 不暴露 errno 原文 · 仅给类型 · 防容器逃逸侦察辅助
        print(
            f"[kan] ⚠️  chmod 失败 (errno {e.errno}) · trade_dates.json 权限可能开放",
            file=sys.stderr,
        )


def _fetch_from_akshare() -> set[date]:
    """从 akshare 拉全部 A 股交易日历 · 包 try/except + sanity check。

    失败抛 RuntimeError (由 get_trade_dates 兜底降级 weekday 启发式)。
    akshare 返回值零校验 sanity check (与 _read_cache 同结构)。

    数据 ~10000 行 · 序列化后 JSON ~100KB · in-memory set ~1MB。
    """
    try:
        import akshare as ak
        import pandas as pd
    except ImportError as e:
        raise RuntimeError(f"akshare/pandas 导入失败: {e}") from e

    try:
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            raise RuntimeError("akshare 返回空 DataFrame")
        if "trade_date" not in df.columns:
            raise RuntimeError(f"akshare DataFrame 缺 trade_date 列 (有 {list(df.columns)})")
        col = df["trade_date"]
        dates = {pd.to_datetime(v).date() for v in col}
        # sanity check akshare 返回值
        if not _sanity_check_dates(dates, context="akshare tool_trade_date_hist_sina"):
            raise RuntimeError(f"akshare 返回值 sanity 失败 (count={len(dates)})")
        return dates
    except RuntimeError:
        raise  # 不二次包装 RuntimeError
    except (KeyError, ValueError, AttributeError) as e:
        raise RuntimeError(f"akshare 拉取失败 ({type(e).__name__}: {e})") from e
    except Exception as e:
        # 兜底: akshare/pandas 上游可能抛 unexpected · 转 RuntimeError 进入 fail-soft
        raise RuntimeError(f"akshare 未知错误 ({type(e).__name__}: {e})") from e


def _weekday_heuristic(as_of: datetime) -> date:
    """退化路径: 周一-周五视为交易日 (不识别节假日)。

    fail-soft fallback · 不抛 RuntimeError。
    """
    today = as_of.date()
    if today.weekday() < 5 and as_of.time() >= DATA_AVAILABLE_AFTER:
        return today
    # 回退到最近 weekday
    cursor = today
    for _ in range(7):
        cursor = cursor - timedelta(days=1)
        if cursor.weekday() < 5:
            return cursor
    return today  # 防御性退出 (理论不可达)


def get_trade_dates() -> set[date]:
    """返回交易日集合 · 7 天 TTL 缓存 · 进程内 memo · 多线程安全。

    double-checked locking 防 fetch_batch 多线程并发首调 akshare。
    akshare fail → 返回空 set · 调用方走 weekday 启发式 path · 不抛 RuntimeError。
    """
    global _trade_dates_memo
    # 第一次 check (无锁 · 命中路径快)
    if _trade_dates_memo is not None:
        return _trade_dates_memo

    with _memo_lock:
        # 第二次 check (锁内 · 防其他 thread 已写入)
        if _trade_dates_memo is not None:
            return _trade_dates_memo

        cached = _read_cache()
        if cached is not None:
            _trade_dates_memo = cached
            return cached

        # akshare 拉取 · 失败降级
        try:
            dates = _fetch_from_akshare()
            _write_cache(dates)
            _trade_dates_memo = dates
            return dates
        except RuntimeError as e:
            # 降级 · 不抛 · 返回空 set · 调用方走 weekday 启发式
            print(
                f"[kan] ⚠️  交易日历不可用 ({e}) · 降级到 weekday 启发式 "
                "(周一-周五视为交易日 · 不识别节假日 · 长假后可能误判)",
                file=sys.stderr,
            )
            _trade_dates_memo = set()  # 空集合 marker · is_trading_day / latest_trade_date 走降级
            return _trade_dates_memo


def is_trading_day(d: date) -> bool:
    """判断指定日期是否为交易日。

    fail-soft: get_trade_dates() 空集合时退化 weekday 启发式。
    """
    dates = get_trade_dates()
    if not dates:
        return d.weekday() < 5  # 周一-周五 (不识别节假日)
    return d in dates


def latest_trade_date(as_of: datetime | None = None) -> date:
    """返回截至 as_of 时刻 "应有" 数据的最近交易日 (已 final 收盘)。

    判定规则:
    - as_of 是交易日 且 时间 ≥ DATA_AVAILABLE_AFTER(15:30) → 当日
    - 否则向前回找最近交易日 (最多 14 天保护)

    示例 (假设系统 TZ=Asia/Shanghai):
    - 周一 16:00          → 周一
    - 周二 10:00 (盘中)    → 周一
    - 周二 09:00 (盘前)    → 周一
    - 周六任何时间         → 周五
    - 长假后第一天 09:00   → 节前最后一个交易日

    fail-soft: 交易日历不可用时退化 weekday 启发式 · 不抛 RuntimeError。
    """
    if as_of is None:
        as_of = datetime.now()

    trade_days = get_trade_dates()
    today = as_of.date()

    # 退化路径: trade_days 为空 (akshare + cache 双失败)
    if not trade_days:
        return _weekday_heuristic(as_of)

    if today in trade_days and as_of.time() >= DATA_AVAILABLE_AFTER:
        return today

    cursor = today
    for _ in range(14):
        cursor = cursor - timedelta(days=1)
        if cursor in trade_days:
            return cursor

    # 14 天保护失败也降级 · 不抛 RuntimeError
    print(
        f"[kan] ⚠️  找不到 {today} 之前 14 天内的交易日 · "
        "用 weekday 启发式 · 试 `kan fetch --force`",
        file=sys.stderr,
    )
    return _weekday_heuristic(as_of)


def market_phase(as_of: datetime | None = None) -> str:
    """返回当前市场相位 · 返回值 = PHASE_* 之一。

    PHASE_PRE        非交易日前 / 交易日 < 9:30
    PHASE_INTRADAY   交易日 9:30 ≤ t < 15:00 (实时变动 · 涨跌停可能瞬时反转)
    PHASE_POST       交易日 ≥ 15:00 (含数据延迟未 final 的 15:00-15:30 窗口)
    PHASE_CLOSED_DAY 非交易日 (周末 / 节假日)

    fail-soft: trade_days 为空时用 weekday 启发式判 trading_day。
    """
    if as_of is None:
        as_of = datetime.now()

    trade_days = get_trade_dates()
    if not trade_days:
        # 退化: weekday 启发式 (不识别节假日)
        if as_of.date().weekday() >= 5:
            return PHASE_CLOSED_DAY
    elif as_of.date() not in trade_days:
        return PHASE_CLOSED_DAY

    t = as_of.time()
    if t < MARKET_OPEN:
        return PHASE_PRE
    if t < MARKET_CLOSE:
        return PHASE_INTRADAY
    return PHASE_POST


def clear_memo() -> None:
    """测试用: 清除 module-level memo 让 monkeypatch 生效 · 多线程安全。"""
    global _trade_dates_memo
    with _memo_lock:
        _trade_dates_memo = None
