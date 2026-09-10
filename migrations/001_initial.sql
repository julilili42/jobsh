CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    domain TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    provider TEXT NOT NULL,
    provider_account TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    discovery TEXT NOT NULL,
    discovered_at TEXT,
    last_success_at TEXT,
    UNIQUE (provider, provider_account)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    locations TEXT NOT NULL,
    location_text TEXT,
    work_mode TEXT NOT NULL CHECK (work_mode IN ('remote', 'hybrid', 'onsite', 'unknown')),
    employment_type TEXT,
    source_category TEXT,
    classification_rule TEXT,
    it_classification TEXT NOT NULL DEFAULT 'uncertain'
        CHECK (it_classification IN ('it', 'non_it', 'uncertain')),
    original_url TEXT NOT NULL,
    german_eligibility_evidence TEXT,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    closed_at TEXT,
    missing_imports INTEGER NOT NULL DEFAULT 0 CHECK (missing_imports >= 0),
    content_hash TEXT NOT NULL,
    raw_record TEXT NOT NULL,
    UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    created_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    unchanged_count INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL,
    error TEXT
);
