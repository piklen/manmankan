"""用户显式日线条件的确定性计算；不产生综合分或投资结论。"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator


class OhlcScreenRequest(BaseModel):
    market: Literal["mainboard"]
    as_of: date
    period: int = Field(ge=2, le=360)
    low_within: int = Field(ge=1)
    max_position: float = Field(ge=0, le=100, allow_inf_nan=False)
    joint_up_days: int = Field(ge=2)

    @model_validator(mode="after")
    def validate_windows(self) -> OhlcScreenRequest:
        if self.low_within > self.period or self.joint_up_days > self.period:
            raise ValueError("低点窗口和连续天数不能超过区间窗口")
        return self


def evaluate_ohlc_screen(
    request: OhlcScreenRequest, universe: pd.DataFrame,
    panel: pd.DataFrame, dates: list[str],
) -> dict:
    """严格比较未四舍五入的价格；平盘、阴线、下跌和缺行均不能穿透。"""
    as_of = request.as_of.strftime("%Y%m%d")
    if len(dates) != request.period + 1 or dates[-1] != as_of or dates != sorted(set(dates)):
        raise ValueError("日历必须包含完整窗口及前置交易日，并与截止日一致")
    groups = dict(tuple(panel.groupby("symbol", sort=False)))
    rows, evaluated, excluded = [], [], []
    for stock in universe.to_dict("records"):
        symbol = stock["symbol"]
        group = groups.get(symbol)
        reason = None
        if group is None or not group["date"].eq(as_of).any():
            reason = "missing_as_of_bar"
        else:
            group = group[group["date"].isin(dates)].sort_values("date").reset_index(drop=True)
            if group["date"].tolist() != dates:
                reason = "incomplete_history"
            else:
                values = group[["open", "high", "low", "close", "adj_factor", "base_factor", "vol", "amount"]].to_numpy(float)
                invalid = (not np.isfinite(values).all() or (values[:, :6] <= 0).any()
                           or (values[:, 6:] <= 0).any()
                           or (group["high"] < group[["open", "close", "low"]].max(axis=1)).any()
                           or (group["low"] > group[["open", "close", "high"]].min(axis=1)).any())
                if invalid:
                    reason = "invalid_bar_or_factor"
        if reason:
            excluded.append({"symbol": symbol, "name": stock["name"], "reason": reason})
            continue
        assert group is not None
        window = group.tail(request.period).reset_index(drop=True)
        close = float(group["close"].iloc[-1])
        low, high = float(window["low"].min()), float(window["high"].max())
        if high == low:
            excluded.append({"symbol": symbol, "name": stock["name"], "reason": "zero_range"})
            continue
        low_indices = window.index[window["low"].eq(low)].tolist()
        age = request.period - 1 - low_indices[-1]
        position = (close - low) / (high - low) * 100
        joint = group["close"].gt(group["open"]) & group["close"].gt(group["close"].shift())
        streak = 0
        for matched in reversed(joint.tolist()):
            if not matched:
                break
            streak += 1
        checks = {
            "joint_up_days": streak >= request.joint_up_days,
            "low_within": age < request.low_within,
            "above_low": close > low,
            "max_position": position <= request.max_position,
        }
        latest_volume = float(group["vol"].iloc[-1])
        previous_volume = group["vol"].iloc[-6:-1]
        row = {
            "symbol": symbol, "name": stock["name"], "industry": stock.get("industry"),
            "close": close, "change_pct": (close / float(group["close"].iloc[-2]) - 1) * 100,
            "joint_up_days": streak, "streak_capped": streak == request.period,
            "low": low, "low_date": dates[-request.period:][low_indices[-1]],
            "low_dates": window.loc[low_indices, "date"].tolist(), "low_age": age,
            "high": high, "from_low_pct": (close / low - 1) * 100, "position_pct": position,
            "gain_5d_pct": (close / float(group["close"].iloc[-6]) - 1) * 100 if len(group) >= 6 else None,
            "gain_10d_pct": (close / float(group["close"].iloc[-11]) - 1) * 100 if len(group) >= 11 else None,
            "volume_vs_prev5": latest_volume / float(previous_volume.mean()) if len(previous_volume) == 5 else None,
            "amount_yuan": float(group["amount"].iloc[-1]) * 1000,
            "checks": checks,
        }
        evaluated.append(row)
        if all(checks.values()):
            evidence = group.copy()
            evidence["previous_close"] = evidence["close"].shift()
            evidence["joint_up"] = joint
            evidence["change_pct"] = (evidence["close"] / evidence["previous_close"] - 1) * 100
            cols = ["date", "open", "high", "low", "close", "previous_close", "change_pct", "joint_up",
                    "raw_open", "raw_high", "raw_low", "raw_close", "adj_factor", "base_factor", "vol", "amount"]
            rows.append({**row, "daily_evidence": evidence.iloc[1:][cols].to_dict("records")})
    return {
        "request": request.model_dump(mode="json"),
        "as_of": as_of, "window_start": dates[1], "previous_session": dates[0],
        "adjustment": "raw_price * adj_factor / adj_factor_at_as_of",
        "coverage": {"universe": len(universe), "evaluated": len(evaluated), "matched": len(rows),
                     "excluded": len(excluded), "excluded_reasons": dict(Counter(x["reason"] for x in excluded)),
                     "exchanges": universe.groupby("exchange").size().to_dict()},
        "condition_counts": {key: sum(r["checks"][key] for r in evaluated)
                             for key in ("joint_up_days", "low_within", "above_low", "max_position")},
        "rows": rows, "evaluated_rows": evaluated, "excluded": excluded,
    }


def run_ohlc_screen(request: OhlcScreenRequest, *, refresh: bool = False) -> dict:
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.ohlc_history import (
        load_adjusted_history,
        load_mainboard_universe,
        load_session_dates,
    )
    from kan.render.base import DISCLAIMER, FIND_DISCLAIMER_TEXT

    if request.as_of > latest_trade_date():
        raise ValueError("--as-of 不能晚于最近已完成收盘的交易日")
    # 当前上市名单不能冒充历史时点的股票池。
    if request.as_of != latest_trade_date():
        raise ValueError("当前入口仅支持最近完整交易日；历史复核需保留当时股票池与原始证据")
    universe = load_mainboard_universe()
    dates = load_session_dates(request.as_of, request.period + 1)
    panel = load_adjusted_history(dates, refresh=refresh)
    result = evaluate_ohlc_screen(request, universe, panel, dates)
    return {"ok": True, "schema_version": 1, "command": "screen ohlc",
            "sources": ["TuShare stock_basic", "TuShare trade_cal SSE/SZSE", "TuShare daily", "TuShare adj_factor"],
            "queried_at": datetime.now().astimezone().isoformat(),
            "disclaimer": f"{DISCLAIMER.strip()}\n{FIND_DISCLAIMER_TEXT}",
            **result}
