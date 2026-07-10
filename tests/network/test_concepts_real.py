"""题材适配器真网络冒烟，默认 CI 通过 `-m "not network"` 跳过。"""
import pytest

from kan.core.models import Theme
from kan.data.concepts import (
    fetch_em_constituents,
    fetch_em_kline,
    fetch_stock_themes,
    fetch_theme_catalog,
)


@pytest.mark.network
def test_concept_catalog_real():
    catalog = fetch_theme_catalog()
    assert catalog is not None
    assert len(catalog) > 100
    assert {"code", "name"} <= set(catalog.columns)


@pytest.mark.network
def test_em_concept_constituent_real():
    theme = Theme(code="BK1629", name="AI应用", source="em")
    try:
        frame = fetch_em_constituents(theme)
    except Exception as exc:
        pytest.xfail(f"题材成分数据源动态: {type(exc).__name__}: {exc}")
    assert frame is not None
    if not frame.empty:
        assert {"stock_code", "short_name"} <= set(frame.columns)


@pytest.mark.network
def test_em_concept_kline_real():
    theme = Theme(code="BK1629", name="AI应用", source="em")
    try:
        frame = fetch_em_kline(theme)
    except Exception as exc:
        pytest.xfail(f"题材 K 线数据源动态: {type(exc).__name__}: {exc}")
    if frame is None or frame.empty:
        pytest.xfail("题材 K 线返空")
    assert {"open", "high", "low", "close"} <= set(frame.columns)


@pytest.mark.network
def test_em_concept_reverse_real():
    frame = fetch_stock_themes("002230")
    assert len(frame) > 5
    assert "concept_code" in frame.columns
