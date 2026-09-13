# jobsh

Local job aggregator with full-text search and a read-only MCP server.

```bash
uv sync
uv run jobsh discovery --provider personio --limit 100 --collections 2
uv run jobsh discovery --provider greenhouse --limit 100
uv run jobsh discovery --provider ashby --limit 100
uv run jobsh discovery --provider smartrecruiters --limit 100
uv run jobsh discovery --provider dvinci --limit 100
uv run jobsh discovery --provider lever --limit 100
uv run jobsh discovery --provider recruitee --limit 100
uv run jobsh discovery --provider workable --limit 100
uv run jobsh discovery --provider workday --limit 100
uv run jobsh source add jsonld https://example.com/jobs/42
uv run jobsh sync
uv run jobsh search python --location Berlin --json
uv run jobsh show 42 --json
uv run jobsh stats --json
uv run jobsh stats --errors
```

Data is stored in `jobsh.db`. Use `--db PATH` before the command to select another
database. Discovery and sync import public jobs from Personio, Greenhouse,
Ashby, SmartRecruiters, d.vinci, Lever, Recruitee, Workable and Workday.
Search includes all open jobs, regardless of occupation or country.

## Architecture

Common Crawl → verified feeds → adapters → SQLite → CLI / MCP.

- `discovery.py` finds feeds and resumes from the saved index position.
- `adapters/` validates complete feeds and maps provider data to job records.
- `sync.py` downloads feeds with bounded workers and saves completed sources immediately.
- `db.py` initializes SQLite and stores sources and jobs; `search.py` queries them.

Each source import commits jobs, closure counters and its run report together.
Failed imports preserve existing jobs. Two successful imports without a job close
it; a returning job reopens with its original ID. Unchanged jobs avoid index writes.
HTTP requests have time/size limits and respect `Retry-After` cooldowns.
Failed discovery candidates are retried after one day. Changed feeds run again
after one hour, unchanged feeds after six; import failures use exponential backoff.

## MCP

```bash
uv run jobsh serve
```

The server communicates over stdio. Add it to your MCP client's server configuration,
replacing the absolute paths:

```json
{
  "mcpServers": {
    "jobsh": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/jobsh",
        "run", "jobsh", "--db", "/absolute/path/jobsh/jobsh.db", "serve"
      ]
    }
  }
}
```

- `search_jobs(query="", title="", location="", work_mode=null, limit=20, cursor=0)`
  returns compact `jobs` with a plain-text `snippet` (up to 320 characters) and
  `next_cursor`. Snippets show context around a query term, or the description
  start when no term matches. Pass that cursor with unchanged filters
  until it is null. An empty query browses all open jobs.
- `get_job(id)` returns the full plain-text description, source URL and freshness/closure dates,
  including for closed jobs.

Search uses SQLite FTS5 over titles and descriptions; words are combined with AND.
C++, C# and .NET are matched literally. Title and location are substring filters;
work mode accepts remote, hybrid, onsite or unknown. Location is source text and
work mode comes from structured metadata where available, otherwise heuristics:
the agent should inspect descriptions for actual eligibility.

Pages contain at most 100 hits, ordered by ID, using cursor pagination without
deep offsets or full result counts. CLI JSON uses the same page format; continue
with `--cursor ID`. Pagination sees live data, so a concurrent sync may change results.
MCP tools use separate read-only connections; WAL allows searches during sync.
Existing jobs are preserved; legacy classification columns are ignored.

## Adding a provider

Register an `Adapter` in `src/jobsh/adapters/__init__.py` with:

- `domains`: Common Crawl discovery domains; use `()` for manual-only adapters.
- `source(url)`: extract `(provider_account, feed_url)`, or return `None`.
- `fetch_records(url, timeout)`: validate and normalize the complete feed into job
  dictionaries (see `adapters/personio.py` and `db.JOB_FIELDS`). Raise `ValueError`
  for invalid or incomplete feeds, and `OSError` for network errors. Only a
  successfully validated empty feed may return `[]`.
- Optional `verify(url, timeout)`: a lightweight discovery check; otherwise
  discovery uses `fetch_records`.

Run `jobsh discovery --provider NAME`; `sync` selects the adapter from each stored
source. Database writes, job lifecycle and concurrency remain shared. Adapters
must support concurrent calls.

JSON feeds reuse `adapters.json_feed.normalize` for validation, duplicate checks,
hashing and serialization. Each provider maps a job with a plain Python function;
return `None` to exclude an unlisted job. Feed completeness and pagination stay
with the provider (see `adapters/greenhouse.py` and `adapters/lever.py`).

```bash
uv run python -m unittest discover -s tests
```
