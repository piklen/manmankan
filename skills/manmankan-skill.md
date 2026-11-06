# manmankan Skill · AI Agent 能力清单

当前主线是 **发现群体现象 → 核对成员证据 → 留下观察与自己的想法 → 显式复看同一批成员**。先用 `kan discover` / MCP `kan_discover` 获取完整范围的分布、行业变化与各自分母；用户明确要求留存时再用 `kan observe` / MCP `kan_observe` 保存原事实与用户文字。复看保持原成员和窗口，不覆盖原记录；两个滚动窗口可能重叠，不是持有收益或因果验证。

已有明确走势条件时用 `kan trend`；财务/估值筛选用 `kan find`，指定公司材料用 `kan research`；历史事件才用 `kan study`。价格、分组和统计由共享 Python 核心计算，模型不另算，也不自动把观察变成股票候选。本文为主线契约，安装来源见 [README](../README.md#安装与主线体验)。


> 本文件是给 AI Agent 读的"说明书"。
> 当 Agent 读到本文件时，它应该能够自主发现 manmankan 的全部能力、命令语法、输出格式和错误处理方式。
> 格式参考 Agent Skills 标准（agent-data-cli / Dune CLI / Anthropic Skills）。

---

## 市场观察

用户明确要求留住观察时，使用`kan observe save request.json`或MCP `kan_observe(action="save")`，固定`query.as_of`；保存原完整成员与用户自己的文字。之后`review`冻结原成员与window，按共同完整者比较，不覆盖原记录；不自动替用户写判断或建候选。

优先用 `kan discover --window 20 --format json` 或 MCP `kan_discover` 发现完整范围的群体现象，再用明确条件核对。输入 `universe/codes/industries/as_of/window`；输出当前分布、行业剖面、相邻等长窗口变化、固定成员轨迹与完整成员。

当前、两段对照与轨迹各自有分母；缺失不当零、下跌或退出。成员按 `distribution_bin` 和 `transition` 下钻，事实不另算。默认时间窗口只是描述尺度，不生成选股策略；旧数据日必须显式选择。

## 工具概述

用户明确要求“连续同时收阳与收盘上涨＋区间低点日期/位置”时，使用
`kan ohlc --help` 核对显式参数，按 [`docs/ohlc-screen.md`](../docs/ohlc-screen.md)
执行。该入口固定前复权基准；不要拼接旧 qfq 缓存重算，不把收盘连续或阳线连续替代交集。

**manmankan** (`kan`) 是一个本地优先的 A 股市场观察与研究工具。
它提供 React Web、CLI、Python API、typed HTTP 和 MCP，但不内置 LLM；板块趋势由统一 `BoardTrendQuery → BoardTrendSnapshot` 服务计算，跨日事实由 `BoardDailyReview` 保存，当前趋势筛选由 `TrendSearchQuery → TrendSearchResult` 计算，历史事件由 `StudyQuery` 表达。AI 整理明确查询、执行确定性服务并引用对应证据。

**命令入口**：终端执行 `kan <command> [options]`
**安装**：`uv tool install manmankan` 为 PyPI 稳定包；主线体验见 [README](../README.md#安装与主线体验)
**市场**：当前仅 A 股
**首用文档**：`docs/ai-quickstart.md`
**MCP 文档**：`docs/mcp.md`
**本地研究与个人资料**：`docs/selection-workbench.md`

---

## 命令族

### 当前趋势与两日变化

波段筛选：`kan trend --universe all --swing up --window 60 --reversal-pct 5`（下降改 `down`、混合改 `mixed`）。精确阳阴数量问题用 `--window 15 --bull-excess 0 --return-above 0`，不要替换成上涨日计数。typed条件支持 `bull_count/bear_count/candle_balance/trend_slope/trend_efficiency/swing_structure/swing_direction/swing_count`，均需窗口。`swing_reversal_pct` 随Query保存/传递；结构编码1/-1/0分别为抬高/降低/混合，不足为null。图证 `swings` 给出确认点、确认日、当前未完成段与 `structure_broken`，不是事后预测。口径见[趋势研究](../docs/trend-research.md#波段结构与趋势因子)。

两日变化：明确选择 `kan trend --universe all --down-days 5 --compare-to previous_session`，或用 `--compare-to YYYY-MM-DD` 指定对照日。读取 `comparison.coverage` 与逐行两端实际值；未知不能解释为新增/退出，`rows` 仍是当前匹配。 当前匹配读取 `coverage`、`missing_rows`、`as_of` 和来源；资料不足不等于条件不满足。形态参照自身窗口由 `excluded_rows` 单列。

### 研究证据包

`kan research 600519 --dimensions income,balancesheet,cashflow --format json` 获取三表28个关键金额科目。按表核对 `report_period / announcement_date / actual_announcement_date / report_type / period_basis`：利润与现金流量为年初累计（现金余额项除外），资产负债为期末余额；不能直接把累计值当作单季值。一张表失败时查看 `errors[].dimension`，其余证据仍可用；可加 `--refresh` 更新。

`kan research 600519 --format json` 或 MCP `kan_research` 按明确代码生成同一份研究事实。默认维度为 `market,valuation,fundamentals`，最多20个代码；各维度可独立请求。`kan research 600519 --dimensions fundamentals --refresh --format json` 只刷新财务，不拉行情；MCP 对应 `refresh:true`。财务按需每日检查来源，分别记录报告期、公告日与检查时间。先检查 `status / coverage / errors`，再核对每份 evidence 的来源、日期、单位及缺失。`ok=true` 仅表示没有执行错误，不等于资料完整；财务 `fresh` 表示近期检查过来源，不等于当日披露。引用指向包内证据，不代表推断获得证明。完整契约见 `docs/research.md`。

### 0. 保存条件与核对历史

保存筛选使用 Web/TUI 或 Python `save_trend_search`；只保存名称与查询。
历史研究使用 `kan study run query.json --format json`，明确原完整范围、条件、历史窗口和后续窗口。
`kan study list/show/rerun` 查看或复算已保存研究，历史证据使用当次封存事实。
`kan workspace status/migrate/rollback` 检查或切换个人状态存储，不回显配置/持仓内容。

### 1. 扫描与发现

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan scan` | 扫描默认池（自选 ∪ 持仓）的多周期位置 | 一次性读取持仓+自选的客观位置 |
| `kan scan --only-holdings` | 只扫描真实持仓池 | 单独查看持仓位置 |
| `kan scan --group <组名>` | 扫描指定分组 | 分组巡检 |
| `kan scan --codes <代码列表>` | 扫描外部代码 | 临时查看一批候选 |
| `kan scan --all` | 扫描完整 A 股市场池（含北交所 / ST） | 首次较慢；适合全市场位置坐标巡检 |
| `kan scan --periods 5,20,60,180 --wide` | 自定义 2-360 周期并全量展示 | 避免窄屏只看到部分周期 |
| `kan scan --compact` | 终端只展示短/中/长关键周期 | 控制终端 token 和横向宽度 |
| `kan scan --industry <行业>` | 扫描申万行业成分股 | 行业维度扫描 |
| `kan info <代码>` | 单只股票全景：位置/估值/资金/技术 + 所属行业位置对照 | 深度研判单只股票时用 |
| `kan compare <代码1> <代码2> ... --periods 20,60` | 多股横向对比 | 候选池缩窄时比较 |

### 2. 条件筛选

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan find` | 一次性按条件筛选股票 | 财务、估值等明确条件与字段的一次查询 |
| `--pos N:lt:M` | 位置筛选（N 日位置 < M%） | 如 `--pos 180:lt:10` = 180 日低位 |
| `--resonance low:gte:N` | 共振筛选（至少 N 个周期同时触及低位阈值） | 只报告同时触及的周期数，不评价可靠性 |
| `--pe` / `--pb` / `--dv` / `--turnover` / `--market-cap` / `--volume-ratio` | 估值、股息率、换手、市值、量比筛选 | 来自截面指标；`--dv gte:3` 表示股息率 TTM 不低于 3%；看 `data_availability` 区分缺数据 |
| `--roe` | ROE 逐股报告期筛选 | 需要先缩小代码池 / 行业 / 题材；全市场模式不支持 |
| `--moneyflow` / `--moneyflow-daily` / `--moneyflow-days` | 主力资金净额、单日资金、连续净流入天数 | 单位万元；输出分类资金流裸值 |
| `--exclude-st` | 排除 ST 股 | 是否排除由用户定义的股票池范围决定，不能由 agent 偷加 |
| `--gain N:OP:V` / `--ma-bias N:OP:V` | 2-360 周期涨幅和均线乖离率 | 周期直接写入 filter，如 `20:gt:5` |
| `--sort FIELD:asc/desc` / `--offset N` / `--limit N` | 排序与分页 | 适合全市场或大行业池低上下文消费 |

### 3. 候选池管理

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan add <代码...> [--group <组名>]` | 批量加自选股 | 可指定分组 |
| `cat codes.txt \| kan add -` | 从 stdin 批量添加 | 外部候选池回填自选 |
| `kan add --industry <行业> --dry-run` | 批量添加预览 | 先看数量和影响，不写入 |
| `kan add <代码> --fetch` | 添加后立即拉 K 线 | 避免下次 scan 冷启动 |
| `kan remove <代码>` | 删自选股 | |
| `kan list [--group <组名>]` | 列出自选股 | |
| `kan group create/list/rename/delete/default` | 分组管理 | 分组是组织自选股的首选方式 |
| `kan move <代码> <源组> <目标组>` | 移动股票到另一组 | |
| `kan clear --group <组名>` | 清空分组 | 慎用 |
| `kan import/export` | 导入导出 CSV | 批量操作 |

### 4. 行情与榜单

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan history <代码> --period N [--format json]` | 位置历史回溯 | N 支持 2-360；只展示快照中已记录周期 |
| `kan trend --universe personal --up-days N` | 连续涨跌跟踪 | 发现异动 |
| `kan trend --universe all --down-days N` | 全市场连续涨跌跟踪 | 大池首轮看分布，必要时再缩小候选池 |
| `kan board rank --kind industry --by moneyflow --format json` | 板块资金排名 | 板块级客观裸值聚合 |
| `kan board trend --kind industry --up 3 --format json` | 申万行业指数连续涨跌 | 默认按收盘较前收；`--level 1/2/3` 切行业层级 |
| `kan board trend --kind theme --up 3 --format json` | 概念题材指数连续涨跌 | 题材使用 THS N 类概念指数；读取 `source` / `data_availability` |
| `kan board trend --kind theme --up 3 --candle --format json` | 概念题材连续阳线 | `--candle` 按当日 close 与 open；不要与收盘连续上涨混称 |
| `kan index [sh sz cyb hs300] --format json` | 常用指数日线位置参照 | 补大盘基准 |
| `kan range <代码> [--format json]` | 历史日内下探、上冲范围与触及后收盘事实 | 基准为前收、只用完整日 K；默认 `--periods 5,15`、线性插值分位 `--levels 75,85,90,95`，并保留实际覆盖率 |
| `kan range --codes 600519,000858 [--format json]` | 最多 20 只股票的日内范围复核 | 代码不重复、保持输入顺序；终端逐股保留全部档位及条件结果，JSON 读取 `studies/errors/partial`，不按幅度排序 |
| `kan low N` / `kan high N` | N 日新低/新高 | 极端位置发现；支持 `--all` 全市场池 |

板块指数研究的 Python 入口为 `kan.api.query_board_trends`、`query_board_pulse`、`create_board_review` 与 `study_board_history`。它们保留来源、日期、覆盖与缺失；没有同名旧 HTTP 路由或每日复看 Web 页面。成员涨跌是群体事实，不能解释为指数权重贡献或新闻因果。

`kan range <代码> --down 3 --up 7` 可复核用户明确给出的 `-3%` 下探和 `+7%` 上冲阈值；显式 `0` 是有效零幅度线，只有参数省略才表示未请求。终端先回答自定幅度，再按方向分组、同档各周期相邻展示；单股与批量均保留全部请求档位和触及后的收盘次数。单股参数与 `--codes` 二选一；批量存在逐股失败时读取统一顶层 `error`、成功的 `studies` 和逐股 `errors`，同时保留 `partial` 与非零退出码。阈值内的 `reference_price` 是当前参考收盘按 0.01 元价格档 `ROUND_HALF_UP` 得到的两位折算价，不是历史事件价或实时价；`threshold_pct` 是证据分类实际采用的 4 位公开阈值，可原样回传复核。AI 必须保留实际样本数和条件结果的分子/分母，不能把 `1/1` 只写成 `100%`，零触及不能当零概率；短窗口包含在长窗口内，并非独立样本。日涨跌幅相对前收而非持仓盈亏，日 K 不能统计水下时长。只把结果解释为历史范围和触及后的收盘事实；不得输出止损/止盈推荐、最佳阈值或涨跌预测。

### 5. 真实持仓

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan hold add <代码> --cost C --shares N` | 录入持仓成本和股数 | 由用户或脚本提供结构化事实 |
| `kan hold add <代码> --cost C --shares N --add` | 追加录入并重算均价 | 只做事实合并 |
| `kan hold reduce <代码> --shares N` | 减少持股数 | 更新用户提供的事实账本 |
| `kan hold cash <金额>` | 更新现金 | 计算账户总资产和仓位 |
| `kan hold import <csv>` / `pbpaste \| kan hold import -` | 批量导入持仓 | AI 解析截图后可转成 CSV/stdin 调用 |
| `kan hold --format json --mask` | 持仓总览 JSON 且金额脱敏 | 截图 / 演示 / 外部模型低泄漏输入 |
| `kan hold scan` | 只扫描真实持仓池 | 与普通 scan 输出口径一致 |

`kan hold` 只能输出客观坐标、盈亏事实、仓位和除权除息核对提醒；不得把持仓状态改写成交易动作或处置结论。

### 6. 数据维护

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan fetch` | 更新当前自选数据 | 需要更新明确范围时执行；默认摘要输出 |
| `kan fetch 600519 000858` | 更新指定股票 | 新加入自选股后 |
| `kan fetch --all` | 预拉完整 A 股市场 K 线缓存 | 耗时较久；给 `scan/low/high --all` 预热；明显不完整的上游响应会停止且不缓存 |
| `kan fetch --verbose` | 逐只输出拉取状态 | 排障时使用 |

Web 的“市场与数据”页还可启动 SQLite 持久刷新任务。终态包括 `succeeded / partial / failed / interrupted`；部分失败不等于完整成功，重新发起会复用已写入缓存。

---

## JSON 输出约定

所有数据查询命令支持 `--format json`。JSON 输出遵循以下契约：

### 成功响应
```json
{
  "ok": true,
  "schema_version": 1,
  "data_time": "2026-06-04",
  "results": [...],
  "data_availability": {"pe": false, "moneyflow": true},
  "stats": {"total": 23, "returned": 23},
  "disclaimer": "坐标 ≠ 信号。仅供参考，不构成投资建议。"
}
```

### 错误响应
```json
{
  "ok": false,
  "error": {
    "code": "invalid_fields",
    "message": "--fields 包含未知字段",
    "hint": "例: kan fields list --format json"
  }
}
```

### AI 消费要点
- **先检查 `ok` 字段**——`false` 时不要尝试解析 `results`
- **`data_availability` 是诚实信号**——维度未请求、不可用、缺失要分开处理
- **`schema_version` 用于版本适配**——当前为 1
- **紧凑模式**：`kan find --compact` 降低 JSON 字段量；`kan scan --compact` 降低终端横向宽度
- **字段白名单**：`--fields @core,@valuation,@moneyflow` 只返回指定字段组，节省 token
- **查询计划**：`kan find ... --dry-run` 只返回数据源和字段计划，不取数
- **会话 delta**：`kan find ... --snapshot` / `--since <snapshot_id>` 显式保存和比较结构化结果
- **证据**：只引用返回的实际值、日期、来源与缺口；历史研究读取当次封存行情
- **日内范围**：`kan range <代码> --format json` 保留默认 5/15 日的样本数和 75/85/90/95 四档；`kan range --codes ... --format json` 最多 20 只并读取 `studies/errors/partial`；用户给出 `--down/--up` 时只复核该阈值

### MCP 趋势与研究

`kan_trend` 接收完整 `TrendSearchQuery`，与 CLI/Web 同源；`kan_research` 获取公司研究证据包。
真实工具列表以 `kan schema --section mcp --format json` 为准。
AI 不得把“低估、强势、近期”等模糊词静默映射成阈值，不得删除不支持条件后继续执行。

---

## 典型 AI 工作流

### 工作流 0：首次观察与留存

```bash
# 1. 确认安装版本和实际入口，不取行情
kan --version
kan discover --help
kan observe schema

# 2. 从完整范围的群体事实开始，不预置股票筛选条件
kan discover --window 20 --format json

# 3. 用户明确要留住观察时，按schema准备自己的标题/想法和固定query.as_of
kan observe save request.json --format json
kan observe list --format json
kan observe review <观察ID> --format json

# 4. 需要连接AI客户端时，先预览本机MCP注册目标
kan mcp install --dry-run --format json
```

先读取截止日、完整范围和各自的可判断分母。缺行情时，按用户所需范围与日期明确更新，再重跑观察；不自动扩大范围或换成旧日期。只有用户已有明确条件或指定代码时，继续调用 `kan trend`、`kan find` 或 `kan research`。

### 工作流 1：用户已明确规则的全市场扫描

```bash
# 1. 可选：预热全市场 K 线缓存（首次较慢）
kan fetch --all

# 2. 全市场位置坐标巡检
kan scan --all --periods 20,60,180 --format json

# 3. 执行用户明确给出的 180 日位置与 ST 范围
kan find --all --pos 180:lt:10 --exclude-st --format json --compact

# 4. 叠加资金流和估值过滤，控制字段量
kan find --all --pos 180:lt:10 --exclude-st --moneyflow gt:1000 \
  --fields @core,@context,@moneyflow --format json

# 5. 读取候选的客观详情
kan info <候选代码> --format json
```

### 工作流 2：行业维度扫描

```bash
# 1. 查看板块资金排名
kan board rank --kind industry --by moneyflow --format json

# 2. 查看连续上涨不少于 3 天的行业指数；只返回用户指定的客观阈值
kan board trend --kind industry --up 3 --format json

# 3. 连续阳线是另一口径，必须显式加 --candle
kan board trend --kind theme --up 3 --candle --format json

# 4. 用户给出行业名和阈值后执行，不根据榜单自动拼策略
kan find --industry <用户指定行业> --pos 60:lt:20 --format json --compact
```

### 工作流 3：真实持仓坐标

```bash
# 1. 查看真实持仓盈亏、仓位和 30/60/180 日位置
kan hold --format json --mask

# 2. 扫描全部持仓和关注
kan scan

# 3. 单独查看真实持仓池
kan find --only-holdings --format json
```

### 工作流 4：小代码池估值 / ROE 取数

```bash
# ROE 是逐股报告期数据；全市场模式不支持，先缩小代码池
kan find --codes 600519,000858 --roe gt:10 \
  --fields @core,@fundamentals --format json
```

### 工作流 5：自选股分组管理

```bash
# 1. 从行业扫描导入一批候选
kan add --industry <行业>  # 内置二次确认，会先显示数量
kan group create <组名>
kan add <代码> --group <组名>
kan add ...（逐只或批量导入）

# 2. 定期巡检分组
kan scan --group <组名>
```

---

## 已知限制（AI 需注意）

| 限制 | 影响 | 绕过方式 |
|------|------|----------|
| 上游数据可能缺失或限流 | 相关维度返回 null / `data_unavailable` | 先看 `data_availability` 和 JSON error hint |
| 部分逐股高成本维度不支持 `--all` | 如股东/ROE 类全市场模式不可用 | 改用行业/代码池小范围查询 |
| `kan history` 的位置回溯依赖扫描快照 | 未记录过的周期显示 null / `-` | 先用 `kan scan --periods N` 积累后再查 |
| MCP 默认本地运行 | stdio 适合已集成客户端；本机 HTTP endpoint 适合支持 Streamable HTTP 的 agent | `kan mcp install --dry-run --format json` 或 `kan mcp http --host localhost --port 8765` |
| 持仓实时价只服务盈亏现价口径 | 位置 / 共振仍按日 K 计算 | 看 `price_mode` 和 `data_cutoff` |

---

## 发现机制

Agent 可以通过以下方式发现 manmankan 的能力：

1. **本文件**（`skills/manmankan-skill.md`）——完整的能力清单
2. **`kan schema --format json`**——机器可读发现 CLI JSON、find DSL、MCP tools 和错误 envelope
3. **`kan --help` / `kan help`**——中文速记，含 group / JSON / fields / MCP 入口
4. **`kan examples`**——端到端工作流示例
5. **`kan fields list --format json`**——字段 preset 和白名单
6. **`kan mcp install --dry-run --format json`**——机器可读预览可注册的本机 MCP 客户端和目标配置
7. **`kan mcp http --help`**——查看本机 Streamable HTTP endpoint 参数和安全开关
8. **`kan <command> --help`**——每个命令的详细参数
9. **`docs/find.md`**——`kan find` 的完整 JSON schema 和字段定义
10. **`docs/ai-quickstart.md`**——首次接入的结构 smoke、真实行情路径和 MCP 规则
11. **`docs/mcp.md`**——MCP 支持客户端、dry-run、HTTP transport、写入规则和 agent 解释边界
12. **`docs/selection-workbench.md`**——研究保存、个人资料与现有入口边界

建议 AI 在首次使用 manmankan 时：

1. 读本文件及安装来源说明，用 `kan --version`、`kan discover --help` 确认实际入口。
2. 先用 `kan discover --format json` 看完整范围的分布、行业变化、覆盖和日期；缺数据时再按明确范围更新。
3. 用户要留住观察时，用 `kan observe schema/save/list/show/review` 保存与核对原事实、原成员和自己的想法。
4. 已有明确条件或指定对象，再读取 `kan trend --help`、`kan find --help`、`kan research --help`，按对应事实契约继续。

---

*维护：manmankan 能力变更时同步更新本文件 · 最后更新：2026-11-07*
