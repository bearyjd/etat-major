# Manual research answer format

`etat-major research brief feature:<project>/<id> --workspace D --out FILE` writes
a Markdown prompt for human review. It includes the Feature's project, title,
problem, desired outcome, and optional `research_questions` list. If the list is
empty, the prompt asks about the problem and outcome or falls back to the title.

Use one block per finding. Start each with `### F<n>`, where `n` is a unique
positive integer without leading zeroes. Include every field once in the order
shown, with one line per field. Blank lines may separate blocks. Paste the blocks
without an introduction or code fences.

~~~text
### F<n>
Claim:
Source URL:
Date:
Kind: reddit|github-issue|docs|article|store-review|other
Evidence: firsthand|author|secondhand|opinion|unverified
Conflicts:
Not verified:
~~~

Enter one listed value each for Kind and Evidence. Use a full HTTP(S) Source URL
and a publication Date in YYYY-MM-DD format. Use Conflicts for a comma-separated
list of other finding headings such as `F2, F3` or for a short description of
conflicting views with their URLs. Use Not verified for details that need
follow-up. When information is missing, do not invent threads or citations; write not found instead.
Source URL, Date, Conflicts and Not verified may also be left blank.

`etat-major research import FILE --workspace D --id NNNN` imports at least one
finding into `research/NNNN-chatgpt-research.md`. It refuses an existing ID and
reports malformed input with the file, field and line number. Control characters,
raw angle brackets, and reserved human-only lifecycle terms are refused in field
values.

Imports use `status: unreviewed` and `provenance: ai-generated`. Source URLs are
preserved verbatim. A finding missing a URL or date uses `evidence: unverified`
and is displayed as unsourced. An undated URL is retained on the finding with
`source_date_missing: true` so another finding's date cannot make it appear
sourced. Drafts may contain an empty source list. The importer records unresolved
notes and leaves source verification and review to the human.
