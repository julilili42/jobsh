# Architecture

One Python application and one SQLite database:

```text
Common Crawl -> candidate hosts -> verified Personio feeds
verified feeds -> normalize jobs -> SQLite -> local CLI
```

[Common Crawl](https://commoncrawl.org/url-index) is used only to discover
Personio hosts. Current jobs always come directly from the verified XML feeds.
Keep Personio data outside the normalized job model. Use Python's standard
library for HTTP, XML, JSON, command flags, logging, concurrency, and database
access through `sqlite3`. Enable foreign-key enforcement and WAL mode.
