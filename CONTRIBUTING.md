# 贡献指南

感谢你对慢慢看的兴趣！

如果你是第一次贡献，先看 [`docs/contributor-quickstart.md`](docs/contributor-quickstart.md)。那里按“选题 → 本地跑起来 → 最短 smoke → 按改动验证 → 发 PR”给出一条更短的实操路径。

## 开发环境

要求 Python 3.11+，推荐使用 [uv](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/piklen/manmankan.git
cd manmankan
uv sync

# 激活 pre-commit hook (隐私词扫描 · 防 PII 泄漏)
git config core.hooksPath .githooks
```

> ⚠️ 必须设 `core.hooksPath .githooks` 才能跑本地 pre-commit hook（隐私词扫描 + ruff lint）。
> CI 也会兜底跑（`.github/workflows/test.yml` privacy-scan job），但本地拦截能省一次 push 失败。

## 运行测试

```bash
uv run pytest
uv run pytest --cov=kan          # 带覆盖率
```

## 适合先做的小改动

如果你是第一次参与，可以从这些低风险范围开始：

- 文档错别字、命令示例、FAQ 和安装说明。
- `kan examples` / `kan --help` 中已经存在命令的说明补齐。
- 不改 JSON schema 的测试补充。
- 数据源失败时的错误提示改善（必须保留 `例:` 可复制命令）。

不适合作为第一次 PR 的范围：

- 新增数据源、改 JSON 顶层字段、改 release workflow。
- 新增筛选规则或技术指标解释。
- 任何可能被理解成买卖动作、评级、目标价或策略结论的输出。

使用 AI 编程助手参与代码贡献时，先读 [`AGENTS.md`](AGENTS.md)；使用 AI agent 调用 CLI 时，先读 [`docs/ai-quickstart.md`](docs/ai-quickstart.md) 和 [`skills/manmankan-skill.md`](skills/manmankan-skill.md)。

## 代码风格

- 使用 [ruff](https://docs.astral.sh/ruff/) 做 lint 和格式化：`uv run ruff check kan/`
- 类型注解：所有公开函数应有类型注解
- 命名：小写 + 下划线
- Pydantic v2 用于数据模型

## 合规红线（重要）

本项目严格定位为**行情数据展示工具**，PR 不应引入任何形式的：

- 买卖建议 / 评分评级 / 策略推荐
- 涨跌预测 / 目标价
- "建议关注 / 低估 / 见底 / 抄底" 等暗示性词汇

详见 [`docs/compliance.md`](docs/compliance.md)。

## 提交流程

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feat/your-feature`
3. 提交改动：`git commit -m "feat: ..."`
4. 推送到 fork：`git push origin feat/your-feature`
5. 在 GitHub 上发起 Pull Request

## Git Author Email 推荐(隐私保护)

公开开源仓 commit author email 通过 `git log` 可见 · 是 OSINT 数据库 / spam 钓鱼的常见来源。
推荐贡献者用 **GitHub noreply alias**(隐藏个人邮箱):

```bash
# 全局设置(所有 repo 生效)
git config --global user.email "<your-id>+<github-username>@users.noreply.github.com"

# 或仅本仓
git config user.email "<your-id>+<github-username>@users.noreply.github.com"
```

获取你的 noreply email:GitHub Settings → Emails → 启用 "Keep my email addresses private" · 页面会显示形如
`12345+username@users.noreply.github.com`。

**老 commits 不动**(避免 force-push 重写已发布历史)· 新 commits 起用 noreply。

## Commit Message 规范

使用 Conventional Commits 格式：

```
feat: 新功能
fix: 修复 bug
docs: 文档变更
refactor: 重构（不改变功能）
test: 测试相关
chore: 构建/依赖等杂项
```

- subject 简洁描述「做了什么」（用户视角）
- body 描述「why + how」
- **不带** `Co-authored-by: <AI tool>` trailer
- **不带** `🤖 Generated with <AI tool>` 类签名行
- **不带** AI 工具的 promo 链接

## 公开输出语言规范

manmankan 是公开开源项目，所有 commit / changelog / docs / 代码注释都是**永久公开档案**：

- 一旦 push 到 `origin/main`，即使删除也会留底（GitHub forks / archive 镜像 / search index）
- 一旦发布到 PyPI，包内 metadata（含 README / CHANGELOG）**完全无法修改**，只能 yank

**写之前先想 — 这条信息在 5 年后被 GitHub 上一个素未谋面的 contributor 看到，会不会显得奇怪？**

公开输出统一使用中性词：

- 提到维护者用 `维护者` / `开发者` / `用户`，不用任何昵称或私人称谓
- 提到协作过程用通用工程语言（`实测` / `已确认` / `测试`），不用内部 sprint 视角
- 提到代码评审用 `代码审查者`，不用 AI 工具名

发布前必跑禁用词扫描：

```bash
bash scripts/check-privacy-leaks.sh
```

或一次性启用 git pre-commit hook：

```bash
git config core.hooksPath .githooks
```

非零退出 = 立即停止 + 修完再 commit。

扫描器的禁用词分两层，避免「检查脚本本身泄漏待查词」：

- **公开词**（通用 AI 工具署名）内联在脚本里，CI 也会拦；
- **维护者自定的私密词 / 内部代号**放在 `.ai/private/privacy-deny.txt`（**gitignored，不进仓库**），脚本运行时动态读取，命中只回显「文件:行号」、不回显词本身。
- 该文件缺失时（CI runner / 新 clone）自动降级为只扫公开词——属正常，无需补建。CI 判定的是公开层；本地 pre-commit / commit-msg 判定的是公开层 + 私密层，二者不同是有意设计。私密层误报时应先修本地词表口径，不应跳过 hook。

维护者维护自己的私密词清单时，编辑本地 `.ai/private/privacy-deny.txt` 即可（一行一项，`re:` 前缀表示正则）。

## AI 协助开发

如果你用 AI 编程助手协助开发：

- **Commit message 不带 AI co-author trailer 和 AI 工具签名行**
  - 例外：依赖管理 / CI 自动化 bot 的 trailer 是业界标准，允许保留
    （`Co-authored-by: dependabot[bot]` / `renovate[bot]` / `github-actions[bot]` / `pre-commit-ci[bot]`）
  - 区分原则：AI 编程助手（生成代码 + 推理决策 + 上下文相关）禁；自动化 bot（无判断介入 + 无上下文泄漏）允许

- **代码注释 / 文档不暴露 AI 协作过程**
  - 不写 "AI 建议" / "和维护者讨论后" / "audit step #N" 等过程语
  - 注释只解释 why（非平凡决策 / 隐藏约束 / 已知坑），不引用任何内部协作语境

- **提交前跑 `bash scripts/check-privacy-leaks.sh` 自检**

## 报告问题

通过 [GitHub Issues](https://github.com/piklen/manmankan/issues) 报告 bug 或提出功能建议。
反馈前先看 [`SUPPORT.md`](SUPPORT.md) 区分 Issues / Discussions；贴日志或 JSON envelope 前先看 [`安全反馈说明`](docs/china-quickstart.md#8-反馈问题时请带上这些信息)，脱敏 token、代理账号、本机路径和持仓金额。

请提供：

- 复现步骤
- 期望行为 vs 实际行为
- Python 版本、操作系统
- 相关日志或截图
