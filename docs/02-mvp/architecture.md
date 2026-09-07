# Architecture

One Python application and one SQLite database:

```text
Personio XML feeds -> normalize + validate -> SQLite -> local CLI
```

Keep Personio data outside the normalized job model. Use Python's standard
library for HTTP, XML, JSON, command flags, logging, concurrency, and database
access through `sqlite3`. Enable foreign-key enforcement and WAL mode.
