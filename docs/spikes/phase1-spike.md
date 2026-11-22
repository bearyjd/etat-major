# Phase 1 spike: can Backlog.md's task format carry the product contract?

Status: decided. Closes the open question in `docs/SPEC.md`: "Confirm Backlog.md's file format can carry acceptance criteria and owner, or define the task contract on top of it."

## Decision

**Define our own contract on top.** The task file is État-major's own format, with the frontmatter from the SPEC example. Backlog.md is not a dependency.

Backlog.md's format can carry each part of the contract only by convention, and one part (the `draft` status) collides with its own behaviour. A validator is needed either way, so we keep one schema instead of two overlapping ones.

## Contract under test

From `docs/SPEC.md` (principle 3, the example task file, the status lifecycle):

1. **Singleton owner:** exactly one `owner` per task.
2. **Structured acceptance list:** a YAML `acceptance:` list of strings.
3. **Intent statuses:** only `draft`, `ready`, `blocked` and `done` are written to the file, and only a human writes `done`.

## What was inspected

- Repository: https://github.com/MrLesk/Backlog.md
- Commit: `9087714336b3de5641a0ec5ed5d1342d12d68205`
- Method: static reading of the source at that commit. The CLI, MCP server and web UI were not run.

## Key evidence

| Contract part | What Backlog.md does | Fit |
|---|---|---|
| Status vocabulary | `statuses` in `backlog/config.yml` is user-configurable (default `To Do`, `In Progress`, `Done`). The parser reads `status` as a free string with no enum (`src/markdown/parser.ts`). The last configured status is the terminal one (`src/utils/terminal-status.ts`). | `ready`, `blocked` and `done` fit by config. |
| `draft` status | Reserved. Backlog.md matches the status name `draft` case-insensitively and treats it as its own draft concept: creating a task with that status gives it a `DRAFT-n` id, and editing a task to that status moves it out of `tasks/` into the `drafts/` folder (`src/core/backlog.ts`). | Does not fit. Our `draft` is an intent status on an ordinary task file. |
| Human-only `done` | No write authorization. Any CLI, MCP or web caller can set any configured status. | Not expressible in the format. |
| Owner | `assignee` is `string[]` (`src/types/index.ts`). The parser accepts a scalar or a list and normalises to a list, and a missing value becomes `[]`. Nothing limits it to one value. There is no `owner` field. | Carries an owner by convention only. Zero or several values are both valid for Backlog.md. |
| Acceptance | A Markdown checklist in the body, between `<!-- AC:BEGIN -->` and `<!-- AC:END -->`, as `- [ ] #1 text`. Each item has an index, a text and a checked flag (`src/markdown/structured-sections.ts`). | Structured, but a different shape and place from a YAML list. The checked flag has no counterpart in our contract. |

- **Acceptance mapping, import:** checklist item texts in file order, dropping the `#n` index and checked flag. No section, or a section with no items, gives `acceptance: []`, so an absent key and `[]` are indistinguishable in a Backlog.md file.
- **Acceptance mapping, export:** `- [ ] #n text`, unchecked, numbered from 1 in list order. `acceptance: []` writes no section. The parser reads one non-empty line per item, so export rejects empty or multiline strings.

## Why this decision

- `draft` cannot be used as a status inside Backlog.md's tooling without triggering its drafts workflow.
- The singleton owner and the YAML acceptance list both need a validator of our own. Once that exists, Backlog.md's schema adds a second source of truth without removing work.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Adopt as-is (default config) | The statuses are `To Do`, `In Progress`, `Done`. `draft`, `ready` and `blocked` are missing, and `In Progress` is a state we derive and never write. |
| Adopt with config (statuses `draft, ready, blocked, done`, `assignee` as owner, checklist as acceptance) | `draft` collides with the reserved drafts behaviour. The singleton owner is unchecked. Acceptance is in the wrong place and loses the empty-list case. We would write the validator anyway and also carry a Bun/TypeScript tool in a Python project. |
| Keep our frontmatter but store acceptance as the Backlog.md checklist | The list would need body parsing to read, and the checked flag invites writing completion state into git. |
| Fork Backlog.md | A large maintenance surface for a format that is simple to define. |

## Consequences

- The next units implement the task schema from the SPEC example: `owner` as one non-empty string, `status` as one of the four intent values, `acceptance` as a YAML list of strings.
- `CLAUDE.md` says "Backlog.md, unless its format cannot carry acceptance criteria and owner". The exception applies. The maintainer should confirm the wording.

## Open questions

- How is "only a human writes `done`" enforced? Author metadata cannot prove a human. Owner: **u2** (the validator unit).
- How are native Backlog.md drafts (files in its `drafts/` folder) handled? Owner: **u2**.
- Hook recorder and roll-up query ("what needs me"), not evaluated here. Owner: **u4**.
