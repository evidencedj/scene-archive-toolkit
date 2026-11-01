-- Scene Archive Browser — Datenbankschema
-- Eine Zeile pro Release-Ordner, eine Zeile pro Datei darin.

CREATE TABLE IF NOT EXISTS releases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_name   TEXT NOT NULL UNIQUE,   -- z.B. "Gang_Starr-Moment_Of_Truth-1998-CMS"
    status        TEXT NOT NULL,          -- scenereleases | scenereleases_nosrr | incomplete | dupes
    artist        TEXT,
    title         TEXT,
    year          TEXT,
    release_group TEXT,
    format        TEXT,                   -- CD, VLS, FLAC, WEB, ... (fuer Statistik/Filter/Sortierung)
    container     TEXT,                   -- Traegerformat unabhaengig von der Kodierung (CD, Vinyl, WEB, ...)
    is_flac       INTEGER DEFAULT 0,      -- 1 wenn echte .flac Dateien im Ordner liegen
    track_count   INTEGER DEFAULT 0,
    total_size    INTEGER DEFAULT 0,      -- Bytes, Summe aller Dateien
    nfo_text      TEXT,                   -- roher NFO-Inhalt, fuer Volltextsuche
    has_cover     INTEGER DEFAULT 0,      -- 1 wenn ein .jpg/.png Cover gefunden wurde
    indexed_at    TEXT NOT NULL,
    date_added    TEXT,                   -- wann das Release in den Bestand kam, siehe indexer.py
    gdrive_folder_id TEXT,                -- ungenutzt seit 1.7 (Google Drive entfernt), bleibt der Kompatibilitaet wegen
    genre         TEXT,                   -- haeufigstes ID3 Genre (Originalschreibweise), NULL wenn ungetaggt
    genre_key     TEXT,                   -- normalisiertes Genre, fuer Filter und Statistik
    genre_mtime   INTEGER                 -- Ordner-mtime beim letzten Genre-Lesen, steuert das Neulesen
);

CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id    INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    relpath       TEXT NOT NULL,          -- relativ zum Release-Ordner (Multi-CD: "CD1/...")
    size          INTEGER DEFAULT 0,
    extension     TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_release ON files(release_id);
CREATE INDEX IF NOT EXISTS idx_releases_year ON releases(year);
CREATE INDEX IF NOT EXISTS idx_releases_group ON releases(release_group);
CREATE INDEX IF NOT EXISTS idx_releases_status ON releases(status);
CREATE INDEX IF NOT EXISTS idx_releases_date_added ON releases(date_added);
CREATE INDEX IF NOT EXISTS idx_releases_genre_key ON releases(genre_key);

-- Volltextsuche ueber Kuenstler, Titel, Gruppe, Ordnername und NFO-Inhalt.
-- content='releases' + content_rowid='id' spiegelt die releases-Tabelle,
-- so bleibt FTS klein und synchron ueber Trigger statt Duplizierung von Hand.
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
