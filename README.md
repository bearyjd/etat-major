# État-major

A self-hosted visual product-development workspace. It connects **why** you are building something (research and decisions), **what exists** (how the code works), **what should exist** (features, roadmap, planned architecture) and **how you are getting there** (evidence), so you can move along **Research → Decision → Feature → Design → Code → Evidence** in either direction. It is useful with no agent running.

**Status** — Design docs, a CLI over local and recorded data (`trace`, `decisions`, `index`, `research`, `gradle`, `components`, `floorplan`, `progress`, `workspace`, `serve`), and a read-only Planning and Understand web view served on loopback. Pinned, deterministic Floorplan steps run through the `floorplan` command, and a Trail runner wrapper builds in a disposable copy. Live GitHub access and the session-host and Meute integrations are pending.

Direction: [docs/VISUALIZATION-ARCHITECTURE.md](docs/VISUALIZATION-ARCHITECTURE.md). Plan: [docs/VISUALIZATION-ROADMAP.md](docs/VISUALIZATION-ROADMAP.md). Traceability model: [docs/TRACEABILITY.md](docs/TRACEABILITY.md). Tool choices: [docs/TOOL-EVALUATION.md](docs/TOOL-EVALUATION.md). [docs/SPEC.md](docs/SPEC.md) is the earlier agent-command-center design, partly superseded. Research notes: [docs/RESEARCH.md](docs/RESEARCH.md).

## Four connected views

1. **Discover (why):** market research, competitors, pain points, evidence, alternatives, decisions (including rejected ones) and feature proposals.
2. **Understand (what exists):** an architecture map and function-level code graph with source navigation. Verified, inferred and AI-generated information are always labelled apart.
3. **Design & Build (what should exist):** vision, approved features, a Now/Next/Later roadmap, Kanban, dependencies, diagrams and planned-architecture blueprints, linked to the code they touch.
4. **Progress (how we are getting there):** commits, pull requests, checks and releases mapped to features and milestones. Every completion claim links to proof or reads `unverified`.

## What it is not

Not a terminal, a coding-agent runner, a scheduler or a general project-management tool. Interactive agent sessions belong to the session host (today Paseo; [Codeman](https://github.com/Ark0N/Codeman) is legacy) and unattended runs to [Meute](https://github.com/bearyjd/meute); both are optional and separate. Architecture maps come from [Floorplan](https://github.com/haydenschmitty/floorplan) and function-level structure from Trail, both through replaceable read-only adapters. Code analysis is reused, not rebuilt. External research uses a manual ChatGPT handoff that you review. Durable intent lives in Git as Markdown, YAML and Mermaid.

## Principles

- Git holds intent. A rebuildable cache holds derived data and is never authoritative.
- Progress comes from evidence (commits, PRs, checks, tests, releases, human acceptance), never from an agent's own estimate.
- Never store, proxy or pool Claude or Codex credentials, and never switch accounts to dodge limits.

## Working in this repo

Read [CLAUDE.md](CLAUDE.md) first. Keep personal paths, hostnames and keys out of the repo.

## License

[AGPL-3.0](LICENSE).
