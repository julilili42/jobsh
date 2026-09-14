CREATE VIRTUAL TABLE IF NOT EXISTS jobs_filter_fts
USING fts5(title, location_text, tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS jobs_filter_fts_insert AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_filter_fts(rowid, title, location_text)
    VALUES (new.id, new.title, new.location_text);
END;
CREATE TRIGGER IF NOT EXISTS jobs_filter_fts_update
AFTER UPDATE OF title, location_text ON jobs BEGIN
    DELETE FROM jobs_filter_fts WHERE rowid = old.id;
    INSERT INTO jobs_filter_fts(rowid, title, location_text)
    VALUES (new.id, new.title, new.location_text);
END;
CREATE TRIGGER IF NOT EXISTS jobs_filter_fts_delete AFTER DELETE ON jobs BEGIN
    DELETE FROM jobs_filter_fts WHERE rowid = old.id;
END;

INSERT INTO jobs_filter_fts(rowid, title, location_text)
SELECT id, title, location_text FROM jobs
WHERE id NOT IN (SELECT rowid FROM jobs_filter_fts);
