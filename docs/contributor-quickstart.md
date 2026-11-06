# 贡献者快速开始

慢慢看是 A 股数据研究工具。贡献从一个可观察的问题开始：找到相关调用链，完成改动，验证用户真正会走的路径。

## 本地运行

要求 Python 3.11+、uv；修改 Web 时使用 Node.js 24。

```bash
git clone https://github.com/piklen/manmankan.git
cd manmankan
uv sync --frozen
npm --prefix webui ci
git config core.hooksPath .githooks
uv run kan --help
uv run kan web
```

中国网络环境的安装和配置见 [中国用户快速开始](china-quickstart.md)。个人镜像、代理、token 和行情不提交到仓库。

只检查机器接口时可运行一条离线命令：

```bash
uv run kan find --codes 600519,000858 --format json --dry-run
```

它验证查询参数与 JSON 输出，不拉行情。查找研究指标用 `uv run kan study catalog`；MCP 安装预览用 `uv run kan mcp install --dry-run --format json`。

## 按改动验证

先跑最接近改动的有效检查。下面是选择依据，不是每次都要执行的清单。

| 改动 | 本地验证 |
|---|---|
| 计算、聚合、数据口径 | 受影响测试文件；用手算样本检查数值、分母、缺失与截止日 |
| CLI 或 HTTP 行为 | 相关契约测试，再实际运行变更入口 |
| 页面交互或样式 | 相关 Web 流程测试；浏览器操作桌面/窄屏主路径；`npm --prefix webui run build` |
| Python 依赖、包结构或入口 | `uv lock --check`，构建 wheel 后在干净环境运行 `scripts/smoke-installed.py` |
| 文档 | 核对相关命令和链接；提交前隐私扫描 |

例如，仅修改趋势计算时：

```bash
uv run pytest -q tests/test_trend_search.py
uv run ruff check kan/service/trend_search.py tests/test_trend_search.py
```

前端 `build` 已执行 API 生成、TypeScript 检查和打包，不必再重复执行 `check`。`webui/` 是源码，`kan/web/spa/` 是 wheel 中的构建产物，API schema 与构建产物由命令生成并一同提交。

CI 集中执行 Linux 离线回归、Web 流程、真实 PTY 输出与恢复，以及 macOS/Windows 干净安装。本地无需复跑完整平台矩阵。确需排查集成问题时使用 `uv run pytest -q -m "not network and not tty"`；启动耗时基准在修改启动路径时按需运行 `scripts/measure_slo.py`。

测试围绕当前契约和已发现的故障：不为私有函数逐个补测试、不比较源码字符串、不锁死命令数量、不保留旧实现的 monkeypatch 兼容路径。计算事实、外部输入边界、用户数据和安装可用性仍需有效覆盖。

## 提交

1. 检查当前分支与工作区，只包含本次修改。
2. 创建 `feature/<slug>` 分支，精确暂存文件。
3. 运行 `bash scripts/check-privacy-leaks.sh`，按上表完成必要验证。
4. 使用 `feat: ...`、`fix: ...` 等简短提交信息；PR 写清用户可观察的变化和实际验证。

用户可见内容保持客观，有来源、有时间和明确缺口，不给推荐、预测或买卖动作。参见 [合规边界](compliance.md)。趋势/研究契约变化同步 [趋势研究](trend-research.md)，机器接口变化同步对应帮助与 [AI 快速开始](ai-quickstart.md)。

不提交 token、个人账号、私有路径或真实持仓金额；不在提交、注释、文档加入 AI 工具署名。反馈问题前阅读 [SUPPORT](../SUPPORT.md) 与 [安全反馈说明](china-quickstart.md#8-反馈问题时请带上这些信息)。
