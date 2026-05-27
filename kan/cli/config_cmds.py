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

from kan.app import app
from kan.data.tushare import DEFAULT_ENDPOINT
from kan.storage import config
from kan.storage.config import mask_token

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


def _print_token(cfg: dict, *, raw: bool = False) -> None:
    env_tok = os.environ.get("TUSHARE_TOKEN")
    cfg_tok = cfg.get("tushare_token")
    effective_tok = env_tok if env_tok else cfg_tok
    if effective_tok and isinstance(effective_tok, str) and effective_tok.strip():
        cleaned = effective_tok.strip()
        if raw:
            # 单 key 查 · 给原值 · 适合 token=$(kan config get tushare-token) 脚本场景
            typer.echo(cleaned)
            return
        masked = mask_token(cleaned)
        if env_tok:
            typer.echo(
                f"tushare_token: {masked}   "
                f"(set via TUSHARE_TOKEN env, overriding config)"
            )
        else:
            typer.echo(f"tushare_token: {masked}   (set via config)")
    else:
        # 未配置时给散户引导(U-8)· 而不是无声跳过该行
        typer.echo(
            "tushare_token: 未配置 · "
            "用 `kan config set tushare-token <你的_token>` "
            "启用 TuShare Pro 数据源(可选 · 不配也能跑)"
        )


def _print_endpoint(cfg: dict, *, raw: bool = False) -> None:
    env_ep = os.environ.get("TUSHARE_ENDPOINT")
    cfg_ep = cfg.get("tushare_endpoint")
    effective = env_ep or cfg_ep or DEFAULT_ENDPOINT
    if raw:
        typer.echo(effective)
        return
    if env_ep:
        typer.echo(
            f"tushare_endpoint: {env_ep}   "
            f"(set via TUSHARE_ENDPOINT env, overriding config)"
        )
    elif cfg_ep:
        typer.echo(f"tushare_endpoint: {cfg_ep}   (set via config)")
    else:
        # 默认状态也给 set 引导 · 对齐 _print_token 风格 ·
        # 自部署代理 / 内网镜像用户必须知道用 dash 不是 underscore (key 命名约定)
        typer.echo(
            f"tushare_endpoint: {DEFAULT_ENDPOINT} (默认 · "
            f"自部署代理用 `kan config set tushare-endpoint <url>` 切换)"
        )


@config_app.command("get")
def get_cmd(
    key: str | None = typer.Argument(
        None,
        help="可选 · 单 key 查询(tushare-token / tushare-endpoint)· "
             "未指定显示全部 · 单 key 模式输出原值(token 仍 mask)"
    ),
) -> None:
    """显示当前配置(token 自动 mask · env 覆盖时标注 · 未配置时给散户引导)。"""
    cfg = config.load()

    if key is not None:
        if key not in _KEY_MAP:
            typer.echo(
                f"❌ 未知配置项: {key}\n"
                f"   支持: {' / '.join(_KEY_MAP)}\n"
                f"   例: kan config get tushare-token",
                err=True,
            )
            raise typer.Exit(code=2)
        if _KEY_MAP[key] == "tushare_token":
            _print_token(cfg)
        else:
            _print_endpoint(cfg)
        return

    _print_token(cfg)
    _print_endpoint(cfg)


@config_app.command("set")
def set_cmd(
    key: str = typer.Argument(..., help="配置项名（tushare-token / tushare-endpoint）"),
    value: str = typer.Argument(..., help="配置值"),
) -> None:
    """设置一项配置（原子写入 ~/.local/share/kan/config.json）。"""
    if key not in _KEY_MAP:
        typer.echo(
            f"❌ 未知配置项: {key}\n"
            f"   支持: {' / '.join(_KEY_MAP)}\n"
            f"   例: kan config set tushare-token <你的_token>",
        )
        raise typer.Exit(code=2)

    internal_key = _KEY_MAP[key]
    cleaned = value.strip()

    if internal_key == "tushare_token" and not cleaned:
        typer.echo("❌ token 不能为空 · 例: kan config set tushare-token abc123def456")
        raise typer.Exit(code=2)
    if internal_key == "tushare_endpoint" and not cleaned.startswith(("http://", "https://")):
        typer.echo(
            "❌ 端点需以 http:// 或 https:// 开头\n"
            "   例: kan config set tushare-endpoint https://api.tushare.pro",
        )
        raise typer.Exit(code=2)

    cfg = config.load()
    cfg[internal_key] = cleaned
    config.save(cfg)

    if internal_key == "tushare_token":
        typer.echo(f"✅ 已保存 tushare_token ({mask_token(cleaned)}) 到 ~/.local/share/kan/config.json")
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
