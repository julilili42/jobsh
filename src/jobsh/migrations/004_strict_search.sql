DROP TRIGGER jobs_fts_insert;
DROP TRIGGER jobs_fts_update;
DROP TRIGGER jobs_fts_delete;
DROP TABLE jobs_fts;

CREATE VIRTUAL TABLE jobs_fts
USING fts5(title, description, tokenize='unicode61 remove_diacritics 0');

CREATE TRIGGER jobs_fts_insert AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
CREATE TRIGGER jobs_fts_update AFTER UPDATE OF title, description ON jobs BEGIN
    DELETE FROM jobs_fts WHERE rowid = old.id;
    INSERT INTO jobs_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
CREATE TRIGGER jobs_fts_delete AFTER DELETE ON jobs BEGIN
    DELETE FROM jobs_fts WHERE rowid = old.id;
END;

INSERT INTO jobs_fts(rowid, title, description)
SELECT id, title, description FROM jobs;
