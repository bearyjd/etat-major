# Changelog

All notable changes to État-major are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) as described under
[Versioning policy](#versioning-policy).

## [0.2.0] - unreleased

Numbers refer to pull requests.

### Added

- `etat-major --version` prints the version on one line. (#39)
- `export planning --json` prints the Planning payload without the web extra. It is the same
  document that `serve` returns at `/project.json`. (#41)
- The Planning payload, `/project.json` included, carries `"schema": "etat-major/planning@1"`,
  described by a closed JSON Schema. (#42)
- `export discover --json` prints research and decisions as `etat-major/discover@1`, with its
  JSON Schema. (#43)
- `export understand --json` prints components, artifact coverage and a symbol summary as
  `etat-major/understand@1`, with its JSON Schema. File paths are included only with
  `--include-files`, and a document over 4 MiB is refused. Some answers in its contract are
  still provisional. (#44, #47)

### Changed

- `CLAUDE.md` and `README.md` are host-neutral: they speak of a session host, with Codeman as
  the legacy one. No other file changed. (#40)
- Planning, Discover and Understand pages and payloads follow one line-break rule: prose keeps
  real line feeds, other free text is one line, and other control and formatting characters stay
  visible as `\uXXXX`. Research briefs write each value on one line. (#49)
  This changes the content of string values: before it, line breaks arrived as the literal text
  `\u000a`. The schema markers stay `@1` because all three first ship in this release, so no
  release produced the old form. Anything built against an earlier commit of `main` sees the
  difference. After 0.2.0, such a change to how a value is encoded needs a new marker.

### Fixed

- Overlapping or touching location matches are redacted once, as a single
  `[redacted location]`. (#46)
- Multi-line text no longer shows escaped line breaks in view and export payloads. (#49)

### Security

- Git subprocesses take a scrubbed environment and settings that switch off programs named by a
  repository's configuration under fixed keys, such as fsmonitor, hooks and signature verifiers.
  Drivers whose names a repository chooses cannot be disabled this way; each runner follows a
  further rule documented in `git_hardening.py`. (#45)

## [0.1.0] - never tagged

The version set by the first project scaffold. It was never tagged or released; this entry is
the baseline, covering what had been merged up to #38.

- Command line over local and recorded data: `trace`, `decisions list`, `index`,
  `research brief` and `research import`, `gradle deps` and `gradle drift`, `components`,
  `floorplan`, `progress`, `workspace validate` and `serve`.
- Versioned JSON output (`--format json`) with JSON Schemas.
- Recorded Floorplan and Trail readers, and wrappers that run their deterministic steps in a
  disposable copy.
- Read-only Planning, Understand and Discover web views on loopback.
- A GitHub evidence capture script, not verified against a real run.

## Versioning policy

Versions are `MAJOR.MINOR.PATCH` and tags are `vMAJOR.MINOR.PATCH`, with no pre-release or
build suffix. The package version is `__version__` in `src/etat_major/__init__.py`.

The versioned interface is:

- the command line: command names, flags and the meaning of exit codes;
- the JSON documents that carry a `schema` marker `etat-major/<name>@N`, both the
  `--format json` envelopes and the `export` payloads, with their JSON Schemas.

Web page markup, human-readable text output and Python modules are not part of it.

A change is **breaking** when it removes or renames a command or flag, makes a flag required,
changes what a flag or exit code means, or removes, renames, retypes or redefines a key of a
JSON document. Changing how a string value is encoded redefines its key. A breaking change to a
JSON document also takes a new marker (`@2` after `@1`). A new key that comes with its schema
update may keep the marker. These rules compare a release with the one before it; commits
between releases carry no compatibility promise.

While the major version is 0, breaking changes and new features raise the minor version and
releases with fixes only raise the patch version. A breaking change is named as such in its
changelog entry. From 1.0.0, breaking changes raise the major version, compatible additions the
minor version and fixes the patch version.

Clients must gate on `schema` and reject a value they do not know. The package version does not
say which payload shape a document has, and the payload's own `version` field is not the package
version. The schemas are closed, so a client that validates strictly needs the schema from the
release that produced the document.
