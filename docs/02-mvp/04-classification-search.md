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
