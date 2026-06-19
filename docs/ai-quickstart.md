# AI agent 快速开始

`manmankan` 给外部 AI agent 提供可审计的 A 股数据输入：CLI、JSON、字段白名单和本地 MCP。工具只返回客观数据和用户显式规则命中结果，不内置 LLM，也不输出买卖动作、评级、目标价或策略结论。

## 1. 安装和发现

```bash
uv tool install manmankan
kan --version
KAN_NO_UPDATE_CHECK=1 kan find --codes 600519,000858 --format json
```

源码 main 或支持示例清单的版本，可以继续发现更多命令：

```bash
kan examples --format json
kan fields list --format json
```

`kan examples --format json` 会返回机器可读的候选命令清单。实际输出会包含更多示例，AI agent 可以先读 `examples[].command` 再选择最短命令：

```json
{
  "command": "examples",
  "examples": [
    {
      "title": "首次结构 smoke",
      "command": "kan find --codes 600519,000858 --format json",
      "detail": "不拉行情；确认 CLI、JSON envelope、退出码和免责声明正常。"
    },
    {
      "title": "真实行情坐标 JSON",
      "command": "kan scan --codes 600519,000858 --periods 5,20,60,180 --format json",
      "detail": "拉公开日 K；输出多周期位置、区间涨跌、共振和数据截止日。"
    }
  ]
}
```

这些命令只是入口示例；运行结果仍然要按 `ok` / 退出码 / `data_availability` / `disclaimer` 规则处理。

如果在仓库源码里调试，用：

```bash
uv sync
KAN_NO_UPDATE_CHECK=1 uv run kan examples
KAN_NO_UPDATE_CHECK=1 uv run kan examples --format json
KAN_NO_UPDATE_CHECK=1 uv run kan fields list --format json
```

源码调试时也可以用 `uv run kan examples --format json` 和 `uv run kan fields list --format json` 确认机器可读 examples 与字段 / preset 清单；这两个 smoke 都不拉行情。

## 2. 两条首用路径

### 结构 smoke：不拉行情

用于确认安装、入口、JSON envelope、免责声明和退出码都正常。这个命令只解析显式代码池，不触发行情拉取。

```bash
kan find --codes 600519,000858 --format json
```

AI 处理规则：

- 先检查 `ok` 或命令退出码。
- `results` 只有代码池事实，不代表行情维度已拉取。
- `disclaimer` 必须保留到下游输出。

### 真实行情坐标：会拉公开日 K

用于拿到多周期位置、区间涨跌、共振和数据截止日。首次运行会建立本地缓存，可能需要几十秒；后续同日运行会快很多。

```bash
kan scan --codes 600519,000858 --periods 5,20,60,180 --format json
```

AI 处理规则：

- 读取 `data_cutoff` / `fetched_at`，不要假设数据是实时的。
- `position_pct` 是区间坐标：`0` 接近该周期最低，`100` 接近该周期最高。
- `low_resonance` / `high_resonance` 是多个周期同时触及阈值的计数，不是行动信号。
- `null` 表示该维度没有可用数据；不要把它当作 `0`。

## 3. 可复制提示词

把 `kan find --codes ... --format json` 或 `kan scan --codes ... --format json` 的输出粘给外部 AI 时，可以直接用下面的提示词。提示词只让 AI 解释和整理数据，不让 AI 给交易结论。

### 解释 JSON 字段和缺数据状态

```text
你是 A 股数据解释助手。下面是 `kan find --codes 600519,000858 --format json` 的输出。

请先检查 `ok`、`error`、`data_availability` 和 `disclaimer`，再用中文说明：
1. 每个顶层字段的含义。
2. `results` 只代表显式代码池事实，不代表行情位置已经取到。
3. 哪些维度已形成证据，哪些维度未请求、不可用或缺失。

不要输出买卖建议、持仓建议、目标价、涨跌预测或股票评级。最后原样保留免责声明。

JSON:
```

### 转成后续核验清单

```text
你是研究助理。下面是 manmankan 的 JSON 输出，请把它整理成后续核验清单，不要给交易结论。

要求：
- 只使用 JSON 中已经存在的字段，缺失字段标为“未形成证据”。
- 每只股票最多列 3 个已知事实和 3 个待核验问题。
- 如果 `data_availability` 显示某维度不可用，不要补推断。
- 原样保留 `disclaimer`。
- 不输出买卖建议、持仓建议、目标价、涨跌预测或“强/弱/好/坏”评级。

JSON:
```

## 4. 低上下文 JSON

`kan find` 支持紧凑 JSON 和字段白名单：

```bash
kan find --industry 半导体 --format json --fields @core,@context
kan find --all --pe lt:20 --format json --compact --no-compact-context
kan find --codes 600519,000858 --roe gt:10 --fields @core,@fundamentals --format json
```

字段和 preset 以命令输出为准：

```bash
kan fields list --format json
```

`--all`、估值、资金、技术、筹码、股东等维度可能依赖 TuShare token 或上游接口权限。用 `data_availability` 区分未请求、不可用和缺失。

`@fundamentals` 是 ROE、净利润同比、营收同比等逐股报告期字段；全市场模式不支持这类逐股高成本维度，先用 `--codes`、`--industry` 或 `--theme` 缩小候选池。

## 5. MCP 接入

预览可写入的本机客户端配置：

```bash
kan mcp install --dry-run
```

`--dry-run` 只预览，不写配置；脱敏输出样例见 [`docs/mcp.md`](mcp.md)。

只注册指定客户端：

```bash
kan mcp install --client <client>
```

直接启动 stdio server：

```bash
kan mcp serve
```

MCP 工具仍沿用 CLI/JSON 契约。AI 调 MCP 时也要保留免责声明、检查错误 envelope，并把数据解释为研究输入而不是交易结论。

支持的客户端和写入规则见 [`docs/mcp.md`](mcp.md)。

## 6. 错误处理

JSON 模式下业务错误使用 envelope：

```json
{
  "ok": false,
  "error": {
    "code": "data_unavailable",
    "message": "...",
    "hint": "例: ..."
  }
}
```

处理顺序：

1. 检查进程退出码或 MCP `isError`。
2. 如果 JSON 有 `ok:false`，只读 `error.code/message/hint`，不要解析 `results`。
3. 如果 `data_availability` 标记维度缺失，明确说明该维度未形成证据。
4. 不要基于空字段补全推断。

需要把 JSON envelope 或错误输出贴到 GitHub 时，先看 [`SUPPORT.md`](../SUPPORT.md) 区分 Issues / Discussions；公开反馈前按 [`安全反馈说明`](china-quickstart.md#8-反馈问题时请带上这些信息) 脱敏 token、代理账号、本机路径和真实持仓金额。

## 7. 合规输出边界

可以说：

- "600519 在 180 日区间的位置百分位为 X。"
- "该命令返回了符合用户显式规则的候选池。"
- "资金 / 估值维度本次不可用，不能据此比较。"

不要说：

- "应买入 / 应卖出 / 适合持有。"
- "目标价是 X。"
- "这是优质标的 / 强信号 / 策略结论。"

完整边界见 `docs/compliance.md`。
