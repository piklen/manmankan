"""题材数据适配器单元测试。"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import pandas as pd
import pytest
import requests

from kan.core.models import Theme
from kan.data import concepts


@pytest.fixture(autouse=True)
def _reset_em_code_map(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(concepts, "_em_code_by_name", None)


def test_quiet_call_returns_value_and_suppresses_output(capsys):
    def noisy(value: int) -> int:
        print("noise")
        return value

    assert concepts._quiet_call(noisy, 7) == 7
    assert capsys.readouterr().out == ""


def test_fetch_theme_catalog_normalizes_columns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys.modules["akshare"], "stock_board_concept_name_ths",
        lambda: pd.DataFrame([{"code": "301558", "name": "阿里巴巴概念"}]),
    )

    frame = concepts.fetch_theme_catalog()

    assert frame is not None
    assert frame.to_dict("records") == [{"code": "301558", "name": "阿里巴巴概念"}]


@pytest.mark.parametrize("raw", [None, pd.DataFrame()])
def test_fetch_theme_catalog_preserves_empty(monkeypatch: pytest.MonkeyPatch, raw):
    monkeypatch.setattr(sys.modules["akshare"], "stock_board_concept_name_ths", lambda: raw)
    assert concepts.fetch_theme_catalog() is raw


def test_fetch_em_theme_catalog_normalizes_columns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys.modules["akshare"],
        "stock_board_concept_name_em",
        lambda: pd.DataFrame([{"板块代码": "BK1629", "板块名称": "AI应用", "排名": 1}]),
    )

    frame = concepts._fetch_em_theme_catalog()

    assert frame is not None
    assert frame.to_dict("records") == [{"code": "BK1629", "name": "AI应用"}]


def test_resolve_em_code_uses_code_or_cached_name(monkeypatch: pytest.MonkeyPatch):
    direct = Theme(code="BK1629", name="AI应用", source="em")
    assert concepts._resolve_em_code(direct) == "BK1629"

    calls = 0

    def catalog():
        nonlocal calls
        calls += 1
        return pd.DataFrame([{"code": "BK1629", "name": "AI应用"}])

    monkeypatch.setattr(concepts, "_fetch_em_theme_catalog", catalog)
    legacy = Theme(code="886108", name="AI应用", source="ths")
    assert concepts._resolve_em_code(legacy) == "BK1629"
    assert concepts._resolve_em_code(legacy) == "BK1629"
    assert calls == 1


def test_resolve_em_code_reports_missing_and_empty_catalog(monkeypatch: pytest.MonkeyPatch):
    legacy = Theme(code="886108", name="不存在", source="ths")
    monkeypatch.setattr(
        concepts,
        "_fetch_em_theme_catalog",
        lambda: pd.DataFrame([{"code": "BK1629", "name": "AI应用"}]),
    )
    with pytest.raises(LookupError, match="未找到"):
        concepts._resolve_em_code(legacy)

    monkeypatch.setattr(concepts, "_em_code_by_name", None)
    monkeypatch.setattr(concepts, "_fetch_em_theme_catalog", lambda: None)
    with pytest.raises(RuntimeError, match="清单为空"):
        concepts._resolve_em_code(legacy)


def test_fetch_ths_constituents_skips_non_ths_code():
    theme = Theme(code="BK1629", name="AI应用", source="em")
    assert concepts.fetch_ths_constituents(theme) is None


@dataclass
class _Response:
    text: str = ""
    payload: dict | None = None

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        assert self.payload is not None
        return self.payload


def test_fetch_ths_constituents_parses_pages(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "page/1": """
          <span class="page_info">1/2</span><table><tr><th>x</th></tr>
          <tr><td>1</td><td>600519</td><td>贵州茅台</td></tr></table>
        """,
        "page/2": """
          <span class="page_info">2/2</span><table><tr><th>x</th></tr>
          <tr><td>2</td><td>000858</td><td>五粮液</td></tr></table>
        """,
    }

    def fake_get(url: str, **_kwargs):
        key = "page/1" if "page/1" in url else "page/2"
        return _Response(text=pages[key])

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(concepts, "_ths_headers", lambda: {"User-Agent": "test"})
    theme = Theme(code="301558", name="阿里巴巴概念", source="ths")

    frame = concepts.fetch_ths_constituents(theme)

    assert frame is not None
    assert frame.to_dict("records") == [
        {"stock_code": "600519", "short_name": "贵州茅台"},
        {"stock_code": "000858", "short_name": "五粮液"},
    ]


def test_fetch_em_constituents_normalizes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys.modules["akshare"],
        "stock_board_concept_cons_em",
        lambda **_kwargs: pd.DataFrame([{"代码": "600519", "名称": "贵州茅台", "最新价": 1}]),
    )
    theme = Theme(code="BK1629", name="AI应用", source="em")

    frame = concepts.fetch_em_constituents(theme)

    assert frame is not None
    assert frame.to_dict("records") == [{"stock_code": "600519", "short_name": "贵州茅台"}]


def test_fetch_em_constituents_preserves_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys.modules["akshare"], "stock_board_concept_cons_em", lambda **_kwargs: None,
    )
    theme = Theme(code="BK1629", name="AI应用", source="em")
    assert concepts.fetch_em_constituents(theme) is None


def test_fetch_em_kline_normalizes(monkeypatch: pytest.MonkeyPatch):
    raw = pd.DataFrame([{
        "日期": "2026-07-09",
        "开盘": 1,
        "最高": 2,
        "最低": 0.5,
        "收盘": 1.5,
        "成交量": 10,
        "成交额": 20,
    }])
    monkeypatch.setattr(
        sys.modules["akshare"], "stock_board_concept_hist_em", lambda **_kwargs: raw,
    )
    theme = Theme(code="BK1629", name="AI应用", source="em")

    frame = concepts.fetch_em_kline(theme)

    assert frame is not None
    assert {"trade_date", "open", "high", "low", "close", "volume", "amount"} <= set(frame.columns)


def test_fetch_em_kline_preserves_empty(monkeypatch: pytest.MonkeyPatch):
    empty = pd.DataFrame()
    monkeypatch.setattr(
        sys.modules["akshare"], "stock_board_concept_hist_em", lambda **_kwargs: empty,
    )
    theme = Theme(code="BK1629", name="AI应用", source="em")
    assert concepts.fetch_em_kline(theme) is empty


def test_fetch_stock_themes_normalizes_payload(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "success": True,
        "result": {
            "data": [{
                "SECURITY_CODE": "002230",
                "NEW_BOARD_CODE": "BK1629",
                "BOARD_NAME": "AI应用",
                "SELECTED_BOARD_REASON": "公开事实",
            }],
        },
    }
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: _Response(payload=payload))

    frame = concepts.fetch_stock_themes("002230")

    assert frame.to_dict("records") == [{
        "stock_code": "002230",
        "concept_code": "BK1629",
        "name": "AI应用",
        "source": "东方财富",
        "reason": "公开事实",
    }]


def test_fetch_stock_themes_handles_unsuccessful_payload(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *_args, **_kwargs: _Response(payload={"success": False}),
    )
    assert concepts.fetch_stock_themes("600519").empty
