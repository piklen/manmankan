"""web serializer 的 NaN/Inf 护栏回归测试。

背景:Starlette JSONResponse 用 allow_nan=False,任何 NaN/Inf 会在路由 return
之后的渲染阶段抛 ValueError → 500,且路由内 try/except 兜不住。上游数据层通常
已净化 NaN(_opt_float→None),但 web 序列化层必须自带对称护栏,不能依赖上游。
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from starlette.responses import JSONResponse

from kan.web import find_adapter, serialize

NAN = float("nan")
INF = float("inf")


def test_round_neutralizes_nan_inf() -> None:
    for fn in (serialize._round, find_adapter._round):
        assert fn(None) is None
        assert fn(NAN) is None
        assert fn(INF) is None
        assert fn(-INF) is None
        assert fn(1.234) == 1.23
        assert fn(1.234, 1) == 1.2


def _nan_info_result() -> SimpleNamespace:
    """构造一个数值字段全为 NaN 的 InfoServiceResult 替身。"""
    period = SimpleNamespace(
        period=30,
        insufficient=False,
        position_pct=NAN,
        at_low=False,
        at_high=False,
        n_low=NAN,
        n_high=NAN,
        gain_pct=NAN,
        distance_to_low_pct=NAN,
        distance_to_high_pct=NAN,
    )
    inner = SimpleNamespace(
        periods=[period],
        current_price=NAN,
        scan_date=None,
        low_resonance=0,
        high_resonance=0,
        volume_price_state=None,
        valuation_trade_date=None,
        pe_ttm=NAN,
        pb=NAN,
        ps_ttm=NAN,
        dv_ttm=NAN,
        turnover_rate=NAN,
        volume_ratio=NAN,
        total_mv=NAN,
        circ_mv=NAN,
    )
    volume = SimpleNamespace(window=5, ratio=NAN, label="量能平稳", state="量平")
    trend = SimpleNamespace(
        streak=0,
        streak_pct=NAN,
        direction=None,
        daily_changes=[("2026-07-01", NAN)],
    )
    return SimpleNamespace(
        symbol="600519",
        name="贵州茅台",
        result=inner,
        trend=trend,
        volume=volume,
        data_cutoff=None,
        fetched_at=None,
        stale=False,
        valuation=None,
    )


def test_serialize_info_neutralizes_nan_and_renders() -> None:
    payload = serialize.serialize_info(_nan_info_result())

    # 裸传三处 + period + valuation + price 全部归一成 None
    assert payload["price"] is None
    assert payload["change_pct"] is None
    assert payload["volume"]["ratio"] is None
    assert payload["trend"]["streak_pct"] is None
    assert payload["periods"][0]["position_pct"] is None
    assert payload["periods"][0]["gain_pct"] is None
    assert payload["valuation"]["pe_ttm"] is None

    # 决定性:护栏前这一步会抛 ValueError(allow_nan=False)→ 500
    body = JSONResponse(payload).body
    assert b"NaN" not in body
    assert b"Infinity" not in body


def test_payload_has_no_residual_nan() -> None:
    payload = serialize.serialize_info(_nan_info_result())

    def _walk(obj: object) -> None:
        if isinstance(obj, float):
            assert not math.isnan(obj) and not math.isinf(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(payload)


def test_serialize_board_context_uses_real_model_fields() -> None:
    """回归:/stock/{code} 曾 500 — serializer 读了模型上不存在的 stock_pct/rank。

    真实模型 BoardPositionPeriod 字段是 position_pct / rank_low_to_high / sample,
    模板契约键是 stock_pct / rank / rank_total · 映射错位即 AttributeError。
    """
    from kan.core.models import BoardPositionContext, BoardPositionPeriod

    ctx = BoardPositionContext(
        industry="食品饮料",
        board_code="801016",
        board_level=1,
        constituent_count=122,
        cached_sample=122,
        periods=[
            BoardPositionPeriod(
                period=30,
                position_pct=72.8,
                board_avg_pct=31.9,
                rank_low_to_high=118,
                sample=122,
            )
        ],
    )

    payload = serialize._serialize_board_context(ctx)

    assert payload["industry"] == "食品饮料"
    assert payload["periods"] == [
        {
            "period": 30,
            "stock_pct": 72.8,
            "board_avg_pct": 31.9,
            "rank": 118,
            "rank_total": 122,
        }
    ]
