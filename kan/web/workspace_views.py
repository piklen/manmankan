"""数据管理页的本地配置事实。"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from kan.storage import config


def _token_status() -> dict[str, Any]:
    from kan.data.tushare import _resolve_config

    token, _endpoint = _resolve_config()
    configured = bool(token)
    return {
        "ok": True,
        "configured": configured,
        "masked": config.mask_token(token) if configured else None,
        "source": "environment" if os.environ.get("TUSHARE_TOKEN") else "config" if configured else "unconfigured",
    }


def settings_facts() -> dict[str, Any]:
    """设置页只读事实。"""
    from kan.data.tushare import _resolve_config
    from kan.storage import paths

    cfg = config.load()
    _token, endpoint = _resolve_config()
    return {
        "data_dir": str(paths.DATA_DIR),
        "kline_cache_files": _kline_cache_count(paths.DATA_DIR),
        "tushare_endpoint_domain": _endpoint_domain(endpoint),
        "tushare_endpoint_source": "environment" if os.environ.get("TUSHARE_ENDPOINT") else "config" if cfg.get("tushare_endpoint") else "default",
    }


def update_data_connection(token: str | None, endpoint: str | None) -> None:
    """只保存用户本次填写的字段；空白保留，环境变量生效时不写无效配置。"""
    from kan.storage.config import validate_tushare_endpoint

    changes = {}
    if token and token.strip():
        if os.environ.get("TUSHARE_TOKEN"):
            raise ValueError("TUSHARE_TOKEN 环境变量正在生效；请在启动环境修改并重启，网页不会覆盖它。")
        changes["tushare_token"] = token.strip()
    if endpoint and endpoint.strip():
        if os.environ.get("TUSHARE_ENDPOINT"):
            raise ValueError("TUSHARE_ENDPOINT 环境变量正在生效；请在启动环境修改并重启，网页不会覆盖它。")
        changes["tushare_endpoint"] = validate_tushare_endpoint(endpoint)
    if changes:
        config.update(**changes)


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
