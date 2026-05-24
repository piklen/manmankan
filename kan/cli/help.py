"""kan help 命令 · 命令速记 cheat-sheet 独立模块。

v0.0.5.0 起从 cli_watchlist_cmds 抽出 · 减少 cli_watchlist god-file 行数 ·
help 文案变更不再触发 cli_watchlist 编辑冲突。

注册机制:被 kan.cli 顶层 import 触发 @app.command 装饰器执行。
"""
from kan.app import app


@app.command(name="help")
def help_cmd() -> None:
    """查看命令帮助"""
    from rich.console import Console

    from kan import __version__

    # 速记表顶部加版本号 · issue 复现成本下降
    Console().print(f"""[bold]慢慢看 · v{__version__} · 命令速记[/bold]

[bold cyan]自选股管理[/bold cyan]
  kan add 600519 000858       添加自选股（代码）
  kan add 茅台                添加自选股（名称搜索）
  kan add --industry 半导体   按行业批量添加成分股（二次确认）
  kan add --theme AI          按题材批量添加成分股（二次确认）
  kan remove 600519 茅台      移除自选股（支持多只 + 名称）
  kan remove --industry 白酒  按行业批量移除自选 ∩ 该行业
  kan remove --theme AI       按题材批量移除自选 ∩ 该题材
  kan list                    查看自选列表
  kan list --industry 半导体  只列某行业的自选
  kan list --theme AI         只列某题材的自选
  kan import stocks.csv       CSV 批量导入
  kan clear                   清空自选列表

[bold cyan]位置扫描[/bold cyan]
  kan scan                  全景扫描 10 周期（低点模式）
  kan scan --high           全景扫描 10 周期（高点模式）
  kan scan -S               仅显示有共振信号的股票（--signal）
  kan scan --diff           显示与上次扫描的变化

[bold cyan]低点/高点筛选[/bold cyan]
  kan low 60                谁在 60 日低点？
  kan low 30 60 120         多周期一次看
  kan high 30               谁在 30 日高点？

[bold cyan]单只详情 / 多股对比[/bold cyan]
  kan info 600519                    单只股票全周期位置 + 涨跌 + 共振
  kan compare 600519 000858          多股横向对比（2-8 只 · -p 30,60,120）

[bold cyan]连续涨跌[/bold cyan]
  kan trend                 连续涨跌看板（不筛选）
  kan trend --down          只看连跌 ≥ 3 天（默认值）
  kan trend --down 5        只看连跌 ≥ 5 天
  kan trend --up            只看连涨 ≥ 3 天（默认值）
  kan trend --up 5          只看连涨 ≥ 5 天
  kan trend --latest 7      展示近 7 天走势详情
  kan trend --candle        阳线阴线口径（默认收盘价口径）
  kan trend --industry 半导体     行业范围连续涨跌（自选 ⭐ 高亮）
  kan trend --hot rank            热榜范围连续涨跌
  kan trend --theme AI应用        题材范围连续涨跌

  [dim]以上参数可任意组合：kan trend --down 5 --latest 7 --candle --industry 半导体[/dim]
  [dim]N 范围：2-30[/dim]

[bold cyan]行业 / 热榜 / 题材扫描[/bold cyan]
  kan scan --industry 半导体      扫指定行业全成分股（自选股 ⭐ 高亮）
  kan scan --hot rank             扫东财热榜（rank 人气榜 / surge 飙升榜）
  kan scan --theme AI应用         扫指定题材全成分股
  kan low 30 --industry 白酒      行业里筛 30 日低点
  kan high 60 --theme AI应用      题材里筛 60 日高点
  kan info --industry 半导体      查看行业板块档案
  kan theme list                  列出热门题材（top 30）
  kan theme search 数据要素       模糊搜题材

  [dim]scan / low / high / trend / fetch 全部支持 --industry / --hot / --theme 自由切换[/dim]
  [dim]--industry / --hot / --theme 三者互斥 · 加 --only-watchlist 取自选交集[/dim]

[bold cyan]导出格式[/bold cyan]
  kan scan --format md      markdown 表格输出
  kan scan --format json    JSON 结构化输出
  kan compare 600519 000858 --format md

  [dim]--format 适用 scan / low / high / info / trend / compare[/dim]

[bold cyan]数据管理[/bold cyan]
  kan fetch                 拉取数据（通常不需要，scan 自动更新）
  kan fetch --force         强制刷新
  kan fetch --industry X    预拉某行业全部成分股
  kan fetch --hot rank      预拉东财人气榜股票
  kan fetch --theme AI      预拉某题材全部成分股

[bold cyan]配置（tushare-pro 凭证）[/bold cyan]
  kan config get                              查看当前配置（全部）
  kan config get tushare-token                查看单 key（v0.0.5.1+）
  kan config set tushare-token <YOUR_TOKEN>   设 tushare 凭证
  kan config set tushare-endpoint https://x   设 tushare API 端点
  kan config unset tushare-token              清凭证

[bold cyan]版本管理[/bold cyan]
  kan update                检查并升级到最新版（会 prompt 确认）
  kan update --check        仅检查不升级
  kan update -y             跳过确认 · 用于脚本 / CI

[bold cyan]shell 命令补全[/bold cyan] (mac/linux/windows)
  kan completion install    安装补全脚本（自动检测 shell · 之后 kan s<Tab>=kan scan）
  kan completion install zsh  显式指定 shell（zsh/bash/fish/powershell）

[dim]涨跌停自动标记 · ST 默认显示，kan scan --exclude-st 可排除[/dim]
[dim]任何命令加 --help / -h 看详细说明[/dim]
""")
