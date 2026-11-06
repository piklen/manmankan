# MCP 接入

`manmankan` 提供本地 MCP server，让 AI 客户端调用同一套 Python application service 与既有 CLI / JSON 数据契约。当前支持 stdio 和本机 Streamable HTTP 两种 transport。MCP 可直接筛选当前趋势、执行确定性研究查询并返回证据，不提供买卖动作、评级、目标价或策略结论。

MCP `tools/list` 会返回每个工具的 `inputSchema` 和 `outputSchema`。`tools/call` 返回可读的 text content；工具结果为 JSON object 时同时返回 `structuredContent`，客户端可以直接校验和读取结构。

## 市场观察与持续核对

`kan_discover` 接收 `DiscoveryQuery`，直接返回当前分布、行业、固定成员轨迹与完整成员。先读`as_of`和各自覆盖分母，不从一个比例推断全体或未来。

`kan_observe` 的`action`为`list/show/save/review`。只有用户明确要求留存才`save`，此时`query.as_of`必须固定；`title/note`是用户的观察与自己的想法。`show`读取存档，`review`保留原代码集合和窗口，不覆盖原事实。列表返回`observations`数组，其余返回相应记录或复看结果。两次窗口可能重叠，不能当作从原日持有至当前的收益。

## 当前趋势筛选：`kan_trend`

`kan_trend` 使用 `TrendSearchQuery → TrendSearchResult`，与 Web、TUI 和 `kan trend` 直接调用同一服务。它读取本地日线，不自动补行情、保存筛选或创建历史研究。先明确股票范围和条件；`conditions: []` 表示调用方明确选择无条件浏览，不会暗加策略阈值。

下面是调用 `kan_trend` 的 `arguments`，数字仅演示用户明确填写的条件：

```json
{
  "universe": "all",
  "conditions": [
    {"field": "down_days", "operator": "gte", "value": 5}
  ]
}
```

指定代码池并核对先跌后涨：

```json
{
  "universe": "codes",
  "codes": ["600519", "300750"],
  "conditions": [
    {"field": "previous_down_days", "operator": "gte", "value": 3},
    {"field": "up_days", "operator": "gte", "value": 2}
  ]
}
```

范围可选 `all / personal / codes`；`personal` 包含自选、持仓与未拒绝候选。`industries` 按当前申万一级完整行业名筛范围；`as_of` 指定完整收盘日，留空请求最近完整收盘。日线条件全部按 AND 组合，字段、窗口与单位见 `kan study catalog`；`shape_distance` 还必须提供明确的 `reference: {symbol, as_of}`，不会把参照自身同日窗口当匹配。

收盘涨跌使用 `up_days / down_days`，阳阴线使用 `bull_days / bear_days`，同时收阳且收涨使用 `joint_up_days`；平盘、十字或缺行中断对应连续段。`previous_down_days / previous_up_days` 表示当前反向段紧接的前一段，`rising_days / falling_days` 搭配 `window` 表示最近 N 个市场交易日内的次数。若表达“上涨最多 3 天”，须同时显式传 `up_days lte 3` 和 `up_days gt 0`；单独 `lte 3` 在数值上也包含零天。区间计数 `rising_days / falling_days` 允许 0，例如最近 10 日上涨最多 3 天只需 `rising_days(window=10) lte 3`，不能暗加大于 0。

返回 `coverage.total/evaluated/matched/missing`、匹配 `rows`、无法判断的 `missing_rows`，以及行业筛选后的完整 `scope_codes`。`rows` 提供条件实际值、`lower_bounds`、当前连续段日期与涨跌幅、多周期位置、区间涨跌、来源和实际走势。缺行情不是不符合条件，只有长度下界也不能宣称恰好 N 天。`common_data_date/count` 提示缓存主要截止日与对象数，不会静默替换请求日期。

可选 `compare_to: "previous_session"` 或明确的 `YYYY-MM-DD` 开启两日对比。`comparison.as_of` 是对照日，`comparison.coverage` 汇总新出现、持续、退出、未知和自匹配排除；`comparison.rows` 给出两日 `matched / close / conditions / reason`。资料不足的 `matched` 为 `null`，不能当作 `false`。当前 `rows` 仍只代表截止日匹配，保存研究与当前对照分开。

当前筛选需要历史验证时，沿用完整 `scope_codes` 构造明确的 Study 条件和观察窗口，使用 `kan study` 或 Web/TUI 历史入口；不要只拿今天的匹配对象冒充原研究池。当前 MCP 不提供 Study 或保存筛选工具，不能虚构对应工具名。

## 公司研究事实

研究事实入口 `kan_research` 使用 `ResearchRequest → ResearchBundle`，直接调用共享 Python 服务。示例参数为 `{"codes":["600519"],"dimensions":["fundamentals"],"refresh":true}`，只刷新财务，不依赖行情。默认维度为市场、估值、财务；逐维度日期、来源、单位、缺失与引用在同一个包中返回。财务分别记录报告期、公告日和来源检查时间；不调用模型、不读取持仓。`ok=true,status=partial` 表示执行成功但材料质量不完整；实际取数失败通过 `isError=true` 报告并保留成功部分。完整契约见 [`research.md`](research.md)。

三表示例：`{"codes":["600519"],"dimensions":["income","balancesheet","cashflow"]}`。只获取所选表，返回报告期、实际公告日、合并报表类型与累计/期末口径；金额为元。逐表失败写入 `errors[].dimension`，不丢弃其他可用表。

## 快速路径

```bash
uv tool install manmankan
kan mcp install --dry-run
kan mcp install --dry-run --format json
kan mcp install --client codex
kan mcp http --port 8765
```

先跑 `--dry-run`。人看终端表格；agent / 脚本用 `--format json` 读取 `results` 和 `summary`。确认目标客户端和配置路径无误后，再指定一个客户端写入配置；不要一开始对所有客户端批量写配置。

Windows / PowerShell 不能用 `KAN_NO_UPDATE_CHECK=1 kan ...` 这种 Bash 写法，环境变量要先写进 `$env:`：

```powershell
$env:KAN_NO_UPDATE_CHECK = "1"
kan mcp install --dry-run
```

确认 `--dry-run` 预览的目标客户端和配置路径无误后，再写入单个客户端配置：

```powershell
kan mcp install --client codex
```

`--dry-run` 会列出可写入的客户端、动作和目标配置，但不会创建或修改文件。真实输出会按终端宽度换行，下面是脱敏后的 compact 形态：

```text
$ KAN_NO_UPDATE_CHECK=1 kan mcp install --dry-run
client          status        target                       detail
codex           would-update  ~/.codex/config.toml          mcp_servers.manmankan
claude-code     would-run     claude mcp add --scope user   kan-mcp
claude-desktop  would-update  <desktop app config>          mcpServers.manmankan
cursor          would-update  ~/.cursor/mcp.json            mcpServers.manmankan
vscode          would-update  ~/.vscode/mcp.json            servers.manmankan
gemini-cli      would-update  ~/.gemini/settings.json       mcpServers.manmankan
opencode        would-update  ~/.config/opencode/...        mcp.manmankan
```

看到 `would-update` / `would-run` 说明这次只是预览。确认目标客户端无误后，再执行 `kan mcp install --client <client>` 写入单个客户端配置。

Agent 或脚本可以直接取 JSON：

```bash
KAN_NO_UPDATE_CHECK=1 kan mcp install --client codex --dry-run --format json
```

脱敏摘录：

```json
{
  "ok": true,
  "command": "mcp install",
  "dry_run": true,
  "selected_clients": ["codex"],
  "results": [
    {
      "client": "codex",
      "status": "would-update",
      "target": "~/.codex/config.toml",
      "detail": "mcp_servers.manmankan"
    }
  ],
  "summary": {
    "total": 1,
    "failed": 0,
    "status_counts": {
      "would-update": 1
    },
    "needs_restart": true
  }
}
```

直接启动 stdio server：

```bash
kan mcp serve
```

启动本机 Streamable HTTP endpoint：

```bash
kan mcp http --host localhost --port 8765 --path /mcp
```

默认只绑定本机 loopback 地址，并检查浏览器 `Origin`，避免本地 MCP 被网页或 DNS rebinding 意外调用。`--allow-non-localhost` 只给可信内网或本机反向代理场景使用；对外入口应放在有鉴权和域名的上层网关后，不要直接裸露本机 MCP 端口。

安装包同时提供 `kan-mcp` entry point。客户端配置会优先使用已安装的 `kan-mcp`，其次使用 `kan mcp serve`，源码调试时回退到当前 Python 解释器运行 `kan.mcp.server`。

## 支持的客户端

`kan mcp install --client <client>` 支持以下 client 名称：

| client | 写入方式 |
|---|---|
| `codex` | `~/.codex/config.toml` 的 `mcp_servers.manmankan` |
| `claude-code` | 优先调用 `claude mcp add --scope user`，否则写入用户级 MCP 配置 |
| `claude-desktop` | desktop app 用户级 config |
| `cursor` | `~/.cursor/mcp.json` |
| `vscode` | `~/.vscode/mcp.json` |
| `windsurf` | Windsurf MCP config |
| `cline` | `~/.cline/mcp.json` |
| `gemini-cli` | `~/.gemini/settings.json` |
| `opencode` | `opencode.json` 的 `mcp.manmankan` |
| `zed` | Zed `context_servers.manmankan` |
| `openclaw` | OpenClaw MCP config |
| `amazon-q` | Amazon Q agent config |

支持列表以 `kan mcp install --help` 和 `kan/mcp/install.py` 为准。

## 写入规则

- 只写用户级配置，不写系统级配置。
- `--dry-run` 只预览，不创建或修改文件。
- 已存在 `manmankan` 配置时会覆盖同名配置；其他 MCP server 保持不变。
- JSON 配置文件如果不是对象或 JSON 无效，会返回 `failed`，不会继续覆盖。
- 写入后需要重启对应客户端。
- `kan mcp http` 是独立启动命令，不会自动写入客户端配置；HTTP client 连接 `http://localhost:<port>/mcp`。

## Agent 解释规则

MCP 工具返回的数据仍然遵守 CLI / JSON 契约：

`kan_observe` 保存先前 `kan_discover` 的观察时，传入对应 market/industry 组的 `fingerprint` 到 `expected_fingerprint`。事实变化会拒绝保存，用户文字应保留并重新核对，不能去掉指纹自动重试。

- 首次接入可先调用 `kan_schema`，或在 CLI 侧跑 `kan schema --format json --section mcp --compact` 查看工具 schema。
- 先检查 MCP `isError`；命令返回错误 envelope 时检查 `error` 或 `ok:false`。`kan_trend` 的成功结果使用 `coverage`，没有 `ok` 字段。
- 优先读取 `structuredContent`；没有该字段时再回退到 text content。
- 保留返回中的 `disclaimer`（若有）和 `warnings`。
- `kan_trend` 读取 `as_of`、`common_data_date/count`、`missing_rows` 与逐股来源；其他工具按各自返回读取 `data_cutoff / fetched_at`，不要假设数据实时。
- `kan_trend` 用 `coverage` 和缺口原因区分命中、未满足、无法判断；返回 `data_availability` 的其他工具按该字段区分未请求、缺数据和不支持。
- 把结果解释为研究输入，不输出买卖建议、预测、评级或策略结论。

`kan_screen_then_hydrate` 是复合 MCP tool：用用户显式 filter 做一次 `find`，并在同一次调用里按 `hydrate_fields` 补字段。默认字段是 `@core,@valuation,@moneyflow,@technical`。它只减少 tool 往返，不会添加默认策略、评分、排名结论或买卖建议。

需要把 MCP 返回、JSON envelope、错误输出或 dry-run 输出贴到 GitHub 时，先看 [`SUPPORT.md`](../SUPPORT.md) 区分 Issues / Discussions；公开反馈前按 [`安全反馈说明`](china-quickstart.md#8-反馈问题时请带上这些信息) 脱敏 token、代理账号、本机路径和真实持仓金额。

首次接入建议同时阅读 [`docs/ai-quickstart.md`](ai-quickstart.md) 和 [`docs/find.md`](find.md)。
