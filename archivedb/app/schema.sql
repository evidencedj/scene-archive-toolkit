-- Scene Archive Browser: database schema
-- One row per release folder, one row per file inside it.

CREATE TABLE IF NOT EXISTS releases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_name   TEXT NOT NULL UNIQUE,   -- z.B. "Gang_Starr-Moment_Of_Truth-1998-CMS"
    status        TEXT NOT NULL,          -- scenereleases | scenereleases_nosrr | incomplete | dupes
    artist        TEXT,
    title         TEXT,
    year          TEXT,
    release_group TEXT,
    format        TEXT,                   -- CD, VLS, FLAC, WEB, ... (for statistics/filter/sorting)
    container     TEXT,                   -- source medium independent of the encoding (CD, Vinyl, WEB, ...)
    is_flac       INTEGER DEFAULT 0,      -- 1 if real .flac files are in the folder
    track_count   INTEGER DEFAULT 0,
    total_size    INTEGER DEFAULT 0,      -- bytes, sum of all files
    nfo_text      TEXT,                   -- raw NFO content, for full text search
    has_cover     INTEGER DEFAULT 0,      -- 1 if a .jpg/.png cover was found
    indexed_at    TEXT NOT NULL,
    date_added    TEXT,                   -- when the release entered the archive, see indexer.py
    gdrive_folder_id TEXT,                -- unused since 1.7 (Google Drive removed), kept for compatibility
    genre         TEXT,                   -- most frequent ID3 genre (original spelling), NULL if untagged
    genre_key     TEXT,                   -- normalised genre, for filter and statistics
    genre_mtime   INTEGER                 -- folder mtime at the last genre read, controls re-reading
);

CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id    INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    relpath       TEXT NOT NULL,          -- relative to the release folder (multi-CD: "CD1/...")
    size          INTEGER DEFAULT 0,
    extension     TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_release ON files(release_id);
CREATE INDEX IF NOT EXISTS idx_releases_year ON releases(year);
CREATE INDEX IF NOT EXISTS idx_releases_group ON releases(release_group);
CREATE INDEX IF NOT EXISTS idx_releases_status ON releases(status);
CREATE INDEX IF NOT EXISTS idx_releases_date_added ON releases(date_added);
CREATE INDEX IF NOT EXISTS idx_releases_genre_key ON releases(genre_key);

-- Full text search over artist, title, group, folder name and NFO content.
-- content='releases' + content_rowid='id' mirrors the releases table,
-- so FTS stays small and in sync through triggers instead of manual duplication.
CREATE VIRTUAL TABLE IF NOT EXISTS releases_fts USING fts5(
    folder_name, artist, title, release_group, nfo_text,
    content='releases', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS releases_ai AFTER INSERT ON releases BEGIN
    INSERT INTO releases_fts(rowid, folder_name, artist, title, release_group, nfo_text)
    VALUES (new.id, new.folder_name, new.artist, new.title, new.release_group, new.nfo_text);
END;

CREATE TRIGGER IF NOT EXISTS releases_ad AFTER DELETE ON releases BEGIN
    INSERT INTO releases_fts(releases_fts, rowid, folder_name, artist, title, release_group, nfo_text)
    VALUES ('delete', old.id, old.folder_name, old.artist, old.title, old.release_group, old.nfo_text);
END;

CREATE TRIGGER IF NOT EXISTS releases_au AFTER UPDATE ON releases BEGIN
    INSERT INTO releases_fts(releases_fts, rowid, folder_name, artist, title, release_group, nfo_text)
    VALUES ('delete', old.id, old.folder_name, old.artist, old.title, old.release_group, old.nfo_text);
    INSERT INTO releases_fts(rowid, folder_name, artist, title, release_group, nfo_text)
    VALUES (new.id, new.folder_name, new.artist, new.title, new.release_group, new.nfo_text);
END;
