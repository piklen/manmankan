# 热榜扫描功能 · 设计方案

> 状态:设计待实施 · 目标版本 v0.0.5.0 · 分支 `feat/v0.0.5.0`
> 最后更新:2026-05-23

## 1. 背景与目标

`kan` 已支持两种扫描标的来源:自选股(默认)、申万行业成分股(`--industry`)。本功能新增第三种:**东方财富热榜**。

热榜在本功能里的定位是 **"临时自选股"** —— 即时拉取一批当前上榜的股票作为扫描标的,套用慢慢看标准的多周期位置 / 趋势分析。用户不必把这些股票加进自选,扫完即弃。

## 2. 非目标(明确不做)

- **同花顺热榜**:akshare 无同花顺人气 / 热度榜端点(只有"创新高 / 连续上涨"等技术选股榜,性质不同)。本轮不纳入。
- *****REMOVED***关注榜 / 百度热搜**:***REMOVED***榜是 5602 行全市场排名(需 top-N 截断 + 拉取慢);百度热搜代码字段不规整。本轮不纳入,留作后续候选。
- **"热榜看板"模式**:不做"按热度排序、首列即热度名次"的独立榜单展示。热榜只作标的来源,输出仍是位置扫描表。
- **`info` / `list` 命令**:`info --hot` 无对应物(热榜无指数实体);`list --hot` 语义边际。不加。

## 3. 命令范围

`--hot` 加到 5 个查看类命令:`scan` / `low` / `high` / `trend` / `fetch`。

改写自选的命令(`add` / `remove` / `clear`)与 `--hot` 无关,不涉及。

## 4. 参数设计

`--hot` 为 typer 枚举选项,2 个英文值:

| 值 | 榜单 | akshare 端点 |
|---|---|---|
| `rank` | 东财人气榜 | `stock_hot_rank_em` |
| `surge` | 东财飙升榜 | `stock_hot_up_em` |

约束:

- `--hot` 与 `--industry` 互斥 → `❌ --industry 与 --hot 不能同时使用`,exit 2。
- `--hot` 与显式股票代码互斥(沿用 `fetch --industry` 已有校验)。
- `--only-watchlist` 对 `--hot` 生效:targets = 热榜 ∩ 自选,全部 ⭐ 高亮。

## 5. 数据模块 `kan/hot.py`

新建,职责对标 `boards.py`。

### 5.1 数据结构

- `HotList(str, Enum)`:`RANK = "rank"` / `SURGE = "surge"`(同时作 typer 选项枚举)。
- `HotEntry`:`rank: int` / `symbol: str` / `name: str`。

### 5.2 接口

`fetch_hot_list(which: HotList, force: bool = False) -> list[HotEntry]`

- 调对应 akshare 端点(`stock_hot_rank_em` / `stock_hot_up_em`)。
- 字段映射:`当前排名 → rank`、`代码 → symbol`、`股票名称 → name`。
- **代码归一化**:东财返回带交易所前缀(`SZ000725` / `SH603759`),剥前 2 位字母前缀 → 6 位裸代码。无法归一化的条目跳过,经 `debug_log` 记数。
- akshare / pandas 函数内延迟 import(冷启动规则)。

### 5.3 缓存

- JSON cache,路径 `HOT_DIR / hot_<which>.json`(`paths.py` 新增 `HOT_DIR`,参照 `BOARDS_DIR`)。
- TTL **1 小时**:热榜为实时榜,但慢慢看是盘后工具,1h 内重复跑结果稳定,且不反复打数据源。过期自动重拉。`force=True` 忽略缓存。

### 5.4 失败处理

- 拉取失败 / 空数据 → 抛 `HotListUnavailableError`(异常名带 `Error` 后缀)。
- 不建假 fallback(沿用 `boards.py` 单源原则)。
- 命令层 catch → `❌ 热榜数据源暂时不可用,稍后再试`,exit 1。

## 6. `resolve_scan_targets` 改动

`_scan_targets.py`:当前 `resolve_scan_targets(industry, only_watchlist, watchlist_pairs) -> (targets, BoardMeta | None)`。

改为接受 `hot` 参数,三选一分支:

| 输入 | targets | meta |
|---|---|---|
| `industry` 给定 | 行业成分股 | `BoardMeta`(现状不变) |
| `hot` 给定 | 热榜股票 | `HotMeta` |
| 都没给 | `watchlist_pairs` | `None` |

新增 `HotMeta`:

- `list_name: str` —— `东财人气榜` / `东财飙升榜`
- `rank_map: dict[str, int]` —— `{代码: 名次}`
- `highlight: set[str]` —— 热榜 ∩ 自选代码

返回类型 → `tuple[targets, BoardMeta | HotMeta | None]`。命令层在现有 `if board_meta is not None:` 处加 `isinstance` 判断,分流到热榜渲染。

校验:`industry` 与 `hot` 同时给 → 抛 `ValueError`(命令层提前拦截,给友好提示)。

## 7. 渲染

- **标题**:`慢慢看 · 东财人气榜 位置扫描 · 低点模式`(类比 `{board.name} 行业位置扫描`)。
- **名次列**:`scan` / `trend` 表格在"股票"列前加一列 `榜`,显示当前名次整数。`scan --hot` 标的按热榜名次顺序进入 targets,故默认即名次序展示,无需额外排序。`low` / `high` 按位置排序,名次列为乱序参考值。
- **`--only-watchlist`**:targets = 热榜 ∩ 自选,全部 ⭐。

## 8. 合规

- 标题 / 列名用中性词("热榜""人气榜""飙升榜""名次"),不触关键词黑名单;不写"值得关注""热门推荐"等。
- footer `DISCLAIMER` 照常。
- caption 加一行切割数据来源与工具观点:`名次为东方财富热榜实时排名 · 非慢慢看观点 · 热榜为实时榜单`。
- 热榜实时、K 线盘后延时:scan 现有 stale 警告(基于 K 线 `data_cutoff`)照常工作,不新增机制。

## 9. 测试

- `tests/test_hot.py`:mock akshare → 代码归一化、缓存 TTL、`HotListUnavailableError` 抛出、异常代码跳过。
- 扩展 `tests/test_scan_cli.py`:CliRunner runtime 真测(mock `hot.fetch_hot_list`)—— `scan --hot rank` 出表、`--hot` + `--industry` 互斥报错、`--only-watchlist` 交集。
- 遵守 CHANGELOG "bootstrap-test 作弊 → 真测" 纪律,不用字符串断言糊弄。

## 10. 风险与待验证

- 东财人气榜可能混入非主板代码(北交所等);归一化需识别并跳过 `kan` 不支持的代码段 —— 实施首步验证。
- 东财端点偶发被反爬限流;`HotListUnavailableError` + 1h cache 缓解,无 fallback。
- 100 只股票冷启动需拉 100 条 K 线,首次慢;沿用 `_auto_fetch_stale` 现有 spinner 进度。

## 11. 版本

- 目标版本 **v0.0.5.0**,与 `--industry` 同批发布,同分支 `feat/v0.0.5.0`。
- `roadmap.md` 未列此功能;实施时在 `CHANGELOG.md` 落 Added 条目。是否补进 `roadmap.md` 由维护者定。
