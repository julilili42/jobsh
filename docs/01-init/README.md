# 01 - Init

Coding agents have changed how we work, but searching for a job still feels
stuck in the past. An agent can evaluate postings well, yet it first has to find
them by searching the web one page at a time. It lacks the data to do the job
properly.

[Pinloop](https://github.com/pinloop-ai/pinloop-cli) is a compelling take on
this problem. It gives coding agents a CLI backed by a frequently refreshed job
index. Pinloop searches worldwide. I think a product focused on Germany can
offer better coverage and a better local experience. Pinloop uses
[Fantastic.jobs](https://fantastic.jobs/) for its job data, whose smallest API
plan costs $95 per month for 20,000 jobs. That is too expensive for an
experimental project, so jobsh will initially collect jobs directly from public
ATS feeds instead. This requires more work, but keeps the project cheap and
gives it control over coverage and freshness.

The unofficial [Arbeitsagentur API](https://github.com/bundesAPI/jobsuche-api)
and the free
[Arbeitnow API](https://www.arbeitnow.com/api/job-board-api) may also help fill
or measure gaps. Before building a crawler, the MVP should measure their German
IT coverage. Direct ATS adapters are only needed where that coverage falls
short.

```sh
ssh jobsh
```

## The Problem

I want to help others, build something I would use myself, and learn something
new along the way.

I have spent hours scrolling through job boards like LinkedIn, Indeed,
Glassdoor, etc. I kept seeing the same listings and wondering what I missed. I
want a modern aggregator that is fast, clean, and useful to people and agents.

German job listings are fragmented across company websites, job boards, and
many applicant tracking systems. In a 2025 survey of 301 employers, no single
system exceeded 19% usage and 17% fell into "other." The market is spread across
SAP SuccessFactors, softgarden, Personio, rexx, and many smaller systems
([DGFP study](https://www.dgfp.de/uploads/documents/FINAL-Recruiting-Struktur-BenchmarkStudie-2025.pdf)).

Discovering these sources and measuring them against the real number of public
IT postings are core problems. Coverage should be tracked by source and segment
against a regularly reviewed sample of employer career pages.

jobsh should collect postings from their best available public source. It must
normalize different formats into one model and keep the index fresh as the
number of sources grows.

The index should be independent of its UI and expose only a small application
interface. SSH commands use it first. An MCP server may follow once the index
works.

SSH requires no installation, works anywhere, and fits the technical audience.
It can be used interactively or from scripts.

## MVP

The first version can start with one applicant tracking system. Personio exposes
a public XML feed containing a company's open positions
([documentation](https://developer.personio.de/docs/retrieving-open-job-positions)).
That is enough to prove one complete path:

```txt
Personio feed -> normalize -> SQLite -> search -> SSH
```

It should be able to:

- Register a company and its Personio feed
- Import the feed repeatedly without creating duplicates
- Track new, changed, and removed postings
- Identify likely IT roles with a small rule-based classifier
- Search by title, location, and remote status
- Show the source and last-seen time for every result
- Return human-readable text or JSON
- Serve `search` and `show` over SSH

For example:

```sh
ssh jobsh search "backend python" --remote
ssh jobsh show 01J...
ssh jobsh search "security" --location berlin --json
```

The list of possible features is practically endless:

- More ATS adapters
- Automatic source discovery
- Deduplication across sources
- Profiles and semantic search
- Watches and notifications
- Agent tools
- A richer TUI with Vim keybindings

None of that is needed to validate the core idea, so it can wait.

## Tech Stack

I want the crawler and SSH application to be a single Python service. Python's
standard library covers HTTP, JSON, XML, command-line parsing, and concurrency,
which keeps the first version small and easy to deploy.

SQLite will hold companies, sources, postings, and crawl state. Its FTS5
extension should be enough for the first version. Raw source responses can stay
on disk during development. Object storage can be added if retaining them at
scale becomes useful.

The initial shape should stay small:

```txt
./
├── pyproject.toml
├── jobsh/
│   ├── __main__.py  -> Application entry point
│   ├── personio.py  -> Personio client and normalization
│   ├── jobs.py      -> Job model and persistence
│   └── ssh.py       -> SSH commands and rendering
├── migrations/      -> SQLite schema
├── testdata/        -> Recorded source responses
└── docs/            -> Cumulative journal
```

[AsyncSSH](https://asyncssh.readthedocs.io/) can handle SSH sessions. A richer
terminal UI can wait until plain SSH commands work end to end.

Pinloop will remain a useful reference for agent-oriented workflows. jobsh
starts with a narrower purpose: a transparent, SSH-native index of German IT
jobs.
