# État-major

A self-hosted, living visual map of your repositories: how each one works, what you are building toward, and how you are getting there, with evidence. It is useful with no agent running.

**Status:** pre-implementation. The product direction is in [docs/VISUALIZATION-ARCHITECTURE.md](docs/VISUALIZATION-ARCHITECTURE.md) and the plan in [docs/VISUALIZATION-ROADMAP.md](docs/VISUALIZATION-ROADMAP.md). [docs/SPEC.md](docs/SPEC.md) is the earlier agent-command-center design, partly superseded. Evidence behind component choices is in [docs/RESEARCH.md](docs/RESEARCH.md).

## Three views

1. **Understand:** repository selector, file tree, symbol search, an interactive module and function graph, and source navigation. Verified, inferred and AI-generated information are always labelled apart.
2. **Build:** vision, milestones, a Now/Next/Later roadmap, a Kanban board, task dependencies and versioned Mermaid diagrams, linked to the code they touch.
3. **Progress:** commits, pull requests, checks and releases mapped to milestones. Every completion claim links to proof or reads `unverified`.

## What it is not

Not a terminal, a coding-agent runner, a scheduler or a general project-management tool. Interactive agent sessions belong to [Codeman](https://github.com/Ark0N/Codeman) and unattended runs to [Meute](https://github.com/bearyjd/meute); both are optional and separate. Repository structure comes first from Trail through a replaceable adapter. Durable intent lives in Git as Markdown, YAML and Mermaid.

## Principles

- Git holds intent. A rebuildable cache holds derived data and is never authoritative.
- Progress comes from evidence (commits, PRs, checks, tests, releases, human acceptance), never from an agent's own estimate.
- Never store, proxy or pool Claude or Codex credentials, and never switch accounts to dodge limits.

## Working in this repo

Read [CLAUDE.md](CLAUDE.md) first. Keep personal paths, hostnames and keys out of the repo.

## License

[AGPL-3.0](LICENSE).
