# Manual Anthropic API review descriptor

Use `etat-major serve --manual-review FILE` to include the record of one
completed manual review in Planning. Create the descriptor locally. Record the
Git commit reviewed and compute SHA-256 over the original report bytes
independently. Planning reads the descriptor at startup and exposes its
metadata. It validates the shape of the commit and digest. The original
report remains in its private storage.

```yaml
version: 1
source: manual-anthropic-api-review
task: netlens/0042
ref: reports/manual/latency-review.md
recorded_at: "2026-11-22T14:00:00Z"
outcome: completed
commit: "0123456789abcdef0123456789abcdef01234567"
report_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
```

- Use one flat UTF-8 YAML mapping of up to 8 KiB with exactly the fields shown.
  JSON with the same fields is also valid.
- Use an existing `PROJECT/TASK_ID` from the project selected with `--project`.
- Use a relative reference of up to 512 characters. Separate segments with
  slashes. Start each segment with an ASCII letter or digit and use ASCII
  letters, digits, periods, underscores or hyphens for the remaining characters.
  Planning displays this as text.
- Quote the RFC 3339 timestamp and include a time zone. Use a short plain-text
  outcome of up to 256 characters. Keep sensitive details in the original report.
- The commit and report digest are 40 and 64 hexadecimal characters,
  respectively. Quote both so YAML treats them as strings.

Planning lists a valid descriptor under the task’s Generated evidence and
reports an invalid descriptor in Sources. Generated describes a recorded
artifact. The task’s acceptance and delivery evidence comes from the existing
Planning inputs.
