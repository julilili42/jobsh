# Delivery

Implement the numbered steps in order. Every step except step 0 adds its smallest
relevant test beside the code. Keep each change small enough to review
and run all tests with `uv run python -m unittest discover` in CI.

Keep one provider, one application, and one database for the MVP. Add further
providers based on measured gaps. SSH, profiles, watches, semantic search, MCP,
Vim navigation, and a full TUI can follow after the pilot.
