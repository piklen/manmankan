# AGENTS.md

## Scope

This file applies to the whole `manmankan` repository.

`manmankan` is a local-first China A-share screening and research workbench. Ordinary
retail users are the primary users: the local Web experience owns first-run, versioned
Screens, auditable runs, candidate research, comparisons, holdings, and data recovery.
AI agents and developers are secondary users served through the same stable CLI, JSON,
Python API, typed HTTP, and MCP contracts.

The tool stops at data facts. It must not produce buy/sell actions, ratings, price
targets, stock picks, strategy conclusions, or hosted advisory workflows.

## Start Here

- For ordinary-user first-run and daily workflows, read `README.md` and `docs/china-quickstart.md`.
- For using the CLI as an AI agent, read `skills/manmankan-skill.md` and `docs/ai-quickstart.md`.
- For JSON contracts, read `docs/find.md`.
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

Before changing user-visible CLI behavior, run at least one real CLI smoke:

```bash
KAN_NO_UPDATE_CHECK=1 uv run kan --help
KAN_NO_UPDATE_CHECK=1 uv run kan examples
KAN_NO_UPDATE_CHECK=1 uv run kan find --codes 600519,000858 --format json
```

When changing packaging, installation, MCP, public docs, or release surfaces, also run:

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
- `kan/cli/` owns argument parsing and user-facing command orchestration.
- `kan/service/` owns reusable business logic shared by Web, CLI, MCP, and Python API.
- `kan/data/` owns provider adapters and fallback chains.
- `kan/storage/` owns the SQLite workspace repository, XDG market/cache files, migration,
  rollback, and export payloads.
- `kan/render/` owns terminal rendering only.
- MCP tools should wrap CLI/service behavior; do not create a second business contract there.
- Do not let an AI/developer feature displace the ordinary-user Web path or introduce
  different calculations for the same fact.

## Change Discipline

- Keep README, `docs/`, `skills/manmankan-skill.md`, CLI help, tests, and site copy in sync.
- If a JSON field, filter, preset, or error envelope changes, update `docs/find.md` and tests.
- If an AI-facing workflow changes, update `skills/manmankan-skill.md` and `docs/ai-quickstart.md`.
- If a user-visible output changes, check `docs/compliance.md` before merging.
- The AI may autonomously choose and bump the next compatible patch version, prepare release artifacts, and complete pre-release verification. Publishing to PyPI/GitHub Release is the final public-release approval gate unless the maintainer already authorized release in the current request.
