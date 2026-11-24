# Understand MVP

**Status: proposed design.** The reviewed component model and both runner wrappers
provide the inputs. The view consumes their recorded
artifacts on startup. Refreshing artifacts is a separate maintainer action.
[Current gates](NEXT.md) · [Phase 2 roadmap](VISUALIZATION-ROADMAP.md) ·
[Architecture](VISUALIZATION-ARCHITECTURE.md)

## First slice

Add an Understand page to the existing optional Planning service for its configured
project. Use the current startup snapshot, server-rendered HTML and inline CSS.
Start with a component list and render files, symbols, call evidence and the
excerpt only for the selected component, file and symbol. Stack the list and
inspector on phones and place them side by side when space permits. Keep status
labels readable without color. A Planning feature's explicit component reference
can link directly to the corresponding selected component in Understand.
This slice adds no frontend dependencies, public API, graph canvas, arbitrary
file browser, or repository picker. The application makes no outbound requests,
calls no models, and performs no Git writes.
[Planning pilot](PLANNING.md) · [Component references](TRACEABILITY.md#architecturelink)

### Records and navigation

1. Load the project's component declarations with the existing component loader.
   Show parent links and preserve the declared summary provenance and any recorded
   review. Identify seeded proposals as proposals.
2. Form the file inventory from the union of the valid recorded Floorplan file
   list and Trail symbol paths. Use `ComponentModel.owner_of(path)` to group
   files. Show ties and unowned files explicitly. A file present in only one
   artifact remains navigable. Label ownership coverage as coverage of this
   recorded inventory. Floorplan contributes file evidence, and its optional
   import links are deferred.
3. Use `SymbolIndex.symbols_in(path)` for the selected file and
   `callers(id)` and `callees(id)` for one-hop `calls` evidence. Label each row
   with the adapter's `verified` or `inferred` provenance, preserving the
   artifact confidence. If the opposite endpoint has no matching recorded
   symbol, also label it `unresolved` and omit its navigation link. An empty
   list means the artifact recorded no matching edges. Name-matched Kotlin
   calls remain inferred even when both endpoints exist.
4. Report each artifact as present, missing or invalid, with freshness shown
   independently as fresh, stale or unknown. Compare supplied, trusted
   artifact revisions with the selected source revision. Keep stale records
   navigable with their snapshot label. Missing Trail leaves component and
   available file navigation intact. Missing Floorplan leaves component, file,
   and symbol navigation intact wherever Trail records a path. With neither
   artifact, show component declarations and explain that file coverage is
   unavailable.

Reuse the independent recorded adapters so one missing artifact does not block
the other. The joined `load_repo_index` requires both files and remains suited
to paired exports.
[Components](contracts/components.md) · [Floorplan](contracts/floorplan-adapter.md) ·
[Trail](contracts/trail-adapter.md) · [RepoIndex](contracts/repo-index.md)

### Selection and rendering limits

- Assign an opaque token to each selectable component, file and symbol at
  startup. Derive it deterministically from the type and canonical ID, check
  all tokens for collisions before exposing them, and keep a reverse lookup
  in the snapshot. Use the same token for the DOM anchor throughout that
  snapshot. A token from a different snapshot may be unavailable after
  regeneration. Accept only tokens in the configured project's lookup and
  validate component, file and symbol membership together. Reject unknown or
  mismatched selections without reading a file.
- Render at most 25 rows per page per list, including each callers and callees
  list. Sort by canonical ID and use the recorded endpoint tuple to break ties
  in edge lists. Render counts and Previous/Next links for each list. Limit
  rendered display strings to 512 characters, apart from the source excerpt,
  and cap the complete UTF-8 HTML response at 256 KiB. If the response reaches
  the cap, return a small view with the current selection and a prompt to
  narrow it. Preserve status and truncation notices in that view.
- Link targets already on the page by fragment. Link deferred targets by a
  server-rendered selection URL built from the target's token and its
  associated selections, including the page containing it, then append its
  anchor. Never put a repository path into a route or construct a
  filesystem path from browser input.

### Source excerpt boundary

Show an excerpt only for a symbol in the configured Trail index whose snapshot
revision matches an explicitly configured immutable source snapshot. Keep
excerpts disabled for mutable working trees in this slice. Limit
the excerpt to the recorded one-based span, capped at 40 lines and 8 KiB of
source text, from a regular UTF-8 file of at most 256 KiB. Mark truncation.
Validate repository-relative paths, open beneath the configured source root
using directory descriptors, and refuse symlinked parents and leaf files. Use
only index-selected paths. The browser cannot submit a path or use a route to
fetch arbitrary source. Never render body text from Trail or source markup as
HTML. Escape control characters and HTML, and redact private locations before
display. A stale span, missing revision, or rejected input leaves the symbol
and its call evidence available, with a bounded file-and-field reason and no
absolute path or remote.

## Acceptance on real NetLens recordings

- Record the source revision and artifact revisions from a real NetLens copy.
  Select a human-reviewed component and an owned Kotlin file with a Trail
  function that has at least one recorded caller and one recorded callee.
  Record the IDs and expected directions before testing. Compare the displayed
  neighbors and their labels with the recorded edges, and the source lines
  with the matching source snapshot. Use recorded edges with verified and
  inferred confidence where available and exercise any absent case with
  adapter data trimmed from real output. Show an unresolved recorded endpoint
  without creating a destination.
- At 375 × 812 and 1440 × 1000, follow component → file → symbol → caller and
  callee using touch or pointer and keyboard navigation. Confirm visible focus,
  working anchors, bounded source display, no page-wide horizontal scrolling,
  and no browser requests to other origins. Repeat in an ordinary browser and
  in the optional sandboxed Codeman Web Tab.
- Exercise a file, symbol and call target beyond the first page. Verify direct
  links to deferred targets, stable distinct anchors for similar typed IDs,
  and counts and navigation at the list limit. Submit unknown or mismatched
  tokens and verify there is no source read. Verify a capped response still
  identifies the current selection and explains how to narrow the view.
- Repeat with Floorplan omitted, Trail omitted, and stale or unknown revisions.
  Confirm the remaining recorded navigation and coverage labels, and require
  the source excerpt to be withheld for stale or unknown Trail revisions.
  Exercise unsafe paths, symlinks, invalid spans, oversized files, and markup
  in tests. Record the viewport, artifact revisions, tested symbol, and
  observed results in the implementation verification.
[Real-data proof-out](FLOORPLAN-PROOF.md)

## Local verification

NetLens commit `5188ca6725007bd663ce0eaa5ad2de9e460d26a0` supplied the source,
Floorplan and Trail inputs. Floorplan recorded 716 files and Trail recorded
5,498 symbols. In the seeded `app` component, the browser followed
`MetricTiles.kt#LatencyTile` to one recorded caller and two recorded callees.
The directions, confidence and provenance labels matched the recording. The
excerpt matched lines 95–128 of the source export.

Chromium checks passed at 375 × 812 and 1440 × 1000 in an ordinary tab and a
local simulation of Codeman's opaque Web Tab proxy. The stale Trail check
retained the recorded calls and withheld the source excerpt. The component
declarations used for this run are seed proposals. A human-reviewed component
and verification in the deployed Codeman Web Tab remain acceptance items.
