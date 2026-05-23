"""F11 真网络冒烟 · 跑真 adata HTTP · 验证 spike 假设未回归。

默认 CI 跳过(用 -m "not network")。
本地开发 + daily cron 跑(用 -m network)。
"""
import pytest


@pytest.mark.network
def test_adata_ths_catalog_real():
    """adata THS catalog 应返回 ≥ 100 题材 · spike 当时 391 · 假设 ≥100 不破。"""
    import adata
    df = adata.stock.info.all_concept_code_ths()
    assert df is not None
    assert len(df) > 100
    assert "index_code" in df.columns
    assert "name" in df.columns


@pytest.mark.network
def test_adata_ths_concept_constituent_real():
    """adata THS 题材成分股(AI应用 886108) · 容忍数据源动态(0 行也接受 · 反爬时 graceful degradation)。"""
    import adata
    try:
        df = adata.stock.info.concept_constituent_ths(index_code="886108")
    except Exception as e:
        pytest.xfail(f"adata 数据源动态(反爬/endpoint 变):{type(e).__name__}: {e}")
    assert df is not None
    if len(df) > 0:
        assert "stock_code" in df.columns
        assert "short_name" in df.columns


@pytest.mark.network
def test_adata_em_kline_real():
    """adata EM 题材 K 线(AI应用 BK1629) · 容忍反爬 (RemoteDisconnected 是已知 spike 模式)。"""
    import adata
    try:
        df = adata.stock.market.get_market_concept_east(index_code="BK1629", k_type=1)
    except Exception as e:
        pytest.xfail(f"adata 数据源动态(反爬/endpoint 变):{type(e).__name__}: {e}")
    if df is None or len(df) == 0:
        pytest.xfail("EM K 线返空 · 数据源动态 · 不阻塞 CI")
    cols = set(df.columns)
    assert {"open", "high", "low", "close"} <= cols


@pytest.mark.network
def test_adata_em_reverse_real():
    """adata EM datacenter 个股反查(科大讯飞 002230) · 应返回 ≥ 5 题材 · 1s 内。"""
    import time

    import adata
    t0 = time.time()
    df = adata.stock.info.get_concept_east(stock_code="002230")
    elapsed = time.time() - t0
    assert df is not None
    assert len(df) > 5
    assert elapsed < 5.0  # spike 实测 0.18s · 网络抖动容忍
    assert "concept_code" in df.columns


@pytest.mark.network
def test_adata_arm64_py_mini_racer_known_issue():
    """记录 Apple Silicon arm64 的 py_mini_racer dylib 缺失 · 文档化已知问题。

    本测试不应阻塞 CI · 只在 arm64 darwin 上 expected fail。
    """
    import platform
    if not (platform.system() == "Darwin" and platform.machine() == "arm64"):
        pytest.skip("only relevant on Apple Silicon")

    import adata
    with pytest.raises((RuntimeError, AttributeError), match=r"libmini_racer|py_mini_racer|mr_eval_context"):
        adata.stock.market.get_market_concept_ths(index_code="886108", k_type=1)
