"""固定截止日的日线证据：原始 OHLC × 当日因子 / 截止日因子。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from kan.data.tushare import TushareDataContractError, _post_tushare_api, _resolve_config
from kan.storage.paths import DATA_DIR, atomic_write_parquet

RAW_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
FACTOR_FIELDS = "ts_code,trade_date,adj_factor"


def _query(api: str, params: dict, fields: str) -> pd.DataFrame:
    token, endpoint = _resolve_config()
    if not token:
        raise RuntimeError("日线证据需要已配置的 TuShare 凭证")
    data, error = _post_tushare_api(
        endpoint=endpoint, token=token, api_name=api, params=params, fields=fields,
    )
    if data is None:
        detail = error.msg if error else "无数据"
        raise RuntimeError(f"{api}: {detail}")
    df = pd.DataFrame(data.get("items", []), columns=data.get("fields", []))
    missing = set(fields.split(",")) - set(df.columns)
    if missing or df.empty:
        raise TushareDataContractError(api, f"空响应或缺少字段 {sorted(missing)}")
    return df


def load_mainboard_universe() -> pd.DataFrame:
    """不使用自选、热榜或缺少市场分类的代码缓存。"""
    fields = "ts_code,symbol,name,industry,market,exchange,list_status,list_date"
    df = _query("stock_basic", {"list_status": "L"}, fields)
    if len(df) < 5000 or df["symbol"].duplicated().any():
        raise TushareDataContractError("stock_basic", "全市场代码表不完整或代码重复")
    pool = df[
        df["market"].eq("主板") & df["list_status"].eq("L")
        & ((df["exchange"].eq("SSE") & df["symbol"].str.startswith("60"))
           | (df["exchange"].eq("SZSE") & df["symbol"].str.startswith("00")))
    ].copy()
    if set(pool["exchange"]) != {"SSE", "SZSE"}:
        raise TushareDataContractError("stock_basic", "主板股票池缺少沪市或深市")
    return pool.sort_values("symbol").reset_index(drop=True)


def load_session_dates(as_of: date, count: int) -> list[str]:
    """沪深官方交易日历必须一致；不使用工作日启发式补日期。"""
    start = as_of - timedelta(days=count * 2 + 60)
    params = {"start_date": start.strftime("%Y%m%d"), "end_date": as_of.strftime("%Y%m%d")}
    calendars = []
    for exchange in ("SSE", "SZSE"):
        df = _query("trade_cal", {**params, "exchange": exchange}, "exchange,cal_date,is_open")
        if not df["exchange"].eq(exchange).all() or df["cal_date"].duplicated().any():
            raise TushareDataContractError("trade_cal", "交易所不匹配或日期重复")
        expected = pd.date_range(start, as_of).strftime("%Y%m%d").tolist()
        if sorted(df["cal_date"].astype(str)) != expected:
            raise TushareDataContractError("trade_cal", "日历存在缺日或越界日期")
        calendars.append(sorted(df.loc[pd.to_numeric(df["is_open"]).eq(1), "cal_date"].astype(str)))
    if calendars[0] != calendars[1] or len(calendars[0]) < count:
        raise TushareDataContractError("trade_cal", "沪深日历不一致或交易日不足")
    if calendars[0][-1] != as_of.strftime("%Y%m%d"):
        raise ValueError("--as-of 必须是已完成收盘的交易日")
    return calendars[0][-count:]


def _daily_evidence(td: str, *, refresh: bool) -> pd.DataFrame:
    # 缓存原始价格和因子，不缓存随未来分红变化的 qfq 分母。
    path = DATA_DIR / f"ohlc_facts_v1_{td}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    frames = []
    for api, fields in (("daily", RAW_FIELDS), ("adj_factor", FACTOR_FIELDS)):
        df = _query(api, {"trade_date": td}, fields)
        if (len(df) < 3000 or not df["trade_date"].astype(str).eq(td).all()
                or df["ts_code"].duplicated().any()):
            raise TushareDataContractError(api, f"{td} 截面不完整、日期不符或代码重复")
        frames.append(df)
    merged = frames[0].merge(frames[1], on=["ts_code", "trade_date"], how="left", validate="one_to_one")
    atomic_write_parquet(merged, path)
    return merged


def load_adjusted_history(dates: list[str], *, refresh: bool = False) -> pd.DataFrame:
    """按日期批量拉全市场，避免逐股请求；缺因子保留 NaN，由评估层排除。"""
    with ThreadPoolExecutor(max_workers=8) as executor:
        frames = list(executor.map(lambda td: _daily_evidence(td, refresh=refresh), dates))
    return adjust_history(pd.concat(frames, ignore_index=True), dates[-1])


def adjust_history(raw: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """保留 raw_* 和 adj_factor，让同一份输入可独立复核。"""
    df = raw.copy()
    df["symbol"] = df["ts_code"].str.split(".").str[0]
    df["date"] = df["trade_date"].astype(str)
    for col in ("open", "high", "low", "close", "vol", "amount", "adj_factor"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    base = df.loc[df["date"].eq(as_of)].set_index("symbol")["adj_factor"]
    df["base_factor"] = df["symbol"].map(base)
    for col in ("open", "high", "low", "close"):
        df[f"raw_{col}"] = df[col]
        df[col] = (df[col] * df["adj_factor"]).round(10) / df["base_factor"]
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)
