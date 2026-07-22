"""kan find · 用户主导的条件筛选 DSL。

按用户输入条件 · 在自选/行业/题材/热榜池里筛符合的股票。
"工具仅返回数据 · 不替你判断"

AI JSON 层 (AI 消费入口):
- `--format json`:命中股票带全维度 metadata (triggered_filters + context + valuation)
- `--format md`:markdown 表格
- 无 filter + `--format json|md`:整池全维度 (= AI 取数环节 · 不带 filter = 数据 provider)
- 强制 disclaimer 字段 (compliance §5/§7 · 项目内强制输出 · 测试守护)

合规(manmankan/docs/compliance.md §7):
- 用户显式指定 filter · 不内置筛选策略 preset
- 输出 "符合条件的股票" · 不"推荐"
- 估值/质量/资金/技术/股东等裸值可按用户 filter 输出
"""
from __future__ import annotations

import typer

import kan.cli.find_options as opt
from kan.app import app
from kan.cli.find_io import _exit_find_error, _resolve_code_pairs_or_exit_json
from kan.cli.find_runner import _run_all_stocks_path, _run_kline_path
from kan.core.find_registry import (
    dimensions_from_fields,
    parse_find_fields,
)
from kan.data.relative_strength import DEFAULT_RS_INDEX
from kan.storage import export


@app.command()
def find(
    pos: opt.PosOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    resonance: opt.ResonanceOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    exclude_st: opt.ExcludeStOption = False,
    exclude_star: opt.ExcludeStarOption = False,
    exclude_bj: opt.ExcludeBjOption = False,
    match_any: opt.MatchAnyOption = False,
    pe: opt.PeOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    pb: opt.PbOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    turnover: opt.TurnoverOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    market_cap: opt.MarketCapOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    volume_ratio: opt.VolumeRatioOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    roe: opt.RoeOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    moneyflow: opt.MoneyflowOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    moneyflow_daily: opt.MoneyflowDailyOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    moneyflow_days: opt.MoneyflowDaysOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rsi: opt.RsiOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    macd_dif: opt.MacdDifOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    macd: opt.MacdOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    kdj_j: opt.KdjJOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    streak: opt.StreakOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    winner: opt.WinnerOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    ma_bias: opt.MaBiasOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    gain: opt.GainOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    atr_pct: opt.AtrPctOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    up_days: opt.UpDaysOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rs_index: opt.RsIndexOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rs_board: opt.RsBoardOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    rs_index_code: opt.RsIndexCodeOption = DEFAULT_RS_INDEX,
    holders: opt.HoldersOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    top10: opt.Top10Option = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    north: opt.NorthOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    industry: opt.IndustryOption = None,
    hot: opt.HotOption = None,
    theme: opt.ThemeOption = None,
    only_watchlist: opt.OnlyWatchlistOption = False,
    only_holdings: opt.OnlyHoldingsOption = False,
    group: opt.GroupOption = None,
    limit: opt.LimitOption = None,
    offset: opt.OffsetOption = 0,
    sort: opt.SortOption = None,
    all_stocks: opt.AllStocksOption = False,
    codes: opt.CodesOption = None,
    fmt: opt.FormatOption = export.OutputFormat.terminal,
    compact: opt.CompactOption = False,
    compact_context: opt.CompactContextOption = True,
    fields: opt.FieldsOption = [],  # noqa: B006 · typer multi-option 需要 list 默认值
    explain: opt.ExplainOption = False,
    dry_run: opt.DryRunOption = False,
    agent_summary: opt.AgentSummaryOption = False,
    snapshot: opt.SnapshotOption = False,
    since: opt.SinceOption = None,
) -> None:
    """按你的规则筛股 · 不替你定规则。

    示例:
      kan find --pos 180:lt:5                          # 180 日位置 < 5%
      kan find --resonance low:gte:3                   # 低点共振 ≥ 3 周期
      kan find --pos 60:lt:10 --resonance low:gte:2    # 多条件 AND
      kan find --any --pos 20:lt:10 --moneyflow-daily gt:10000  # 任一 filter 命中
      kan find --industry 半导体 --pos 180:lt:10       # 半导体里 180 日位置 < 10%
      kan find --exclude-st --pos 180:lt:5             # 排 ST + 位置 filter
      kan find --industry 半导体 --format json         # 整池全维度 JSON(AI 取数)
      kan find --industry 半导体 --pe lt:30 --moneyflow-daily gt:0  # 估值+资金组合
      kan find --all --pe lt:20 --format json          # 全市场 PE<20 截面筛
      kan find --all --pe lt:20 --format json --compact --no-compact-context
      kan find --all --pe lt:20 --format json --fields @core,@valuation
      kan find --codes 600519,000858 --pos 180:lt:20   # 自定义代码池里筛位置
      printf "600519\n000858\n" | kan find --codes - --gain 30:gt:10
      kan find --all --rsi lt:30 --streak gte:3 --format json  # 全市场 RSI<30 + 连板≥3
      kan find --industry 半导体 --top10 gte:50 --format json  # 半导体里前十大流通集中度≥50%

    Filter:
      单维度 filter 只反映该维度 · 命中不等于整体位置低/高 · 多维度请叠加 filter 或用 kan info 看全周期
      默认所有 filter 都需命中；加 --any 时任一 filter 命中即返回，triggered_filters 记录实际命中项
      核心层:
        --pos PERIOD:OP:VAL    PERIOD 取 2-360 任意整数 · OP 取 lt/lte/gt/gte/eq/ne
        --resonance LEVEL:OP:VAL   LEVEL 取 low/high · OP 同上 · VAL 取 [0, 10]
        --exclude-st           排 ST (quiet · 不记 triggered)
        --exclude-star         排科创板
        --exclude-bj           排北交所
      估值 / 质量 / 资金:
        --pe OP:VAL            PE TTM 裸值筛 · 例 lt:20
        --pb OP:VAL            PB 裸值筛 · 例 lt:3
        --turnover OP:VAL      换手率% 裸值筛 · 例 gt:5
        --market-cap OP:VAL    总市值(亿元)裸值筛 · 例 gt:100
        --volume-ratio OP:VAL  量比裸值筛 · 例 gt:1.5
        --roe OP:VAL           ROE % 裸值筛 · 例 gte:15 · 逐股 · --all 不支持
        --moneyflow OP:VAL     主力净额(万元) · 近 5 日合计优先,缺失回落单日 · 例 gt:0
        --moneyflow-daily OP:VAL  单日主力净额(万元) · 例 gt:0
        --moneyflow-days OP:VAL   连续主力净流入天数 · 例 gte:3
      技术 / 趋势动量（进阶 · 需理解口径）:
        --rsi/--macd-dif/--macd/--kdj-j OP:VAL  技术裸值筛 · 前复权 · 例 --rsi lt:30
        --ma-bias PERIOD:OP:VAL  乖离率 · PERIOD 取 2-360 任意整数 · 例 20:gt:0
        --gain PERIOD:OP:VAL   近 N 日涨幅% · 例 30:gt:20 · K 线池/--all 预计算快照
        --atr-pct OP:VAL       ATR 波动率% · 例 lt:5 (atr/close · 裸值)
        --up-days OP:VAL       连阳天数 · 例 gte:3 · K 线池/--all 预计算快照
      情绪 / 筹码 / 股东（进阶 · 需理解披露与缺数据口径）:
        --streak OP:VAL        连板天数 · 例 gte:3 · 不含 ST
        --winner OP:VAL        获利盘% · 例 gte:50
        --holders OP:VAL       股东户数环比% · 例 lt:0 · 逐股 · --all 不支持
        --top10 OP:VAL         前十大流通集中度% · 例 gte:50 · 逐股 · --all 不支持
        --north OP:VAL         北向持股% · 例 gte:3 (香港中央结算季度代理) · 逐股 · --all 不支持

    输出 (AI JSON 层):
      --format terminal  默认 · Rich 表格 (需至少一个 filter)
      --format json      AI 友好 · 命中带 metadata · 无 filter = 整池取数
      --compact          json 低字段量输出 · 适合脚本/外部模型首轮筛选
      --no-compact-context  compact 不输出 positions/resonance,避免无 K 线 filter 时取快照
      --fields LIST      json 字段白名单或 @preset · 例 @core,@valuation
      --agent-summary    json 低上下文摘要:字段覆盖/缺数/分布/样本
      --dry-run/--explain  json 查询计划:数据源/维度/成本提示,不实际取数
      --snapshot/--since json 显式会话快照 / delta
      --format md        markdown 表格

    池 selector (跟 kan scan 一致 · 三者互斥):
      --industry NAME / --hot rank|surge / --theme NAME (不指定默认自选)
      --codes LIST (逗号/空格/换行分隔 · `--codes -` 从 stdin 读)
      --only-watchlist 只查自选；配合 pool 时取交集
      --only-holdings 只查真实持仓
      --group GROUP (选自选股具名组)
    """
    from rich.console import Console

    from kan.core.find_dsl import ConditionSet, FilterParseError
    from kan.render.base import FIND_DISCLAIMER_TEXT

    console = Console()
    find_disclaimer = f"[bold dim]{FIND_DISCLAIMER_TEXT}[/bold dim]"
    is_export = fmt is not export.OutputFormat.terminal
    if fmt is export.OutputFormat.csv:
        _exit_find_error(
            fmt,
            code="invalid_format",
            message="kan find 不支持 --format csv · 请用 --format json 或 --format md",
            hint="例: kan find --pos 180:lt:5 --format json；或 kan scan --format csv 导出扫描结果",
            exit_code=2,
        )
    if (explain or dry_run or agent_summary or snapshot or since) and fmt is not export.OutputFormat.json:
        _exit_find_error(
            fmt,
            code="invalid_agent_option",
            message="--explain/--dry-run/--agent-summary/--snapshot/--since 仅支持 --format json",
            hint="例: kan find --codes 600519,000858 --format json --dry-run",
            exit_code=2,
        )
    if compact and fmt is not export.OutputFormat.json:
        _exit_find_error(
            fmt,
            code="invalid_compact",
            message="--compact 仅支持 --format json",
            hint="例: kan find --pos 180:lt:5 --format json --compact",
            exit_code=2,
        )
    if not compact_context and not compact:
        _exit_find_error(
            fmt,
            code="invalid_compact_context",
            message="--no-compact-context 只能和 --format json --compact 一起使用",
            hint="例: kan find --all --pe lt:20 --format json --compact --no-compact-context",
            exit_code=2,
        )
    if fields and fmt is not export.OutputFormat.json:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message="--fields 仅支持 --format json",
            hint="例: kan find --industry 半导体 --format json --fields @core,@valuation",
            exit_code=2,
        )
    if compact and fields:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message="--fields 与 --compact 不能同时使用",
            hint=(
                "二者都定义结果字段形态；需要显式字段时只用 --fields。"
                "例: kan find --format json --fields @core,@valuation"
            ),
            exit_code=2,
        )
    try:
        field_paths = parse_find_fields(fields)
    except ValueError as e:
        _exit_find_error(
            fmt,
            code="invalid_fields",
            message=str(e),
            hint="例: --fields @core,@valuation 或 --fields code,name,price",
            exit_code=2,
        )
    field_dimensions = dimensions_from_fields(field_paths)

    # 0. Validate --limit · 防 Python 负切片导致的 silent data loss
    # limit=None 哨兵:K 线模式后续解析为 50 · 截面模式 (--all) 为全量。
    if limit is not None and limit <= 0:
        _exit_find_error(
            fmt,
            code="invalid_limit",
            message="--limit 必须为正整数",
            hint="例: kan find --pos 180:lt:5 --limit 20",
            exit_code=2,
        )

    # 1. Parse DSL flags
    try:
        conditions = ConditionSet.from_flags(
            pos=pos,
            resonance=resonance,
            pe=pe,
            pb=pb,
            turnover=turnover,
            market_cap=market_cap,
            volume_ratio=volume_ratio,
            roe=roe,
            moneyflow=moneyflow,
            moneyflow_daily=moneyflow_daily,
            moneyflow_days=moneyflow_days,
            rsi=rsi,
            macd_dif=macd_dif,
            macd=macd,
            kdj_j=kdj_j,
            streak=streak,
            winner=winner,
            ma_bias=ma_bias,
            gain=gain,
            atr_pct=atr_pct,
            up_days=up_days,
            rs_index=rs_index,
            rs_board=rs_board,
            holders=holders,
            top10=top10,
            north=north,
            exclude_st=exclude_st,
            match_any=match_any,
        )
    except FilterParseError as e:
        _exit_find_error(
            fmt,
            code="invalid_filter",
            message=str(e),
            hint="例: kan find --pos 180:lt:5 或 kan find --resonance low:gte:3",
            exit_code=2,
        )

    # 解析 --sort FIELD:asc|desc → (field, direction) · 校验字段与方向
    sort_spec: tuple[str, str] | None = None
    if sort is not None:
        from kan.service.find_service import SORT_FIELD_GETTERS
        raw_parts = sort.split(":")
        field = raw_parts[0].strip().replace("-", "_")  # market-cap → market_cap
        direction = raw_parts[1].strip().lower() if len(raw_parts) > 1 else "desc"
        if field not in SORT_FIELD_GETTERS:
            _exit_find_error(
                fmt,
                code="invalid_sort",
                message=f"--sort 字段 '{raw_parts[0]}' 不支持",
                hint=f"可选: {', '.join(SORT_FIELD_GETTERS)} · 例: --sort moneyflow:desc",
                exit_code=2,
            )
        if direction not in ("asc", "desc"):
            _exit_find_error(
                fmt,
                code="invalid_sort",
                message=f"--sort 方向 '{direction}' 不支持",
                hint="只支持 asc|desc · 例: --sort pe:asc",
                exit_code=2,
            )
        sort_spec = (field, direction)

    # 无 filter:terminal 默认报错引导 (人类 UX 不变 · 测试守护);
    # json/md 放开 = AI 取数环节 (整池全维度 · 不带 filter = 数据 provider)。
    if conditions.is_empty() and not is_export and not all_stocks:
        _exit_find_error(
            fmt,
            code="missing_filter",
            message="terminal 模式至少需要一个 filter",
            hint=(
                "例: kan find --pos 180:lt:5；kan find --pe lt:20；"
                "取数模式例: kan find --codes 600519,000858 --format json"
            ),
            exit_code=1,
        )

    # 2. Validate pool flags (复用 scan 互斥校验)
    if sum(1 for x in (industry, hot, theme, codes) if x is not None) > 1:
        _exit_find_error(
            fmt,
            code="mutually_exclusive_pool",
            message="--industry / --hot / --theme / --codes 四者互斥",
            hint="例: kan find --industry 半导体 --pos 180:lt:10",
            exit_code=2,
        )
    source_mode = industry is not None or hot is not None or theme is not None or codes is not None
    if all_stocks and source_mode:
        _exit_find_error(
            fmt,
            code="mutually_exclusive_pool",
            message="--all 与 --industry / --hot / --theme / --codes 互斥",
            hint="例: kan find --all --pe lt:20 --format json",
            exit_code=2,
        )
    if all_stocks and only_watchlist:
        _exit_find_error(
            fmt,
            code="invalid_all_pool",
            message="--all 与 --only-watchlist 不能同时使用",
            hint="例: kan find --all --pe lt:20 --format json",
            exit_code=2,
        )
    if all_stocks and group is not None:
        _exit_find_error(
            fmt,
            code="invalid_all_pool",
            message="--all 已指定全市场池，不再叠加 --group",
            hint="例: kan find --all --pe lt:20 --format json；或 kan find --group <组名> --format json",
            exit_code=2,
        )
    if codes is not None and only_watchlist:
        _exit_find_error(
            fmt,
            code="invalid_codes_pool",
            message="--codes 与 --only-watchlist 不能同时使用",
            hint="例: kan find --codes 600519,000858 --pos 180:lt:20",
            exit_code=2,
        )
    if codes is not None and group is not None:
        _exit_find_error(
            fmt,
            code="invalid_codes_pool",
            message="--codes 已显式指定候选池，不再叠加 --group",
            hint="例: kan find --codes 600519,000858 --gain 30:gt:10",
            exit_code=2,
        )
    if only_holdings and source_mode:
        _exit_find_error(
            fmt,
            code="invalid_holdings_pool",
            message="--only-holdings 不能和 --industry / --hot / --theme / --codes 同时使用",
            hint="例: kan find --only-holdings --format json",
            exit_code=2,
        )
    if only_holdings and group is not None:
        _exit_find_error(
            fmt,
            code="invalid_holdings_pool",
            message="--only-holdings 已指定真实持仓池，不再叠加 --group",
            hint="例: kan find --only-holdings --format json",
            exit_code=2,
        )
    if only_holdings and only_watchlist:
        _exit_find_error(
            fmt,
            code="invalid_holdings_pool",
            message="--only-holdings 与 --only-watchlist 不能同时使用",
            hint="例: kan find --only-holdings --format json",
            exit_code=2,
        )
    if only_holdings and all_stocks:
        _exit_find_error(
            fmt,
            code="invalid_holdings_pool",
            message="--only-holdings 与 --all 不能同时使用",
            hint="例: kan find --only-holdings --format json",
            exit_code=2,
        )
    if all_stocks and (exclude_star or exclude_bj):
        _exit_find_error(
            fmt,
            code="unsupported_all_filter",
            message="--all 暂不支持 --exclude-star / --exclude-bj",
            hint="例: kan find --codes 600519,688981 --exclude-star --format json",
            exit_code=2,
        )
    code_pairs = _resolve_code_pairs_or_exit_json(codes, fmt) if codes is not None else None
    if explain or dry_run:
        from kan.service.find_plan import build_find_query_plan
        from kan.service.find_service_models import FindOutputProfile

        output = FindOutputProfile(
            mode=fmt.value,
            compact=compact,
            compact_context=compact_context,
            field_paths=field_paths,
            field_dimensions=frozenset(field_dimensions),
            agent_summary=agent_summary,
        )
        typer.echo(export.to_json(build_find_query_plan(
            conditions=conditions,
            output=output,
            industry=industry,
            hot=hot,
            theme=theme,
            group=group,
            code_pairs=code_pairs,
            only_holdings=only_holdings,
            all_stocks=all_stocks,
            limit=limit,
            offset=offset,
            sort=sort_spec,
            dry_run=dry_run,
        )))
        return
    # 2.5 全市场截面取数 (--all) · 不走 K 线管线 · 早返回不读自选
    if all_stocks:
        _run_all_stocks_path(
            source_mode=source_mode,
            conditions=conditions,
            field_dimensions=field_dimensions,
            field_paths=field_paths,
            fmt=fmt,
            compact=compact,
            compact_context=compact_context,
            is_export=is_export,
            limit=limit,
            offset=offset,
            sort=sort_spec,
            rs_index_code=rs_index_code,
            agent_summary=agent_summary,
            snapshot=snapshot,
            since=since,
        )
        return

    _run_kline_path(
        code_pairs=code_pairs,
        source_mode=source_mode,
        industry=industry,
        hot=hot,
        theme=theme,
        only_watchlist=only_watchlist,
        only_holdings=only_holdings,
        exclude_star=exclude_star,
        exclude_bj=exclude_bj,
        group=group,
        conditions=conditions,
        field_dimensions=field_dimensions,
        field_paths=field_paths,
        fmt=fmt,
        compact=compact,
        compact_context=compact_context,
        is_export=is_export,
        limit=limit,
        offset=offset,
        sort=sort_spec,
        rs_index_code=rs_index_code,
        console=console,
        find_disclaimer=find_disclaimer,
        agent_summary=agent_summary,
        snapshot=snapshot,
        since=since,
    )
