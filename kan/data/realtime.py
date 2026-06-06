"""盘中实时价 · 新浪主源 + 腾讯 fallback。

实时价只服务持仓盈亏现价口径；位置/共振仍使用日 K 收盘价。
"""
from __future__ import annotations

import re
import time
import urllib.request
from dataclasses import dataclass

from kan.infra.log import debug_log

_CACHE_TTL_SECONDS = 5.0
_BATCH_SIZE = 80
_cache: dict[str, tuple[float, RealtimeQuote]] = {}


@dataclass(frozen=True)
class RealtimeQuote:
    symbol: str
    name: str
    price: float | None
    prev_close: float | None
    source: str
    trade_time: str | None = None
    status: str = "ok"


def _prefix(symbol: str) -> str:
    if symbol.startswith(("6", "9")):
        return "sh"
    if symbol.startswith(("8", "4")):
        return "bj"
    return "sz"


def _request_text(url: str, *, encoding: str = "gbk") -> str:
    from kan.data.fetcher import _ensure_no_proxy

    _ensure_no_proxy()
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read().decode(encoding, errors="ignore")


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _quote_from_values(
    *,
    symbol: str,
    name: str,
    price_raw: str,
    prev_raw: str,
    trade_time: str | None,
    source: str,
) -> RealtimeQuote:
    price = _to_float(price_raw)
    prev_close = _to_float(prev_raw)
    status = "ok"
    if price is None or price <= 0:
        price = prev_close
        status = "suspended" if price is not None else "missing"
    return RealtimeQuote(
        symbol=symbol,
        name=name,
        price=round(price, 2) if price is not None else None,
        prev_close=round(prev_close, 2) if prev_close is not None else None,
        source=source,
        trade_time=trade_time,
        status=status,
    )


def _to_float(value: str) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _fetch_sina(symbols: list[str]) -> dict[str, RealtimeQuote]:
    from kan.infra import circuit_breaker

    cb = circuit_breaker.get_breaker()
    if cb.is_down("sina_realtime"):
        return {}
    result: dict[str, RealtimeQuote] = {}
    try:
        for batch in _chunks(symbols, _BATCH_SIZE):
            ids = ",".join(f"{_prefix(s)}{s}" for s in batch)
            text = _request_text(f"https://hq.sinajs.cn/list={ids}")
            for line in text.splitlines():
                m = re.match(r'var hq_str_[a-z]+(?P<symbol>\d{6})="(?P<body>.*)";', line)
                if not m:
                    continue
                body = m.group("body")
                if not body:
                    continue
                fields = body.split(",")
                if len(fields) < 32:
                    continue
                symbol = m.group("symbol")
                result[symbol] = _quote_from_values(
                    symbol=symbol,
                    name=fields[0].strip() or symbol,
                    price_raw=fields[3],
                    prev_raw=fields[2],
                    trade_time=f"{fields[30]} {fields[31]}" if fields[30] else None,
                    source="sina_realtime",
                )
        cb.record("sina_realtime", ok=bool(result))
    except Exception as e:
        debug_log(__name__, "sina realtime fetch failed", e)
        cb.record("sina_realtime", ok=False)
        return {}
    return result


def _fetch_tencent(symbols: list[str]) -> dict[str, RealtimeQuote]:
    from kan.infra import circuit_breaker

    cb = circuit_breaker.get_breaker()
    if cb.is_down("tencent_realtime"):
        return {}
    result: dict[str, RealtimeQuote] = {}
    try:
        for batch in _chunks(symbols, _BATCH_SIZE):
            ids = ",".join(f"{_prefix(s)}{s}" for s in batch)
            text = _request_text(f"https://qt.gtimg.cn/q={ids}")
            for line in text.splitlines():
                m = re.match(r'v_[a-z]+(?P<symbol>\d{6})="(?P<body>.*)";', line)
                if not m:
                    continue
                fields = m.group("body").split("~")
                if len(fields) < 5:
                    continue
                symbol = m.group("symbol")
                trade_time = fields[30] if len(fields) > 30 else None
                result[symbol] = _quote_from_values(
                    symbol=symbol,
                    name=fields[1].strip() or symbol,
                    price_raw=fields[3],
                    prev_raw=fields[4],
                    trade_time=trade_time,
                    source="tencent_realtime",
                )
        cb.record("tencent_realtime", ok=bool(result))
    except Exception as e:
        debug_log(__name__, "tencent realtime fetch failed", e)
        cb.record("tencent_realtime", ok=False)
        return {}
    return result


def fetch_realtime_quotes(symbols: list[str]) -> dict[str, RealtimeQuote]:
    """批量获取实时价；缓存几秒，主源缺口由腾讯补齐。"""
    now = time.monotonic()
    out: dict[str, RealtimeQuote] = {}
    missing: list[str] = []
    for symbol in symbols:
        cached = _cache.get(symbol)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            out[symbol] = cached[1]
        else:
            missing.append(symbol)
    if missing:
        primary = _fetch_sina(missing)
        remain = [s for s in missing if s not in primary]
        fallback = _fetch_tencent(remain) if remain else {}
        for symbol, quote in {**primary, **fallback}.items():
            _cache[symbol] = (now, quote)
            out[symbol] = quote
    return out
