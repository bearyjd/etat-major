# Recorded Meute snapshot v1

Supply one local snapshot with `--meute FILE` on `progress` or `serve`. The
file is an État-major interchange format for a single project. A publisher
selects the fields below from a copied report's metadata and records when
the snapshot was assembled.

```yaml
version: 1
project: netlens
exported_at: "2026-11-22T12:00:00Z"
reports:
  - ref: reports/example/scan-2026-11-21.md
    recorded_at: "2026-11-21T12:00:00Z"
    outcome: ok
    task: netlens/0042
```

- Use a UTF-8 YAML mapping, up to 256 KiB and 256 rows. JSON in this shape
  also works. Unknown fields, duplicate keys, aliases, unsupported versions
  and symlinks are rejected.
- Use the exact workspace project ID (up to 128 characters). Quote
  timestamps and tokens that YAML reads as booleans or numbers. Use RFC 3339
  with seconds, an explicit UTC offset or `Z`, and up to six fractional
  digits. The report timestamp must be at or
  before the export timestamp. Past snapshots remain valid historical
  evidence and display both times.
- Keep the original stable relative report reference where it is safe to
  publish. Use up to 512 ASCII characters, with slash-delimited segments
  starting with a letter or digit and otherwise containing letters, digits,
  underscores, hyphens or periods. État-major displays the reference as
  plain text.
- Copy the recorded outcome as a lowercase token of up to 32 characters,
  starting with a letter and otherwise containing lowercase letters,
  digits, underscores or hyphens. The outcome describes the recorded run.
- Include the optional `task` only if the source explicitly gives a product
  task key, in `project/id` form (up to 160 characters). A row without an
  explicit key, with an unknown task, or with a key in another project
  stays visible as unlinked. The Planning projection omits task keys from
  other projects. Each linked report supplies
  `artifact:<ref>` on the generated rung of that task. Identical rows
  collapse and conflicting rows for one reference invalidate the snapshot.

## Publishing from a saved artifact

1. Use a regular, already-recorded report from the project approved for
   publication. Read only the metadata needed for the snapshot. The
   sampled reports have `started` and `status` fields that can supply
   `recorded_at` and `outcome`. Record the export time separately.
2. Omit the task key unless the metadata gives an explicit product task
   key. In the sampled reports, the native `task` field names a Meute job
   and there is no explicit product task key. Repository and job names
   cannot supply a product task key.
3. Write the minimal snapshot to a separate local file. Leave Meute state
   untouched. Exclude private report bodies, remotes, links, absolute
   paths and credentials. The inbox dump and per-report commands are
   unnecessary for publishing this format.

The disposable real-data smoke reflects an actual recorded report without
task attribution. The committed unlinked fixture retains the observed
field shapes and uses a neutral relative reference. The linked fixture
uses a synthetic product task. An explicitly attributed real report is
still a gate for the pilot.
