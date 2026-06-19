# AGENTS.md

## Scope

This file applies to the whole `manmankan` repository.

`manmankan` is a local-first China A-share data translation CLI. It turns watchlists,
industries, themes, hot lists, holdings, full-market pools, or explicit code lists into
auditable terminal and JSON outputs for humans, scripts, and external AI agents.

The tool stops at data facts. It must not produce buy/sell actions, ratings, price
targets, stock picks, strategy conclusions, or hosted advisory workflows.

## Start Here

- For using the CLI as an AI agent, read `skills/manmankan-skill.md`.
- For a short first-run path, read `docs/ai-quickstart.md`.
- For JSON contracts, read `docs/find.md`.
- For compliance language, read `docs/compliance.md`.
- For architecture direction, read `docs/architecture.md`.
- For contribution rules, read `CONTRIBUTING.md`.

## youzi Private Environment Boundary

Inside `/Library/Code/AI/youzi`, data-hub test/production endpoint mapping lives in the root workspace SOT (`projects/data-hub/status.md`) and private credentials. Daily manmankan testing, endpoint smoke, pressure tests, and ordinary deploy validation should use the test edge from that SOT; do not hit the production edge unless the maintainer explicitly asks for a stable production deployment. Keep concrete private domains out of public manmankan docs.

## Development Commands

Use Python 3.11+ and `uv`.

```bash
uv sync
uv lock --check
uv run ruff check kan/ tests/
uv run mypy
uv run pytest -q -m "not network and not tty"
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

- Prefer existing CLI/service/data/render/storage boundaries before adding abstractions.
- `kan/cli/` owns argument parsing and user-facing command orchestration.
- `kan/service/` owns reusable business logic for CLI, MCP, and future local service layers.
- `kan/data/` owns provider adapters and fallback chains.
- `kan/storage/` owns XDG local files and export payloads.
- `kan/render/` owns terminal rendering only.
- MCP tools should wrap CLI/service behavior; do not create a second business contract there.

## Change Discipline

- Keep README, `docs/`, `skills/manmankan-skill.md`, CLI help, tests, and site copy in sync.
- If a JSON field, filter, preset, or error envelope changes, update `docs/find.md` and tests.
- If an AI-facing workflow changes, update `skills/manmankan-skill.md` and `docs/ai-quickstart.md`.
- If a user-visible output changes, check `docs/compliance.md` before merging.
- Do not bump the package version unless the maintainer explicitly asks for a release.
