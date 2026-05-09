-- Accomplishments tracker schema

CREATE TABLE IF NOT EXISTS accomplishments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        DATE NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    category    TEXT NOT NULL DEFAULT 'Other',
    impact      TEXT NOT NULL DEFAULT 'Medium',
    links       TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_accomplishments_date ON accomplishments(date);
CREATE INDEX IF NOT EXISTS idx_accomplishments_category ON accomplishments(category);

CREATE TABLE IF NOT EXISTS artifacts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    accomplishment_id INTEGER NOT NULL,
    filename          TEXT NOT NULL,
    stored_path       TEXT NOT NULL,
    mime_type         TEXT,
    size_bytes        INTEGER,
    uploaded_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (accomplishment_id) REFERENCES accomplishments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_artifacts_accomplishment ON artifacts(accomplishment_id);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS accomplishment_tags (
    accomplishment_id INTEGER NOT NULL,
    tag_id            INTEGER NOT NULL,
    PRIMARY KEY (accomplishment_id, tag_id),
    FOREIGN KEY (accomplishment_id) REFERENCES accomplishments(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id)            REFERENCES tags(id)            ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_accomplishment_tags_tag ON accomplishment_tags(tag_id);
