# Floorplan proof-out

Run 2026-11-22 on a real repository, to decide whether Floorplan belongs in État-major. Evidence labels: **VERIFIED** (observed in a run or in source) and **UNVERIFIED** (not tested). Criteria and the decision rule were written before the data came in.

## Method

- **Test repository:** a public Android/Kotlin app with 33 Gradle modules, 945 tracked files (721 Kotlin, a little Python, JavaScript and shell) and 624 commits. Everything ran on throwaway copies.
- **Floorplan 0.11.0** (pinned commit), run from a clone with no install. The mechanical scan and build need no model. The architecture layer was written by Codex following Floorplan's own documented workflow. Codex took 265 s and about 85,000 tokens and produced 80 components with all 724 code files assigned and no build warnings.
- **Trail 0.30.5** built on a separate copy, telemetry off.
- **Skeptic pass:** an independent Codex run with live web search was told to argue against Floorplan and to score alternatives, including a null hypothesis (Trail plus Git-backed diagrams plus our own overlay).
- **Accuracy pass:** a separate agent, not told who wrote the summaries, checked ten randomly drawn component summaries (fixed seed) against the code.

## Pre-registered criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Model-written summaries: 8 of 10 sampled components correct | **Failed on the strict rating** (2 of 10 fully correct) |
| 2 | Component ids stable after an edit and a rename | **Passed** |
| 3 | Cost acceptable | **Passed**: 265 s and about 85,000 tokens for the whole layer |
| 4 | More useful than the alternatives on real questions | **Partly tested** (see module dependencies); the question set was not run |
| 5 | Our CLI accepts the real output unchanged | **Passed for Floorplan; found a bug for Trail** (below) |
| 6 | Complementary to Trail | **Passed** for imports on Kotlin |

## Findings

**Module dependencies (VERIFIED, with one caveat).** Ground truth: the `project(":x")` dependencies declared in the Gradle build files. Floorplan's resolved import links covered 99 of 107 (93%). Trail's resolved `calls` and `extends` edges covered 76 of 107 (71%). All 7,105 of Trail's Kotlin `imports` edges have unresolved targets, so imports give no dependency graph there. The ground truth was re-derived later with our own Gradle adapter: the same 107 declared dependencies, all written as `project(":x")` (this repository uses no type-safe accessors), so the ground truth stands. The 8 declared dependencies that Floorplan alone missed were not examined.

**Accuracy of the model-written summaries (VERIFIED, 10-component sample).** Of 34 claims, 25 were correct, 9 partly right, none wrong. Overall ratings: 2 correct, 8 partly. The errors are overstatement and omission, not invention:
- A "monitor" component reads as ongoing endpoint monitoring, but checks run only when a user taps a button; the stored interval is never scheduled.
- A Wi-Fi component says "sampled signal levels" and omits the largest part, a walk-through survey feature.
- An audit component says it "records audit results" but only logs one summary event.
- Two components had empty `paths`; four module-wide globs also matched tests, so file-to-component mapping overlapped and its `files` counts disagreed with the globs (16 against 8, 34 against 24, 14 against 10, 67 against 36).

A new developer would be well served for orientation and misled on specifics.

**Stability (VERIFIED).** A refresh after one rename and one edit took 1.5 s with no model. All 80 component ids were retained. The renamed file got a new id (ids are paths), as expected, so our rename reconciler is still required.

**Our adapters on real data.**
- The Floorplan reader loaded the real 80-node, 724-file graph without changes.
- **Bug in our Trail adapter:** it rejected the real graph, because it only accepts four node kinds (`file`, `class`, `function`, `method`) and real Kotlin graphs also contain `interface`, `variable`, `enum` and `type`. The Python fixtures hid this. To fix.
- Trail wrote its graph to `.trail/cache/.graph/wiring.json` here, not `graft/` as in an earlier run, so any wrapper must locate the file. Our adapter takes the path as input.
- Trail detected 33 Gradle modules from build markers, which gives a module structure for free.

**Skeptic pass (claims spot-checked, three of three held).** Its recommendation: keep Trail, pilot a Git-backed overlay, add a Gradle adapter if build facts are missing, treat Floorplan as optional. Its strongest points against Floorplan: the architecture layer is model-written, `graph.json` is explicitly rebuilt every run with no stability promise, and a third party asked in issue #142 whether the shape will stay stable and has had no reply. It listed alternatives worth a look (a Gradle module-graph exporter, Aalekh, LikeC4, Structurizr, dependency-cruiser), none of which we ran.

## Decision (rule applied as written)

The pre-registered rule: if criteria 1 and 5 pass, adopt both layers; if criterion 1 fails but the mechanical map adds value, keep the mechanical map only; if the mechanical map adds nothing, drop Floorplan.

Criterion 1 failed on the strict rating and the mechanical map added value, so:

1. **Adopt Floorplan narrowly, as an optional, deterministic provider of file-level import links and component globs.** It fills a verified gap: Trail's Kotlin imports do not resolve. Run only its scan, build and refresh scripts, on a copy.
2. **Do not depend on its model-written architecture layer.** A reviewed component model kept in Git is the source of truth for components. It is seeded from Gradle modules and Trail scopes. A model-written draft may be offered as a suggestion, labelled `ai-generated`, and nothing is trusted until a person reviews it.
3. **Do not use Floorplan blueprints as the planning model.** Blueprint mode is greenfield only (verified earlier); the planned-versus-built overlay stays ours.
4. **Do not treat `graph.json` as a stable contract.** Keep the pinned commit, the schema-string check and a recorded fixture in CI.
5. **Add a Gradle declared-dependency adapter.** Declared module dependencies are exact and cheap to read; compare them with actual imports to show drift.

## Follow-ups

- The Trail node-kinds fix, the Gradle declared-dependency adapter and a fix for the Floorplan reader's real-shape bugs were built after this proof-out and are in a separate change (see the next section). Their status here is **built and tested on this real repository, not yet merged**.
- Rank drift findings by evidence strength, and read build-logic convention plugins (see below).
- Re-score the accuracy criterion after correcting the two obviously misleading summaries, to see whether a reviewed model draft is usable.
- **Not run:** the skeptic's fuller experiment (a Python and TypeScript fixture, Android entry points, a Unicode rename, byte-identical runs with egress blocked), a question-set comparison of Floorplan, Trail and plain directory grouping, a blueprint on a real feature, LikeC4 and Aalekh trials, and a dependency audit.

## Declared versus actual dependencies, on the real repository

After the adapters were fixed, `etat-major gradle drift` ran on the same repository with the real Floorplan and Trail graphs in 0.45 s. Of the 107 declared module dependencies, **102 showed up in the code** (95%), **5 were declared but showed no use**, and **44 module pairs were used but not declared**. Spot-checked against the source:

| Finding | Check | Verdict |
| --- | --- | --- |
| Feature module A uses feature module B: 44 undeclared pairs from Trail `calls` edges | No `import` of B anywhere in A | **False positive**: Trail's name-based call resolution produced cross-module edges with no import |
| A feature module uses `core:ui`: undeclared | The convention plugin in `build-logic` adds `implementation(project(":core:ui"))` to every feature module | **False positive**: declared, but in a build-logic plugin the adapter does not read (it notes "composite build not followed") |
| `wol` declares `core:network`: unused | Zero imports of that module in `wol` | **Plausibly a real unused dependency** |
| `core:oui` declared by three modules: unused | No imports of it in those modules | **Plausibly real** (not checked for resource or reflection use) |

Takeaways, all from this one repository: Floorplan's resolved imports are the strong evidence; Trail's call edges alone are weak for cross-module claims; a drift report must rank by evidence strength and understand convention plugins before its "undeclared" list is trusted. Two of four spot-checked items were noise, so the raw lists must not be presented as findings.

## What the real-data run found in our own code

Running our adapters on real artifacts exposed four bugs that hand-made fixtures had hidden: the Trail reader rejected four real node kinds; `gradle drift` applied a 256 KiB build-file cap to multi-megabyte graph files; a normal `includeBuild` line was reported as an error; and the Floorplan reader rejected the real `project` object because the Slice 1 fixture had the wrong shape. All four are fixed in the separate change, and each is now covered by a real-shaped fixture. Process rule going forward: an adapter is not done until it has run on a real artifact.

