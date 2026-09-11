# 3. Make repeated imports safe

Run imports manually for the MVP. Bound request time and response size, respect
rate limits and `Retry-After`, and serialize database writes.

Fetch and validate a complete feed before updating its jobs. Apply upserts,
missing-job counters, and the successful-run marker in one transaction.

- Close a missing job only after two consecutive complete imports.
- A timeout, parse failure, or invalid record cannot trigger closures.
- Reopen the existing job ID if a closed job returns.

**Done:** a failed source does not affect existing data or searches.

**Test:** one lifecycle test covers creation, update, removal, reappearance, and
a failed import.

Implemented by `jobsh sync`: missing-job counters, upserts, closures, and the
success marker commit together. Existing databases receive the counter column
automatically. Failed fetches, validation, or database writes leave jobs intact.

HTTP 429/503 responses fail the current import and set a per-host cooldown from
`Retry-After` (seconds or HTTP date; 60 seconds if absent or invalid). Further
requests during that cooldown fail immediately. Cooldowns last for the current
process; there are no automatic retries.

Run the lifecycle, rollback, and database-upgrade checks with:

```sh
uv run python -m unittest tests.test_safe_reimports tests.test_http
```
