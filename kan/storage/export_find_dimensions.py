"""find JSON 的维度字段公开转换。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.models import (
        ChipMetrics,
        FundamentalMetrics,
        MoneyflowMetrics,
        RelativeStrengthMetrics,
        SentimentMetrics,
        ShareholderMetrics,
        TechnicalMetrics,
        ValuationMetrics,
    )

def _valuation_public_dict(v: ValuationMetrics | None) -> dict | None:
    """ValuationMetrics → 对外 JSON。

    合规 (compliance §2/§7):
    - 量价 / 市值客观事实 (close / turnover_rate / volume_ratio / total_mv / circ_mv)
      + 估值裸值 (pe_ttm / pb / ps_ttm / dv_ttm) 一并输出。
    - 放开理由:filter 由用户显式指定 (--pe 是用户主导的数据筛选 · 非工具荐股) ·
      行业分位主观性强 (回看窗口 / 行业划分皆为选择) · 裸值反而客观 (项目决策)。
    - 仍守:不评分 / 不评级 / 不判断词 (compliance §3 黑名单 · find JSON 守护测试不动)。
    """
    if v is None:
        return None
    return {
        "trade_date": v.trade_date.isoformat() if v.trade_date else None,
        "close": v.close,
        "pe_ttm": v.pe_ttm,
        "pb": v.pb,
        "ps_ttm": v.ps_ttm,
        "dv_ttm": v.dv_ttm,
        "turnover_rate": v.turnover_rate,
        "volume_ratio": v.volume_ratio,
        "total_mv": v.total_mv,
        "circ_mv": v.circ_mv,
        "source": v.source,
    }


def _fundamentals_public_dict(f: FundamentalMetrics | None) -> dict | None:
    """FundamentalMetrics → 对外 JSON (估值/质量/资金维度 · ROE/增速裸值)。

    合规 (compliance §7):ROE / 增速是单向正向因子 (无"贵/便宜"双向误导)· 原始
    指标名 · 不评分 / 不判断词 · 裸值可出 (用户主导 --roe filter)。
    """
    if f is None:
        return None
    return {
        "end_date": f.end_date.isoformat() if f.end_date else None,
        "roe": f.roe,
        "netprofit_yoy": f.netprofit_yoy,
        "or_yoy": f.or_yoy,
        "source": f.source,
    }


def _moneyflow_public_dict(m: MoneyflowMetrics | None) -> dict | None:
    """MoneyflowMetrics → 对外 JSON (估值/质量/资金维度 · 主力净额裸值)。

    合规 (compliance §2):主力净额是客观资金事实 (同 OHLCV 安全区)· 裸值可出。
    """
    if m is None:
        return None
    return {
        "trade_date": m.trade_date.isoformat() if m.trade_date else None,
        "net_amount": m.net_amount,
        "buy_elg_amount": m.buy_elg_amount,
        "buy_lg_amount": m.buy_lg_amount,
        "buy_md_amount": m.buy_md_amount,
        "buy_sm_amount": m.buy_sm_amount,
        "inflow_days": m.inflow_days,
        "outflow_days": m.outflow_days,
        "net_amount_5d": m.net_amount_5d,
        "source": m.source,
    }


def _technical_public_dict(t: TechnicalMetrics | None) -> dict | None:
    """TechnicalMetrics → 对外 JSON (技术/情绪/筹码维度 · 前复权技术指标裸值)。

    合规 (compliance §3/§7):原始指标名 (macd/kdj/rsi/ma/boll) · 不输出"超买/超卖/
    金叉/死叉"判断词 · 只出裸值。filter 阈值用户主导 (--rsi 等)。
    """
    if t is None:
        return None
    return {
        "trade_date": t.trade_date.isoformat() if t.trade_date else None,
        "close": t.close,
        "macd_dif": t.macd_dif,
        "macd_dea": t.macd_dea,
        "macd": t.macd,
        "kdj_k": t.kdj_k,
        "kdj_d": t.kdj_d,
        "kdj_j": t.kdj_j,
        "rsi_6": t.rsi_6,
        "rsi_12": t.rsi_12,
        "rsi_24": t.rsi_24,
        "ma_5": t.ma_5,
        "ma_10": t.ma_10,
        "ma_20": t.ma_20,
        "ma_60": t.ma_60,
        "atr": t.atr,
        "atr_pct": t.atr_pct(),
        "ma_bias": {
            "5": t.ma_bias(5),
            "10": t.ma_bias(10),
            "20": t.ma_bias(20),
            "60": t.ma_bias(60),
        },
        "boll_upper": t.boll_upper,
        "boll_mid": t.boll_mid,
        "boll_lower": t.boll_lower,
        "source": t.source,
    }


def _sentiment_public_dict(s: SentimentMetrics | None) -> dict | None:
    """SentimentMetrics → 对外 JSON (技术/情绪/筹码维度 · 连板/炸板裸值)。

    合规 (compliance §2/§3):连板天数 / 炸板次数是客观市场事实 · 不输出"妖股/强势"
    判断词。s 为 None = 该股当日未涨跌停 (稀疏事件型 · 见 SentimentMetrics)。
    """
    if s is None:
        return None
    return {
        "trade_date": s.trade_date.isoformat() if s.trade_date else None,
        "limit_times": s.limit_times,
        "open_times": s.open_times,
        "first_time": s.first_time,
        "last_time": s.last_time,
        "fd_amount": s.fd_amount,
        "limit": s.limit,
        "up_stat": s.up_stat,
        "source": s.source,
    }


def _chip_public_dict(c: ChipMetrics | None) -> dict | None:
    """ChipMetrics → 对外 JSON (技术/情绪/筹码维度 · 获利盘/成本分布裸值)。

    合规 (compliance §2/§7):获利盘比例 / 成本分位是客观计算值 · 不输出判断词。
    """
    if c is None:
        return None
    return {
        "trade_date": c.trade_date.isoformat() if c.trade_date else None,
        "winner_rate": c.winner_rate,
        "cost_5pct": c.cost_5pct,
        "cost_50pct": c.cost_50pct,
        "cost_95pct": c.cost_95pct,
        "weight_avg": c.weight_avg,
        "source": c.source,
    }


def _shareholder_public_dict(s: ShareholderMetrics | None) -> dict | None:
    """ShareholderMetrics → 对外 JSON (股东持股维度 · 户数环比/集中度/北向裸值)。

    合规 (compliance §7 股东持股维度 守则):户数环比 / 前十大流通集中度 / 北向占比是已披露
    客观事实衍生 · 不输出"主力建仓/洗盘/控盘/高度控盘"判断词。季度披露 · 各字段独立
    可空 (未披露 / 未进前十 → None)。北向用"香港中央结算"季度名义持有人代理。
    """
    if s is None:
        return None
    return {
        "holder_end_date": s.holder_end_date.isoformat() if s.holder_end_date else None,
        "holder_num": s.holder_num,
        "holder_chg_pct": s.holder_chg_pct,
        "top10_end_date": s.top10_end_date.isoformat() if s.top10_end_date else None,
        "top10_float_ratio": s.top10_float_ratio,
        "north_hold_ratio": s.north_hold_ratio,
        "source": s.source,
    }

def _relative_strength_public_dict(rs: RelativeStrengthMetrics | None) -> dict | None:
    """RelativeStrengthMetrics → 对外 JSON (个股 − 对照 区间涨幅差 · 客观裸值)。

    合规 (compliance §6/§7):相对强度是两段客观涨幅的算术差 · 裸值可出 · 不输出
    强弱/龙头判断词。周期 dict 的 int key 转 str (JSON 对象 key 须为字符串 · 同 context)。
    """
    if rs is None:
        return None

    def _by_period(d: dict[int, float]) -> dict[str, float]:
        return {str(k): v for k, v in d.items()}

    return {
        "industry": rs.industry,
        "index_code": rs.index_code,
        "index_name": rs.index_name,
        "stock_gain": _by_period(rs.stock_gain),
        "index_gain": _by_period(rs.index_gain),
        "board_gain": _by_period(rs.board_gain),
        "rs_index": _by_period(rs.rs_index),
        "rs_board": _by_period(rs.rs_board),
        "source": rs.source,
    }
