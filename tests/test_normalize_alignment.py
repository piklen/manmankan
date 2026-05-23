"""三源 normalize 语义一致性测试 · 东财 / baostock / 腾讯

目的：保证三个数据源经 `_normalize_kline()` 出口后语义一致。

背景：2026-05-10 实战发现 P0 bug —— 腾讯 `stock_zh_a_hist_tx` 返回的 "amount"
字段实际上是「成交手数」（= volume in 股 ÷ 100），不是真 amount。本测试用
mock fixture 复现该问题，并以 xfail 标记锚定未来 _fetch_tencent 修复目标。

参考真实数据（贵州茅台 600519 · 2026-05-08）：
- baostock: volume=3336853 股 · amount=4582855939.26 元 · close=1372.99
- 腾讯:    raw_amount=33369 (= 3336853/100 ≈ 33368.53 手) · close=1372.99

所有 fixture 不依赖网络，CI-safe。
"""

from __future__ import annotations

import pandas as pd
import pytest

from kan.data import fetcher
from kan.data.fetcher import KLINE_COLUMNS, _normalize_kline
from kan.data.sources import _EM_COLUMN_MAP

# ── Fixture：同一交易日同一只股票 (600519 · 2026-05-08) ─────────────────
# 三份 raw 来自三个源各自的 schema · 进 _normalize_kline 前形态各异

REF_DATE = "2026-05-08"
REF_CLOSE = 1372.99
REF_OPEN = 1370.00
REF_HIGH = 1378.50
REF_LOW = 1365.00
REF_VOLUME_SHARES = 3336853  # 股
REF_AMOUNT_YUAN = 4582855939.26  # 元
REF_VOLUME_LOTS = REF_VOLUME_SHARES // 100  # 33368 手 ≈ 腾讯 raw_amount


@pytest.fixture
def eastmoney_raw() -> pd.DataFrame:
    """东方财富原始 schema：中文列 + 额外列（振幅/涨跌幅）· 数值类型已是 float/int"""
    return pd.DataFrame({
        "日期": ["2026-05-07", REF_DATE],
        "开盘": [1365.00, REF_OPEN],
        "收盘": [1369.50, REF_CLOSE],
        "最高": [1372.00, REF_HIGH],
        "最低": [1360.00, REF_LOW],
        "成交量": [3100000, REF_VOLUME_SHARES],  # 股
        "成交额": [4.25e9, REF_AMOUNT_YUAN],  # 元
        "振幅": [0.88, 0.99],  # 额外列 · normalize 应丢弃
        "涨跌幅": [0.5, 0.25],
    })


@pytest.fixture
def baostock_raw() -> pd.DataFrame:
    """baostock 原始 schema：英文列 + 全字符串值（baostock 协议特性）"""
    return pd.DataFrame(
        [
            ["2026-05-07", "1365.0000", "1372.0000", "1360.0000", "1369.5000", "3100000", "4250000000.000000"],
            [REF_DATE, f"{REF_OPEN:.4f}", f"{REF_HIGH:.4f}", f"{REF_LOW:.4f}", f"{REF_CLOSE:.4f}",
             str(REF_VOLUME_SHARES), f"{REF_AMOUNT_YUAN:.6f}"],
        ],
        columns=["date", "open", "high", "low", "close", "volume", "amount"],
    )


@pytest.fixture
def tencent_raw() -> pd.DataFrame:
    """腾讯原始 schema：英文列 · ⚠️ amount 字段实际是「成交手数」（P0 bug）

    没有独立 volume 列。fetcher.py 当前未做转换 · 直接交给 _normalize_kline · 出口语义错。
    """
    return pd.DataFrame({
        "date": ["2026-05-07", REF_DATE],
        "open": [1365.00, REF_OPEN],
        "close": [1369.50, REF_CLOSE],
        "high": [1372.00, REF_HIGH],
        "low": [1360.00, REF_LOW],
        # ⚠️ 这里的 "amount" 实际是手数 = volume_shares / 100
        "amount": [3100000 // 100, REF_VOLUME_LOTS],
    })


# ── 测试 1: 东财 normalize 后 volume 单位是股 / amount 是元 ──────────────


def test_eastmoney_normalized_volume_unit(eastmoney_raw: pd.DataFrame):
    renamed = eastmoney_raw.rename(columns=_EM_COLUMN_MAP)
    df = _normalize_kline(renamed)

    assert list(df.columns) == KLINE_COLUMNS
    assert len(df) == 2
    row = df[df["date"] == pd.to_datetime(REF_DATE).date()].iloc[0]

    # volume = 股数 · amount = 元 · 完全一致
    assert row["volume"] == pytest.approx(REF_VOLUME_SHARES, rel=1e-9)
    assert row["amount"] == pytest.approx(REF_AMOUNT_YUAN, rel=1e-9)
    assert row["close"] == pytest.approx(REF_CLOSE, rel=1e-9)
    # 额外列 (振幅/涨跌幅) 必须被丢弃
    assert "振幅" not in df.columns
    assert "涨跌幅" not in df.columns


# ── 测试 2: baostock str→float 后精度足够 ──────────────────────────────


def test_baostock_normalized_str_to_float_precision(baostock_raw: pd.DataFrame):
    df = _normalize_kline(baostock_raw)

    # date 是 datetime.date · 数值列是 numeric（pandas 对纯整数字符串会推成 int64，浮点为 float64）
    assert df["close"].dtype == "float64"
    assert pd.api.types.is_numeric_dtype(df["volume"])
    assert pd.api.types.is_numeric_dtype(df["amount"])

    row = df[df["date"] == pd.to_datetime(REF_DATE).date()].iloc[0]

    # str→float 精度 · 不能丢失关键小数位
    assert row["close"] == pytest.approx(REF_CLOSE, rel=1e-9)
    assert row["open"] == pytest.approx(REF_OPEN, rel=1e-9)
    assert row["high"] == pytest.approx(REF_HIGH, rel=1e-9)
    assert row["low"] == pytest.approx(REF_LOW, rel=1e-9)
    assert row["volume"] == pytest.approx(REF_VOLUME_SHARES, rel=1e-9)
    assert row["amount"] == pytest.approx(REF_AMOUNT_YUAN, rel=1e-6)  # str 截断到 6 位小数


# ── 测试 3: G1 修复后腾讯不污染 amount/volume · 保守 drop 策略 ──────────


def test_tencent_drops_amount_to_avoid_cross_board_unit_mismatch(tencent_raw: pd.DataFrame):
    """G1 修复（2026-05-10）· R1 扩展验证发现腾讯 amount 字段语义跨板块不一致：
    - 主板/创业板：amount 实际是「成交手数」（= shares / 100）
    - 科创板（688/689）：amount 实际是「成交股数」（1:1）

    既然单位不可移植 · _fetch_tencent 改为保守 drop amount 列 ·
    让 _normalize_kline 把 amount 和 volume 都填 NaN ·
    下游看到 NaN 跳过相关计算 · 比错值更安全。
    """
    from unittest.mock import patch

    with patch("akshare.stock_zh_a_hist_tx", return_value=tencent_raw):
        raw = fetcher._fetch_tencent("600519", "20260501")

    assert raw is not None
    assert "amount" not in raw.columns, "腾讯 fallback 必须 drop 'amount' 字段"

    df = _normalize_kline(raw)
    row = df[df["date"] == pd.to_datetime(REF_DATE).date()].iloc[0]
    # G1 修复后期望：amount/volume 都 NaN · 价格列仍正常
    assert pd.isna(row["amount"]), "G1 修复后腾讯路径 amount 应为 NaN（不污染缓存）"
    assert pd.isna(row["volume"]), "G1 修复后腾讯路径 volume 应为 NaN（避免反推误差）"
    assert row["close"] == pytest.approx(REF_CLOSE, rel=1e-9), "价格列必须可信"


# ── 测试 4: 三源同一天 close 数值一致 ──────────────────────────────────


def test_three_sources_close_alignment(
    eastmoney_raw: pd.DataFrame,
    baostock_raw: pd.DataFrame,
    tencent_raw: pd.DataFrame,
):
    em_df = _normalize_kline(eastmoney_raw.rename(columns=_EM_COLUMN_MAP))
    bs_df = _normalize_kline(baostock_raw)
    tx_df = _normalize_kline(tencent_raw)

    target = pd.to_datetime(REF_DATE).date()

    em_close = em_df.loc[em_df["date"] == target, "close"].iloc[0]
    bs_close = bs_df.loc[bs_df["date"] == target, "close"].iloc[0]
    tx_close = tx_df.loc[tx_df["date"] == target, "close"].iloc[0]

    # 同日 close 三源差异 < 0.5%
    closes = [em_close, bs_close, tx_close]
    spread = (max(closes) - min(closes)) / min(closes)
    assert spread < 0.005, f"三源 close 偏差过大: {closes}"

    # 也校验 high/low 一致
    em_row = em_df[em_df["date"] == target].iloc[0]
    bs_row = bs_df[bs_df["date"] == target].iloc[0]
    assert em_row["high"] == pytest.approx(bs_row["high"], rel=1e-6)
    assert em_row["low"] == pytest.approx(bs_row["low"], rel=1e-6)


# ── 测试 5: dropna + 缺失列填 NaN ──────────────────────────────────────


def test_normalize_drops_invalid_rows():
    """close=NaN 或 date=invalid 的行必须被丢弃；缺失 optional 列必须补 NaN"""
    raw = pd.DataFrame({
        "date": ["2026-05-06", "not-a-date", "2026-05-08"],
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100.5, 101.5, None],  # 第 3 行 close 为 NaN
        # 故意不给 volume / amount —— 应该自动补 NaN 列
    })
    df = _normalize_kline(raw)

    # 只剩一行：date=invalid 被 to_datetime 转 NaT 后 dropna 丢弃；close=NaN 也丢弃
    assert len(df) == 1
    assert df["date"].iloc[0] == pd.to_datetime("2026-05-06").date()

    # volume / amount 必须存在且为 NaN
    assert "volume" in df.columns
    assert "amount" in df.columns
    assert pd.isna(df["volume"].iloc[0])
    assert pd.isna(df["amount"].iloc[0])


# ── 测试 6: 缺 required 列要 raise ─────────────────────────────────────


@pytest.mark.parametrize("missing", ["date", "open", "high", "low", "close"])
def test_required_column_missing_raises(missing: str):
    full = {
        "date": ["2026-05-08"],
        "open": [100], "high": [101], "low": [99], "close": [100.5],
    }
    full.pop(missing)
    raw = pd.DataFrame(full)

    with pytest.raises(ValueError, match=f"必需列: {missing}"):
        _normalize_kline(raw)
