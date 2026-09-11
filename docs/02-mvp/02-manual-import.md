# 2. Build a manual import

Add `db.py`, `jobs.py`, `personio.py`, and the initial SQL migration. Open every
SQLite connection through `db.py`, with foreign-key enforcement and WAL mode.
Start with four tables:

| Table | Purpose |
| --- | --- |
| `companies` | Employer identity and known domain |
| `sources` | Feed endpoint, discovery provenance, and last successful import |
| `jobs` | Source identity, normalized fields, raw record, and lifecycle |
| `sync_runs` | Completion state, counts, duration, and errors |

Store title, description, locations, work mode, employment type, IT
classification, original URL, and source identity. Keep `published_at`,
`first_seen_at`, `last_seen_at`, and `closed_at` separate. Preserve the latest
raw record and a hash of the normalized content.

Run `jobsh sync` to fetch every registered feed, validate and normalize its
records, and upsert its jobs. Enforce uniqueness on `(source_id, external_id)`.

Missing fields stay unknown. Keep the original location text. Preserve multiple
locations and use `remote`, `hybrid`, `onsite`, or `unknown` for work mode.
Record the evidence for German eligibility.

**Done:** a real feed imports successfully. Reimporting it preserves job IDs and
row counts. Changed content updates the same job.

**Test:** an integration test imports a recorded response twice, then imports a
changed version and verifies stable IDs, row counts, and updated content.
