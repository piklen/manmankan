"""TuShare Pro 数据源 · 自写轻量 HTTP client（POST JSON 协议）。

不依赖官方 tushare SDK：SDK `DataApi.__init__(token, timeout)` 把端点写死
在私有 `__http_url = 'http://api.tushare.pro'` 属性,要替端点只能 monkey-patch
`_DataApi__http_url`。自写 client 反而更简单、无 transitive deps、风格统一。

配 token 即顶优先（替 baostock 主路径），未配 token 行为零变化。
"""
from __future__ import annotations

import os
import re

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")

DEFAULT_ENDPOINT = "http://api.tushare.pro"


def _normalize_symbol_to_ts(symbol: str) -> str:
    """6 位代码 → TuShare ts_code 格式。

    规则：
    - 60xxxx / 68xxxx / 9xxxxx → .SH（上证主板 / 科创板 / B 股）
    - 00xxxx / 30xxxx → .SZ（深证主板 / 创业板）
    - 83xxxx / 43xxxx / 87xxxx / 82xxxx → .BJ（北交所 / 新三板精选）
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
