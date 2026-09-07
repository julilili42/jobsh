# 1. Verify Personio

Find 20 German employers with public Personio XML feeds and compare their feeds
with their career pages.

Verify stable IDs, original links, relevant fields, German eligibility, usage
terms, and whether a missing record reliably means that a job has closed. Save
example responses and observation dates.

If Personio cannot support a reliable pilot, repeat the check with another ATS
that exposes complete public employer feeds. Implement only the first provider
that passes it.

**Done:** 20 usable feeds or a documented reason to try the next ATS, recorded
examples, known gaps, and an explicit refresh and closure contract.

**Test:** every recorded XML file is well-formed, and the fixture set contains
at least one position with an ID and title.
