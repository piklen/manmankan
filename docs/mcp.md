# MCP 接入

`manmankan` 提供本地 stdio MCP server，让 AI 客户端直接调用同一套 CLI / JSON 数据契约。MCP 只负责把结构化行情数据交给 agent，不提供买卖动作、评级、目标价或策略结论。

## 快速路径

```bash
uv tool install manmankan
kan mcp install --dry-run
kan mcp install --client codex
```

先跑 `--dry-run`。确认目标客户端和配置路径无误后，再指定一个客户端写入配置；不要一开始对所有客户端批量写配置。

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

首次接入建议同时阅读 [`docs/ai-quickstart.md`](ai-quickstart.md) 和 [`docs/find.md`](find.md)。
