"""盘中实时价解析和 fallback 测试。"""
from __future__ import annotations


def test_sina_realtime_parser(monkeypatch) -> None:
    from kan.data import realtime

    fields = [""] * 32
    fields[0] = "贵州茅台"
    fields[2] = "1670.00"
    fields[3] = "1688.88"
    fields[30] = "2026-06-06"
    fields[31] = "10:30:00"
    text = f'var hq_str_sh600519="{",".join(fields)}";'

    monkeypatch.setattr(realtime, "_request_text", lambda *_args, **_kw: text)

    quotes = realtime._fetch_sina(["600519"])

    quote = quotes["600519"]
    assert quote.name == "贵州茅台"
    assert quote.price == 1688.88
    assert quote.prev_close == 1670.0
    assert quote.source == "sina_realtime"
    assert quote.trade_time == "2026-06-06 10:30:00"


def test_tencent_realtime_parser_marks_suspended(monkeypatch) -> None:
    from kan.data import realtime

    fields = [""] * 31
    fields[1] = "五粮液"
    fields[3] = "0.00"
    fields[4] = "150.50"
    fields[30] = "20260606103000"
    text = f'v_sz000858="{"~".join(fields)}";'

    monkeypatch.setattr(realtime, "_request_text", lambda *_args, **_kw: text)

    quotes = realtime._fetch_tencent(["000858"])

    quote = quotes["000858"]
    assert quote.price == 150.5
    assert quote.prev_close == 150.5
    assert quote.status == "suspended"
    assert quote.source == "tencent_realtime"


def test_fetch_realtime_quotes_uses_tencent_fallback(monkeypatch) -> None:
    from kan.data import realtime

    realtime._cache.clear()
    monkeypatch.setattr(realtime, "_fetch_sina", lambda symbols: {})
    monkeypatch.setattr(
        realtime,
        "_fetch_tencent",
        lambda symbols: {
            symbols[0]: realtime.RealtimeQuote(
                symbol=symbols[0],
                name="贵州茅台",
                price=1688.88,
                prev_close=1670.0,
                source="tencent_realtime",
            )
        },
    )

    quotes = realtime.fetch_realtime_quotes(["600519"])

    assert quotes["600519"].source == "tencent_realtime"
