# 1. Discover and verify Personio feeds

Query the latest [Common Crawl CDXJ Index](https://commoncrawl.org/cdxj-index) for
distinct hosts below `jobs.personio.de`. Treat these archived URLs only as
discovery candidates. Deduplicate the hosts and verify each current feed at
`https://<account>.jobs.personio.de/xml?language=de`.

```sh
uv run jobsh discovery
uv run jobsh discovery --limit 100
```

Register verified feed endpoints directly in SQLite.

Common Crawl pages are read lazily, one index block per request. `--limit`
stops reading once that many distinct candidate hosts have been encountered;
duplicates and unrelated hosts do not count. The selected hosts are sorted
before verification. The limit counts hosts, not verified feeds or job listings.
Without a limit, all pages are read. Requests remain sequential with a one-second
pause between pages; feed verification uses `--workers` (default 8).
Malformed JSON responses are retried twice before reporting the failing URL.

Keep a manually reviewed reference sample of 20 Personio career pages. Use it to
measure discovery gaps and compare feeds with their current career pages.

For verified feeds, record the account, feed URL, and observation date. Check
stable IDs, original links, relevant fields, German
eligibility, usage terms, and whether a missing record reliably means that a job
has closed. Save representative index rows and XML responses.

If Personio cannot support a reliable pilot, repeat the check with another ATS
that exposes complete public employer feeds. Implement only the first provider
that passes it.

**Done:** a repeatable discovery command, a deduplicated list of verified feeds,
coverage against the 20-page reference sample, recorded examples, known gaps,
and an explicit refresh and closure contract.

**Test:** recorded Common Crawl rows produce unique candidate hosts; invalid
feeds are rejected, and a valid XML fixture yields a position with an ID and
title.
