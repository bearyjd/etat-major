# Research-to-delivery traceability

The central relationship in État-major is a navigable chain, in both directions:

**Research → Decision → Feature → Design → Code → Evidence**

Click a module to see which features it implements and why they were chosen. Click a feature to see its research, its intended architecture, its tasks, the existing code it touches, its progress and the acceptance criteria still open. This document defines the smallest model that makes that possible. Contracts for the code and evidence ends are in [VISUALIZATION-ARCHITECTURE.md](VISUALIZATION-ARCHITECTURE.md).

## Principles

- **Git is the durable store.** Research, decisions, features and tasks are Markdown with YAML frontmatter in the intent workspace. Generated code maps are local caches and are never the only record of a decision.
- **Research is not a task.** A finding may lead to a rejection, a postponement or a change of strategy. Those outcomes are kept so that people and agents do not re-propose evaluated ideas.
- **Provenance everywhere.** Each fact is `verified`, `inferred`, `ai-generated` or `human`. A well-written AI summary is still `ai-generated` until a person reviews it and its sources.
- **No invented sources.** A finding without a source URL and date is stored as `unsourced` and never counts as evidence.
- Keep it small. No database, and no schema beyond what these four records need.

## Layout

```text
workspace/
  research/0007-android-network-tools.md     # ResearchArtifact
  decisions/0012-add-latency-graph.md        # Decision
  features/netlens/0031-latency-graph.md     # Feature
  tasks/netlens/0042-...md                   # Task (existing contract)
```

**Reference grammar.** Every cross-reference is `<kind>:<id>`. Project-scoped records (`feature`, `task`, `milestone`) use `<project>/<n>`, for example `feature:netlens/0031`, `task:netlens/0042`, `milestone:netlens/m3`. `research` and `decision` ids are global (`research:0007`, `decision:0012`). A finding inside research is `research:0007#f1`. Code references are prefixed by layer: `fp:n:<component>` or `fp:f:<path>` (Floorplan), `trail:<path>#<symbol>` (Trail). Loaders reject any other spelling.

File paths in code references are repository-relative. Use ASCII `/` between non-empty segments. Leading `~`, drive-letter prefixes, dot segments, backslashes and Unicode slash lookalikes are invalid.

**Minimum for Slice 1.** Each record needs an `id` and `status`. Research also needs a `title`, `provenance` and at least one source with a URL and date. A Decision needs a `question` and, when approved, rejected or postponed, `decided_by: human`. A Feature needs a `project` and `title`. The planned status requires an approved linked Decision.

## Records

### ResearchArtifact

```yaml
id: 0007
title: What do Android network-tool users complain about?
question: Which gaps do users report in competing Android network tools?
project: netlens            # optional; may be cross-project
status: reviewed            # unreviewed | reviewed | superseded
provenance: ai-generated    # set by the importer; a human may reclassify per finding
collected_by: chatgpt       # tool or person that gathered it
collected_on: 2026-11-21
sources:
  - url: https://example.org/thread/123
    date: 2026-09-14
    kind: reddit            # reddit | github-issue | docs | article | store-review | other
    evidence: firsthand     # firsthand | author | secondhand | opinion | unverified
findings:
  - id: f1
    text: Users report slow scans on large subnets.
    source: https://example.org/thread/123
    confidence: medium      # low | medium | high
    conflicts_with: [f3]    # optional
  - id: f3
    text: The impact of slow scans on repeat users is unclear.
    evidence: unverified
unresolved:
  - Is the complaint specific to one competitor?
```

Findings without a `source` are allowed only with `evidence: unverified` and are shown as unsourced.

### Decision

```yaml
id: 0012
question: Should NetLens add a live latency graph?
status: approved            # proposed | approved | rejected | postponed | superseded
decided_on: 2026-11-21
decided_by: human           # only a human records a decision
chosen: Add a live latency graph to the host detail screen.
alternatives:
  - option: Export CSV only
    why_not: Does not address the reported need to see trends.
rationale: Repeated firsthand complaints; competitors lack it.
evidence: [research:0007#f1]
features: [feature:netlens/0031]
revisit_on: 2027-03-01      # optional
```

Rejected and postponed decisions are first-class and searchable. Before proposing a feature, check `decisions/` for the same question.

### Feature

```yaml
id: 0031
project: netlens
title: Live latency graph
problem: Users cannot see latency trends during a scan.
outcome: A graph of round-trip time per host over the last 5 minutes.
status: planned             # stored intent only: idea | researching | proposed | planned
priority: 2
research: [research:0007]
decisions: [decision:0012]   # approved/rejected/postponed come from the linked Decision
milestones: [milestone:netlens/m3]
tasks: [task:netlens/0042, task:netlens/0043]
acceptance:
  - id: a1
    text: Graph updates at least once per second.
  - id: a2
    text: Graph is covered by an automated test.
architecture:               # ArchitectureLink records
  - ref: fp:n:ui.hostdetail            # existing component this feature changes
    relation: modifies                 # new | modifies | uses
  - ref: fp:f:app/src/main/kotlin/net/Latency.kt
    relation: new
```

### ArchitectureLink

Embedded in a Feature or a Task, never a separate file. Stored fields: `ref` (layer-prefixed, see the grammar) and `relation` (`new`, `modifies`, `uses`); `provenance` is `human` unless stated. Nothing about built or planned is stored; it is computed against an indexed revision:

- `new`: ref absent is a **gap** (planned, not yet built); ref present is **built**.
- `modifies` or `uses`: ref present is **existing** (not evidence of progress); ref absent is **stale** (the link points at code that no longer exists, or was renamed; the rename reconciler in Phase 2 resolves renames, until then a rename reads stale).

**Precedence.** A Feature's ArchitectureLinks are the authoritative statement of planned architecture. A Floorplan `plan.json` blueprint is a generated view of the `new` links (it cannot reference existing code); it is never edited as the source.

## Lifecycle

`Idea → Researching → Proposed → Approved → Planned → Implementing → Verified → Released`, plus the exits `Rejected` and `Postponed` from any step before Approved.

| Stage | Stored in the file? | How it is known |
| --- | --- | --- |
| Idea, Researching, Proposed | Yes (human intent) | The Feature file; Researching expects at least one ResearchArtifact |
| Approved, Rejected, Postponed | **Derived from the linked Decision**, which is the single authority | A Decision with `decided_by: human`. A Feature file may not say `planned` without an approved Decision |
| Planned | Yes | The human has created tasks from the approved Feature |
| Implementing | **Derived** | A linked task has a branch or open draft PR (the Kanban In Progress column) and is not yet accepted |
| Verified | **Derived** | All linked tasks are merged with a passing check on the merge commit, and the Feature carries `accepted_by` and `accepted_on` (the same human-acceptance fields as tasks, added with the Phase 4 contract). Per-acceptance-item verification is an open question; until then the human states in the acceptance that the criteria are met |
| Released | **Derived** | A release or tag contains the merge commits |

Not every idea moves forward. Moving a Feature to Approved needs a human-recorded Decision; nothing auto-advances.

**Kanban mapping.** In Progress = branch or open draft PR; Review = open non-draft PR, or merged without acceptance; Done = `status: done` with acceptance; Blocked = stored status or unmet dependency. A task marked `done` with no PR evidence is shown Done but `unverified`.

**Tooling never decides for a human.** The importer, the UI and any agent write only `proposed`, `unreviewed` or `draft` values. They never write `approved`, `reviewed`, `decided_by`, `accepted_by` or `accepted_on`. A test enforces this. Git author metadata cannot prove a human made a change; the trusted-family setup accepts that and designs no further mechanism.

## Two-way navigation (what the model must answer)

- **Module → why.** Given a file or symbol, find Features whose ArchitectureLinks reference it, then their Decisions and ResearchArtifacts.
- **Feature → everything.** Research, decision, tasks, target components and files, progress rungs (see ProgressEvidence), open acceptance items, gaps and stale links.
- **Research → what it caused.** Decisions citing it, and the Features and code those led to, including rejected outcomes.
- **Decision → consequences.** Features, tasks and evidence; whether the original goal was met (the Verified stage compared with the stated outcome).

The minimum trace query, `etat-major trace feature:<project>/<id>`, prints that chain with provenance and marks each missing link `unverified` or `gap`.

Feature–Decision links are read from either record, and the workspace and trace warn when only one side lists the link.

Validation processes at most 2,000 entries per directory, including the `features/` directory itself. It reports unexpected directories without scanning their contents. The CLI prints up to 200 validation issues and a count of any additional issues detected. Each `invalid:` line is limited to 512 characters after escaping.

### CLI exit codes

- `0` for success, including traces with warnings or unsourced findings.
- `1` for missing, stale or gap trace items, or workspace validation issues.
- `2` for usage errors, including unknown features, missing or invalid workspace directories, and unavailable or invalid Floorplan graphs.

## Manual ChatGPT research handoff (first version)

ChatGPT is the preferred external research and brainstorming partner, especially for Reddit, which Claude's search tools cannot reliably reach. The first version is a **manual copy and paste**. There is no automatic sending, no scraping of ChatGPT sessions, no undocumented API and no background research agent. Direct integration may be considered later only if a supported mechanism exists and clearly helps.

1. **Brief.** `etat-major research brief feature:<project>/<id>` writes a Markdown prompt file. It contains the project context you approve, current capabilities, the specific questions, the sources to examine (Reddit, GitHub, documentation), and the required answer format below. It does not read secrets and contains no local paths, hostnames or keys; the command refuses to write if its redaction check finds any.
2. **Human review.** You read the brief and decide what leaves your machine. Nothing is sent by État-major.
3. **Paste into ChatGPT**, then copy its answer.
4. **Import.** `etat-major research import <file>` parses the answer into a draft ResearchArtifact with `status: unreviewed` and `provenance: ai-generated`. Items without a URL and date are flagged `unsourced`. Source URLs are kept verbatim and never rewritten.
5. **Review and approve.** You check the sources, fix classifications (firsthand, author, opinion) and mark the artifact `reviewed`. Only then may it back a Decision.
6. **Extract.** From the reviewed artifact you record findings, alternatives and, if warranted, a Decision and Feature proposal.

Required answer format requested in the brief:

```text
For each finding: the claim; the source URL; publication date; whether it is firsthand,
the tool author, or secondhand; conflicting views with their URLs; and anything you could
not verify. Do not invent threads or citations; say "not found" instead.
```

The importer does not check that a URL is real or says what is claimed. That check is the reviewer's job, which is why imported research is never `verified` automatically.

## Example: a NetLens feature

1. Research competing Android networking tools via the brief; import and review the answer (ResearchArtifact 0007).
2. Compare against existing capability using the Understand view of NetLens.
3. Record a Decision to add a latency graph, with rejected alternatives.
4. Draft the Feature with acceptance criteria and a Floorplan blueprint (planned components).
5. Approve it; create tasks.
6. Follow commits, checks and releases through ProgressEvidence.
7. At Verified, compare the delivered result with the Feature's `outcome`.
8. From any of these, navigate to the others.
