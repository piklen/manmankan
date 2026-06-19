"""Root help text shared by the full Typer app and the fast console entry path."""
from __future__ import annotations


def root_help_text() -> str:
    """Build the Chinese root cheat sheet without importing all CLI command modules."""
    from kan.core.find_registry import (
        format_find_field_presets,
        format_find_filter_groups,
    )

    find_filter_groups = "\n  ".join(format_find_filter_groups().splitlines())
    find_field_presets = format_find_field_presets()

    return f"""[bold]慢慢看 · 命令速记[/bold]

[bold cyan]自选股管理[/bold cyan]
  kan add 600519 000858       添加自选股（代码）
  cat codes.txt | kan add -   从 stdin 批量添加代码
  kan add 600519 --fetch      添加后立即拉取 K 线缓存
  kan add 茅台                添加自选股（名称搜索）
  kan add --industry 半导体   按行业批量添加成分股（二次确认）
  kan add --theme AI          按题材批量添加成分股（二次确认）
  kan remove 600519 茅台      移除自选股（支持多只 + 名称）
  kan remove --industry 白酒  按行业批量移除自选 ∩ 该行业
  kan remove --theme AI       按题材批量移除自选 ∩ 该题材
  kan list                    查看自选列表
  kan list --industry 半导体  只列某行业的自选
  kan list --theme AI         只列某题材的自选
  kan group                   管理自选股分组
  kan import stocks.csv       CSV 批量导入
  kan clear                   清空自选列表

[bold cyan]真实持仓[/bold cyan]
  kan hold add 600519 --cost 1680 --shares 100  手动录入持仓事实
  kan hold add 600519 --cost 1600 --shares 100 --add  追加录入并重算均价
  kan hold reduce 600519 --shares 100           减少持股数
  kan hold cash 73000                           更新现金
  kan hold import positions.csv                 CSV 批量导入持仓
  kan hold                                      持仓盈亏 + 仓位 + 位置总览
  kan hold --format json --mask                 JSON 输出并脱敏金额
  kan hold scan                                 只扫描真实持仓池

[bold cyan]位置扫描[/bold cyan]
  新手从 kan scan 和 kan find 开始
  kan scan                  默认池全景扫描（自选 ∪ 持仓）
  kan scan --only-holdings  只扫描真实持仓池
  kan scan --wide           窄屏也展示全部周期
  kan scan --compact        只展示短/中/长关键周期
  kan scan --periods 5,20,60,180  自定义 2-360 周期集合
  kan scan --high           全景扫描（高点模式）
  kan scan -S               仅显示有共振信号的股票（--signal）
  kan scan --diff           显示与上次扫描的变化

[bold cyan]低点/高点筛选[/bold cyan]
  kan low 60                谁在 60 日低点？（find --pos 快捷入口）
  kan low 30 60 120         多周期一次看
  kan high 30               谁在 30 日高点？（find --pos 快捷入口）

[bold cyan]单只详情 / 多股对比 / 历史回溯[/bold cyan]
  kan info 600519                    单只股票全周期位置 + 涨跌 + 共振
  kan compare 600519 000858          多股横向对比（2-30 只 · 终端自动分页）
  kan history 600519                 位置历史回溯（-p 切周期 · 纯离线读每日快照）
  kan index                          常用大盘指数位置参照（上证/深成/创业板/沪深300）

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

[bold cyan]条件筛选[/bold cyan]
  kan find --pos 180:lt:5                      位置 filter · 180 日位置 < 5%
  kan find --resonance low:gte:3               共振 filter · 低点共振 ≥ 3 周期
  kan find --pos 60:lt:10 --resonance low:gte:2  多条件 AND
  kan find --any --pos 20:lt:10 --moneyflow-daily gt:10000  多条件任一命中
  kan find --exclude-st --pos 180:lt:5         排 ST · 位置 filter
  kan find --only-holdings --format json       真实持仓池取数
  kan find --industry 半导体 --pos 180:lt:10   行业池里筛 180 日位置 < 10%
  kan find --codes 600519,000858 --gain 30:gt:10  任意代码池里筛近 30 日涨幅
  cat codes.txt | kan find --codes - --pos 60:lt:20  stdin 代码池
  kan find --all --up-days gte:3               全市场截面筛连涨天数
  kan find --pos 180:lt:5 --limit 20           自定义输出条数
  kan find --industry 半导体 --format json     整池全维度 JSON(AI 取数 · 无 filter 即取数)
  kan find --all --pe lt:20 --format json --compact  低字段量 JSON
  kan find --all --pe lt:20 --format json --compact --no-compact-context  省略 K 线上下文
  kan find --industry 半导体 --format json --fields @core,@valuation

  [dim]PERIOD: 2-360 任意整数 · OP: lt/lte/gt/gte/eq/ne · LEVEL: low/high[/dim]
  [dim]单维度 filter 只反映该维度 · 默认 AND；--any 为任一 filter 命中 · 命中不等于整体位置低/高[/dim]
  [dim]可用 filter 分组:
  {find_filter_groups}[/dim]
  [dim]可用 fields preset:
  {find_field_presets}[/dim]
  [dim]告诉你坐标，不替你决策 · 命中条件 ≠ 买入信号[/dim]

[bold cyan]行业 / 热榜 / 题材扫描[/bold cyan]
  kan scan --industry 半导体      扫指定行业全成分股（自选股 ⭐ 高亮）
  kan scan --hot rank             扫东财热榜（rank 人气榜 / surge 飙升榜）
  kan scan --theme AI应用         扫指定题材全成分股
  kan low 30 --industry 白酒      行业里筛 30 日低点
  kan high 60 --theme AI应用      题材里筛 60 日高点
  kan info --industry 半导体      查看行业板块档案
  kan theme list                  列出热门题材（top 30）
  kan theme search 数据要素       模糊搜题材
  kan theme trend --min-streak 1  题材连涨榜阈值下探到 1 天
  kan theme trend --sort latest   按最新单日涨幅排序
  kan board rank --kind industry --by moneyflow  行业资金净额榜
  kan board rank --kind theme --by pos -p 30      题材位置分位榜

  [dim]scan / low / high / trend / fetch 全部支持 --industry / --hot / --theme 自由切换[/dim]
  [dim]find 支持 --industry / --hot / --theme / --all / --codes / --only-holdings 候选池 · 池参数互斥[/dim]

[bold cyan]导出格式[/bold cyan]
  kan scan --format md      markdown 表格输出
  kan scan --format json    JSON 结构化输出
  kan compare 600519 000858 --format md
  kan board rank --kind industry --by gain --format json

  [dim]--format 适用 scan / low / high / info / trend / compare / history / find / hold / board rank[/dim]

[bold cyan]数据管理[/bold cyan]
  kan fetch                 拉取数据（通常不需要，scan 自动更新）
  kan fetch --force         强制刷新
  kan fetch --verbose       逐只输出拉取状态
  kan fetch --industry X    预拉某行业全部成分股
  kan fetch --hot rank      预拉东财人气榜股票
  kan fetch --theme AI      预拉某题材全部成分股

[bold cyan]配置（tushare-pro 凭证）[/bold cyan]
  kan config get                              查看当前配置（全部）
  kan config get tushare-token                查看单 key
  kan config set tushare-token <YOUR_TOKEN>   设 tushare 凭证
  kan config set tushare-endpoint https://x   设 tushare API 端点
  kan config unset tushare-token              清凭证

[bold cyan]版本管理[/bold cyan]
  kan update                检查并升级到最新版（会 prompt 确认）
  kan update --check        仅检查不升级
  kan update -y             跳过确认 · 用于脚本 / CI

[bold cyan]shell 命令补全[/bold cyan] (mac/linux/windows)
  kan setup                 交互式配置补全 + MCP（检测环境后让你选择）
  kan completion install    安装补全脚本（自动检测 shell · 之后 kan s<Tab>=kan scan）
  kan completion install zsh  显式指定 shell（zsh/bash/fish/powershell）

[bold cyan]AI / MCP[/bold cyan]
  kan examples              查看 3-5 个端到端工作流
  kan fields list           查看 find JSON 字段白名单
  kan mcp install           注册 manmankan MCP 到本机常见客户端
  kan mcp serve             启动 stdio MCP server
  kan mcp http              启动本机 Streamable HTTP MCP endpoint

[dim]涨跌停自动标记 · ST 默认显示，kan scan --exclude-st 可排除[/dim]
[dim]任何命令加 --help / -h 看详细说明[/dim]
"""


def print_root_help() -> None:
    """Render the root help with Rich styling."""
    from rich.console import Console

    Console().print(root_help_text())
