# 0. Initialize Python with uv, SQLite, and the project structure

Initialize the package and lock its environment:

```sh
uv init --package --name jobsh --vcs none --no-readme .
uv sync
```

Keep the project structure small:

```text
./
├── .python-version
├── pyproject.toml
├── uv.lock
├── src/jobsh/
│   ├── __init__.py
│   └── __main__.py
├── migrations/
├── tests/
├── testdata/
└── docs/
```

Add a `uv run python -m jobsh --help` entry point and confirm that the selected
Python includes `sqlite3`. Commit `uv.lock`; keep the generated database,
`.venv`, and Python caches out of Git.

Database modules, job modules, and the first migration belong to step 2.

**Done:** `uv sync` succeeds, the help command exits successfully, and `sqlite3`
imports with the selected Python.
