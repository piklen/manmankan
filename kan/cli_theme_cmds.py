"""`kan theme` 子命令组 · 题材发现入口 · F11 引入。

参考 `cli_config_cmds.py` 体例(typer.Typer + add_typer 注册风格 LOCKED)。

子命令:
- theme list [--all]    列题材清单(默认拼音前 30 · --all 全部 ~391 + 散户超载警告)
- theme search 关键词    模糊搜题材

注:本版不实现"top N 活跃热度榜"(adata 无批量接口 · O(391) HTTP 触发反爬 · 留 F11.2)。
"""
from __future__ import annotations

import typer

from kan import boards
from kan.app import app

theme_app = typer.Typer(
    name="theme",
    help="题材板块管理(同花顺 ~391 个 · 一股归多个 · 标签型分类)",
    no_args_is_help=True,
)
app.add_typer(theme_app, name="theme")

_DEFAULT_LIST_TOP = 30


def _pinyin_key(name: str) -> str:
    """简易拼音首字母键 · 仅做排序用 · 中英混排兼容。

    实现:中文字符返回 'z' (排在 ASCII 后面),其他原样。
    完整拼音排序留作后续优化(本版用简易 fallback)。
    """
    if not name:
        return "z"
    first = name[0]
    if first.isascii():
        return first.lower()
    return "z" + name  # 中文统一压到 ASCII 后面 · 内部按中文 unicode 顺序


@theme_app.command("list")
def list_cmd(
    all_: bool = typer.Option(False, "--all", help="显示全部题材(~391 · 散户超载警告)"),
) -> None:
    """列题材清单(默认拼音前 30 · --all 全部)。"""
    try:
        catalog = boards.load_theme_catalog()
    except boards.ThemeDataUnavailableError as e:
        typer.echo(f"❌ 题材清单不可用: {e}", err=True)
        raise typer.Exit(1) from None

    total = len(catalog)
    sorted_catalog = sorted(catalog, key=lambda t: _pinyin_key(t.name))

    if all_:
        typer.echo(f"🎯 题材清单 · 全部 {total} 个(同花顺源)\n")
        display = sorted_catalog
    else:
        typer.echo(f"🎯 题材清单 · {total} 个(同花顺源 · 默认显示前 {_DEFAULT_LIST_TOP} 拼音序)\n")
        display = sorted_catalog[:_DEFAULT_LIST_TOP]

    for t in display:
        size_label = f"({t.size} 只成分股)" if t.size else ""
        typer.echo(f"  {t.code}  {t.name}  {size_label}".rstrip())

    typer.echo("")
    if not all_ and total > _DEFAULT_LIST_TOP:
        typer.echo(f"💡 共 {total} 个题材 · 看全部:kan theme list --all  ·  模糊搜:kan theme search 关键词")
    typer.echo("💡 题材是标签 · 一只股可能在多个题材中(科大讯飞同属 AI/教育/智慧城市等)")
    typer.echo("💡 题材分类各家口径不同 · 这是同花顺口径")
    typer.echo("⚠️  题材跟「投机炒作」是 CSRC 监管重点 · 用工具看位置不等于买卖建议")


@theme_app.command("search")
def search_cmd(
    keyword: str = typer.Argument(..., help="题材关键词(模糊匹配)"),
) -> None:
    """模糊搜题材 · 列所有命中候选。"""
    from kan.boards import normalize_theme_name

    try:
        catalog = boards.load_theme_catalog()
    except boards.ThemeDataUnavailableError as e:
        typer.echo(f"❌ 题材清单不可用: {e}", err=True)
        raise typer.Exit(1) from None

    k_norm = normalize_theme_name(keyword)
    matches = [t for t in catalog if k_norm in normalize_theme_name(t.name)]

    if not matches:
        typer.echo(f"未找到含「{keyword}」的题材 · 0 个候选")
        return

    typer.echo(f"🔍 搜「{keyword}」· 命中 {len(matches)} 个候选:\n")
    for t in matches[:30]:  # 最多展示 30 候选 · 防刷屏
        typer.echo(f"  {t.code}  {t.name}")
    if len(matches) > 30:
        typer.echo(f"\n  ... 还有 {len(matches) - 30} 个 · 用更具体关键词缩小范围")
    typer.echo("")
    typer.echo("💡 用完整题材名跑扫描:kan scan --theme=AI应用")
