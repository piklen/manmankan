# MCP 接入

`manmankan` 提供本地 stdio MCP server，让 AI 客户端直接调用同一套 CLI / JSON 数据契约。MCP 只负责把结构化行情数据交给 agent，不提供买卖动作、评级、目标价或策略结论。

## 快速路径

```bash
uv tool install manmankan
kan mcp install --dry-run
kan mcp install --client codex
```

先跑 `--dry-run`。确认目标客户端和配置路径无误后，再指定一个客户端写入配置；不要一开始对所有客户端批量写配置。

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

直接启动 server：

```bash
kan mcp serve
```

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

## Agent 解释规则

MCP 工具返回的数据仍然遵守 CLI / JSON 契约：

- 先检查 MCP `isError` 或 JSON `ok:false`。
- 保留 `disclaimer`。
- 读取 `data_cutoff` / `fetched_at`，不要假设数据实时。
- 用 `data_availability` 区分未请求、缺数据和当前模式不支持。
- 把结果解释为研究输入，不输出买卖建议、预测、评级或策略结论。

需要把 MCP 返回、JSON envelope、错误输出或 dry-run 输出贴到 GitHub 时，先看 [`SUPPORT.md`](../SUPPORT.md) 区分 Issues / Discussions；公开反馈前按 [`安全反馈说明`](china-quickstart.md#8-反馈问题时请带上这些信息) 脱敏 token、代理账号、本机路径和真实持仓金额。

首次接入建议同时阅读 [`docs/ai-quickstart.md`](ai-quickstart.md) 和 [`docs/find.md`](find.md)。
