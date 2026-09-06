# 显式日线条件与复权证据

`kan screen ohlc` 用于用户同时指定日线交集、区间低点日期与位置上限的查询。
它输出 JSON 事实，不自动保存 Screen、候选状态或排序偏好。所有条件和范围都必须
由用户显式传入；省略参数只显示用法，不运行条件组合。

```text
kan screen ohlc --market mainboard --as-of YYYY-MM-DD \
  --period N --low-within K --max-position P --joint-up-days M
```

| 参数 | 契约 |
|---|---|
| `--market mainboard` | `stock_basic` 完整沪深主板 A 股，包含 ST；不读取自选或持仓 |
| `--as-of` | 当前最近已完成收盘的交易日，沪深交易日历必须一致 |
| `--period N` | 最近 N 个市场交易日，2–360；额外读取一个前置日供收盘比较 |
| `--low-within K` | N 日最低价在最后 K 日内出现，包含截止日，1–N |
| `--max-position P` | `(close − min(low)) / (max(high) − min(low)) × 100 <= P`，P 为 0–100 |
| `--joint-up-days M` | 从截止日倒数，连续至少 M 日同时 `close > open`、`close > previous_close`，2–N |
| `--refresh` | 跳过日线证据缓存，重新获取所需日期的原始日线和因子 |

最新收盘价还必须严格大于区间最低价。相等、阴线或比前收下跌都会中断交集连续；
条件比较不使用展示时四舍五入的百分比。重复最低价取最近一次，同时输出全部出现日期。
`low_age=0` 表示最低价就在截止日，`low_age < K` 才在最近 K 日内。

价格来自 TuShare `daily`，复权因子来自 `adj_factor`，统一计算
`raw_price × 当日因子 / 截止日因子`。原始 OHLC 和因子随证据保留。历史 qfq
截面可能由不同时间的分母生成，直接拼接可能改变区间低点日期；本入口独立读取原始事实，
不复用旧 `find` / `trend` 的 qfq 截面缓存。原有这些入口的缓存不在本次变更中迁移，
需要严格一致基准的这类条件请使用本入口。

JSON 顶层包含 `request`、`as_of`、`window_start`、`previous_session`、`sources`、
`queried_at`、`adjustment`、`coverage` 与 `disclaimer`。其中：

- `rows` 是全部严格匹配的股票，按代码排列，没有综合分；`daily_evidence` 保留整个区间的原始价、复权价、前收、因子及每日交集布尔值。
- `evaluated_rows` 是所有可计算股票的指标和各条件布尔值；`condition_counts` 为各条件单独命中数量，不能相加视为交集。
- `excluded` 逐股解释无法验证的情况；`coverage.universe = evaluated + excluded`。`ok=true` 不代表每只股票均有完整历史，必须读取覆盖率。
- `missing_as_of_bar` 表示截止日无日线；`incomplete_history` 表示 N+1 个市场交易日中有缺行，可能是停牌、上市较晚或数据缺失，工具不猜原因、不用前值补造交易。
- `invalid_bar_or_factor` 表示非有限/非正价格、因子或成交量额，或 OHLC 关系不合法；`zero_range` 表示区间高低相等，位置不可计算。
- 连续天数最多可确认 N 日，达到上限时 `streak_capped=true`，应读成“至少 N 日”。
- `volume_vs_prev5` 为当日成交量 / 此前五个交易日平均成交量，不是盘中量比。`amount_yuan` 为元，原始证据 `vol` 为手、`amount` 为千元；不足 5/10 日时对应辅助指标为 `null`。

Python 调用 `kan.service.ohlc_screen_service.run_ohlc_screen(OhlcScreenRequest(...))`
与 CLI 共用计算。保存了当时股票池、日期和原始日线时，可通过同模块
`evaluate_ohlc_screen` 及 `kan.data.ohlc_history.adjust_history` 离线复核。
当前联网入口不拿今天的上市名单冒充历史时点名单，也没有新增 HTTP/MCP 端点。

上述条件只描述历史事实，不能确认价格已经见底或预测后续方向。
