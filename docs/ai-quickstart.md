# AI agent 快速开始

`manmankan` 给外部 AI agent 提供可审计的 A 股数据输入：CLI、JSON、字段白名单和本地 MCP。工具只返回客观数据和用户显式规则命中结果，不内置 LLM，也不输出买卖动作、评级、目标价或策略结论。

## 1. 安装和发现

```bash
uv tool install manmankan
kan --version
kan examples
kan fields list --format json
```

如果在仓库源码里调试，用：

```bash
uv sync
KAN_NO_UPDATE_CHECK=1 uv run kan examples
```

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

## 3. 低上下文 JSON

`kan find` 支持紧凑 JSON 和字段白名单：

```bash
kan find --industry 半导体 --format json --fields @core,@context
kan find --all --pe lt:20 --format json --compact --no-compact-context
```

字段和 preset 以命令输出为准：

```bash
kan fields list --format json
```

`--all`、估值、资金、技术、筹码、股东等维度可能依赖 TuShare token 或上游接口权限。用 `data_availability` 区分未请求、不可用和缺失。

## 4. MCP 接入

预览可写入的本机客户端配置：

```bash
kan mcp install --dry-run
```

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

## 5. 错误处理

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

## 6. 合规输出边界

可以说：

- "600519 在 180 日区间的位置百分位为 X。"
- "该命令返回了符合用户显式规则的候选池。"
- "资金 / 估值维度本次不可用，不能据此比较。"

不要说：

- "应买入 / 应卖出 / 适合持有。"
- "目标价是 X。"
- "这是优质标的 / 强信号 / 策略结论。"

完整边界见 `docs/compliance.md`。
