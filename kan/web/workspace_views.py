"""数据管理页的本地配置事实。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from kan.storage import config


def _token_status() -> dict[str, Any]:
    token = config.load().get("tushare_token")
    token_text = token.strip() if isinstance(token, str) else ""
    configured = bool(token_text)
    return {
        "ok": True,
        "configured": configured,
        "masked": config.mask_token(token_text) if configured else None,
    }


def settings_facts() -> dict[str, Any]:
    """设置页只读事实。"""
    import os

    from kan.data.tushare import DEFAULT_ENDPOINT
    from kan.storage import paths

    cfg = config.load()
    endpoint_raw = os.environ.get("TUSHARE_ENDPOINT") or cfg.get("tushare_endpoint") or DEFAULT_ENDPOINT
    endpoint = endpoint_raw.strip() if isinstance(endpoint_raw, str) else DEFAULT_ENDPOINT
    if not endpoint.startswith(("http://", "https://")):
        endpoint = DEFAULT_ENDPOINT
    return {
        "data_dir": str(paths.DATA_DIR),
        "kline_cache_files": _kline_cache_count(paths.DATA_DIR),
        "tushare_endpoint_domain": _endpoint_domain(endpoint),
    }


def _kline_cache_count(data_dir) -> int:
    try:
        return sum(
            1 for path in data_dir.glob("*.parquet")
            if path.stem.isdigit() and len(path.stem) == 6
        )
    except OSError:
        return 0


def _endpoint_domain(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return ""
    return parsed.hostname or ""
