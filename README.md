# jobsh

Local job aggregator with full-text search and a read-only MCP server.

```bash
uv sync
uv run jobsh discovery --provider personio --limit 100
uv run jobsh discovery --provider greenhouse --limit 100
uv run jobsh sync
uv run jobsh search python --location Berlin --json
uv run jobsh show 42 --json
```

Data is stored in `jobsh.db`. Use `--db PATH` before the command to select another
database. Discovery and sync import all jobs from Personio and Greenhouse.
Search includes all open jobs, regardless of occupation or country.

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
  returns compact `jobs` and `next_cursor`. Pass that cursor with unchanged filters
  until it is null. An empty query browses all open jobs.
- `get_job(id)` returns the full description, source URL and freshness/closure dates,
  including for closed jobs.

Search uses SQLite FTS5 over titles and descriptions; words are combined with AND.
C++, C# and .NET are matched literally. Title and location are substring filters;
work mode accepts remote, hybrid, onsite or unknown. Location is source text and
work mode is heuristic: the agent should inspect descriptions for actual eligibility.

Pages contain at most 100 hits, ordered by ID, using cursor pagination without
deep offsets or full result counts. CLI JSON uses the same page format; continue
with `--cursor ID`. Pagination sees live data, so a concurrent sync may change results.
MCP tools use separate read-only connections; WAL allows searches during sync.
Existing jobs are preserved; legacy classification columns are ignored.

## Adding a provider

Register an `Adapter` in `src/jobsh/adapters.py` with:

- `domain`: the Common Crawl discovery domain.
- `source(url)`: extract `(provider_account, feed_url)`, or return `None`.
- `fetch_records(url, timeout)`: validate and normalize the complete feed into job
  dictionaries (see `personio_feed.py` and `jobs.JOB_FIELDS`). Raise `ValueError`
  for invalid or incomplete feeds, and `OSError` for network errors. Only a
  successfully validated empty feed may return `[]`.

Run `jobsh discovery --provider NAME`; `sync` selects the adapter from each stored
source. Database writes, job lifecycle and concurrency remain shared. Adapters
must support concurrent calls.

```bash
uv run python -m unittest discover -s tests
```
