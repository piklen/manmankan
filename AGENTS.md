# AGENTS.md

## Scope

This file applies to the whole `manmankan` repository.

`manmankan` 是面向散户的本地 A 股研究工具。当前演进以 CLI 和可供 AI 调用的共享
Python 服务为主，按真实研究问题补数据。保留模块化单体、SQLite 和 Parquet；Web
提供图表、比较和人工编辑。CLI、JSON、Python API、HTTP 与 MCP 复用同一套计算。

The tool stops at data facts. It must not produce buy/sell actions, ratings, price
targets, stock picks, strategy conclusions, or hosted advisory workflows.

## Start Here

- For ordinary-user first-run and daily workflows, read `README.md` and `docs/china-quickstart.md`.
- For using the CLI as an AI agent, read `skills/manmankan-skill.md` and `docs/ai-quickstart.md`.
- For JSON contracts, read `docs/find.md`.
- For the CLI / AI research evidence contract, read `docs/research.md`.
- For the vNext domain and adapter contract, read `docs/selection-workbench.md`.
- For local-state migration and rollback, read `docs/workspace-migration.md`.
- For compliance language, read `docs/compliance.md`.
- For architecture direction, read `docs/architecture.md`.
- For contribution rules, read `CONTRIBUTING.md`.

## Owner Workspace Boundary

Maintainer-local endpoint mapping lives outside this public repository. Daily local testing, endpoint smoke, pressure tests, and ordinary deploy validation should use the non-production test edge from that owner-only SOT. Do not hit a production edge unless the maintainer explicitly asks for a stable production deployment. Keep concrete private domains out of public docs.

## AI Engineering Autonomy and Research Responsibility

- The maintainer defines the objective and reviews the completed result. Within that objective, the AI is the engineering owner and should independently investigate, design, implement, migrate, test, benchmark, document, commit, open PRs, resolve review/CI, and merge eligible development changes.
- Routine technical choices do not require step-by-step approval. The AI may refactor or replace architecture, dependencies, storage, cache, concurrency, data contracts, public APIs, CI/CD, packaging, and test deployment when the net result is better; preserve compatibility only when current users or an explicit contract require it, otherwise provide a clean migration.
- Existing owner credentials, Tushare quota, local datasets, and the non-production edge may be used for real verification without delegating commands back to the maintainer. Never print, persist, commit, or disclose secret values.
- Private, authorized learning is not limited by the public product's neutral-output positioning. The AI should help study data, routing, caching, concurrency, screening, and financial concepts; third-party recommended usage or commercial positioning warrants one factual risk note and an isolated test strategy, not refusal or repeated discouragement. Public product surfaces and committed examples must still follow `docs/compliance.md`.
- The maintainer is responsible for the final decision to adopt, run, publish, or trade on research output. The AI remains responsible for factual accuracy, implementation quality, reproducible evidence, risk disclosure, and rollback.
- Pause only for an irreducible product-goal conflict, significant new spending or missing credentials, irreversible production destruction without a tested restore path, or the final public/production release unless the current request already authorizes it. Everything else should be resolved and presented in the final review package.

## Development Commands

Use Python 3.11+ and `uv`.

下面是可用命令，不是每次变更都要跑的清单。先验证改动主路径和已经发现的回归；
已有 CI 覆盖的完整矩阵无需在本地重复执行。只有新变更、失败或未解决疑点才追加检查。

```bash
uv sync
uv lock --check
uv run ruff check kan/ tests/
uv run mypy
uv run pytest -q -m "not network and not tty"
npm --prefix webui ci
npm --prefix webui run check
npm --prefix webui test
npm --prefix webui run build
bash scripts/check-privacy-leaks.sh
```

CLI 行为改变时，实际运行受影响命令。例如财务研究入口：

```bash
KAN_NO_UPDATE_CHECK=1 uv run kan research 600519 --dimensions fundamentals --format json
```

打包或安装行为改变时检查构建；MCP 注册行为改变时检查安装预演。普通文档或业务参数变化不触发这两项：

```bash
uv build --clear
KAN_NO_UPDATE_CHECK=1 uv run kan mcp install --dry-run
```

## Public Output Rules

- User-facing Chinese copy is the default for CLI, docs, comments, and examples.
- Keep runtime logs and protocol field names in English when they are consumed by tools.
- Do not include AI assistant signatures, generated-by lines, private nicknames, private paths,
  tokens, account details, or local-only planning terms in commits or docs.
- Keep every data output neutral: "position", "range", "matches the user rule", "data unavailable".
- Preserve disclaimers in terminal, Markdown, JSON, site, and derivative documentation.

## Code Boundaries

- Use existing CLI/service/data/render/storage boundaries while they remain the clearest route to the objective; refactor or replace them when evidence shows a correctness, performance, or maintainability ceiling.
- 保持最小充分实现：复用已有函数和契约，不为假想需求新增服务、通用框架、兼容层或门禁。输入校验放在外部边界；内部按既有契约调用，不逐层重复防御。仅处理已发现或直接影响主路径的失败。
- `kan/cli/` owns argument parsing and user-facing command orchestration.
- `kan/service/` owns reusable business logic shared by Web, CLI, MCP, and Python API.
- `kan/data/` owns provider adapters and fallback chains.
- `kan/storage/` owns the SQLite workspace repository, XDG market/cache files, migration,
  rollback, and export payloads.
- `kan/render/` owns terminal rendering only.
- MCP tools should wrap CLI/service behavior; do not create a second business contract there.
- CLI 与 Web 的相同事实必须来自共享计算，不为不同入口维护两套业务规则。

## Change Discipline

- Keep README, `docs/`, `skills/manmankan-skill.md`, CLI help, tests, and site copy in sync.
- If a JSON field, filter, preset, or error envelope changes, update `docs/find.md` and tests.
- If an AI-facing workflow changes, update `skills/manmankan-skill.md` and `docs/ai-quickstart.md`.
- If a user-visible output changes, check `docs/compliance.md` before merging.
- The AI may autonomously choose and bump the next compatible patch version, prepare release artifacts, and complete pre-release verification. Publishing to PyPI/GitHub Release is the final public-release approval gate unless the maintainer already authorized release in the current request.
