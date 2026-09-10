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

## Greenhouse

```bash
uv run jobsh discovery --provider greenhouse --limit 100
uv run jobsh sync
```

The adapter recognizes hosted and embedded boards on `boards.greenhouse.io`
and `job-boards.greenhouse.io`. It uses the public Job Board API without an API key.
Boards are imported worldwide. Search returns open IT jobs with explicit Germany
eligibility; ambiguous jobs remain stored and accessible through `show`.

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
