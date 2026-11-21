# Phase 1 spike: Backlog.md task format and hook-to-SQLite events

Status: decided. Closes the open question in `docs/SPEC.md`: "Confirm Backlog.md's file format can carry acceptance criteria and owner, or define the task contract on top of it."

## Scope

- In scope: whether the Backlog.md task file format can carry the product contract.
- Deferred to unit **u4**: the hook recorder (hook script writing events into SQLite) and the roll-up query ("what needs me"). Nothing in this spike evaluates them, and the decision below does not depend on them.

## Product contract under test

From `docs/SPEC.md` (rule 3, example task file, status lifecycle):

1. **Singleton owner.** Exactly one `owner` per task (for example `alice`).
2. **Acceptance criteria as a structured list.** A YAML `acceptance:` list of strings.
3. **Intent statuses** limited to `draft`, `ready`, `blocked`, `done`. Only a human writes `done`. `running`, `needs-you`, `review` and `failed` are derived and never written.

## What was inspected

- Repository: https://github.com/MrLesk/Backlog.md
- Commit: `9087714336b3de5641a0ec5ed5d1342d12d68205` (committed 2026-11-21 18:50:15 +0000), cloned to a temporary directory outside this repo.
- Files read: `backlog/config.yml`, a sample task (`backlog/tasks/back-200 - ...md`), `src/markdown/parser.ts`, `src/markdown/serializer.ts`, `src/markdown/frontmatter.ts`, `src/markdown/structured-sections.ts`, `src/types/index.ts`, `src/file-system/operations.ts`.

## Findings

### Task file shape

Frontmatter fields written by the serializer: `id`, `title`, `status`, `assignee`, `reporter`, `created_date`, `updated_date`, `due_date`, `labels`, `milestone`, `dependencies`, `references`, `documentation`, `modified_files`, `parent_task_id`, `subtasks`, `priority`, `type`, `project`, `ordinal`, `onStatusChange`. The body holds Markdown sections (Description, Acceptance Criteria, Implementation Plan and others).

### Status: configurable, but only as a free string

- `config.yml` carries `statuses: ["To Do", "In Progress", "Done"]` by default. The list is user-configurable (`src/core/init.ts`, `src/file-system/operations.ts`).
- The parser reads `status` as `String(frontmatter.status || "")`, with no hard-coded enum. A configured set of `draft`, `ready`, `blocked`, `done` is therefore representable, and `default_status` can be `draft`.
- Backlog.md treats the last status as terminal (`isTerminalStatus` in `src/core/milestones.ts`), so `done` should be listed last.
- **No write authorization.** Any CLI, MCP or web caller can set any configured status. "Only a human writes `done`" is not enforceable by Backlog.md. It would have to be enforced by our own layer, whichever format we choose.
- Backlog.md also has a separate `drafts/` folder and a `completed/` folder. A `draft` status inside `tasks/` would overlap with the `drafts/` concept, which is confusing but not blocking.
- Verdict: a configured status set **satisfies the status vocabulary** and **does not satisfy the write rule** (nothing in the format could).

### Owner: assignee is a list

- `assignee` is `string[]` (`src/types/index.ts`). The parser accepts a scalar or a list and normalises to a list (`src/markdown/parser.ts`). The serializer always writes a list, for example `assignee: []`.
- The format and tooling do not limit it to one value, and an empty list is the default. A singleton owner is not guaranteed.
- A convention would work: exactly one element, mapped to `owner`. Backlog.md would not enforce it. Our reader would have to reject zero or more than one.
- Verdict: the field **can carry** an owner but **does not satisfy the singleton** contract by itself.

### Acceptance criteria: checklist in the body, not frontmatter

- Stored in the body as a Markdown checklist between markers:

  ```
  ## Acceptance Criteria
  <!-- AC:BEGIN -->
  - [ ] #1 Maps all source tables listed in docs/sources.md
  - [x] #2 Unit tests pass in CI
  <!-- AC:END -->
  ```

- Each item has an index (`#N`), text and a checked flag (`AcceptanceCriterion` with `index`, `checked`, `text`).
- Verdict: it **can carry** structured acceptance criteria, but in a different shape from our YAML `acceptance:` list. The checked flag has no counterpart in our contract.

### Unknown frontmatter keys

- `stringifyFrontmatter` preserves unknown keys from the original file on rewrite (`preserveUnknownFrontmatter`). Our extra keys (`initiative`, `owner`, `budget_tokens`, `acceptance`) would survive a Backlog.md edit. This is by implementation, not by documented guarantee.
- The serializer's own field list includes `project` and `priority`, but `priority` is typed as `high|medium|low` in the sample, not our integer `2`. Our values would be preserved or rewritten depending on parsing, which is another reason not to share fields.

## Decision

**Define our own contract on top.** The task file format is État-major's own contract, with the frontmatter from the SPEC example (`id`, `title`, `initiative`, `project`, `owner`, `status`, `priority`, `acceptance`, `budget_tokens`). Backlog.md is **not a dependency**. Its files and ours stay close enough that a Backlog.md folder can be read or imported, as described below.

Why not adopt as-is or adopt with config:

- Configured statuses solve the vocabulary only. They cannot make the checklist, `assignee` or the human-only `done` rule match the contract.
- `assignee` is a list, so the singleton owner would be a convention that Backlog.md never checks, and the `owner` key is not used by Backlog.md.
- Acceptance criteria live in the body as a checklist, not in a frontmatter list, so we would need a translation layer either way.
- Since a validating layer is needed anyway, we keep one schema (pydantic) as the single source of truth instead of two overlapping ones.

This keeps the SPEC rule that task files are editable in Obsidian or any editor. It also keeps the option of using Backlog.md's UI as a viewer, since unknown keys are preserved.

### Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Adopt as-is (default config) | Statuses are `To Do`, `In Progress`, `Done`. These include derived states we must never write and omit `draft`, `ready` and `blocked`. |
| Adopt with config (statuses `draft, ready, blocked, done`, `assignee` as owner) | The vocabulary fits, but the singleton owner is unenforced, acceptance criteria are in the wrong place and shape, and a human-only `done` cannot be expressed. We would add the contract layer anyway, then carry a Bun/TypeScript tool and its config in a Python project for no gain. |
| Store acceptance criteria only as the Backlog.md checklist | Our contract wants a plain list of strings in frontmatter, readable without parsing body markers. The checked flag also invites writing completion state into git, which clashes with the human-only `done` rule. |
| Fork Backlog.md | Large maintenance surface for a format that is simple to define ourselves. |

## Contract we define

- `owner`: a single non-empty string. Zero, a list or more than one value is a validation error.
- `status`: one of `draft`, `ready`, `blocked`, `done`. Any other value in a file is rejected, including the derived states `running`, `needs-you`, `review`, `failed`.
- `done`: written only by a human. The file format cannot prove who wrote it, so the guard lives in the board/API layer. Agents and adapters go through an API that refuses to set `done`.
- `acceptance`: a YAML list of non-empty strings, order significant, with no checked state.

## Acceptance criteria mapping

Between Backlog.md's checklist and our YAML `acceptance` field.

| Direction | Rule |
|---|---|
| Backlog.md to ours (import) | Read the lines between `<!-- AC:BEGIN -->` and `<!-- AC:END -->`. Each `- [ ] #N text` or `- [x] #N text` becomes one list entry, `text`, in order. The `#N` prefix is dropped. |
| Import variants | Upstream also accepts unnumbered items (`- [ ] text`, `- [x] text`) and, when the AC markers are absent, a markerless checklist under the `## Acceptance Criteria` heading. The importer handles both the same way: one entry per checklist item, in order, with the optional `#N` dropped. Any checklist line it cannot parse, or any criteria section it cannot locate, is reported as an import error. Criteria are never dropped silently. |
| Checked flag on import | Discarded from the contract. It is not copied to `status`. A checked box never produces `done`. An importer may report how many were checked, for a human to review. |
| Ours to Backlog.md (export) | Entry `i` (starting at 1) becomes `- [ ] #i text`, wrapped in the AC markers under a `## Acceptance Criteria` heading. All boxes are unchecked. |
| Round trip | `acceptance` to checklist to `acceptance` is lossless for plain-text entries. Entries must be single-line, so line breaks are rejected at validation. |
| Source of truth | Our YAML `acceptance` field. If both exist in one file, the YAML list wins and the checklist is regenerated on export. |

## Consequences

- The next units implement the task schema in `etat_major` with pydantic v2 (frontmatter parse and validation, plus the import and export mapping above).
- The SPEC's open question about Backlog.md is closed by this decision. `CLAUDE.md` says "Backlog.md, unless its format cannot carry acceptance criteria and owner". The format can carry both only by convention, so the exception applies. The maintainer should confirm the CLAUDE.md wording.
- Unit **u4** covers the hook recorder and the roll-up query. The event schema is out of scope here.

## Limits of this spike

- Static reading of source at one commit. Backlog.md's CLI and MCP were not run.
- The preservation of unknown frontmatter keys was read in code, not exercised end to end.
- The only tests are doc-content checks in `tests/test_spike_doc.py`.
