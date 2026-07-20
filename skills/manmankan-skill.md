# manmankan Skill · AI Agent 能力清单

> 本文件是给 AI Agent 读的"说明书"。
> 当 Agent 读到本文件时，它应该能够自主发现 manmankan 的全部能力、命令语法、输出格式和错误处理方式。
> 格式参考 Agent Skills 标准（agent-data-cli / Dune CLI / Anthropic Skills）。

---

## 工具概述

**manmankan** (`kan`) 是一个 A 股本地数据筛选 CLI。
它不接 AI、不荐股、不预测——只提供结构化数据，供外部 AI（你）消费。

**命令入口**：终端执行 `kan <command> [options]`
**安装**：`uv tool install manmankan`
**市场**：当前仅 A 股（架构预留多市场扩展）
**首用文档**：`docs/ai-quickstart.md`
**MCP 文档**：`docs/mcp.md`

---

## 命令族

### 1. 扫描与发现

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan scan` | 扫描默认池（自选 ∪ 持仓）的多周期位置 | 每日起手第一步，了解持仓+自选的整体位置 |
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
| `kan find` | 按条件筛选股票 | **AI 的核心消费入口**——把自然语言需求翻译为 find 参数 |
| `--pos N:lt:M` | 位置筛选（N 日位置 < M%） | 如 `--pos 180:lt:10` = 180 日低位 |
| `--resonance low:gte:N` | 共振筛选（至少 N 个周期同时低位） | 多周期共振比单周期更可靠 |
| `--pe` / `--pb` / `--turnover` / `--market-cap` / `--volume-ratio` | 估值、换手、市值、量比筛选 | 来自截面指标；看 `data_availability` 区分缺数据 |
| `--roe` | ROE 逐股报告期筛选 | 需要先缩小代码池 / 行业 / 题材；全市场模式不支持 |
| `--moneyflow` / `--moneyflow-daily` / `--moneyflow-days` | 主力资金净额、单日资金、连续净流入天数 | 单位万元；输出分类资金流裸值 |
| `--exclude-st` | 排除 ST 股 | **每次全市场扫描都必须加** |
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
| `kan trend [--up/down N]` | 连续涨跌跟踪 | 发现异动 |
| `kan trend --all [--up/down N]` | 全市场连续涨跌跟踪 | 大池首轮看分布，必要时再缩小候选池 |
| `kan board rank --kind industry --by moneyflow --format json` | 板块资金排名 | 板块级客观裸值聚合 |
| `kan index [sh sz cyb hs300] --format json` | 常用指数日线位置参照 | 补大盘基准 |
| `kan low N` / `kan high N` | N 日新低/新高 | 极端位置发现；支持 `--all` 全市场池 |

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
| `kan fetch` | 更新当前自选数据 | 每日首次使用前跑一次；默认摘要输出 |
| `kan fetch 600519 000858` | 更新指定股票 | 新加入自选股后 |
| `kan fetch --all` | 预拉完整 A 股市场 K 线缓存 | 耗时较久；给 `scan/trend/low/high --all` 预热；明显不完整的上游响应会停止且不缓存 |
| `kan fetch --verbose` | 逐只输出拉取状态 | 排障时使用 |

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

---

## 典型 AI 工作流

### 工作流 0：首次接入 smoke

```bash
# 1. 不取数，只确认 CLI / JSON envelope / query plan / disclaimer 正常
kan find --codes 600519,000858 --format json --dry-run

# 2. 代码池宽表补全；无 filter 也会按字段补客观数据
kan find --codes 600519,000858 \
  --fields @core,@valuation,@moneyflow,@technical \
  --format json

# 3. 拉公开日 K，拿真实多周期位置坐标
kan scan --codes 600519,000858 --periods 5,20,60,180 --format json

# 4. 预览本机 MCP 注册目标
kan mcp install --dry-run --format json

# 5. 如客户端支持 HTTP transport，可启动本机 endpoint
kan mcp http --host localhost --port 8765 --path /mcp
```

第 1 步只返回查询计划，不代表行情维度已取到。第 2 步返回字段补全事实，`triggered_filters=[]` 是正常状态。第 3 步首次运行会建立本地缓存，可能需要几十秒；读取 `data_cutoff` / `fetched_at` 后再解释结果。

### 工作流 1：每日全市场扫描

```bash
# 1. 可选：预热全市场 K 线缓存（首次较慢）
kan fetch --all

# 2. 全市场位置坐标巡检
kan scan --all --periods 20,60,180 --format json

# 3. 全市场低位筛选（排除 ST）
kan find --all --pos 180:lt:10 --exclude-st --format json --compact

# 4. 叠加资金流和估值过滤，控制字段量
kan find --all --pos 180:lt:10 --exclude-st --moneyflow gt:1000 \
  --fields @core,@context,@moneyflow --format json

# 5. 对候选池做深度研判
kan info <候选代码> --format json
```

### 工作流 2：行业维度扫描

```bash
# 1. 查看板块资金排名
kan board rank --kind industry --by moneyflow --format json

# 2. 在资金流入前三的行业中找低位股
kan find --industry <行业名> --pos 60:lt:20 --format json --compact
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
| 历史回溯依赖扫描快照 | 未记录过的周期显示 null / `-` | 先用 `kan scan --periods N` 积累后再查 |
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

建议 AI 在首次使用 manmankan 时：
1. 读本文件了解全局能力
2. 跑 `kan schema --format json --section find --compact` 获取最新机器可读契约
3. 跑 `kan scan --help` 和 `kan find --help` 确认人类可读参数说明
4. 跑 `kan fetch` 确保数据是最新的

---

*维护：manmankan 能力变更时同步更新本文件 · 最后更新：2026-06-19*
