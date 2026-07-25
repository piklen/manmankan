"""市场情绪服务 · 提供全市场涨跌、涨停跌停、中位位置等概览数据。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketSentiment:
    """市场情绪数据。"""

    ok: bool
    up_count: int | None = None
    down_count: int | None = None
    flat_count: int | None = None
    limit_up: int | None = None
    limit_down: int | None = None
    median_position_180: float | None = None
    trade_date: str | None = None
    error: str | None = None


def get_market_sentiment() -> MarketSentiment:
    """获取市场情绪数据 · 只读本地缓存，不触发网络请求。"""
    try:
        from kan.data.kline_snapshot import fetch_kline_snapshot

        # 尝试读取最近的全市场快照
        df = fetch_kline_snapshot(force=False)
        if df is None or df.empty:
            return MarketSentiment(ok=False, error="本地没有全市场数据，请先更新")

        # 计算涨跌家数
        if "change_pct" in df.columns:
            up_count = int((df["change_pct"] > 0).sum())
            down_count = int((df["change_pct"] < 0).sum())
            flat_count = int((df["change_pct"] == 0).sum())
        else:
            up_count = down_count = flat_count = None

        # 计算涨停跌停（简化：涨跌幅 >= 9.8% 视为涨停，<= -9.8% 视为跌停）
        if "change_pct" in df.columns:
            limit_up = int((df["change_pct"] >= 9.8).sum())
            limit_down = int((df["change_pct"] <= -9.8).sum())
        else:
            limit_up = limit_down = None

        # 计算 180 日中位位置
        if "pos_180" in df.columns:
            pos_series = df["pos_180"].dropna()
            median_position_180 = round(float(pos_series.median()), 1) if len(pos_series) > 0 else None
        else:
            median_position_180 = None

        # 交易日期
        trade_date = None
        if "trade_date" in df.columns and len(df) > 0:
            trade_date = str(df["trade_date"].iloc[0])

        return MarketSentiment(
            ok=True,
            up_count=up_count,
            down_count=down_count,
            flat_count=flat_count,
            limit_up=limit_up,
            limit_down=limit_down,
            median_position_180=median_position_180,
            trade_date=trade_date,
        )
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "market sentiment unavailable", e)
        return MarketSentiment(ok=False, error="市场数据暂不可用")


def serialize_market_sentiment(sentiment: MarketSentiment) -> dict[str, Any]:
    """序列化市场情绪数据。"""
    return {
        "ok": sentiment.ok,
        "up_count": sentiment.up_count,
        "down_count": sentiment.down_count,
        "flat_count": sentiment.flat_count,
        "limit_up": sentiment.limit_up,
        "limit_down": sentiment.limit_down,
        "median_position_180": sentiment.median_position_180,
        "trade_date": sentiment.trade_date,
        "error": sentiment.error,
    }
