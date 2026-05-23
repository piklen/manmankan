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

    env_tok = os.environ.get("TUSHARE_TOKEN")
    cfg_tok = cfg.get("tushare_token")
    effective_tok = env_tok if env_tok else cfg_tok
    if effective_tok and isinstance(effective_tok, str) and effective_tok.strip():
        masked = _mask_token(effective_tok.strip())
        if env_tok:
            typer.echo(f"tushare_token: {masked}   (set via TUSHARE_TOKEN env, overriding config)")
        else:
            typer.echo(f"tushare_token: {masked}   (set via config)")

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
        )
        raise typer.Exit(code=2)

    internal_key = _KEY_MAP[key]
    cleaned = value.strip()

    if internal_key == "tushare_token":
        if not cleaned:
            typer.echo("❌ token 不能为空")
            raise typer.Exit(code=2)
    elif internal_key == "tushare_endpoint":
        if not cleaned.startswith(("http://", "https://")):
            typer.echo("❌ 端点需以 http:// 或 https:// 开头")
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
