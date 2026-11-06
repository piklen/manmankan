# 贡献指南

慢慢看欢迎解决真实使用问题的改动。第一次进入项目先读 [贡献者快速开始](docs/contributor-quickstart.md)；任务约定见 [AGENTS.md](AGENTS.md)。

## 开发与验证

```bash
uv sync --frozen
npm --prefix webui ci
git config core.hooksPath .githooks
uv run kan web
```

使用 Python 3.11+、uv 和 Node.js 24。Python 使用类型注解、Pydantic v2 和 ruff；界面源码位于 `webui/`，由 `npm --prefix webui run build` 生成 API 类型和 wheel 中的静态资产。

从受影响的测试和真实用户路径验证，不要求每次改动在本地重跑全套。计算逻辑检查手算事实与数据缺口；交互变化实际操作页面或命令；依赖和制品变化才验证干净安装。具体命令和 CI 分工见 [按改动验证](docs/contributor-quickstart.md#按改动验证)。

测试服务于当前行为，不为覆盖率、源码形状、固定文案或命令数量建立门禁。删除实现时同步删除失效测试。真实数据边界、用户资产、计算准确性与输出契约不能用 mock 的自证结果替代。

## 代码和产品边界

- 先沿真实调用链定位问题，复用现有计算。需要重构时直接实现当前契约，不维护旧 API 或测试专用兼容层。
- 中文注释解释非显然意图，运行日志和协议字段保持英文。
- 用户可见事实必须有口径、日期和来源，数据缺失明确呈现。
- 公开产品不提供荐股、涨跌预测、评分评级、目标价或买卖建议。行为边界见 [compliance.md](docs/compliance.md)。

普通文案、错误反馈和可复现问题适合作为第一次贡献。新增数据源、改变数据口径或发布流程时，请在 PR 中说明影响及验证依据。

## 提交与 PR

创建 `feature/<slug>` 分支，只暂存本任务文件。提交使用 Conventional Commits，例如 `feat: 增加行业分布对照` 或 `fix: 修复缺行情的覆盖统计`。PR 说明具体问题、最终行为与实际执行的验证；用户接口变化同步对应帮助和文档。

提交前运行：

```bash
bash scripts/check-privacy-leaks.sh
```

本地 hooks 执行隐私扫描、lint 与分支保护；CI 执行集成验证。版本以包元数据、CHANGELOG 与发布 tag 核对，不从提交文字猜测。公开发布由维护者确认。

## 隐私与反馈

公开仓库、commit 和 PyPI 制品属于长期公开档案。不要提交 token、账号、私有路径、真实持仓金额、内部讨论或 AI 工具署名。使用 GitHub 的 noreply 邮箱可避免在公开提交中暴露个人邮箱；已发布历史不因此重写。

隐私扫描有两层：公开工具署名规则在脚本中，CI 同样执行；维护者的私密词表位于本地 `.ai/private/privacy-deny.txt`，不进仓库。私密词表缺失时只检查公开规则；命中后修正文案或错误词表，不跳过检查。私密词命中只显示位置，不输出原词。

先通过 [SUPPORT.md](SUPPORT.md) 选择 Issues 或 Discussions。报告 bug 时提供复现步骤、期望与实际行为、版本和脱敏后的相关日志；参见 [安全反馈说明](docs/china-quickstart.md#8-反馈问题时请带上这些信息)。
