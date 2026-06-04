# kan find 数据契约

`kan find` 是用户主导的条件筛选器。规则必须由命令参数显式给出;工具只返回符合规则的数据,不提供评分、评级、目标价、买卖建议或策略 preset。

## JSON 输出

```bash
kan find --industry 半导体 --pos 180:lt:10 --format json
kan find --industry 半导体 --pos 180:lt:10 --format json --compact
kan find --all --pe lt:20 --format json --compact
kan find --all --pe lt:20 --format json --compact --no-compact-context
kan find --industry 半导体 --format json --fields @core,@valuation
```

两种 JSON 共享顶层字段:

| 字段 | 含义 |
|---|---|
| `ok` | 成功时为 `true`;业务错误 envelope 中为 `false` |
| `schema_version` | `kan find` JSON 契约版本,与包版本不同 |
| `command` | 固定为 `find` |
| `mode` | 仅 `--all` 路径为 `cross_section` |
| `result_schema` | `full`、`compact` 或 `fields` |
| `rule` | 候选池和用户输入的 filter |
| `results` | 返回结果,已按 `--limit` 截断 |
| `data_availability` | 本次候选池维度可用性统计 |
| `stats` | 候选池、命中数、展示数、数据截止日、stale |
| `disclaimer` | `kan find` 强制免责声明 |

### full vs compact

`--format json` 默认是 `result_schema=full`:每只股票尽量保留完整位置上下文和已取到的维度对象,适合落盘审计或下游程序精细处理。

`--format json --compact` 是 `result_schema=compact`:每只股票只保留首轮筛选常用字段:

- `code` / `name` / `price`
- `triggered_filters`
- `positions` / `low_resonance` / `high_resonance`
- 若本次规则请求了对应维度,保留该维度摘要,例如 `valuation.pe_ttm`、`moneyflow.net_amount`、`technical.rsi_6`
- `data_time`;若 ST、涨停、跌停为真,才出现 `is_st` / `limit_up` / `limit_down`

compact 不等于改变筛选规则,只改变 JSON 字段量。需要完整字段时去掉 `--compact`。

默认 compact 会包含 `positions` / `low_resonance` / `high_resonance`;在 `--all` 下这需要全市场 K 线快照。若首轮只需要截面指标,可加 `--no-compact-context`:

```bash
kan find --all --pe lt:20 --format json --compact --no-compact-context
```

该开关只影响 compact 输出里的位置/共振/涨幅/连阳上下文;若命令本身带 `--pos`、`--resonance`、`--gain`、`--up-days` 等 K 线 filter,仍会取快照用于筛选。

### fields

`--format json --fields LIST` 是 `result_schema=fields`:只输出白名单里显式请求的字段,适合把结果继续交给外部程序或模型时控制上下文成本。

字段语法:

- `LIST` 支持逗号或空白分隔,可多次传入,会去重并保持首次出现顺序
- 只接受白名单字段或 registry preset,不做动态嵌套路径解析
- 可用字段示例:`code`、`name`、`price`、`data_time`、`triggered_filters`、`context.positions`、`context.low_resonance`、`valuation.pe_ttm`、`moneyflow.net_amount`、`technical.rsi_6`
- `--fields` 不能和 `--compact` 同时使用;二者都定义结果字段形态
- `--all` 不支持逐股高成本维度字段,例如 `fundamentals.*`、`shareholder.*`

字段 preset 是客观维度包,只负责展开字段列表,不改变筛选、排序或解释:

| preset | 展开内容 |
|---|---|
| `@core` | `code` / `name` / `price` / `data_time` / `triggered_filters` |
| `@context` | `context.positions` / `context.low_resonance` / `context.high_resonance` |
| `@valuation` | `valuation.*` 常用估值、量价、市值字段 |
| `@valuation_context` | 行业、行业样本、PE/PB 行业内分位和中位 |
| `@moneyflow` | 主力净额和大单/超大单字段 |
| `@technical` | RSI、MACD、KDJ、均线、ATR%、乖离率字段 |
| `@sentiment` | 连板/开板/涨跌停事件字段 |
| `@chip` | 获利盘和成本分布字段 |
| `@shareholder` | 股东户数、前十大流通集中度、北向持股字段;`--all` 不支持 |

示例:

```bash
kan find --industry 半导体 --format json \
  --fields @core,@context,valuation.pe_ttm,moneyflow.net_amount
```

未知字段或未知 preset 会返回 `invalid_fields`。`--fields` 请求某个维度时,该维度会计入 `data_availability`;未请求的维度仍是 `not_requested`。在 `--all` 下,`--fields` 也会反向驱动截面取数,未请求的 moneyflow / technical / sentiment / chip 不会主动拉取。

### match mode

多个 filter 默认是 AND 语义,即所有条件都需命中。显式加 `--any` 时改为任一 filter 命中即返回,`triggered_filters` 仍只记录实际命中的条件:

```bash
kan find --any --pos 20:lt:10 --moneyflow-daily gt:10000 --format json
```

### data_availability

`data_availability` 统计的是候选池维度可用性,用于区分“数据缺失”和“事实为 0”:

```json
{
  "basis": "candidate_pool",
  "pool_size": 87,
  "valuation": {"status": "included", "available": 80, "missing": 7},
  "fundamentals": {"status": "not_requested", "available": null, "missing": null}
}
```

`status` 语义:

| status | 含义 |
|---|---|
| `included` | 本次命令尝试取该维度,`available/missing` 为候选池计数 |
| `not_requested` | 本次命令未取该维度;不要把它解读为缺数据 |
| `not_supported` | 当前模式不支持该维度,例如 `--all` 不支持逐股财务和股东结构 |

注意:`sentiment` 是稀疏事件数据;未出现在涨跌停事件表不等于数据源故障。

## filter 数据来源

| filter | 数据源 | 需要 token | `--all` | 频率 | 缺数据语义 |
|---|---|---:|---:|---|---|
| `--pos` | 小池走本地日 K 缓存;`--all` 走全市场 K 线快照 | 小池否;`--all` 是 | 是 | 日频 | 周期不足为不命中;全市场快照不可用时返回 `data_unavailable` |
| `--resonance` | 小池走本地日 K 缓存;`--all` 走全市场 K 线快照 | 小池否;`--all` 是 | 是 | 日频 | 由位置结果计算;周期不足不计入共振 |
| `--gain` | 小池走本地日 K 缓存;`--all` 走全市场 K 线快照 | 小池否;`--all` 是 | 是 | 日频 | 周期不足或缺少前值为不命中 |
| `--up-days` | 小池走本地日 K 缓存;`--all` 走全市场 K 线快照 | 小池否;`--all` 是 | 是 | 日频 | 非连续阳线可为 `0`,不是缺数据 |
| `--pe` | TuShare `daily_basic` 衍生截面指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--pb` | TuShare `daily_basic` 衍生截面指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--turnover` | TuShare `daily_basic` 衍生截面指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--market-cap` | TuShare `daily_basic` 衍生截面指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--volume-ratio` | TuShare `daily_basic` 衍生截面指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--roe` | TuShare `fina_indicator` 最新报告期 | 是 | 否 | 季度/报告期 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--moneyflow` | TuShare `moneyflow` 衍生资金流向 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--moneyflow-daily` | TuShare `moneyflow` 衍生资金流向 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--moneyflow-days` | TuShare `moneyflow` 衍生资金流向 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--rsi` | TuShare `stk_factor_pro` 衍生技术指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--macd-dif` | TuShare `stk_factor_pro` 衍生技术指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--macd` | TuShare `stk_factor_pro` 衍生技术指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--kdj-j` | TuShare `stk_factor_pro` 衍生技术指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--ma-bias` | 小池走本地日 K 缓存;`--all` 走全市场 K 线快照 | 小池否;`--all` 是 | 是 | 日频 | 周期不足为不命中;全市场快照不可用时返回 `data_unavailable` |
| `--atr-pct` | TuShare `stk_factor_pro` 衍生技术指标 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--streak` | TuShare `limit_list_d` 涨跌停事件表 | 是 | 是 | 日频 | 稀疏事件;未出现在事件表通常表示当日未涨跌停 |
| `--winner` | TuShare `cyq_perf` 筹码分布 | 是 | 是 | 日频 | 指标为空为缺数据;整池缺失时返回 `data_unavailable` |
| `--holders` | TuShare `stk_holdernumber` + `top10_floatholders` 衍生 | 是 | 否 | 季度/披露期 | 未披露或未进前十大流通可为 `None`;整池缺失时返回 `data_unavailable` |
| `--top10` | TuShare `stk_holdernumber` + `top10_floatholders` 衍生 | 是 | 否 | 季度/披露期 | 未披露或未进前十大流通可为 `None`;整池缺失时返回 `data_unavailable` |
| `--north` | TuShare `stk_holdernumber` + `top10_floatholders` 衍生 | 是 | 否 | 季度/披露期 | 未披露或未进前十大流通可为 `None`;整池缺失时返回 `data_unavailable` |
| `--exclude-st` | 股票名称 / 候选池元数据 | 否 | 是 | 随候选池 | 静默过滤,不写入 `triggered_filters` |

## 候选池

| 池 | 说明 |
|---|---|
| 默认 | 当前 default 自选组 |
| `--group` | 指定自选分组 |
| `--industry` | 申万行业成分股 |
| `--theme` | 题材成分股;题材分类来自上游口径 |
| `--hot rank\|surge` | 东方财富热榜 |
| `--codes` | 外部传入代码池,不写入自选 |
| `--all` | 全市场截面池,仅属于 `kan find`;逐股高成本维度不支持 |

## 错误语义

`--format json` 下业务错误返回机器可读 envelope:

```json
{
  "ok": false,
  "command": "find",
  "schema_version": "0.0.6.8",
  "error": {"code": "data_unavailable", "message": "...", "hint": "..."},
  "disclaimer": "..."
}
```

常见 `error.code`:

| code | 含义 |
|---|---|
| `data_unavailable` | 该 filter 依赖的数据源在当前候选池不可用 |
| `empty_intersection` | `--only-watchlist` 后候选池为空 |
| `invalid_fields` | `--fields` 字段未知、为空、与 `--compact` 冲突,或当前模式不支持该维度 |
| `invalid_compact_context` | `--no-compact-context` 未与 `--format json --compact` 一起使用 |
| `invalid_codes` | `--codes` 或 `--codes -` 中包含非 6 位 A 股代码 |
| `empty_codes` | `--codes` 解析后没有任何有效代码 |
