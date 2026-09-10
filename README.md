# jobsh

Local CLI for discovering, importing, and searching German IT jobs.

```bash
uv sync
uv run jobsh discovery --limit 100
uv run jobsh sync
uv run jobsh search python --remote
```

Data is stored in `jobsh.db` by default. Use `--db PATH` before the command to
select another database.

```bash
uv run python -m unittest discover -s tests
```

Implementation notes live in [`docs/02-mvp`](docs/02-mvp/README.md).

## Adding a provider

Register an `Adapter` in `src/jobsh/adapters.py` with:

- `domain`: the Common Crawl discovery domain.
- `source(url)`: extract `(provider_account, feed_url)`, or return `None`.
- `fetch_records(url, timeout)`: validate and normalize the complete feed into job
  dictionaries (see `personio_feed.py` and `jobs.JOB_FIELDS`). Raise `ValueError`
  for invalid or incomplete feeds, and `OSError` for network errors. Only a
  successfully validated empty feed may return `[]`.

Run `jobsh discovery --provider NAME`; `sync` selects the adapter from each
stored source. Adapters handle provider formats; database writes, classification,
job lifecycle, and concurrency remain shared. Adapters must support concurrent calls.
