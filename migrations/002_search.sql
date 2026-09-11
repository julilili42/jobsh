CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(title, description);

CREATE TRIGGER IF NOT EXISTS jobs_fts_insert AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
CREATE TRIGGER IF NOT EXISTS jobs_fts_update AFTER UPDATE OF title, description ON jobs BEGIN
    DELETE FROM jobs_fts WHERE rowid = old.id;
    INSERT INTO jobs_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
CREATE TRIGGER IF NOT EXISTS jobs_fts_delete AFTER DELETE ON jobs BEGIN
    DELETE FROM jobs_fts WHERE rowid = old.id;
END;

INSERT INTO jobs_fts(rowid, title, description)
SELECT id, title, description FROM jobs WHERE id NOT IN (SELECT rowid FROM jobs_fts);
