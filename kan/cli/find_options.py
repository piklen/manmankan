"""`kan find` Typer 参数注解。"""
from __future__ import annotations

from typing import Annotated

import typer

from kan.core.find_registry import format_find_field_presets
from kan.data.hot import HotList
from kan.storage import export

PosOption = Annotated[
    list[str],
    typer.Option(
        "--pos",
        help="位置 filter PERIOD:OP:VAL 例 180:lt:5 (180 日位置 < 5%) · 可多次",
    ),
]

ResonanceOption = Annotated[
    list[str],
    typer.Option(
        "--resonance",
        help="共振 filter LEVEL:OP:VAL 例 low:gte:3 (低点共振 ≥ 3 周期) · 可多次",
    ),
]

ExcludeStOption = Annotated[
    bool,
    typer.Option("--exclude-st", help="排除 ST/*ST 股票"),
]

ExcludeStarOption = Annotated[
    bool,
    typer.Option("--exclude-star", help="排除科创板股票"),
]

ExcludeBjOption = Annotated[
    bool,
    typer.Option("--exclude-bj", help="排除北交所股票"),
]

MatchAnyOption = Annotated[
    bool,
    typer.Option("--any", help="任一 filter 命中即返回；默认所有 filter 都需命中"),
]

PeOption = Annotated[
    list[str],
    typer.Option(
        "--pe",
        help="估值 filter OP:VAL 例 lt:20 (PE TTM < 20 · 裸值筛) · 可多次",
    ),
]

PbOption = Annotated[
    list[str],
    typer.Option(
        "--pb",
        help="估值 filter OP:VAL 例 lt:3 (PB < 3 · 裸值筛) · 可多次",
    ),
]

TurnoverOption = Annotated[
    list[str],
    typer.Option(
        "--turnover",
        help="换手率 filter OP:VAL 例 gt:5 (换手 > 5% · 裸值筛) · 可多次",
    ),
]

MarketCapOption = Annotated[
    list[str],
    typer.Option(
        "--market-cap",
        help="总市值 filter OP:VAL 例 gt:100 (总市值 > 100 亿 · 单位亿元) · 可多次",
    ),
]

VolumeRatioOption = Annotated[
    list[str],
    typer.Option(
        "--volume-ratio",
        help="量比 filter OP:VAL 例 gt:1.5 (量比 > 1.5 · 裸值筛) · 可多次",
    ),
]

RoeOption = Annotated[
    list[str],
    typer.Option(
        "--roe",
        help="质量 filter OP:VAL 例 gte:15 (ROE ≥ 15%) · 逐股 · --all 不支持 · 可多次",
    ),
]

MoneyflowOption = Annotated[
    list[str],
    typer.Option(
        "--moneyflow",
        help="主力资金 filter OP:VAL 例 gt:0 (近 5 日合计优先 · 单位万元) · 可多次",
    ),
]

MoneyflowDailyOption = Annotated[
    list[str],
    typer.Option(
        "--moneyflow-daily",
        help="单日主力净额 filter OP:VAL 例 gt:0 (单位万元) · 可多次",
    ),
]

MoneyflowDaysOption = Annotated[
    list[str],
    typer.Option(
        "--moneyflow-days",
        help="连续主力净流入天数 filter OP:VAL 例 gte:3 · 可多次",
    ),
]

RsiOption = Annotated[
    list[str],
    typer.Option(
        "--rsi",
        help="技术 filter OP:VAL 例 lt:30 (RSI 6 日 · 前复权裸值) · 可多次",
    ),
]

MacdDifOption = Annotated[
    list[str],
    typer.Option(
        "--macd-dif",
        help="技术 filter OP:VAL 例 gt:0 (MACD DIF 快线) · 可多次",
    ),
]

MacdOption = Annotated[
    list[str],
    typer.Option(
        "--macd",
        help="技术 filter OP:VAL 例 gt:0 (MACD 柱 · 柱>0=DIF 在 DEA 上方) · 可多次",
    ),
]

KdjJOption = Annotated[
    list[str],
    typer.Option(
        "--kdj-j",
        help="技术 filter OP:VAL 例 lt:20 (KDJ J 值) · 可多次",
    ),
]

StreakOption = Annotated[
    list[str],
    typer.Option(
        "--streak",
        help="情绪 filter OP:VAL 例 gte:3 (连板天数 ≥ 3 · 不含 ST) · 可多次",
    ),
]

WinnerOption = Annotated[
    list[str],
    typer.Option(
        "--winner",
        help="筹码 filter OP:VAL 例 gte:50 (获利盘 ≥ 50%) · 可多次",
    ),
]

MaBiasOption = Annotated[
    list[str],
    typer.Option(
        "--ma-bias",
        help="乖离率 filter PERIOD:OP:VAL 例 20:gt:0 (收盘距 20 日线 % · 裸值) · 可多次",
    ),
]

GainOption = Annotated[
    list[str],
    typer.Option(
        "--gain",
        help="涨幅 filter PERIOD:OP:VAL 例 30:gt:20 (近 30 日涨幅 % · K 线池) · 可多次",
    ),
]

AtrPctOption = Annotated[
    list[str],
    typer.Option(
        "--atr-pct",
        help="波动率 filter OP:VAL 例 lt:5 (ATR/close % · 裸值) · 可多次",
    ),
]

UpDaysOption = Annotated[
    list[str],
    typer.Option(
        "--up-days",
        help="连阳天数 filter OP:VAL 例 gte:3 (连续阳线数 · K 线池) · 可多次",
    ),
]

RsIndexOption = Annotated[
    list[str],
    typer.Option(
        "--rs-index",
        help="相对大盘 filter PERIOD:OP:VAL 例 30:gt:0 (个股 − 大盘指数 涨幅差% · 跑赢=正) · 可多次",
    ),
]

RsBoardOption = Annotated[
    list[str],
    typer.Option(
        "--rs-board",
        help="相对行业 filter PERIOD:OP:VAL 例 30:gt:0 (个股 − 所属申万一级行业 涨幅差% · 跑赢=正) · 可多次",
    ),
]

RsIndexCodeOption = Annotated[
    str,
    typer.Option(
        "--rs-index-code",
        help="--rs-index 对照指数 (默认沪深300 · 支持别名 上证/深成/创业板/沪深300 或 ts_code)",
    ),
]

HoldersOption = Annotated[
    list[str],
    typer.Option(
        "--holders",
        help="股东 filter OP:VAL 例 lt:0 (户数环比减少) · 逐股 · --all 不支持 · 可多次",
    ),
]

Top10Option = Annotated[
    list[str],
    typer.Option(
        "--top10",
        help="股东 filter OP:VAL 例 gte:50 (前十大流通集中度%) · 逐股 · --all 不支持 · 可多次",
    ),
]

NorthOption = Annotated[
    list[str],
    typer.Option(
        "--north",
        help="股东 filter OP:VAL 例 gte:3 (北向持股% · 香港中央结算季度代理) · 逐股 · --all 不支持 · 可多次",
    ),
]

IndustryOption = Annotated[
    str | None,
    typer.Option("--industry", help="池: 申万行业 (例 半导体)"),
]

HotOption = Annotated[
    HotList | None,
    typer.Option("--hot", help="池: 东财热榜 rank|surge"),
]

ThemeOption = Annotated[
    str | None,
    typer.Option("--theme", help="池: 题材成分股 (例 AI应用)"),
]

OnlyWatchlistOption = Annotated[
    bool,
    typer.Option(
        "--only-watchlist",
        help="只查自选；配合 industry/hot/theme 时取交集",
    ),
]

OnlyHoldingsOption = Annotated[
    bool,
    typer.Option("--only-holdings", help="池: 只查真实持仓"),
]

GroupOption = Annotated[
    str | None,
    typer.Option("--group", "-g", help="自选股分组 (默认 default 组)"),
]

LimitOption = Annotated[
    int | None,
    typer.Option(
        "--limit",
        help="输出条数上限 (默认 K 线模式 50 · --all 截面模式全量)",
    ),
]

OffsetOption = Annotated[
    int,
    typer.Option(
        "--offset",
        help="跳过前 N 条 (配合 --limit 分页 · 默认 0)",
    ),
]

SortOption = Annotated[
    str | None,
    typer.Option(
        "--sort",
        help=(
            "排序 FIELD:asc|desc · FIELD 取 "
            "pe/pb/turnover/market-cap/volume-ratio/moneyflow/moneyflow-daily/moneyflow-days · "
            "例 moneyflow:desc"
        ),
    ),
]

AllStocksOption = Annotated[
    bool,
    typer.Option(
        "--all",
        help="全市场截面取数 ~5500 只 (估值/资金/技术/位置/涨幅/连阳 · 需 token)",
    ),
]

CodesOption = Annotated[
    str | None,
    typer.Option(
        "--codes",
        help="池: 自定义代码列表 (逗号/空格/换行分隔；传 - 从 stdin 读)",
    ),
]

FormatOption = Annotated[
    export.OutputFormat,
    typer.Option("--format", help="输出格式:terminal(默认)/ md / json(AI 消费)"),
]

CompactOption = Annotated[
    bool,
    typer.Option(
        "--compact",
        help="仅用于 --format json:输出低字段量结果 + data_availability",
    ),
]

CompactContextOption = Annotated[
    bool,
    typer.Option(
        "--compact-context/--no-compact-context",
        help="仅用于 --format json --compact:是否输出位置/共振 K 线上下文",
    ),
]

FieldsOption = Annotated[
    list[str],
    typer.Option(
        "--fields",
        help=(
            "仅用于 --format json:字段白名单或 @preset,"
            f"可用 {format_find_field_presets()}"
        ),
    ),
]

ExplainOption = Annotated[
    bool,
    typer.Option(
        "--explain",
        help="仅输出查询计划：候选池、数据源、字段维度和成本提示，不实际取数",
    ),
]

DryRunOption = Annotated[
    bool,
    typer.Option(
        "--dry-run",
        help="等价于 --explain；用于 agent 调用前预演查询路径",
    ),
]

AgentSummaryOption = Annotated[
    bool,
    typer.Option(
        "--agent-summary",
        help="仅用于 --format json:返回字段覆盖、缺数、分布和少量样本",
    ),
]

SnapshotOption = Annotated[
    bool,
    typer.Option(
        "--snapshot",
        help="仅用于 --format json:显式保存本次结构化结果，返回 snapshot.id",
    ),
]

SinceOption = Annotated[
    str | None,
    typer.Option(
        "--since",
        help="仅用于 --format json:和指定 snapshot.id 比较，返回 delta",
    ),
]
