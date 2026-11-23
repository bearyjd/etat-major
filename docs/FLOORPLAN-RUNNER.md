# Run recorded Floorplan steps locally

The Floorplan runner supports three deterministic operations on Linux. It needs
a trusted Node executable on PATH and the local Floorplan source at commit
`94f81b463b7617e06d873ac71323ce71644c8399`. The runner checks one digest of the
pinned scripts and assets. Prepare a private disposable copy of the code as a
separate directory before invoking it.

Use a copy with regular files, safe repository-relative names, and no Git
metadata, symlinks, hard links, or embedded mounts, including bind mounts. Keep
the copy and pinned sources stable during the operation. The runner checks
the Linux mount table and file devices before starting. The copy's parent
must be writable for a private temporary metadata directory. While the step
runs, the wrapper creates a temporary empty `.git` marker and points Git at
that private metadata so Floorplan can discover deeply nested files.
Discovery follows the copy's Git ignore rules. The wrapper removes both
temporary entries when the step finishes. Caller-supplied Git metadata
remains unsupported.

```sh
etat-major floorplan scan --copy disposable-copy --source pinned-floorplan
etat-major floorplan build --copy disposable-copy --source pinned-floorplan
etat-major floorplan refresh --copy disposable-copy --source pinned-floorplan
```

Scan writes `floorplan/.cache/scan.json`. For build, supply
`floorplan/architecture.json` in the copy and use a scan from that same copy.
Build writes a graph and Floorplan's bundled static assets. État-major reads
only the graph. Refresh uses the existing graph and architecture, scans the
code again, and replaces the graph and `floorplan/.cache/changes.json`.
Refresh always uses Floorplan's code mode. Floorplan may invoke its own
deterministic scan and build scripts during refresh.

The wrapper uses fixed arguments, unattended mode, a scrubbed environment, a
deadline, and bounded captured output. It validates that each expected artifact
was rewritten. Its terminal output reports relative artifacts, verified rename
pairs, and the count of retained Floorplan node IDs. Reviewed État-major
components remain separate from these node IDs. Model steps, downloads, and
viewer launch are outside the runner's scope.

## Real-data check

A disposable Android snapshot was scanned and built, then refreshed after a
Kotlin source file was renamed. The graph retained all 80 authored component
IDs across 724 indexed files. Refresh reported the old and new paths, and
the temporary Git marker and metadata were removed.
