# TuShare Pro 数据源接入 · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `kan` 在用户配置 TuShare Pro token（+ 可选自定义端点）后，把 TuShare Pro 作为 `fetch_kline` 顶优先数据源；未配 token 时行为零变化。

**Architecture:** 新增 `kan/tushare_pro.py`（自写 ~80 行 HTTP client + 配置解析 + `_fetch_tushare` 入口），扩展 `kan/config.py` schema 加两字段，在 `kan/fetcher.py::fetch_kline` 头部插入条件分支；CLI 增加 `kan config` 子命令组（`kan/cli_config_cmds.py`）做 token/endpoint 的 get/set/unset。所有改动 backward-compatible。

**Tech Stack:** Python 3.11+, pytest, typer, requests (已在 deps), pandas, monkeypatch for tests。

**Spec:** [`docs/design-tushare-pro.md`](./design-tushare-pro.md)

**Worktree:** `.worktrees/feat-v0.0.5-tushare-pro`（branch `feat/v0.0.5-tushare-pro` 自 `feat/v0.0.5.0` fork）

---

## Task 1: 股票代码 → ts_code 归一化

**Files:**
- Create: `kan/tushare_pro.py`
- Test: `tests/test_tushare_pro.py`

TuShare Pro 要求 `<symbol>.<exchange>` 格式（如 `600519.SH`）。本任务建模块 + 第一个纯函数。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_tushare_pro.py`:

```python
"""kan/tushare_pro.py · TuShare Pro 数据源接入测试"""

import pytest

from kan import tushare_pro


class TestNormalizeSymbolToTs:
    """6 位股票代码 → TuShare ts_code 格式（带交易所后缀）"""

    @pytest.mark.parametrize("symbol,expected", [
        ("600519", "600519.SH"),  # 上证主板
        ("601318", "601318.SH"),
        ("688981", "688981.SH"),  # 科创板
        ("000001", "000001.SZ"),  # 深证主板
        ("002594", "002594.SZ"),
        ("300750", "300750.SZ"),  # 创业板
        ("830799", "830799.BJ"),  # 北交所
        ("430047", "430047.BJ"),  # 新三板精选
        ("900901", "900901.SH"),  # 上证 B 股
    ])
    def test_normalizes_by_prefix(self, symbol, expected):
        assert tushare_pro._normalize_symbol_to_ts(symbol) == expected

    def test_unknown_prefix_defaults_to_sz(self):
        """未知前缀走深证防御性回退（实际 A 股不存在 5xxxxx，但 SDK 应不抛）"""
        assert tushare_pro._normalize_symbol_to_ts("500001") == "500001.SZ"

    def test_invalid_symbol_raises(self):
        with pytest.raises(ValueError, match="6 位"):
            tushare_pro._normalize_symbol_to_ts("abc")
        with pytest.raises(ValueError, match="6 位"):
            tushare_pro._normalize_symbol_to_ts("12345")
```

- [ ] **Step 2: 跑测试验证失败**

```bash
uv run pytest tests/test_tushare_pro.py -v
```

Expected: ImportError / ModuleNotFoundError on `from kan import tushare_pro`

- [ ] **Step 3: 实现模块骨架 + 函数**

新建 `kan/tushare_pro.py`:

```python
"""TuShare Pro 数据源 · 自写轻量 HTTP client（POST JSON 协议）。

不依赖官方 tushare SDK：SDK `DataApi.__init__(token, timeout)` 把端点写死
在私有 `__http_url = 'http://api.tushare.pro'` 属性,要替端点只能 monkey-patch
`_DataApi__http_url`。自写 client 反而更简单、无 transitive deps、风格统一。

配 token 即顶优先（替 baostock 主路径），未配 token 行为零变化。
"""
from __future__ import annotations

import re

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")


def _normalize_symbol_to_ts(symbol: str) -> str:
    """6 位代码 → TuShare ts_code 格式。

    规则：
    - 60xxxx / 68xxxx / 9xxxxx → .SH（上证主板 / 科创板 / B 股）
    - 00xxxx / 30xxxx → .SZ（深证主板 / 创业板）
    - 83xxxx / 43xxxx / 87xxxx → .BJ（北交所 / 新三板精选）
    - 其他 → .SZ（防御性回退）
    """
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"必须是 6 位股票代码，实际收到: {symbol!r}")
    p = symbol[0]
    if p == "6" or symbol[:2] in ("68", "90") or symbol.startswith("9"):
        return f"{symbol}.SH"
    if p in ("0", "3"):
        return f"{symbol}.SZ"
    if symbol[:2] in ("83", "43", "87", "82"):
        return f"{symbol}.BJ"
    return f"{symbol}.SZ"
```

- [ ] **Step 4: 跑测试验证通过**

```bash
uv run pytest tests/test_tushare_pro.py -v
```

Expected: 11 passed

- [ ] **Step 5: 提交**

```bash
git add kan/tushare_pro.py tests/test_tushare_pro.py
git commit -m "feat(tushare-pro): add module + ts_code symbol normalization"
```

---

## Task 2: config.py schema 扩展

**Files:**
- Modify: `kan/config.py`（DEFAULT_CONFIG 加两键）
- Modify: `tests/test_config.py`（追加测试，不动现有）

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加：

```python
class TestTushareFields:
    """v0.0.5 新增 tushare_token / tushare_endpoint 字段"""

    def test_default_tushare_fields_are_none(self, temp_config_path):
        """新装用户读到 None，不打开 tushare 分支"""
        cfg = config.load()
        assert cfg["tushare_token"] is None
        assert cfg["tushare_endpoint"] is None

    def test_save_and_reload_tushare_token(self, temp_config_path):
        cfg = config.load()
        cfg["tushare_token"] = "tk_test_abcdef123456"
        config.save(cfg)
        reloaded = config.load()
        assert reloaded["tushare_token"] == "tk_test_abcdef123456"
        assert reloaded["tushare_endpoint"] is None

    def test_legacy_config_without_tushare_fields_self_heals(self, temp_config_path):
        """老 config.json 没有 tushare_* 字段也能 load → 缺字段补 None"""
        import json
        temp_config_path.write_text(json.dumps({"auto_update": True}))
        cfg = config.load()
        assert cfg["auto_update"] is True
        assert cfg["tushare_token"] is None
        assert cfg["tushare_endpoint"] is None
```

- [ ] **Step 2: 跑测试验证失败**

```bash
uv run pytest tests/test_config.py::TestTushareFields -v
```

Expected: KeyError 'tushare_token' / AssertionError

- [ ] **Step 3: 修改 config.py 加字段**

`kan/config.py` 中 `DEFAULT_CONFIG` dict 改为：

```python
DEFAULT_CONFIG: dict[str, Any] = {
    "auto_update": None,          # null=未设过 · True=自动升级 · False=仅 hint 不升级
    "last_check_date": None,      # ISO date "YYYY-MM-DD" · daily cache 命中
    "latest_seen_version": None,  # 上次发现的最新版本号字符串
    "last_hint_date": None,       # 选 False 后 hint 限流 (每周一次)
    "tushare_token": None,        # v0.0.5: TuShare Pro API token (None=未配置 → 跳过 TS 分支)
    "tushare_endpoint": None,     # v0.0.5: TuShare Pro 端点 (None=用 http://api.tushare.pro 默认)
}
```

其他代码不动 —— `load()` 已经会用 `DEFAULT_CONFIG` 补缺字段，自动覆盖。

- [ ] **Step 4: 跑全套 config 测试**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 全过（既有 + 3 新）

- [ ] **Step 5: 提交**

```bash
git add kan/config.py tests/test_config.py
git commit -m "feat(config): add tushare_token + tushare_endpoint fields"
```

---

## Task 3: 配置解析（env > config > default）

**Files:**
- Modify: `kan/tushare_pro.py`（新增 `_resolve_config()`）
- Modify: `tests/test_tushare_pro.py`（新增 TestResolveConfig）

- [ ] **Step 1: 写失败测试**

在 `tests/test_tushare_pro.py` 末尾追加：

```python
from kan import config


class TestResolveConfig:
    """env > config > default 优先级"""

    DEFAULT_ENDPOINT = "http://api.tushare.pro"

    @pytest.fixture
    def temp_config(self, tmp_path, monkeypatch):
        from kan import paths
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def test_no_config_no_env_returns_none_token_default_endpoint(self, temp_config):
        token, endpoint = tushare_pro._resolve_config()
        assert token is None
        assert endpoint == self.DEFAULT_ENDPOINT

    def test_config_only(self, temp_config):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_from_cfg"})
        token, endpoint = tushare_pro._resolve_config()
        assert token == "tk_from_cfg"
        assert endpoint == self.DEFAULT_ENDPOINT

    def test_env_overrides_config(self, temp_config, monkeypatch):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_from_cfg"})
        monkeypatch.setenv("TUSHARE_TOKEN", "tk_from_env")
        token, _ = tushare_pro._resolve_config()
        assert token == "tk_from_env"

    def test_endpoint_env_overrides(self, temp_config, monkeypatch):
        monkeypatch.setenv("TUSHARE_ENDPOINT", "https://mirror.example.com")
        _, endpoint = tushare_pro._resolve_config()
        assert endpoint == "https://mirror.example.com"

    def test_config_endpoint_used_when_no_env(self, temp_config):
        config.save({**config.DEFAULT_CONFIG, "tushare_endpoint": "https://my.mirror"})
        _, endpoint = tushare_pro._resolve_config()
        assert endpoint == "https://my.mirror"

    def test_blank_token_treated_as_unset(self, temp_config, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "   ")
        token, _ = tushare_pro._resolve_config()
        assert token is None

    def test_invalid_endpoint_falls_back_to_default(self, temp_config, monkeypatch):
        monkeypatch.setenv("TUSHARE_ENDPOINT", "not-a-url")
        _, endpoint = tushare_pro._resolve_config()
        assert endpoint == self.DEFAULT_ENDPOINT
```

- [ ] **Step 2: 跑测试验证失败**

```bash
uv run pytest tests/test_tushare_pro.py::TestResolveConfig -v
```

Expected: AttributeError `_resolve_config` not defined

- [ ] **Step 3: 实现 `_resolve_config`**

在 `kan/tushare_pro.py` 末尾追加：

```python
import os

DEFAULT_ENDPOINT = "http://api.tushare.pro"


def _resolve_config() -> tuple[str | None, str]:
    """解析 token + endpoint 配置。

    优先级（高 → 低）：
      TUSHARE_TOKEN    env > config["tushare_token"]    > None
      TUSHARE_ENDPOINT env > config["tushare_endpoint"] > DEFAULT_ENDPOINT

    校验：
    - token 去首尾空白；空串 / None → 未配置
    - endpoint 必须 http(s):// 前缀；否则回退默认（不抛异常）
    """
    from kan import config as _config

    cfg = _config.load()
    token_raw = os.environ.get("TUSHARE_TOKEN") or cfg.get("tushare_token")
    token = token_raw.strip() if isinstance(token_raw, str) else None
    if not token:
        token = None

    endpoint_raw = os.environ.get("TUSHARE_ENDPOINT") or cfg.get("tushare_endpoint")
    endpoint = endpoint_raw.strip() if isinstance(endpoint_raw, str) else ""
    if not endpoint.startswith(("http://", "https://")):
        endpoint = DEFAULT_ENDPOINT

    return token, endpoint
```

- [ ] **Step 4: 跑测试验证通过**

```bash
uv run pytest tests/test_tushare_pro.py -v
```

Expected: 18 passed (11 prior + 7 new)

- [ ] **Step 5: 提交**

```bash
git add kan/tushare_pro.py tests/test_tushare_pro.py
git commit -m "feat(tushare-pro): config resolver (env > config > default)"
```

---

## Task 4: HTTP client + 字段映射

**Files:**
- Modify: `kan/tushare_pro.py`（新增 `_post_tushare_api()` + `_to_kline_df()`）
- Modify: `tests/test_tushare_pro.py`（新增 TestPostTushareApi）

- [ ] **Step 1: 写失败测试**

在 `tests/test_tushare_pro.py` 追加：

```python
from unittest.mock import MagicMock


class TestPostTushareApi:
    """POST JSON 协议 · 字段映射 · 错误码处理"""

    SAMPLE_RESPONSE = {
        "code": 0,
        "msg": "",
        "data": {
            "fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
            "items": [
                ["20260102", 1500.0, 1520.0, 1490.0, 1510.0, 100000.0, 150000000.0],
                ["20260103", 1510.0, 1530.0, 1500.0, 1525.0, 120000.0, 180000000.0],
            ],
        },
    }

    def test_post_sends_correct_payload(self, monkeypatch):
        captured = {}

        def fake_post(url, json, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = self.SAMPLE_RESPONSE
            return mock

        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)

        result = tushare_pro._post_tushare_api(
            endpoint="http://api.tushare.pro",
            token="tk_test",
            api_name="daily",
            params={"ts_code": "600519.SH", "start_date": "20260101"},
            fields="trade_date,open,high,low,close,vol,amount",
        )

        assert captured["url"] == "http://api.tushare.pro"
        assert captured["json"]["api_name"] == "daily"
        assert captured["json"]["token"] == "tk_test"
        assert captured["json"]["params"]["ts_code"] == "600519.SH"
        assert captured["json"]["fields"] == "trade_date,open,high,low,close,vol,amount"
        assert captured["timeout"] == 30
        assert result == self.SAMPLE_RESPONSE["data"]

    def test_nonzero_code_returns_none(self, monkeypatch):
        def fake_post(url, json, timeout):
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = {"code": 40001, "msg": "token 无效", "data": None}
            return mock
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        assert tushare_pro._post_tushare_api(
            "http://api.tushare.pro", "bad", "daily", {}, "x") is None

    def test_http_5xx_returns_none(self, monkeypatch):
        def fake_post(url, json, timeout):
            mock = MagicMock()
            mock.status_code = 502
            mock.json.return_value = {}
            return mock
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        assert tushare_pro._post_tushare_api(
            "http://api.tushare.pro", "tk", "daily", {}, "x") is None

    def test_network_exception_returns_none(self, monkeypatch):
        def fake_post(*a, **kw):
            raise tushare_pro.requests.exceptions.ConnectionError("DNS fail")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        assert tushare_pro._post_tushare_api(
            "http://api.tushare.pro", "tk", "daily", {}, "x") is None

    def test_exception_message_does_not_leak_token(self, monkeypatch, caplog):
        """token 永不进 logs / exception 文本"""
        import logging
        def fake_post(*a, **kw):
            raise tushare_pro.requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        with caplog.at_level(logging.DEBUG):
            tushare_pro._post_tushare_api(
                "http://api.tushare.pro", "SECRET_TK", "daily", {}, "x")
        for rec in caplog.records:
            assert "SECRET_TK" not in rec.getMessage()


class TestToKlineDf:
    """TuShare 响应 → manmankan KLINE_REQUIRED schema 转换"""

    def test_maps_fields(self):
        data = {
            "fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
            "items": [
                ["20260102", 1500.0, 1520.0, 1490.0, 1510.0, 100000.0, 150000000.0],
            ],
        }
        df = tushare_pro._to_kline_df(data)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
        assert df.iloc[0]["close"] == 1510.0

    def test_empty_items_returns_none(self):
        data = {"fields": ["trade_date", "open"], "items": []}
        assert tushare_pro._to_kline_df(data) is None

    def test_missing_data_returns_none(self):
        assert tushare_pro._to_kline_df(None) is None
        assert tushare_pro._to_kline_df({}) is None
```

- [ ] **Step 2: 跑测试验证失败**

```bash
uv run pytest tests/test_tushare_pro.py::TestPostTushareApi tests/test_tushare_pro.py::TestToKlineDf -v
```

Expected: AttributeError `_post_tushare_api` / `_to_kline_df` not defined

- [ ] **Step 3: 实现 client + 字段映射**

在 `kan/tushare_pro.py` 顶部 import 区追加（不要重复已有）：

```python
import logging
from typing import TYPE_CHECKING

import requests

from kan._log import debug_log

if TYPE_CHECKING:
    import pandas as pd

_TIMEOUT_SECONDS = 30

# TuShare 字段 → manmankan KLINE 标准列
_FIELD_MAP = {
    "trade_date": "date",
    "vol": "volume",
}
```

在文件末尾追加函数：

```python
def _post_tushare_api(
    endpoint: str,
    token: str,
    api_name: str,
    params: dict,
    fields: str,
) -> dict | None:
    """POST JSON 到 TuShare Pro API · 返回 data 块或 None。

    错误兜底（一律返回 None，由调用方 fallback）：
    - 网络异常 / DNS / 超时
    - HTTP 非 2xx
    - 业务 code != 0（token 无效、积分不足、限流）

    关键不变量：token 永不进入 logs / exceptions。
    """
    payload = {
        "api_name": api_name,
        "token": token,
        "params": params,
        "fields": fields,
    }
    try:
        resp = requests.post(endpoint, json=payload, timeout=_TIMEOUT_SECONDS)
    except Exception as e:
        # 不传 e.args 给 debug_log · 仅 type 名 · 防意外泄漏
        debug_log(__name__, f"tushare POST {endpoint}", type(e).__name__)
        return None
    if resp.status_code != 200:
        debug_log(__name__, f"tushare HTTP {resp.status_code}", endpoint)
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    if body.get("code", -1) != 0:
        # body.get("msg") 安全可记 · 不含 token
        debug_log(__name__, "tushare api code", body.get("msg", ""))
        return None
    return body.get("data")


def _to_kline_df(data: dict | None) -> "pd.DataFrame | None":
    """TuShare data 块 → DataFrame，列名映射到 manmankan KLINE 标准。"""
    import pandas as pd
    if not data:
        return None
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return None
    df = pd.DataFrame(items, columns=fields)
    df = df.rename(columns=_FIELD_MAP)
    return df
```

- [ ] **Step 4: 跑测试验证通过**

```bash
uv run pytest tests/test_tushare_pro.py -v
```

Expected: 27 passed (18 prior + 9 new)

- [ ] **Step 5: 提交**

```bash
git add kan/tushare_pro.py tests/test_tushare_pro.py
git commit -m "feat(tushare-pro): HTTP client + field mapping to KLINE schema"
```

---

## Task 5: 顶层 `_fetch_tushare()` 入口

**Files:**
- Modify: `kan/tushare_pro.py`（新增 `_fetch_tushare()`）
- Modify: `tests/test_tushare_pro.py`（新增 TestFetchTushare）

- [ ] **Step 1: 写失败测试**

在 `tests/test_tushare_pro.py` 追加：

```python
class TestFetchTushare:
    """_fetch_tushare 集成：resolver + circuit_breaker + client + DataFrame"""

    @pytest.fixture
    def temp_config(self, tmp_path, monkeypatch):
        from kan import paths
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        # 清 circuit_breaker 状态
        from kan import circuit_breaker
        monkeypatch.setattr(circuit_breaker, "_breaker", None)
        monkeypatch.setattr(circuit_breaker, "DEFAULT_CIRCUIT_PATH", tmp_path / "circuit.json")
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def test_no_token_returns_none(self, temp_config):
        """未配 token → 直接 None，不发请求"""
        assert tushare_pro._fetch_tushare("600519", "20260101") is None

    def test_with_token_returns_dataframe(self, temp_config, monkeypatch):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        sample = {
            "code": 0,
            "data": {
                "fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
                "items": [["20260102", 1500.0, 1520.0, 1490.0, 1510.0, 100000.0, 150000000.0]],
            },
        }

        def fake_post(url, json, timeout):
            mock = MagicMock()
            mock.status_code = 200
            mock.json.return_value = sample
            return mock

        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)
        df = tushare_pro._fetch_tushare("600519", "20260101")
        assert df is not None
        assert "date" in df.columns
        assert "volume" in df.columns
        assert len(df) == 1

    def test_circuit_breaker_skips_when_down(self, temp_config, monkeypatch):
        from kan import circuit_breaker
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})
        # 直接把 tushare 标记 down
        cb = circuit_breaker.get_breaker()
        cb.record("tushare", ok=False)

        called = {"hit": False}
        def fake_post(*a, **kw):
            called["hit"] = True
            raise AssertionError("circuit breaker 没拦住")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)

        assert tushare_pro._fetch_tushare("600519", "20260101") is None
        assert not called["hit"]

    def test_api_failure_records_breaker(self, temp_config, monkeypatch):
        from kan import circuit_breaker
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        def fake_post(*a, **kw):
            raise tushare_pro.requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr(tushare_pro.requests, "post", fake_post)

        tushare_pro._fetch_tushare("600519", "20260101")
        cb = circuit_breaker.get_breaker()
        assert cb.is_down("tushare")
```

- [ ] **Step 2: 跑测试验证失败**

```bash
uv run pytest tests/test_tushare_pro.py::TestFetchTushare -v
```

Expected: AttributeError `_fetch_tushare` not defined

- [ ] **Step 3: 实现 `_fetch_tushare`**

在 `kan/tushare_pro.py` 末尾追加：

```python
def _fetch_tushare(symbol: str, start: str) -> "pd.DataFrame | None":
    """TuShare Pro 日 K 入口 · fetch_kline 顶优先调用。

    Args:
      symbol: 6 位股票代码
      start:  YYYYMMDD 起始日期（与 fetcher.py 其它 _fetch_* 函数一致）

    Returns:
      DataFrame（manmankan KLINE 标准列）或 None（未配 token / 熔断 / 失败）。
      失败时上游 fetch_kline 会 fallback 到 baostock → akshare → 腾讯。
    """
    from kan import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None

    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare"):
        return None

    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None

    try:
        data = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="daily",
            params={"ts_code": ts_code, "start_date": start},
            fields="trade_date,open,high,low,close,vol,amount",
        )
        if data is None:
            cb.record("tushare", ok=False)
            return None
        df = _to_kline_df(data)
        if df is None or df.empty:
            cb.record("tushare", ok=False)
            return None
        cb.record("tushare", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare", type(e).__name__)
        cb.record("tushare", ok=False)
        return None
```

- [ ] **Step 4: 跑测试验证通过**

```bash
uv run pytest tests/test_tushare_pro.py -v
```

Expected: 31 passed (27 prior + 4 new)

- [ ] **Step 5: 提交**

```bash
git add kan/tushare_pro.py tests/test_tushare_pro.py
git commit -m "feat(tushare-pro): _fetch_tushare integration + circuit breaker"
```

---

## Task 6: 接入 `fetch_kline()` 主链

**Files:**
- Modify: `kan/fetcher.py:455-462`（在 baostock 调用前插入 tushare 优先分支）
- Modify: `tests/test_fetcher.py`（新增 2 测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_fetcher.py` 末尾追加：

```python
class TestTushareProDispatch:
    """v0.0.5: 配 token 时 tushare 顶替 baostock 作主路径；未配 token 行为不变"""

    @pytest.fixture
    def isolated_env(self, tmp_path, monkeypatch):
        from kan import config, paths, tushare_pro, circuit_breaker
        monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
        monkeypatch.setattr(circuit_breaker, "_breaker", None)
        monkeypatch.setattr(circuit_breaker, "DEFAULT_CIRCUIT_PATH", tmp_path / "circuit.json")
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
        return tmp_path

    def test_no_token_path_unchanged(self, isolated_env, monkeypatch, fake_akshare_df):
        """未配 token → 不调用 _fetch_tushare → 原 fallback 链生效"""
        called = {"tushare": False}
        def spy_tushare(*a, **kw):
            called["tushare"] = True
            return None
        monkeypatch.setattr(fetcher, "_fetch_tushare", spy_tushare)
        # baostock 也走不通 · 让 akshare 东财 mock 兜底
        monkeypatch.setattr(fetcher, "_fetch_baostock", lambda *a, **kw: None)
        monkeypatch.setattr(fetcher, "_fetch_sina", lambda *a, **kw: None)
        with patch("akshare.stock_zh_a_hist", return_value=fake_akshare_df):
            df = fetcher.fetch_kline("600519", force=True)
        assert not called["tushare"]
        assert not df.empty

    def test_with_token_uses_tushare_first(self, isolated_env, monkeypatch):
        """配 token → tushare 命中 → 不再 fallback baostock"""
        from kan import config
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk"})

        sample = pd.DataFrame({
            "date": [date(2026, 4, 28), date(2026, 4, 29)],
            "open": [100.0, 101.0],
            "high": [101.5, 102.5],
            "low": [99.5, 100.5],
            "close": [101.0, 102.0],
            "volume": [10000, 11000],
            "amount": [1010000.0, 1122000.0],
        })

        baostock_called = {"hit": False}
        def fake_baostock(*a, **kw):
            baostock_called["hit"] = True
            return None

        monkeypatch.setattr(fetcher, "_fetch_tushare", lambda *a, **kw: sample.copy())
        monkeypatch.setattr(fetcher, "_fetch_baostock", fake_baostock)

        df = fetcher.fetch_kline("600519", force=True)
        assert not baostock_called["hit"]
        assert (df["_source"] == "tushare").all()
```

- [ ] **Step 2: 跑测试验证失败**

```bash
uv run pytest tests/test_fetcher.py::TestTushareProDispatch -v
```

Expected: `fetcher` 模块没有 `_fetch_tushare` 属性 / dispatch 没修改

- [ ] **Step 3: 修改 fetcher.py 接入**

在 `kan/fetcher.py` 顶部 import 区追加（如果没有）：

```python
from kan.tushare_pro import _fetch_tushare  # noqa: F401 (re-export for tests / monkeypatch)
```

然后修改 `fetch_kline()` 函数体（约第 455 行起），把原本：

```python
    raw = _fetch_baostock(symbol, start)
    source = "baostock"
    if raw is None:
        akshare_result = _fetch_via_akshare(symbol, start)
        if akshare_result is not None:
            raw, source = akshare_result
    if raw is None:
        raw = _fetch_tencent(symbol, start)
        source = "tencent"
```

改为：

```python
    # v0.0.5: TuShare Pro 优先（配 token 时）→ baostock → akshare 并发 → 腾讯
    raw = _fetch_tushare(symbol, start)
    source = "tushare"
    if raw is None:
        raw = _fetch_baostock(symbol, start)
        source = "baostock"
    if raw is None:
        akshare_result = _fetch_via_akshare(symbol, start)
        if akshare_result is not None:
            raw, source = akshare_result
    if raw is None:
        raw = _fetch_tencent(symbol, start)
        source = "tencent"
```

同时把 fetch_kline 头部 docstring 第一行（"baostock → 东财/新浪并发 → 腾讯"）改为：

```python
    """拉取单只股票前复权日 K 线（tushare 配 token 时优先 → baostock → 东财/新浪并发 → 腾讯）。
```

并把 fallback 设计编号更新为 4 档（在原本 docstring 列表前加 0 档）：

```python
    fallback 设计：
    0. TuShare Pro（仅当 tushare_token 配置时）· 顶优先 · 付费源 / 自部署镜像
    1. baostock 独立服务器最稳 · 数值精度全 A 股板块对齐 · 主路径
    2. 东财 + 新浪 两个 akshare 源并发 race ...
```

- [ ] **Step 4: 跑测试验证通过**

```bash
uv run pytest tests/test_fetcher.py::TestTushareProDispatch -v
uv run pytest tests/test_fetcher.py -v  # 既有测试不能挂
```

Expected: 2 new passed + 所有既有 fetcher 测试 passed

- [ ] **Step 5: 全套回归**

```bash
uv run pytest -q
```

Expected: ≥ 481 passed（479 既有 + 这一轮新增），0 failed

- [ ] **Step 6: 提交**

```bash
git add kan/fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): wire tushare-pro as top-priority source"
```

---

## Task 7: CLI `kan config` 子命令组

**Files:**
- Create: `kan/cli_config_cmds.py`
- Create: `tests/test_cli_config.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_cli_config.py`:

```python
"""kan config 子命令组测试 · get/set/unset + token mask + env 覆盖"""

import pytest
from typer.testing import CliRunner

from kan import config, paths


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)
    return tmp_path


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def app():
    """触发命令注册并返回 typer app · 与既有 test_cli_registration.py 同模式"""
    import kan.cli  # noqa: F401 — 触发子模块 import 注册所有命令
    from kan.app import app
    return app


class TestConfigGet:

    def test_get_empty_shows_default_endpoint_only(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "get"])
        assert result.exit_code == 0
        assert "tushare_endpoint" in result.stdout
        assert "default" in result.stdout.lower() or "默认" in result.stdout
        assert "tushare_token" not in result.stdout  # 未配置不列

    def test_get_with_token_masks(self, runner, app, isolated_env):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_abcdefghij1234"})
        result = runner.invoke(app, ["config", "get"])
        assert result.exit_code == 0
        assert "tushare_token" in result.stdout
        assert "***1234" in result.stdout
        # token 明文不能出现
        assert "tk_abcdefghij" not in result.stdout

    def test_get_with_env_override_marks_source(
        self, runner, app, isolated_env, monkeypatch,
    ):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_cfg00000000"})
        monkeypatch.setenv("TUSHARE_TOKEN", "tk_env00000000")
        result = runner.invoke(app, ["config", "get"])
        assert result.exit_code == 0
        assert "***0000" in result.stdout
        assert "env" in result.stdout.lower()  # 提示用 env 覆盖

    def test_get_with_custom_endpoint(self, runner, app, isolated_env):
        config.save({**config.DEFAULT_CONFIG, "tushare_endpoint": "https://my.mirror"})
        result = runner.invoke(app, ["config", "get"])
        assert "https://my.mirror" in result.stdout


class TestConfigSet:

    def test_set_token_writes_config(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-token", "tk_new_token_1234"])
        assert result.exit_code == 0
        assert "✅" in result.stdout or "已保存" in result.stdout
        # token 明文不能出现在确认输出
        assert "tk_new_token_1234" not in result.stdout
        assert "***1234" in result.stdout
        assert config.load()["tushare_token"] == "tk_new_token_1234"

    def test_set_endpoint_writes_config(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-endpoint", "https://my.host"])
        assert result.exit_code == 0
        assert config.load()["tushare_endpoint"] == "https://my.host"

    def test_set_empty_token_rejected(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-token", "   "])
        assert result.exit_code == 2
        assert "不能为空" in result.stdout or "empty" in result.stdout.lower()

    def test_set_invalid_endpoint_rejected(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "tushare-endpoint", "not-a-url"])
        assert result.exit_code == 2
        assert "http" in result.stdout.lower()

    def test_set_unknown_key_rejected(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "set", "no-such-key", "x"])
        assert result.exit_code != 0


class TestConfigUnset:

    def test_unset_clears_token(self, runner, app, isolated_env):
        config.save({**config.DEFAULT_CONFIG, "tushare_token": "tk_xxxxxxxx"})
        result = runner.invoke(app, ["config", "unset", "tushare-token"])
        assert result.exit_code == 0
        assert config.load()["tushare_token"] is None

    def test_unset_already_none_is_noop_message(self, runner, app, isolated_env):
        result = runner.invoke(app, ["config", "unset", "tushare-token"])
        assert result.exit_code == 0
        assert "ℹ" in result.stdout or "默认" in result.stdout or "无需" in result.stdout
```

- [ ] **Step 2: 跑测试验证失败**

```bash
uv run pytest tests/test_cli_config.py -v
```

Expected: `No such command 'config'`

- [ ] **Step 3: 实现 `kan/cli_config_cmds.py`**

新建 `kan/cli_config_cmds.py`:

```python
"""`kan config` 子命令组 · 用户配置增删查 · v0.0.5 引入。

支持字段（封闭集合）：
- tushare-token     (TuShare Pro API token)
- tushare-endpoint  (TuShare Pro API 端点 · 默认 http://api.tushare.pro)

环境变量 TUSHARE_TOKEN / TUSHARE_ENDPOINT 在运行时覆盖 config.json。
`kan config get` 会显式提示哪些字段被 env 覆盖。
"""
from __future__ import annotations

import os

import typer

from kan import config
from kan.app import app
from kan.tushare_pro import DEFAULT_ENDPOINT

config_app = typer.Typer(
    name="config",
    help="管理 kan 用户配置（TuShare Pro token、端点等）",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")

# CLI 短横线 → config.json 下划线
_KEY_MAP = {
    "tushare-token": "tushare_token",
    "tushare-endpoint": "tushare_endpoint",
}


def _mask_token(token: str) -> str:
    """末 4 位显形，前面 ***；少于 4 位全 mask。"""
    if not token or len(token) < 4:
        return "***"
    return f"***{token[-4:]}"


@config_app.command("get")
def get_cmd() -> None:
    """显示当前配置（token 自动 mask · env 覆盖时标注）。"""
    cfg = config.load()

    # tushare_token
    env_tok = os.environ.get("TUSHARE_TOKEN")
    cfg_tok = cfg.get("tushare_token")
    effective_tok = env_tok if env_tok else cfg_tok
    if effective_tok:
        masked = _mask_token(effective_tok.strip() if isinstance(effective_tok, str) else "")
        if env_tok:
            typer.echo(f"tushare_token: {masked}   (set via TUSHARE_TOKEN env, overriding config)")
        else:
            typer.echo(f"tushare_token: {masked}   (set via config)")

    # tushare_endpoint
    env_ep = os.environ.get("TUSHARE_ENDPOINT")
    cfg_ep = cfg.get("tushare_endpoint")
    if env_ep:
        typer.echo(f"tushare_endpoint: {env_ep}   (set via TUSHARE_ENDPOINT env, overriding config)")
    elif cfg_ep:
        typer.echo(f"tushare_endpoint: {cfg_ep}   (set via config)")
    else:
        typer.echo(f"tushare_endpoint: <default: {DEFAULT_ENDPOINT}>")


@config_app.command("set")
def set_cmd(
    key: str = typer.Argument(..., help="配置项名（tushare-token / tushare-endpoint）"),
    value: str = typer.Argument(..., help="配置值"),
) -> None:
    """设置一项配置（原子写入 ~/.local/share/kan/config.json）。"""
    if key not in _KEY_MAP:
        typer.echo(
            f"❌ 未知配置项: {key}\n支持的字段: {', '.join(_KEY_MAP)}",
            err=True,
        )
        raise typer.Exit(code=2)

    internal_key = _KEY_MAP[key]
    cleaned = value.strip()

    if internal_key == "tushare_token":
        if not cleaned:
            typer.echo("❌ token 不能为空", err=True)
            raise typer.Exit(code=2)
    elif internal_key == "tushare_endpoint":
        if not cleaned.startswith(("http://", "https://")):
            typer.echo("❌ 端点需以 http:// 或 https:// 开头", err=True)
            raise typer.Exit(code=2)

    cfg = config.load()
    cfg[internal_key] = cleaned
    config.save(cfg)

    if internal_key == "tushare_token":
        typer.echo(f"✅ 已保存 tushare_token ({_mask_token(cleaned)}) 到 ~/.local/share/kan/config.json")
    else:
        typer.echo(f"✅ 已保存 {internal_key}={cleaned} 到 ~/.local/share/kan/config.json")


@config_app.command("unset")
def unset_cmd(
    key: str = typer.Argument(..., help="配置项名（tushare-token / tushare-endpoint）"),
) -> None:
    """清除一项配置（回 null = 用默认值）。"""
    if key not in _KEY_MAP:
        typer.echo(
            f"❌ 未知配置项: {key}\n支持的字段: {', '.join(_KEY_MAP)}",
            err=True,
        )
        raise typer.Exit(code=2)

    internal_key = _KEY_MAP[key]
    cfg = config.load()
    if cfg.get(internal_key) is None:
        typer.echo(f"ℹ️  {internal_key} 已是默认值，无需清除")
        return
    cfg[internal_key] = None
    config.save(cfg)
    typer.echo(f"✅ 已清除 {internal_key}（回到默认值）")
```

- [ ] **Step 4: 在 `kan/cli.py` 注册新模块**

修改 `kan/cli.py` 第 79-84 行的 import 块，把 `cli_config_cmds` 加入：

```python
# 触发子模块装饰器执行 · MUST be at module top-level (不能在 cli_main 函数体内)
# 让 `from kan.cli import app` / `import kan.cli` 拿到完整命令列表 · 测试也依赖这点
from kan import (  # noqa: E402, F401
    cli_config_cmds,
    cli_meta_cmds,
    cli_scan_cmds,
    cli_trend_cmds,
    cli_watchlist_cmds,
)
```

- [ ] **Step 5: 跑测试验证通过**

```bash
uv run pytest tests/test_cli_config.py -v
```

Expected: 11 passed

- [ ] **Step 6: 提交**

```bash
git add kan/cli_config_cmds.py kan/cli.py tests/test_cli_config.py
git commit -m "feat(cli): add 'kan config' subcommand group (get/set/unset)"
```

---

## Task 8: CHANGELOG + 全套回归 + 烟测

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 读 CHANGELOG 顶部找 v0.0.5 section**

```bash
head -50 CHANGELOG.md
```

如果已有 `## v0.0.5.0` section 就追加；否则在文档顶部 `## Unreleased` 下追加（按现有约定）。

- [ ] **Step 2: 写 CHANGELOG 条目**

在合适的 section 内追加：

```markdown
### Added (v0.0.5.0)

- **TuShare Pro 数据源接入**（设计：[docs/design-tushare-pro.md](docs/design-tushare-pro.md)）
  - 新增 `kan config` 子命令组：`kan config get/set/unset` 管理用户配置
  - 支持 `tushare-token` 配置（必填，未配则跳过 TuShare 分支）
  - 支持 `tushare-endpoint` 配置（可选，默认 `http://api.tushare.pro`；可填自部署镜像 / 反代）
  - 环境变量 `TUSHARE_TOKEN` / `TUSHARE_ENDPOINT` 在运行时覆盖 config.json
  - 配 token 后 TuShare Pro 顶替 baostock 作 `fetch_kline` 主路径；未配 token 行为零变化
  - `kan config get` 自动 mask token（仅显示末 4 位）；token 永不出现在 logs / exceptions
  - 自写 ~80 行 HTTP client，不依赖官方 `tushare` SDK（SDK 端点硬编码无法替换）
```

- [ ] **Step 3: 全套回归**

```bash
uv run pytest -q --tb=short
```

Expected: ≥ 502 passed（479 既有 + 11 cli_config + 13 tushare_pro），0 failed

- [ ] **Step 4: CLI 烟测**

```bash
uv run kan config get                                           # 应输出 default endpoint 行
uv run kan config set tushare-endpoint https://test.example.com  # ✅ 已保存
uv run kan config get                                           # 应显示 https://test.example.com
uv run kan config unset tushare-endpoint                         # ✅ 已清除
uv run kan config set tushare-token bad                          # ✅ 已保存 (***bad)（但 < 4 字符全 mask）
uv run kan config get                                           # 应显示 *** 或 ***bad
uv run kan config unset tushare-token
```

每一步检查 exit code 与输出符合 ***REMOVED***7。出错则报 stop。

- [ ] **Step 5: 类型 / lint 检查**

```bash
uv run ruff check kan/tushare_pro.py kan/cli_config_cmds.py
```

Expected: All checks passed!

- [ ] **Step 6: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add v0.0.5.0 tushare-pro entries"
```

- [ ] **Step 7: 收尾**

```bash
git log --oneline feat/v0.0.5.0..HEAD                  # 应看到 ~7 个新 commits
git diff feat/v0.0.5.0..HEAD --stat                    # 复核文件改动幅度
```

---

## Self-Review Notes

**Spec 覆盖**：spec §3 架构 → Task 6；§4 文件清单 → 所有 task 覆盖；§5 config → Task 2/3；§6 client → Task 4/5；§7 CLI → Task 7；§8 安全 → Task 4 (token leak test) + Task 7 (mask)；§9 测试 → 每 task TDD。

**未覆盖项**：spec §11 后续工作（其它 API、kan doctor、多端点轮换）显式标"不在本轮"。

**回归基线**：worktree 起手 479 passed；预期收尾 ≥ 502 passed。

**潜在风险**：
- Task 6 改 `fetcher.py:455-470` 时若有其他 AI 在同一 hunk 改了 hot-list 分支，rebase 时可能冲突。提前用 `git fetch origin feat/v0.0.5.0 && git log origin/feat/v0.0.5.0..feat/v0.0.5.0 -- kan/fetcher.py` 确认。
- `kan config` 子命令组若与未来 `auto_update` 迁移冲突，spec §12 已声明本轮不动 `auto_update`。

---

## Execution Handoff

Plan complete and saved to `docs/plan-tushare-pro.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 每 task 派 fresh subagent 实现 + 两阶段 review，迭代快。
**2. Inline Execution** — 本会话内逐 task 跑，带检查点。

请选择执行方式。
