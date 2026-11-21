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
- `done`: written only by a human. The file format cannot prove who wrote it, so the guard covers every write path, not only the API:
  - Canonical task files stay writable by humans (Obsidian, any editor, git). Agent processes get no write access to canonical task files: they run in worktrees or sandboxes and change tasks only through the board API, which refuses to set `done`.
  - Git author metadata is self-reported and is not proof of a human decision. A worktree alone gives no write isolation, and a human-approved merge can carry an agent-authored status change. Neither counts as approval.
  - `done` reaches canonical state only with an authenticated human approval bound to one unique transition, not to content alone. The approval carries: task id, predecessor revision, candidate revision, status `done`, and a **transition sequence number** (a per-task counter, incremented on every canonical status change, including every reopen). Content hashes are allowed as revisions but never suffice alone: in `ready → done → ready → done` the predecessor and candidate bytes can be identical in both cycles, so hashes and statuses match across cycles. The sequence number is what differs. This holds for every path: a direct edit, a merge, a board action and an import. The reader rejects any `done` without an approval whose sequence number equals the next expected one and whose revisions match.
  - Every canonical reopen (any move from `done` to another status) is recorded as a transition that advances the sequence number. A reader that missed the reopen sees a sequence gap or mismatch and must reject the `done`, never treat it as a reread.
  - An approval is single-use. It is consumed atomically at the moment the change is promoted to canonical state, and a consumed approval never validates another transition. Re-reading is idempotent only when the canonical state records the consumed approval id and its sequence number and both match the approval presented. A matching revision pair alone is never a reread. A task reopened and marked `done` again needs a fresh approval with a new sequence number.
  - Single promotion boundary: because canonical files stay editable, a reopen and a restore of the old `done` bytes can both happen before any recorder observes them, and the reader would then see the original revision, sequence and approval id. So a canonical file is never trusted on its own. A status change becomes canonical only by passing through one promotion step that records the transition (sequence number, predecessor and candidate revisions, approval id) before the change is visible. A canonical file whose status or revision differs from the last recorded transition, or that no promotion recorded, is an unpromoted edit. The reader must reject it and must not accept it as a reread, even when its bytes match an earlier `done`. Detection is by comparing the file against the recorded transition, not by observing the intermediate edits.
  - Approval records are written only by a trusted path outside agent control. Agent processes and hooks have no write access to the approval store, and the hook recorder must not be able to create or alter approvals.
  - An import never persists `done` without that approval. An upstream `done` is held as an import error until a human approves it explicitly.
- `acceptance`: a YAML list of non-empty strings, order significant, with no checked state.

## Acceptance criteria mapping

Between Backlog.md's checklist and our YAML `acceptance` field.

| Direction | Rule |
|---|---|
| Backlog.md to ours (import) | Read the lines between `<!-- AC:BEGIN -->` and `<!-- AC:END -->`. Each `- [ ] #N text` or `- [x] #N text` becomes one list entry, `text`, in order. The `#N` prefix is dropped. |
| Import variants | Upstream also accepts unnumbered items (`- [ ] text`, `- [x] text`) and, when the AC markers are absent, a markerless checklist under the `## Acceptance Criteria` heading. The `#N` prefix is stripped only inside the marked block (`<!-- AC:BEGIN -->` to `<!-- AC:END -->`). In a markerless checklist, Backlog.md treats `#N` as literal text, so `- [ ] #42 remains visible` imports as `#42 remains visible`. Unnumbered items import as written. One entry per checklist item, in order. Any checklist line it cannot parse, or any criteria section it cannot locate, is reported as an import error. Criteria are never dropped silently. |
| Checked flag on import | Discarded from the contract. It is not copied to `status`. A checked box never produces `done`. An importer may report how many were checked, for a human to review. |
| Ours to Backlog.md (export) | Entry `i` (starting at 1) becomes `- [ ] #i text`, wrapped in the AC markers under a `## Acceptance Criteria` heading. All boxes are unchecked. |
| Round trip | `acceptance` to checklist to `acceptance` is lossless for plain-text entries. Entries must be single-line, so line breaks are rejected at validation. |
| Source of truth | Our YAML `acceptance` field. If both exist in one file, the YAML list wins and the checklist is regenerated on export. |

## Consequences

- The next units implement the task schema in `etat_major` with pydantic v2 (frontmatter parse and validation, plus the import and export mapping above).
- The SPEC's open question about Backlog.md is closed by this decision. `CLAUDE.md` says "Backlog.md, unless its format cannot carry acceptance criteria and owner". The format can carry both only by convention, so the exception applies. The maintainer should confirm the CLAUDE.md wording.
- Unit **u4** covers the hook recorder and the roll-up query. The event schema is out of scope here.

## Open questions

- How is a human approval authenticated (signed commit, board session login, or another mechanism), and how is an approval record bound to a task transition? This spike only states the requirement above. Unit **u4** owns it, through the `approvals` table in the runtime store. Unit **u2** owns the reader check that rejects an unapproved `done`.
- Which component is the trusted writer of approval records, and how does it consume an approval atomically when promoting a change? The requirement is stated above (approval bound to a unique transition sequence number plus predecessor and candidate revisions, single-use, every reopen recorded, not writable by agents or hooks). Unit **u4** owns the trusted write path and the atomic consume, alongside the `approvals` table. Unit **u4** also owns recording each reopen and issuing the sequence number. Unit **u2** must check the sequence number, both revisions and the consumed state in the reader.

## Limits of this spike

- Static reading of source at one commit. Backlog.md's CLI and MCP were not run.
- The preservation of unknown frontmatter keys was read in code, not exercised end to end.
- This change is docs-only and adds no tests.
- Who owns the single promotion boundary above (the step that records every canonical status change before it becomes visible, and quarantines edits made outside it)? The current unit plan assigns u2 a file validator and u4 a runtime store, hook recorder and roll-up query, and no unit the promotion workflow. Unit **u4** owns it, with the runtime store that holds the transition records. Unit **u2** owns the reader rule that rejects a file not matching the last recorded transition. This is an open design question until the maintainer confirms the assignment and adds it to the plan.
