"""散户体验事实字段。

本模块只做客观计算和代码段识别，不输出交易动作、评分或建议。
"""
from __future__ import annotations


def lot_cost(price: float | None) -> float | None:
    """A 股一手金额 · 默认 100 股。"""
    if price is None:
        return None
    return round(price * 100, 2)


def cash_usage_pct(price: float | None, cash: float | None) -> float | None:
    """一手金额占已配置现金比例。"""
    if price is None or cash is None or cash <= 0:
        return None
    cost = lot_cost(price)
    if cost is None:
        return None
    return round(cost / cash * 100, 2)


def market_board(symbol: str) -> str:
    """按 A 股代码段返回交易板块事实。"""
    code = symbol.strip()
    if code.startswith(("920", "83", "43", "87", "82")):
        return "北交所"
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith("30"):
        return "创业板"
    if code.startswith(("900", "200")):
        return "B股"
    if code.startswith(("60", "00")):
        return "主板"
    return "未识别"


def permission_note(symbol: str) -> str | None:
    """交易权限客观提示 · 不表达能否或是否应该交易。"""
    board = market_board(symbol)
    if board == "科创板":
        return "需科创板权限"
    if board == "北交所":
        return "需北交所权限"
    if board == "创业板":
        return "需创业板权限"
    if board == "B股":
        return "B股权限/账户"
    return None


def volume_price_state(
    *,
    volume_ratio: float | None,
    close: float | None,
    prev_close: float | None,
) -> tuple[str | None, str | None]:
    """返回 (收盘方向, 量价事实组合)。"""
    if close is None or prev_close is None or prev_close <= 0:
        return None, None
    if close > prev_close:
        direction = "收涨"
    elif close < prev_close:
        direction = "收跌"
    else:
        direction = "收平"
    if volume_ratio is None:
        return direction, None
    if volume_ratio >= 1.5:
        volume = "量增"
    elif volume_ratio <= 0.67:
        volume = "量缩"
    else:
        volume = "量平"
    return direction, f"{volume}·{direction}"


def apply_retail_facts(result, *, cash: float | None = None):
    """给 StockScanResult 或 EnrichedResult 补纯事实字段。"""
    return result.model_copy(update={
        "lot_cost": lot_cost(result.current_price),
        "cash_usage_pct": cash_usage_pct(result.current_price, cash),
        "market_board": market_board(result.symbol),
        "permission_note": permission_note(result.symbol),
    })


def exclude_by_permission(
    pairs: list[tuple[str, str]], *, exclude_star: bool = False, exclude_bj: bool = False,
) -> list[tuple[str, str]]:
    """按权限板块过滤候选池。"""
    if not exclude_star and not exclude_bj:
        return pairs
    out: list[tuple[str, str]] = []
    for symbol, name in pairs:
        board = market_board(symbol)
        if exclude_star and board == "科创板":
            continue
        if exclude_bj and board == "北交所":
            continue
        out.append((symbol, name))
    return out
