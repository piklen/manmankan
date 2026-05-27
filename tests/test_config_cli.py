"""kan config CLI 文案防御测试 · v0.0.6.5 加。

只覆盖文案 / 引导 / mask 等 UX 关键不变量 · 业务逻辑测试见 test_config.py(storage 层)。

防御场景:
- `_print_endpoint` 默认状态必须给 set 引导 (v0.0.6.5 前漏掉 · 用户摸索 dash vs underscore 受苦)
- `_print_token` 默认状态必须给 set 引导
- mask_token 永不返回原 token
"""
from __future__ import annotations


def test_print_endpoint_default_shows_set_hint(monkeypatch, capsys):
    """默认状态(无 env + 无 config)的 endpoint 输出必须含 set 引导 + dash key 名。

    回归防御: 防止文案回退到 "https://api.tushare.pro (默认)" 这种无引导版本。
    """
    monkeypatch.delenv("TUSHARE_ENDPOINT", raising=False)

    from kan.cli.config_cmds import _print_endpoint

    _print_endpoint(cfg={}, raw=False)
    out = capsys.readouterr().out
    assert "默认" in out
    assert "kan config set tushare-endpoint" in out  # 必须用 dash 不是 underscore
    assert "https://api.tushare.pro" in out


def test_print_token_default_shows_set_hint(monkeypatch, capsys):
    """默认状态的 token 输出必须含 set 引导(对称 endpoint · 早就有 · 防回退)。"""
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    from kan.cli.config_cmds import _print_token

    _print_token(cfg={}, raw=False)
    out = capsys.readouterr().out
    assert "未配置" in out
    assert "kan config set tushare-token" in out


def test_mask_token_never_returns_raw():
    """mask_token 必须遮住前缀 · 永不返原 token(token 安全核心契约)。"""
    from kan.storage.config import mask_token

    long_token = "9466278d8c5cc0b3417d29a2a74f976bb620b2fb88fc62738adc6d78"
    masked = mask_token(long_token)
    assert masked == "***6d78"
    assert long_token not in masked
    # 边界: 短串 / None / 空串全 mask
    assert mask_token("abc") == "***"
    assert mask_token(None) == "***"
    assert mask_token("") == "***"
