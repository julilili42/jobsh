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
