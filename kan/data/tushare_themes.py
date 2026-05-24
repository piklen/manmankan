"""TuShare Pro 题材数据源 · v0.0.5.7 · 配 token 时优先于 adata EM 路径。

为啥引入 TuShare 路径:
- adata EM datacenter HTTP 服务端不稳定(2026-05-25 实测 RemoteDisconnected
  全部 391 题材失败)· 没 stale cache 兜底时 kan theme trend 直接挂
- TuShare ths_daily 是 batch 接口 · trade_date=YYYYMMDD 一次 HTTP 拿
  ~1232 个 TuShare 题材当日数据(含 A 股 / 港股 / 美股各 exchange)· 1.79s
- 历史 K 线按交易日 loop:60 个交易日 = 60 次 HTTP · 仍比 adata 路径
  (391 题材 × 30 天历史 / 16 worker · 走 datacenter 单题材接口)架构更优

token 优先级:沿用 kan.data.tushare._resolve_config
- env TUSHARE_TOKEN > config['tushare_token'] > None
- env TUSHARE_ENDPOINT > config['tushare_endpoint'] > DEFAULT_ENDPOINT
- token 未配置时 tushare_load_*() 返回 None · caller 退化 adata EM 路径

数据格式 normalize 到 manmankan 标准:
- ts_code: '886108.TI' → 纯数字 '886108'(跟 adata THS catalog 对齐)
- trade_date: 'YYYYMMDD' → datetime.date(跟 EM kline 对齐)
- 列对齐 _KLINE_COLUMNS:date / open / high / low / close / volume / amount
- TuShare ths_daily 不返 volume / amount · 填 NaN(streak 算法不用 volume)

token 不进任何 cache / log:
- _post_tushare_api 内部已做 token redaction(kan.data.tushare 模块)
- 本模块只把题材清单 / K 线数据落 cache · 不写 token
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from kan.core.models import Theme
from kan.data.tushare import _post_tushare_api, _resolve_config
from kan.infra.log import debug_log
from kan.storage.paths import BOARDS_DIR, atomic_write_json, ensure_dirs

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

_THEME_CATALOG_TTL = 24 * 3600
_THEME_KLINES_TTL = 12 * 3600  # K 线 TTL 比 catalog 短(日内可能多次拉)
_DEFAULT_HISTORY_DAYS = 35  # 默认拉 35 个交易日 · calc_trend 循环上限 30 天 · 5 天余量防边界


def tushare_token_configured() -> bool:
    """检查 TuShare token 是否可用 · True=走 TuShare · False=fallback adata EM。"""
    token, _ = _resolve_config()
    return token is not None


def _cache_fresh(path, ttl: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


def tushare_load_theme_catalog() -> list[Theme] | None:
    """走 ths_index?type=N&exchange=A · A 股题材清单(~409 个)· 24h JSON cache。

    Returns:
        list[Theme] · source='tushare' · code 已 strip '.TI' 后缀
        None 表示 TuShare 不可用(token 没配 / 接口返回 None / 数据空)

    caller 拿 None 时应 fallback `boards.load_theme_catalog()`(adata 路径)。
    """
    token, endpoint = _resolve_config()
    if not token:
        return None

    ensure_dirs()
    cache = BOARDS_DIR / "catalog_tushare_ths.json"
    if _cache_fresh(cache, _THEME_CATALOG_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Theme(**t) for t in data]
        except Exception as e:
            debug_log(__name__, f"tushare catalog cache {cache.name} 损坏", e)

    data = _post_tushare_api(
        endpoint, token,
        api_name="ths_index",
        params={"type": "N", "exchange": "A"},
        fields="ts_code,name,count,exchange",
    )
    if data is None:
        return None

    items = data.get("items") or []
    fields = data.get("fields") or []
    if not items or not fields:
        return None

    themes: list[Theme] = []
    for row in items:
        rec = dict(zip(fields, row, strict=False))
        ts_code = str(rec.get("ts_code") or "").strip()
        name = str(rec.get("name") or "").strip()
        if not ts_code or not name:
            continue
        size_raw = rec.get("count")
        try:
            size = int(size_raw) if size_raw is not None else None
        except (TypeError, ValueError):
            size = None
        themes.append(Theme(
            code=ts_code.replace(".TI", ""),
            name=name,
            source="tushare",
            size=size,
        ))

    if not themes:
        return None

    atomic_write_json(cache, [t.model_dump() for t in themes], ensure_ascii=False)
    return themes


def _recent_trading_days(n: int) -> list[date]:
    """近 N 个交易日(降序)· 复用现有 trading_calendar · 失败兜底空 list。"""
    try:
        from kan.core.trading_calendar import get_trade_dates, latest_trade_date

        latest = latest_trade_date()
        all_days = sorted([d for d in get_trade_dates() if d <= latest], reverse=True)
        return all_days[:n]
    except Exception as e:
        debug_log(__name__, "trading_calendar 不可用 · 题材榜无法 batch", e)
        return []


def tushare_load_theme_klines(
    themes: list[Theme],
    *,
    n_trading_days: int = _DEFAULT_HISTORY_DAYS,
) -> dict[str, pd.DataFrame] | None:
    """批量拉 N 个交易日 × 全部题材 → 按 code group · 返回 dict[code, DataFrame]。

    使用 ths_daily(trade_date=YYYYMMDD) · 服务端聚合所有题材当日数据 ·
    N 次 HTTP 拿到 N 天 × ~1232 行 = ~74K 行 · 客户端按 ts_code group 拼装。

    Args:
        themes: 目标题材列表(source='tushare' 才用 · 别的 source 静默跳过)
        n_trading_days: 历史天数 · 默认 60 个交易日 · 覆盖 30 天 streak 余量

    Returns:
        dict[code(纯数字), DataFrame(date/open/high/low/close/volume/amount)]
        None 表示 TuShare 不可用 · caller fallback adata EM 路径
    """
    import pandas as pd

    from kan.storage.paths import atomic_write_parquet

    token, endpoint = _resolve_config()
    if not token:
        return None

    target_codes = {f"{t.code}.TI" for t in themes if t.source == "tushare"}
    if not target_codes:
        return None

    days = _recent_trading_days(n_trading_days)
    if not days:
        return None

    ensure_dirs()
    # cache key:第一天 + 最后一天 + 题材数 · 当日数据变化时(收盘后)key 自动更新
    cache = BOARDS_DIR / f"klines_tushare_{days[-1]}_{days[0]}_{len(target_codes)}.parquet"
    if _cache_fresh(cache, _THEME_KLINES_TTL):
        try:
            big_df = pd.read_parquet(cache)
            return _group_klines_by_code(big_df, target_codes)
        except Exception as e:
            debug_log(__name__, f"tushare klines cache {cache.name} 损坏", e)

    all_rows: list[dict] = []
    failed_days: list[str] = []
    for d in days:
        date_str = d.strftime("%Y%m%d")
        data = _post_tushare_api(
            endpoint, token,
            api_name="ths_daily",
            params={"trade_date": date_str},
            fields="ts_code,trade_date,open,high,low,close,pct_change",
        )
        if data is None:
            failed_days.append(date_str)
            continue
        items = data.get("items") or []
        fields = data.get("fields") or []
        for row in items:
            rec = dict(zip(fields, row, strict=False))
            if rec.get("ts_code") in target_codes:
                all_rows.append(rec)

    if not all_rows:
        return None

    if failed_days:
        debug_log(
            __name__,
            f"tushare ths_daily 部分天数失败({len(failed_days)}/{len(days)})· streak 仍可算 · 失败天数: {failed_days[:3]}...",
            RuntimeWarning(),
        )

    big_df = pd.DataFrame(all_rows)
    big_df["date"] = pd.to_datetime(big_df["trade_date"], format="%Y%m%d").dt.date
    big_df["volume"] = float("nan")
    big_df["amount"] = float("nan")
    big_df = big_df[["ts_code", "date", "open", "high", "low", "close", "volume", "amount"]]

    try:
        atomic_write_parquet(big_df, cache)
    except Exception as e:
        debug_log(__name__, "tushare klines cache 落 parquet 失败 · 不影响本次结果", e)

    return _group_klines_by_code(big_df, target_codes)


def _group_klines_by_code(
    big_df: pd.DataFrame, target_codes: set[str],
) -> dict[str, pd.DataFrame]:
    """big_df(多题材多日)按 ts_code group · 每个 code 一个排序 DataFrame。"""
    result: dict[str, pd.DataFrame] = {}
    for ts_code, group in big_df.groupby("ts_code"):
        if ts_code not in target_codes:
            continue
        code_norm = str(ts_code).replace(".TI", "")
        df = group[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
        df = (
            df.sort_values("date")
            .dropna(subset=["date", "close"])
            .reset_index(drop=True)
        )
        if len(df) >= 2:  # streak 算法最少要 2 行
            result[code_norm] = df
    return result
