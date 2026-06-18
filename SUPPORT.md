# 支持说明

`manmankan` 是本地运行的 A 股数据 CLI。支持入口按问题类型分流，避免把安全问题、数据源波动和投资判断混在一起。

## 先看这些文档

- 首次安装和命令入口：[`README.md`](README.md)
- 中国用户 / 开发者网络与数据源排查：[`docs/china-quickstart.md`](docs/china-quickstart.md)
- AI agent 首次调用：[`docs/ai-quickstart.md`](docs/ai-quickstart.md)
- MCP 客户端接入：[`docs/mcp.md`](docs/mcp.md)
- JSON 字段和缺数据语义：[`docs/find.md`](docs/find.md)
- 公开输出合规边界：[`docs/compliance.md`](docs/compliance.md)
- 第一次贡献代码：[`docs/contributor-quickstart.md`](docs/contributor-quickstart.md)
- 贡献代码：[`CONTRIBUTING.md`](CONTRIBUTING.md)

## 可以用 GitHub Issues 反馈

- CLI 命令报错、退出码不符合预期、错误提示不可操作。
- JSON 字段缺失、schema 文档和实际输出不一致。
- MCP 注册失败、客户端配置路径不正确、dry-run 输出不清楚。
- 安装、Windows / macOS / Linux 环境兼容问题。
- 国内网络下 PyPI 下载、行情源访问、代理、TuShare 权限排查问题。
- 文档示例和真实命令不一致。

## 可以用 GitHub Discussions 交流

如果不是明确 bug，而是用法确认、环境排查、数据源现象、AI / MCP 接入经验或新功能方向讨论，优先用 [GitHub Discussions](https://github.com/piklen/manmankan/discussions)。

适合 Discussions 的问题：

- 中国网络环境下安装慢、PyPI 镜像、代理、Windows / PowerShell 经验交流。
- `kan find` / `kan scan` / `kan hold` 的使用口径确认。
- AI agent 如何消费 JSON / MCP 的工作流讨论。
- 还没形成明确复现步骤的想法或问题。

报告 bug 时请贴：

- `kan --version`
- 操作系统、Python 版本、终端类型
- 完整命令
- 完整错误输出或 JSON envelope
- 是否设置了 TuShare token（不要贴 token 原文）

## 不适合用 Issues 解决

- 个股买卖建议、持仓建议、目标价、涨跌预测。
- 第三方数据源临时限流、接口变更或上游数据口径争议。
- 你的本机自选股、持仓文件、缓存文件的私密内容。
- 二次分发法律结论、第三方数据源授权或具体合规法律意见。

## 安全问题

不要在公开 issue 中披露漏洞。请按 [`SECURITY.md`](SECURITY.md) 使用 GitHub Private Vulnerability Reporting。

## 数据源说明

行情和截面数据依赖 AKShare / baostock 生态及可选 TuShare Pro。上游不可用时，命令应给出可继续操作的错误提示；但上游服务稳定性和数据口径本身不由本项目控制。
