# 贡献者快速开始

> 目标：第一次进仓库的开发者，30 分钟内能判断自己适合改什么、怎么验证、怎么发一个低风险 PR。

慢慢看是股票数据工具，但贡献流程按普通 Python CLI 项目处理。特殊点只有两个：

- 用户可见输出必须保持中性，不给买卖建议、评级、目标价或策略结论。
- 公开仓库不写私密路径、token、AI 工具签名、内部协作过程。

## 1. 先选一个小任务

第一次 PR 优先选这些范围：

- 文档错别字、命令示例、FAQ、安装说明。
- `kan examples` / `kan --help` 中已有命令的说明补齐。
- 不改 JSON schema 的测试补充。
- 数据源失败时的错误提示改善，保留可复制的 `例:` 命令。

可以从 [good first issue](https://github.com/piklen/manmankan/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22) 开始，也可以先发 [Discussions](https://github.com/piklen/manmankan/discussions) 确认想法。

第一次不建议碰：

- 新增数据源、改 JSON 顶层字段、改 release workflow。
- 新增筛选规则、技术指标解释或策略结论。
- 任何可能被理解成推荐、预测、评级或买卖动作的输出。

## 2. 本地跑起来

```bash
git clone https://github.com/piklen/manmankan.git
cd manmankan
uv sync --frozen --all-groups --all-extras
npm --prefix webui ci
git config core.hooksPath .githooks
```

中国网络环境下依赖下载慢时，先看 [`docs/china-quickstart.md`](china-quickstart.md)。不要把个人镜像、代理或 token 配置提交进仓库。

## 3. 做一个最短 smoke

先确认开发环境和 CLI 都能跑：

```bash
KAN_NO_UPDATE_CHECK=1 uv run kan --help
KAN_NO_UPDATE_CHECK=1 uv run kan examples
KAN_NO_UPDATE_CHECK=1 uv run kan examples --format json
KAN_NO_UPDATE_CHECK=1 uv run kan fields list --format json
KAN_NO_UPDATE_CHECK=1 uv run kan screen filters --format json
KAN_NO_UPDATE_CHECK=1 uv run kan find --codes 600519,000858 --format json --dry-run
KAN_NO_UPDATE_CHECK=1 uv run kan mcp install --dry-run --format json
```

Windows / PowerShell 不能用 `KAN_NO_UPDATE_CHECK=1 uv run ...` 这种 Bash 写法，环境变量要先写进 `$env:`：

```powershell
$env:KAN_NO_UPDATE_CHECK = "1"
$env:PYTHONUTF8 = "1"
uv run kan --help
uv run kan examples --format json
uv run kan fields list --format json
uv run kan mcp install --dry-run --format json
```

`uv run kan examples --format json`、`uv run kan fields list --format json` 和 `uv run kan mcp install --dry-run --format json` 是 discovery smoke，用于确认机器可读示例、字段 / preset 清单和 MCP 注册预览；不拉行情，也不写 MCP 配置。

`kan examples --format json` 用于确认机器可读示例清单，不拉行情；AI agent 可先读 [`docs/ai-quickstart.md`](ai-quickstart.md#1-安装和发现) 再选择最短命令。

`kan fields list --format json` 用于确认机器可读字段 / preset 清单，不拉行情。

`kan find --codes ... --format json --dry-run` 是结构 smoke，不拉行情；适合确认 JSON envelope、退出码、免责声明和查询计划。

`kan mcp install --dry-run --format json` 用于确认 MCP 注册预览 payload，不写用户配置。

## 4. 按改动类型验证

纯文档改动至少跑：

```bash
bash scripts/check-privacy-leaks.sh
```

改 Python 代码、CLI 输出或测试时跑：

```bash
uv lock --check
uv run ruff check kan/ tests/
uv run mypy
uv run pytest -q -m "not network and not tty"
bash scripts/check-privacy-leaks.sh
```

改 React、CSS、OpenAPI 或 `/api/v1` 时再跑：

```bash
npm --prefix webui ci
npm --prefix webui run check
npm --prefix webui test
npm --prefix webui run build
git diff --exit-code -- webui/openapi.json webui/src/api/schema.ts kan/web/spa
```

`webui/` 是开发源码，`kan/web/spa/` 是进入 wheel 的构建产物；两者必须在同一提交同步。不要手改生成的 OpenAPI、TypeScript schema 或 hashed bundle。

改安装、打包、MCP、README、站点或 release surface 时额外跑：

```bash
uv build --clear
KAN_NO_UPDATE_CHECK=1 uv run kan mcp install --dry-run --format json
```

## 5. 发 PR 前自检

- PR 标题用 Conventional Commits：`docs: ...` / `fix: ...` / `test: ...`。
- commit message 不带 AI co-author、generated-by 或工具广告。
- 截图、日志和 issue 内容不要包含 token、真实持仓金额、私有路径或代理账号。
- 提交 PR 或 issue 前先看 [`SUPPORT.md`](../SUPPORT.md) 区分入口；贴截图、日志或 JSON envelope 前先看 [`安全反馈说明`](china-quickstart.md#8-反馈问题时请带上这些信息) 并脱敏 token、代理账号、本机路径和真实持仓金额。
- 如果改了用户可见输出，先读 [`docs/compliance.md`](compliance.md)。
- 如果改了 JSON 字段、filter 或 error envelope，同步 [`docs/find.md`](find.md) 和测试。
- 如果改了 `ScreenSpec / ScreenRun` 或 `/api/v1`，同步 [`selection-workbench.md`](selection-workbench.md)、OpenAPI 生成物和 adapter 契约测试。
- 如果改了 AI / MCP 工作流，同步 [`docs/ai-quickstart.md`](ai-quickstart.md)、[`docs/mcp.md`](mcp.md) 或 [`skills/manmankan-skill.md`](../skills/manmankan-skill.md)。

## 6. 用 AI 编程助手协作

把下面这段作为起手上下文给 AI 编程助手即可：

```text
先读 AGENTS.md、CONTRIBUTING.md、docs/compliance.md。
本次只做一个低风险 PR，不改金融结论、不新增推荐/预测/买卖建议。
修改前先看相关文件和相邻调用链。
完成后跑 bash scripts/check-privacy-leaks.sh；如改代码再跑 ruff/mypy/pytest。
commit message 不带 AI 签名或 co-author。
```

AI 可以帮你查调用链、补测试、整理文档，但最终 PR 内容应该只描述代码和用户价值，不描述 AI 协作过程。
