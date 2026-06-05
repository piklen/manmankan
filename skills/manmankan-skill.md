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

---

## 命令族

### 1. 扫描与发现

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan scan` | 扫描当前自选股的多周期位置 | 每日起手第一步，了解持仓+自选的整体位置 |
| `kan scan --group <组名>` | 扫描指定分组 | 分组巡检 |
| `kan scan --codes <代码列表>` | 扫描外部代码 | 临时查看一批候选 |
| `kan scan --industry <行业>` | 扫描申万行业成分股 | 行业维度扫描 |
| `kan info <代码>` | 单只股票全景：位置/估值/资金/技术 | 深度研判单只股票时用 |
| `kan compare <代码1> <代码2> ...` | 多股横向对比 | 候选池缩窄时比较 |

### 2. 条件筛选

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan find` | 按条件筛选股票 | **AI 的核心消费入口**——把自然语言需求翻译为 find 参数 |
| `--pos N:lt:M` | 位置筛选（N 日位置 < M%） | 如 `--pos 180:lt:10` = 180 日低位 |
| `--resonance low:gte:N` | 共振筛选（至少 N 个周期同时低位） | 多周期共振比单周期更可靠 |
| `--pe lt:V` / `--pe gt:V` | PE 估值筛选 | 注意：当前 PE 数据可能缺失（`data_availability.pe=false`） |
| `--moneyflow gt:V` | 主力资金净流入筛选（万元） | 当前为 5 日主力合计 |
| `--exclude-st` | 排除 ST 股 | **每次全市场扫描都必须加** |
| `--gain gt:V` | N 日涨幅筛选 | 避开短期涨幅过大的 |

### 3. 候选池管理

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan add <代码> [--group <组名>]` | 加自选股 | 可指定分组 |
| `kan remove <代码>` | 删自选股 | |
| `kan list [--group <组名>]` | 列出自选股 | |
| `kan group create/list/rename/delete/default` | 分组管理 | 分组是组织自选股的首选方式 |
| `kan move <代码> <源组> <目标组>` | 移动股票到另一组 | |
| `kan clear --group <组名>` | 清空分组 | 慎用 |
| `kan import/export` | 导入导出 CSV | 批量操作 |

### 4. 行情与榜单

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan history <代码> [--format json]` | 日 K 线历史 | 需要原数据时用 |
| `kan trend [--up/down N]` | 连续涨跌跟踪 | 发现异动 |
| `kan board rank --kind industry --by moneyflow` | 板块资金排名 | 大盘温度判断 |
| `kan low N` / `kan high N` | N 日新低/新高 | 极端位置发现 |

### 5. 数据维护

| 命令 | 用途 | AI 使用建议 |
|------|------|------------|
| `kan fetch [--all]` | 更新本地数据 | 每日首次使用前跑一次 |
| `kan fetch --codes <列表>` | 更新指定股票 | 新加入自选股后 |

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
    "code": "UNSUPPORTED_PERIOD",
    "message": "--pos 周期 20 不支持 · 仅 [3,5,7,10,15,30,60,90,120,180]",
    "hint": "最接近的是 15 或 30"
  }
}
```

### AI 消费要点
- **先检查 `ok` 字段**——`false` 时不要尝试解析 `results`
- **`data_availability` 是诚实信号**——`"pe": false` 表示 PE 数据不可用，AI 不应基于 PE 做判断
- **`schema_version` 用于版本适配**——当前为 1
- **紧凑模式**：加 `--compact` 减少输出的空格和缩进；加 `--no-compact-context` 移除上下文约定文本
- **字段白名单**：`--fields @core,@valuation,@moneyflow` 只返回指定字段组，节省 token

---

## 典型 AI 工作流

### 工作流 1：每日全市场扫描

```bash
# 1. 更新数据
kan fetch --all

# 2. 全市场低位筛选（排除 ST）
kan find --all --pos 180:lt:10 --exclude-st --format json --compact

# 3. 叠加资金流和估值过滤
kan find --all --pos 180:lt:10 --exclude-st --moneyflow gt:1000 --format json --compact

# 4. 对候选池做深度研判
kan info <候选代码> --format json
```

### 工作流 2：行业维度扫描

```bash
# 1. 查看板块资金排名
kan board rank --kind industry --by moneyflow --format json

# 2. 在资金流入前三的行业中找低位股
kan find --industry <行业名> --pos 60:lt:20 --format json --compact
```

### 工作流 3：持仓巡检

```bash
# 1. 扫描全部持仓和关注
kan scan

# 2. 检查是否有接近止损位的
kan find --codes <持仓代码列表> --pos 30:lt:15 --format json
```

### 工作流 4：自选股分组管理

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
| PE 数据当前可能缺失 | `kan find --pe` 可能返回空 | 用 tushare MCP 的 `daily_basic` 补 |
| 资金流仅为 5 日合计 | 无法判断"今日转向" | 用 tushare MCP 的 `moneyflow` 补单日 |
| 筛选周期仅支持 10 个固定值 | `--pos 20` 会报错 | 选最接近的（15 或 30） |
| JSON 部分命令输出不稳定 | board rank/industry scan 偶发空输出 | 降级到终端输出 + 正则解析 |
| `kan find --all` 无分页 | 结果可能截断 | 加更严格的筛选条件缩小范围 |
| MCP 仅提供本地 stdio | 远程 HTTP transport 尚未提供 | 先用 `kan mcp install --dry-run` 预览本机客户端注册 |
| 无实时行情 | 所有数据为日线级别 | 盘中不依赖 manmankan 做实时决策 |

---

## 发现机制

Agent 可以通过以下方式发现 manmankan 的能力：

1. **本文件**（`skills/manmankan-skill.md`）——完整的能力清单
2. **`kan --help`**——命令列表（无分组命令入口，需 `kan group --help`）
3. **`kan mcp install --dry-run`**——预览可注册的本机 MCP 客户端和目标配置
4. **`kan <command> --help`**——每个命令的详细参数
5. **`docs/find.md`**——`kan find` 的完整 JSON schema 和字段定义

建议 AI 在首次使用 manmankan 时：
1. 读本文件了解全局能力
2. 跑 `kan scan --help` 和 `kan find --help` 确认最新参数
3. 跑 `kan fetch` 确保数据是最新的

---

*维护：manmankan 能力变更时同步更新本文件 · 最后更新：2026-06-04*
