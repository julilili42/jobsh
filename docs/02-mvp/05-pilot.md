# 5. Run and evaluate the pilot

Document local startup, configuration, migrations, backup, and recovery. Run one
application instance with its SQLite database on an existing machine.

Run the pilot for seven days and import at a documented manual cadence. Record
source failures, time since last successful import, new, changed, and closed
jobs, query latency, and resource use. Show stale data clearly.

Measure the following separately:

- **Coverage:** matched unique IT postings divided by all manually observed IT
  postings for the 20 employers.
- **Import completeness:** jobs captured from the selected feeds.
- **Freshness:** delay between a source observation and its import into jobsh.
- **Classification:** false positives, missed IT roles, and uncertain cases.

Benchmark a local synthetic index of 100,000 jobs with ten concurrent readers.
Target search p95 below one second and record the hardware and results. This is
an acceptance target, not a measured claim.

**Done:** another person can start jobsh, import real jobs, and find them through
the local CLI. The pilot report shows coverage gaps, freshness, operating cost,
and the next source worth adding. All lifecycle and search checks pass.

**Test:** run the complete test suite and an end-to-end CLI check against a copy
of the pilot database before recording the benchmark.
