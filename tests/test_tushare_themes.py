"""kan.data.tushare_themes 单元测试 · 历史背景。

覆盖:
- tushare_token_configured · token / endpoint 解析
- tushare_load_theme_catalog · API 成功 / 失败 / 数据空 / cache 命中
- tushare_load_theme_klines · batch 拉历史 + group by · 部分天失败容忍
- load_theme_leaderboard TuShare 路径分支 · token 配了走 tushare · 没配走 em
"""
from __future__ import annotations

import pytest

from kan.core.models import Theme


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from kan.data import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.data.tushare_themes.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.storage.paths.ensure_dirs", lambda: None)
    return tmp_path


# ── tushare_token_configured ───────────────────────────────────────────


def test_token_not_configured(monkeypatch):
    from kan.data import tushare_themes

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr("kan.data.tushare_themes._resolve_config", lambda: (None, "https://api.tushare.pro"))
    assert tushare_themes.tushare_token_configured() is False


def test_token_configured_via_env(monkeypatch):
    from kan.data import tushare_themes

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config",
        lambda: ("fake-token-1234", "https://api.tushare.pro"),
    )
    assert tushare_themes.tushare_token_configured() is True


# ── tushare_load_theme_catalog ─────────────────────────────────────────


def test_catalog_returns_none_when_no_token(monkeypatch):
    """未配 token: (None, None) · 不算错误 · caller 走 attempted=False 路径。"""
    from kan.data import tushare_themes

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: (None, "http://e"),
    )
    data, err = tushare_themes.tushare_load_theme_catalog()
    assert data is None
    assert err is None  # 未配 token 不是 error


def test_catalog_returns_error_when_api_fails(monkeypatch):
    """背景: API 失败返 (None, TushareApiError) · server msg 透传。"""
    from kan.data import tushare_themes
    from kan.data.tushare import TushareApiError

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes._post_tushare_api",
        lambda *a, **kw: (None, TushareApiError(code=40101, msg="您的token不对", api_name="ths_index")),
    )
    data, err = tushare_themes.tushare_load_theme_catalog()
    assert data is None
    assert err is not None
    assert err.code == 40101
    assert "token不对" in err.msg


def test_catalog_success_strips_ti_suffix(monkeypatch):
    """ts_code '886108.TI' 应被 strip 成纯数字 '886108'。"""
    from kan.data import tushare_themes

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes._post_tushare_api",
        lambda *a, **kw: ({
            "fields": ["ts_code", "name", "count", "exchange"],
            "items": [
                ["886108.TI", "AI应用", 156, "A"],
                ["886112.TI", "数据要素", 88, "A"],
            ],
        }, None),
    )
    catalog, err = tushare_themes.tushare_load_theme_catalog()
    assert err is None
    assert catalog is not None
    assert len(catalog) == 2
    assert catalog[0].code == "886108"  # 已 strip
    assert catalog[0].name == "AI应用"
    assert catalog[0].source == "tushare"
    assert catalog[0].size == 156


def test_catalog_requests_concept_type_and_rejects_industry_rows(monkeypatch):
    """题材 catalog 必须请求 N 概念，且本地拒绝兼容端点混入的 I 行业。"""
    from kan.data import tushare_themes

    captured = {}
    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )

    def fake_post(endpoint, token, *, api_name, params, fields):
        captured.update({"api_name": api_name, "params": params, "fields": fields})
        return ({
            "fields": ["ts_code", "name", "count", "exchange", "type"],
            "items": [
                ["885881.TI", "云办公", 29, "A", "N"],
                ["700676.TI", "化学纤维制造业指数", 88, "A", "I"],
                ["885999.TI", "港股概念", 20, "HK", "N"],
            ],
        }, None)

    monkeypatch.setattr("kan.data.tushare_themes._post_tushare_api", fake_post)

    catalog, err = tushare_themes.tushare_load_theme_catalog()

    assert err is None
    assert captured["api_name"] == "ths_index"
    assert captured["params"] == {"type": "N", "exchange": "A"}
    assert "type" in captured["fields"]
    assert catalog is not None
    assert [(theme.code, theme.name) for theme in catalog] == [("885881", "云办公")]


def test_catalog_empty_items_returns_error(monkeypatch):
    """server 返空 items 返 (None, TushareApiError) · 暴露空 server 数据问题。"""
    from kan.data import tushare_themes

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes._post_tushare_api",
        lambda *a, **kw: ({"fields": ["ts_code", "name"], "items": []}, None),
    )
    data, err = tushare_themes.tushare_load_theme_catalog()
    assert data is None
    assert err is not None
    assert err.code == 0  # 0=客户端检测的"server 空数据"非业务错误
    assert "空数据" in err.msg


# ── tushare_load_theme_klines(batch + group)──────────────────────────


def test_klines_returns_none_when_no_token(monkeypatch):
    from kan.data import tushare_themes

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: (None, "http://e"),
    )
    themes = [Theme(code="886108", name="AI应用", source="tushare")]
    data, err = tushare_themes.tushare_load_theme_klines(themes)
    assert data is None
    assert err is None  # 未配 token 不是 error


def test_klines_skip_non_tushare_themes(monkeypatch):
    """非 source='tushare' 的题材静默跳过(target_codes 空)→ (None, None)。"""
    from kan.data import tushare_themes

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )
    themes = [Theme(code="886108", name="AI应用", source="ths")]  # 不是 tushare
    data, err = tushare_themes.tushare_load_theme_klines(themes)
    assert data is None
    assert err is None


def test_klines_partial_day_failure_tolerated(monkeypatch):
    """单个 trade_date 拉失败不阻塞整体 · 只要有 ≥2 天数据就能算 streak。"""
    from datetime import date

    from kan.data import tushare_themes
    from kan.data.tushare import TushareApiError

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes._recent_trading_days",
        lambda n: [date(2026, 5, 22), date(2026, 5, 21), date(2026, 5, 20)],
    )

    call_count = {"n": 0}

    def _fake_post(endpoint, token, *, api_name, params, fields):
        call_count["n"] += 1
        if call_count["n"] == 2:
            # 第 2 天失败 · 返 (None, error) · loop 记 first_error 继续
            return None, TushareApiError(code=-1, msg="timeout", api_name="ths_daily")
        return ({
            "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "pct_change"],
            "items": [
                ["886108.TI", params["trade_date"], 100, 105, 99, 103, 3.0],
            ],
        }, None)

    monkeypatch.setattr(
        "kan.data.tushare_themes._post_tushare_api", _fake_post,
    )

    themes = [Theme(code="886108", name="AI应用", source="tushare")]
    klines, err = tushare_themes.tushare_load_theme_klines(themes)

    assert err is None  # 部分天失败但仍有数据 · 不传 error 上层(整体成功)
    assert klines is not None
    assert "886108" in klines
    # 3 天 - 1 失败 = 2 天数据 · 满足 streak 最小 2 行
    assert len(klines["886108"]) == 2


def test_klines_all_days_fail_transmits_first_error(monkeypatch):
    """背景: 全 N 天 ths_daily 失败 → (None, first_error) · 透传给上层 diagnosis。"""
    from datetime import date

    from kan.data import tushare_themes
    from kan.data.tushare import TushareApiError

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes._recent_trading_days",
        lambda n: [date(2026, 5, 22), date(2026, 5, 21)],
    )
    # 所有天都返 40203 频率超限 (模拟真实 8000 积分跑 ths_daily 的情况)
    monkeypatch.setattr(
        "kan.data.tushare_themes._post_tushare_api",
        lambda *a, **kw: (None, TushareApiError(
            code=40203, msg="抱歉，您访问接口(ths_daily)频率超限(1次/小时)",
            api_name="ths_daily",
        )),
    )

    themes = [Theme(code="886108", name="AI应用", source="tushare")]
    data, err = tushare_themes.tushare_load_theme_klines(themes)
    assert data is None
    assert err is not None
    assert err.code == 40203
    assert "频率超限" in err.msg
    assert err.api_name == "ths_daily"


def test_klines_no_trading_days_returns_error(monkeypatch):
    from kan.data import tushare_themes

    monkeypatch.setattr(
        "kan.data.tushare_themes._resolve_config", lambda: ("tok", "http://e"),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes._recent_trading_days", lambda n: [],
    )
    themes = [Theme(code="886108", name="AI应用", source="tushare")]
    data, err = tushare_themes.tushare_load_theme_klines(themes)
    assert data is None
    assert err is not None
    assert err.code == 0
    assert "trading_calendar" in err.msg


# ── load_theme_leaderboard 数据源 dispatch ─────────────────────────────


def test_leaderboard_dispatches_to_em_when_no_token(monkeypatch):
    """无 token 时 source='em' · 走 AkShare EM 路径。"""
    from datetime import date

    import pandas as pd

    from kan.core.models import Theme as ThemeM
    from kan.data import theme_leaderboard

    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_token_configured", lambda: False,
    )
    themes = [ThemeM(code="886108", name="AI应用", source="ths")]
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: themes)

    def _fake_kline(theme, force=False):
        return pd.DataFrame({
            "date": [date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)],
            "open": [100, 101, 102],
            "high": [102, 103, 104],
            "low": [99, 100, 101],
            "close": [101, 102, 103],
            "volume": [1000, 1000, 1000],
            "amount": [100000, 100000, 100000],
        })

    monkeypatch.setattr(theme_leaderboard, "fetch_theme_kline", _fake_kline)

    results, _, source, _diag = theme_leaderboard.load_theme_leaderboard(progress_console=None)

    assert source == "em"
    assert len(results) == 1


def test_leaderboard_dispatches_to_tushare_when_token_configured(monkeypatch):
    """配 token 且 TuShare 返回数据 → source='tushare' · 不走 EM 路径。"""
    from datetime import date

    import pandas as pd

    from kan.core.models import Theme as ThemeM
    from kan.data import theme_leaderboard

    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_token_configured", lambda: True,
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_load_theme_catalog",
        lambda: ([ThemeM(code="886108", name="AI应用", source="tushare")], None),
    )
    df = pd.DataFrame({
        "date": [date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)],
        "open": [100, 101, 102],
        "high": [102, 103, 104],
        "low": [99, 100, 101],
        "close": [101, 102, 103],
        "volume": [float("nan")] * 3,
        "amount": [float("nan")] * 3,
    })
    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_load_theme_klines",
        lambda themes: ({"886108": df}, None),
    )

    # EM 路径不应被调用 · 设置为 raise 防默触发
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: (_ for _ in ()).throw(AssertionError("EM 不应被调")))

    results, _, source, _diag = theme_leaderboard.load_theme_leaderboard(progress_console=None)

    assert source == "tushare"
    assert len(results) == 1
    assert results[0].name == "AI应用"


def test_leaderboard_fallback_em_when_tushare_returns_none(monkeypatch):
    """配 token 但 TuShare catalog/klines 失败 → fallback EM(双源保险)。"""
    from datetime import date

    import pandas as pd

    from kan.core.models import Theme as ThemeM
    from kan.data import theme_leaderboard
    from kan.data.tushare import TushareApiError

    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_token_configured", lambda: True,
    )
    # TuShare catalog 拿到 · 但 klines 返回 (None, err)(接口挂)
    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_load_theme_catalog",
        lambda: ([ThemeM(code="886108", name="AI应用", source="tushare")], None),
    )
    monkeypatch.setattr(
        "kan.data.tushare_themes.tushare_load_theme_klines",
        lambda themes: (None, TushareApiError(
            code=40203, msg="频率超限", api_name="ths_daily",
        )),
    )

    # EM 路径应该被调用(fallback)
    em_themes = [ThemeM(code="886108", name="AI应用", source="ths")]
    monkeypatch.setattr(theme_leaderboard, "load_theme_catalog", lambda force=False: em_themes)
    monkeypatch.setattr(
        theme_leaderboard, "fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame({
            "date": [date(2026, 5, 20), date(2026, 5, 21)],
            "open": [100, 101], "high": [102, 103], "low": [99, 100],
            "close": [101, 102], "volume": [1000, 1000], "amount": [1, 1],
        }),
    )

    results, _, source, _diag = theme_leaderboard.load_theme_leaderboard(progress_console=None)

    assert source == "em"  # fallback 生效
    assert len(results) == 1
