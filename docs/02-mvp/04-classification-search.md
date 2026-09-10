# 4. Add classification and local search

Implement `Search` and `GetJob` independently of the CLI. Expose them through
local `search` and `show` commands.

Start with transparent rules over titles, descriptions, and source categories.
Store `it`, `non_it`, or `uncertain` with the matched rule. Keep uncertain
records for review. An IT recruiter is not automatically an IT role. `remote`
alone does not establish eligibility to work from Germany.

Search confirmed IT jobs using SQLite FTS5 plus location and work-mode filters.
Preserve meaningful technical terms such as Go, C++, C#, and .NET. Verify those
queries explicitly and add literal matching where full-text tokenization loses
meaning.

Use parameterized SQL, bounded result limits, stable ordering, and pagination.
Keep normal output on stdout and errors on stderr. JSON mode must contain only
JSON. Invalid commands and missing IDs return nonzero exit codes.

**Done:** title, location, and remote filters compose correctly.

**Test:** evaluate the classifier and composed filters on a manually labeled
sample containing German and English titles, non-IT roles, and ambiguous cases.
Report false positives and missed IT jobs.

## Usage

```sh
uv run jobsh discovery
uv run jobsh sync
uv run jobsh search "C++" --location Berlin --remote --json
uv run jobsh search --title Developer --work-mode hybrid --limit 20 --offset 20
uv run jobsh show 1 --json
```

The Python API is `jobsh.search.search(database, ...)` and
`jobsh.search.get_job(database, job_id)`. Search returns open, confirmed IT jobs
ordered by ID; limits are 1–100 and offsets start at zero. Query words combine
with AND and are treated as text, not as an FTS query language. Title and
location filters are literal substrings. `--remote` means the recorded work
mode only; it does not imply permission to work from Germany.

Classification stores its first matching rule in `classification_rule`.
Explicit non-IT titles take precedence over technical keywords. Generic role
titles require additional technical evidence in the title, description, or
Personio department (`source_category`). Unmatched jobs stay `uncertain` and
remain accessible through `show`. Existing jobs are classified and indexed
when their database is opened after the upgrade.

The [FTS5 index](https://www.sqlite.org/fts5.html) is maintained by database
triggers, including updates, deletions, and rollbacks. C++, C#, and .NET use
literal matching to preserve punctuation; Go uses whole-token full-text search.

## Sample evaluation

`testdata/classification.json` contains 22 hand-labeled synthetic examples:
12 IT, 6 non-IT, and 4 uncertain, with German and English titles. The current
rules produce **0 false positives and 0 missed IT jobs** on this sample; all
four uncertain cases remain uncertain. These development examples are not an
independent or representative benchmark. A human-reviewed sample of real feeds
is still needed to measure production quality.

```sh
uv run python -m unittest tests.test_search
```

Tests also cover composed filters, pagination, Go/C++/C#/.NET, literal inputs,
index updates and rollback, closure/reappearance, database upgrades, JSON-only
stdout, and nonzero exits for invalid input or missing IDs.
