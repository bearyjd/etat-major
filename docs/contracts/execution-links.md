# Recorded execution links

Use `etat-major serve --execution-links FILE` to include recorded handoff
context for tasks in the configured project. The startup snapshot is a UTF-8
YAML mapping or JSON object up to 64 KiB with at most 256 rows.
`codeman-session` is the only session kind. It points to Codeman, the legacy
session host, so the session reference format and URL below are specific to it.

```yaml
version: 1
project: netlens
links:
  - task: netlens/0042
    kind: codeman-session
    ref: 5a1ac876-cf2d-456b-b2ab-48620ca8156a
    seen_at: "2026-11-22T14:00:00Z"
  - task: netlens/0042
    kind: meute-job
    ref: nightly/build-42
    seen_at: "2026-11-22T15:00:00Z"
```

Each task must match an existing `PROJECT/TASK_ID` in the project configured
with `--project`. For Codeman, use a hyphenated UUID. Meute job references
use relative identifiers of up to 512 characters. Each slash-delimited segment
starts with an ASCII letter or digit and can contain ASCII letters, digits,
periods, underscores, and hyphens. Quote the RFC 3339 timestamp and include a
time zone.

Identical rows collapse to one. Different rows for the same kind and reference
invalidate the snapshot. Unknown fields, including URL fields, are invalid.
Planning displays input errors in Sources and continues to show the rest of
the project.

To display a Codeman session URL, set `--codeman-origin https://codeman.example.invalid`
at startup. The origin can include a port and one trailing slash. Planning
builds `/session/<uuid>` from that origin. The sandboxed tab shows the URL as
copyable text for use in a separate browser tab. Without an origin, copy the
session ID. Use the Meute job reference in the native Meute UI. Planning also
displays a copyable loopback return URL with the selected task anchor. See the
[Web Tab setup](../PLANNING.md) for how Codeman matches that URL to saved tabs.

The timestamp records when the pointer was seen. Handoff context leaves task
state and delivery evidence to their existing inputs. Job and session controls
remain in the native services.
