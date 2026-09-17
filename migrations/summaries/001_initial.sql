CREATE TABLE IF NOT EXISTS summary_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summary_algorithms (
    fingerprint TEXT PRIMARY KEY,
    algorithm_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entry_summaries (
    entry_key TEXT PRIMARY KEY,
    entry_date TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    source_hash TEXT NOT NULL,
    algorithm_fingerprint TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok', 'empty', 'failed')),
    summary TEXT NOT NULL DEFAULT '',
    error TEXT,
    generated_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(algorithm_fingerprint) REFERENCES summary_algorithms(fingerprint),
    UNIQUE(entry_date, entry_type)
);

CREATE INDEX IF NOT EXISTS idx_entry_summaries_date ON entry_summaries(entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_entry_summaries_year_month ON entry_summaries(year, month);
CREATE INDEX IF NOT EXISTS idx_entry_summaries_type ON entry_summaries(entry_type);
CREATE INDEX IF NOT EXISTS idx_entry_summaries_status ON entry_summaries(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entry_summaries_cache_key ON entry_summaries(cache_key);

CREATE TABLE IF NOT EXISTS summary_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    algorithm_fingerprint TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'interrupted', 'failed')),
    total INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    generated INTEGER NOT NULL DEFAULT 0,
    reused INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(algorithm_fingerprint) REFERENCES summary_algorithms(fingerprint)
);