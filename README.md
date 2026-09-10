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
