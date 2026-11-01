#!/usr/bin/env python3
"""
indexer.py

Scans the srr folder (SRR_FOLDER) and the nosrr folder (NOSRR_FOLDER) under ARCHIVE_ROOT and (re)builds the SQLite database
that the web frontend reads from. Safe to run repeatedly — every
release is upserted by its folder name, so re-running after new
releases were added only touches what actually changed.

Parsing (year/group/format detection) mirrors archive_stats.py
exactly, so the two tools always agree on what a release "is".

Usage:
  python3 indexer.py                 # full reindex of scenereleases + scenereleases_nosrr
  python3 indexer.py --status incomplete,scenereleases_nosrr,dupes,scenereleases
                                      # also index other status folders

VERSIONSHISTORIE
  1.0  first release of the ArchiveDB indexer.
  1.1  2026-09-24  gdrive_folder_id-Spalte ergaenzt (Migration in open_db()),
                   fuer den "In Google Drive oeffnen"-Button in release.html.
  1.2  2026-10-01  date_added-Spalte ergaenzt: wird nur beim allerersten
                   INSERT eines Release-Ordners gesetzt (nie bei einem
                   Update), aus der mtime des Ordners abgeleitet. Fuer
                   bereits indexierte Bestandsreleases ohne date_added
                   (NULL) laeuft einmalig ein Backfill ueber
                   backfill_date_added(), ebenfalls aus der Ordner-mtime.
  1.5  2026-10-21  Neue Ordnerstruktur (incoming_processor.py v3.0): Standard
                   indexiert jetzt zwei Quellen, "scenereleases" (Ordner mit
                   srrDB geprueften Releases, auf einer Kopie heisst
                   der Zielordner weiter so) und "scenereleases_nosrr". Der
                   Status steht weiter in releases.status. Gibt es einen Namen
                   in beiden Ordnern, gewinnt srr: ein nosrr Eintrag wird dann
                   nicht angelegt, und ein vorhandener Eintrag wird zu srr
                   (die Reihenfolge der Status Ordner ist dafuer wichtig).
  1.6  2026-11-01  Portable Edition: Die beiden Quellordner sind per Umgebungs-
                   variable einstellbar (SRR_FOLDER, Standard "scenereleases_srr";
                   NOSRR_FOLDER, Standard "scenereleases_nosrr"). Die Status
                   Namen in der Datenbank bleiben "scenereleases" (= srr) und
                   "scenereleases_nosrr", damit bestehende Datenbanken und die
                   Filter in der Oberflaeche unveraendert weiterlaufen.
"""

import os
import re
import sys
import sqlite3
import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import genre_stats
except Exception:  # Genre ist optional, der Indexer darf daran nie scheitern
    genre_stats = None

ARCHIVE_ROOT = os.environ.get("ARCHIVE_ROOT", "/archive")
DB_PATH = os.environ.get("DB_PATH", "/data/archive.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Ordnernamen unter ARCHIVE_ROOT. Der Status in der DB bleibt "scenereleases"
# (srr) bzw. "scenereleases_nosrr", der echte Ordner ist hier einstellbar.
SRR_FOLDER = os.environ.get("SRR_FOLDER", "scenereleases_srr").strip().strip("/")
NOSRR_FOLDER = os.environ.get("NOSRR_FOLDER", "scenereleases_nosrr").strip().strip("/")
STATUS_FOLDERS = {"scenereleases": SRR_FOLDER, "scenereleases_nosrr": NOSRR_FOLDER}


def status_dir(status):
    return os.path.join(ARCHIVE_ROOT, STATUS_FOLDERS.get(status, status))

DEFAULT_STATUSES = ["scenereleases", "scenereleases_nosrr"]   # srr zuerst: srr gewinnt bei gleichem Namen

MEDIA_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".ape"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png"}

MIN_YEAR, MAX_YEAR = 1900, 2035

# ---------------------------------------------------------------------------
# Parsing helpers — kept identical to archive_stats.py on purpose
# ---------------------------------------------------------------------------

FORMAT_MAP = {
    "VLS": "VLS", "(VLS)": "VLS", "PROMO VLS": "VLS", "(PROMO VLS)": "VLS",
    "FULL VLS": "VLS", "(FULL VLS)": "VLS", "PROMO-VLS": "VLS",
    "VINYL SINGLE": "VLS",
    "EP": "EP", "(EP)": "EP", "VINYL EP": "EP",
    "CDS": "CD", "CDM": "CD", "(CDS)": "CD", "(CDM)": "CD",
    "PROMO CDS": "CD", "(PROMO CDS)": "CD", "2CD": "CD", "3CD": "CD",
    "CD": "CD", "CDR": "CD", "12CD": "CD", "CD SINGLE": "CD",
    "FULL CDS": "CD", "UK-CDM": "CD", "UK CDS": "CD", "BONUS CD": "CD",
    "PROMO-CDS": "CD", "CD VERSION": "CD", "CD RETAIL": "CD",
    "LP": "LP", "(LP)": "LP", "2LP": "LP", "3LP": "LP",
    "INSTRUMENTAL LP": "LP",
    "VINYL": "Vinyl", "(VINYL)": "Vinyl", "12 INCH": "Vinyl",
    "(12 INCH)": "Vinyl", "12INCH": "Vinyl", "7INCH": "Vinyl",
    "7 INCH": "Vinyl",
    "WEB": "Web", "16BIT": "Web",
    "FLAC": "FLAC", "WEB FLAC": "FLAC", "CD FLAC": "FLAC", "CD-FLAC": "FLAC", "VINYL FLAC": "FLAC",
    "TAPE": "Tape", "(TAPE)": "Tape", "MIXTAPE": "Tape",
    "PROMO": "Promo", "(PROMO)": "Promo", "ADVANCE": "Promo",
    "(ADVANCE)": "Promo", "ALBUM SAMPLER": "Promo", "SAMPLER": "Promo",
    "WHITE LABEL": "Promo", "ADVANCE PROMO": "Promo",
    "RETAIL": "Retail", "(RETAIL)": "Retail", "EXPLICIT RETAIL": "Retail",
    "BOOTLEG": "Bootleg", "(BOOTLEG)": "Bootleg",
    "SINGLE": "Single", "CD SINGLE": "Single",
    "DVDRIP": "Video", "DVDA": "Video", "SVCD": "Video",
    "XVID": "Video", "DVD": "Video", "DVD REMIXES": "Video",
    "LIVE": "Live",
    "REISSUE": "Reissue", "LTD.ED.": "Reissue", "CD REISSUE": "Reissue",
    "REMASTERED": "Reissue", "RE-RELEASE": "Reissue", "RE-RIP": "Reissue",
    "LIMITED EDITION": "Reissue",
    "OST": "OST",
    "REMIX": "Remix", "REMIXES": "Remix", "REMIX VLS": "Remix",
    "REMIX CDS": "Remix",
}


def _year_from_segment(seg):
    cleaned = seg.strip().strip("()").strip()
    if re.fullmatch(r'\d{4}', cleaned):
        y = int(cleaned)
        return cleaned if MIN_YEAR <= y <= MAX_YEAR else None
    if " " not in cleaned:
        m = re.search(r'(?<!\d)(\d{4})$', cleaned)
        if m:
            y = int(m.group(1))
            if MIN_YEAR <= y <= MAX_YEAR:
                return m.group(1)
    return None


def extract_year(s):
    for p in s.replace("_", " ").split("-"):
        y = _year_from_segment(p)
        if y:
            return y
    return None


def extract_group(s):
    m = re.search(r'-([A-Za-z0-9_]{1,12})$', s)
    return m.group(1).upper() if m else None


def _id3v1_year(path):
    try:
        with open(path, "rb") as f:
            f.seek(-128, 2)
            tag = f.read(128)
        if tag[:3] != b"TAG":
            return None
        year = tag[93:97].decode("latin-1", errors="ignore").strip()
        return year if re.match(r'^\d{4}$', year) and MIN_YEAR <= int(year) <= MAX_YEAR else None
    except Exception:
        return None


def id3_fallback_year(folder_path):
    try:
        mp3s = sorted(f for f in os.listdir(folder_path)
                      if f.lower().endswith(".mp3"))
        if not mp3s:
            return None
        path = os.path.join(folder_path, mp3s[0])
        try:
            from mutagen.id3 import ID3
            tags = ID3(path)
            year = str(tags.get("TDRC", "")).strip()[:4]
            if re.match(r'^\d{4}$', year) and MIN_YEAR <= int(year) <= MAX_YEAR:
                return year
        except Exception:
            pass
        return _id3v1_year(path)
    except Exception:
        return None


def _find_format_tag(segment):
    segment_upper = segment.strip().upper()
    if segment_upper in FORMAT_MAP:
        return FORMAT_MAP[segment_upper]
    words = segment_upper.split()
    if len(words) < 2:
        return None
    for tag_len in range(min(4, len(words) - 1), 0, -1):
        for i in range(len(words) - tag_len + 1):
            candidate = " ".join(words[i:i + tag_len])
            if candidate in FORMAT_MAP:
                return FORMAT_MAP[candidate]
    return None


def detect_format(folder_name):
    dash_parts = [p.strip().upper() for p in folder_name.replace("_", " ").split("-")]
    if any(p == "FLAC" or p.endswith(" FLAC") or p.startswith("FLAC ") for p in dash_parts):
        return "FLAC"

    bracket_search = folder_name.replace("_", " ").upper()
    for hit in re.findall(r'\(([^)]+)\)', bracket_search):
        hit = hit.strip()
        if hit in FORMAT_MAP:
            return FORMAT_MAP[hit]
        for word in hit.split():
            if word in FORMAT_MAP:
                return FORMAT_MAP[word]

    parts = [p.strip() for p in folder_name.replace("_", " ").split("-") if p.strip()]
    year_idx = None
    for i, p in enumerate(parts):
        if re.match(r'^\d{4}$', p) and 1970 <= int(p) <= 2030:
            year_idx = i
            break

    if year_idx is not None and year_idx > 1:
        for segment in reversed(parts[1:year_idx]):
            hit = _find_format_tag(segment)
            if hit:
                return hit

    return "Album"


def detect_container(folder_name):
    """
    Same scan as detect_format(), but skips any tag that resolves to
    "FLAC" so a real container underneath (CD, Vinyl, WEB, ...) gets
    picked up instead — detect_format() deliberately lets FLAC
    override everything else (that's the right call for stats/
    sorting by audio format), but that means it alone can't tell you
    whether a FLAC release was a CD rip or a WEB release. Returns
    None if nothing but FLAC could be determined.
    """
    bracket_search = folder_name.replace("_", " ").upper()
    for hit in re.findall(r'\(([^)]+)\)', bracket_search):
        hit = hit.strip()
        if hit in FORMAT_MAP and FORMAT_MAP[hit] != "FLAC":
            return FORMAT_MAP[hit]
        for word in hit.split():
            if word in FORMAT_MAP and FORMAT_MAP[word] != "FLAC":
                return FORMAT_MAP[word]

    parts = [p.strip() for p in folder_name.replace("_", " ").split("-") if p.strip()]
    year_idx = None
    for i, p in enumerate(parts):
        if re.match(r'^\d{4}$', p) and 1970 <= int(p) <= 2030:
            year_idx = i
            break

    if year_idx is not None and year_idx > 1:
        for segment in reversed(parts[1:year_idx]):
            hit = _find_format_tag(segment)
            if hit and hit != "FLAC":
                return hit

    return None


def split_artist_title(folder_name):
    """
    Best-effort split of the Scene "Artist-Title-Format-Year-GROUP"
    convention into an artist and a title for display/search. The
    year and any dash-segment that's itself a recognized format tag
    (CDM, FLAC, VLS, 2CD, WEB, ...) are stripped out, since those are
    already captured separately by extract_year()/detect_format() —
    without this, a release like "Gang_Starr-2_Deep-CDM-FLAC-1992-
    THEVOiD" would show a title of "2 Deep CDM FLAC 1992" instead of
    just "2 Deep".
    """
    group = extract_group(folder_name)
    body = folder_name
    if group:
        body = re.sub(r'-[A-Za-z0-9_]{1,12}$', '', folder_name)
    parts = [p.strip() for p in body.replace("_", " ").split("-") if p.strip()]
    if not parts:
        return "", folder_name.replace("_", " ")
    artist = parts[0]
    rest = parts[1:]

    year_idx = None
    for i, p in enumerate(rest):
        if re.match(r'^\d{4}$', p) and 1970 <= int(p) <= 2030:
            year_idx = i
            break
    if year_idx is not None:
        rest = rest[:year_idx]

    title_parts = [p for p in rest if p.strip().upper() not in FORMAT_MAP]
    title = " ".join(title_parts)
    return artist, title


# ---------------------------------------------------------------------------
# Filesystem scan
# ---------------------------------------------------------------------------

def read_nfo_text(path, max_bytes=65536):
    """
    Scene NFOs are almost always CP437 (the old DOS codepage) — that's
    what makes their box-drawing/ASCII-art borders line up correctly.
    Reading them as Latin-1 or plain ASCII instead doesn't error out,
    but silently turns those border characters into the wrong glyphs,
    which is why NFO art looks broken in most naive viewers. A rarer
    but real case is a genuinely UTF-8 NFO from a more modern release,
    so UTF-8 is tried first (strict) and CP437 is the fallback, not
    the other way round — decoding real UTF-8 as CP437 would mangle
    any accented characters it contains.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp437", errors="replace")

    # Some elaborate NFOs (CMS in particular) use a lone carriage
    # return (\r without a following \n) to overlay two pieces of
    # ASCII art on the same terminal row — a real DOS/ANSI terminal
    # trick that has no browser equivalent. HTML's <pre> rendering
    # treats a bare \r exactly like a real line break, so without
    # this it shows up as an extra, unwanted wrap right in the
    # middle of what was meant to be a single overlaid line. Proper
    # CRLF pairs are normalized first so only genuinely standalone
    # \r characters get stripped, not real Windows-style line endings.
    text = text.replace("\r\n", "\n").replace("\r", "")
    return text


def scan_release_files(release_path):
    """Returns (files, total_size, track_count, has_cover, nfo_text, is_flac)."""
    files = []
    total_size = 0
    track_count = 0
    has_cover = False
    is_flac = False
    nfo_text = None

    for root, _, filenames in os.walk(release_path):
        for fname in filenames:
            full = os.path.join(root, fname)
            relpath = os.path.relpath(full, release_path)
            ext = os.path.splitext(fname)[1].lower()
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            files.append((fname, relpath, size, ext))
            total_size += size
            if ext in MEDIA_EXTENSIONS:
                track_count += 1
            if ext == ".flac":
                is_flac = True
            if ext in COVER_EXTENSIONS:
                has_cover = True
            if ext == ".nfo" and nfo_text is None:
                nfo_text = read_nfo_text(full)

    return files, total_size, track_count, has_cover, nfo_text, is_flac


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def open_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    # Migrations FIRST, before schema.sql runs: schema.sql also creates
    # indexes on columns like date_added, and on an existing database
    # (table already present) "CREATE TABLE IF NOT EXISTS" is a no-op,
    # so those columns must already exist by the time schema.sql's
    # CREATE INDEX statements execute. Harmless no-op on a fresh
    # install too (table doesn't exist yet -> OperationalError, caught).
    for stmt in ("ALTER TABLE releases ADD COLUMN container TEXT",
                "ALTER TABLE releases ADD COLUMN is_flac INTEGER DEFAULT 0",
                "ALTER TABLE releases ADD COLUMN gdrive_folder_id TEXT",
                "ALTER TABLE releases ADD COLUMN date_added TEXT",
                "ALTER TABLE releases ADD COLUMN genre TEXT",
                "ALTER TABLE releases ADD COLUMN genre_key TEXT",
                "ALTER TABLE releases ADD COLUMN genre_mtime INTEGER"):
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass  # table doesn't exist yet, or column already exists
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        con.executescript(f.read())
    con.commit()
    return con


def folder_added_date(release_path):
    """
    Beste verfuegbare Naeherung dafuer, wann ein Release-Ordner in den
    Bestand kam: die mtime des Ordners selbst. Eine echte Birth-Time
    (stat -c %w) waere praeziser, ist aber je nach Dateisystem/Mount
    nicht zuverlaessig verfuegbar, mtime ist der robuste Standard.
    Gibt None zurueck, wenn der Ordner (z.B. durch eine Race Condition
    beim Scan) nicht mehr existiert.
    """
    try:
        ts = os.path.getmtime(release_path)
    except OSError:
        return None
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def backfill_date_added(con):
    """
    Einmaliger Nachtrag fuer Releases, die schon vor Einfuehrung der
    date_added-Spalte indexiert wurden (dort steht aktuell NULL). Holt
    pro betroffenem Release die Ordner-mtime nach. Nach dem ersten Lauf
    bleibt die Abfrage leer und die Funktion ist ein billiges No-Op.
    """
    rows = con.execute(
        "SELECT id, status, folder_name FROM releases WHERE date_added IS NULL"
    ).fetchall()
    filled = 0
    for release_id, status, folder_name in rows:
        release_path = os.path.join(status_dir(status), folder_name)
        added = folder_added_date(release_path)
        if added:
            con.execute("UPDATE releases SET date_added=? WHERE id=?", (added, release_id))
            filled += 1
    if filled:
        con.commit()
        print(f"  Backfill: date_added fuer {filled} Bestandsrelease(s) aus Ordner-mtime nachgetragen")
    return filled


def read_release_genre(release_path):
    """
    Haeufigstes Genre eines Releases aus den ID3 Tags seiner MP3s.
    Gibt (genre, genre_key) zurueck, beides None wenn nichts getaggt ist
    oder genre_stats nicht verfuegbar ist. genre ist die haeufigste
    Originalschreibweise, genre_key die normalisierte Form, ueber die
    spaeter gefiltert und gezaehlt wird (damit "Hip-Hop" und "Hip Hop"
    als ein Genre zaehlen).
    """
    if genre_stats is None:
        return None, None
    try:
        raw = genre_stats.scan_release(release_path)["genres"]
    except Exception:
        return None, None
    per_key = Counter()
    spelling = {}
    for name, n in raw.items():
        key = genre_stats._norm_key(name)
        if not key:
            continue
        per_key[key] += n
        spelling.setdefault(key, Counter())[name] += n
    if not per_key:
        return None, None
    key = per_key.most_common(1)[0][0]
    return spelling[key].most_common(1)[0][0], key


def upsert_release(con, folder_name, status, release_path):
    year = extract_year(folder_name) or id3_fallback_year(release_path)
    group = extract_group(folder_name)
    fmt = detect_format(folder_name)
    container = detect_container(folder_name)
    artist, title = split_artist_title(folder_name)
    files, total_size, track_count, has_cover, nfo_text, is_flac = scan_release_files(release_path)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = con.execute("SELECT id, genre, genre_key, genre_mtime FROM releases WHERE folder_name = ?",
                      (folder_name,))
    row = cur.fetchone()

    # srr gewinnt: ein Name, der schon als srr Release indexiert ist, wird
    # von der nosrr Kopie nicht ueberschrieben.
    if row and status == "scenereleases_nosrr":
        cur_status = con.execute("SELECT status FROM releases WHERE id = ?", (row[0],)).fetchone()[0]
        if cur_status == "scenereleases":
            return

    # Genre nur neu lesen, wenn der Ordner neu ist oder seine mtime sich
    # geaendert hat. Sonst den gespeicherten Wert behalten.
    try:
        folder_mtime = int(os.stat(release_path).st_mtime)
    except OSError:
        folder_mtime = None
    if row and row[3] is not None and row[3] == folder_mtime:
        genre, genre_key = row[1], row[2]
    else:
        genre, genre_key = read_release_genre(release_path)

    if row:
        # date_added bewusst NICHT im UPDATE: das Feld wird nur einmal,
        # beim allerersten INSERT eines Ordners, gesetzt und danach nie
        # wieder angefasst, auch nicht bei taeglichen Reindex-Laeufen.
        release_id = row[0]
        con.execute("""
            UPDATE releases SET status=?, artist=?, title=?, year=?, release_group=?,
                format=?, container=?, is_flac=?, track_count=?, total_size=?,
                nfo_text=?, has_cover=?, indexed_at=?,
                genre=?, genre_key=?, genre_mtime=?
            WHERE id=?
        """, (status, artist, title, year, group, fmt, container, int(is_flac),
              track_count, total_size, nfo_text, int(has_cover), now,
              genre, genre_key, folder_mtime, release_id))
        con.execute("DELETE FROM files WHERE release_id=?", (release_id,))
    else:
        date_added = folder_added_date(release_path)
        cur = con.execute("""
            INSERT INTO releases (folder_name, status, artist, title, year, release_group,
                format, container, is_flac, track_count, total_size, nfo_text, has_cover,
                indexed_at, date_added, genre, genre_key, genre_mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (folder_name, status, artist, title, year, group, fmt, container, int(is_flac),
              track_count, total_size, nfo_text, int(has_cover), now, date_added,
              genre, genre_key, folder_mtime))
        release_id = cur.lastrowid

    con.executemany(
        "INSERT INTO files (release_id, filename, relpath, size, extension) VALUES (?, ?, ?, ?, ?)",
        [(release_id, f[0], f[1], f[2], f[3]) for f in files]
    )


def index_status_dir(con, status):
    status_path = status_dir(status)
    if not os.path.isdir(status_path):
        print(f"skip (not found): {status_path}")
        return 0
    entries = [n for n in sorted(os.listdir(status_path))
              if os.path.isdir(os.path.join(status_path, n)) and not n.startswith("_")]
    count = 0
    for name in entries:
        release_path = os.path.join(status_path, name)
        upsert_release(con, name, status, release_path)
        count += 1
        if count % 100 == 0:
            print(f"  {status}: {count}/{len(entries)} indexed so far...")
    return count


def prune_removed(con, statuses):
    """Drops DB entries for releases that no longer exist on disk for
    any of the indexed statuses (moved, renamed, or deleted since the
    last index run)."""
    removed = 0
    for status in statuses:
        status_path = status_dir(status)
        rows = con.execute("SELECT id, folder_name FROM releases WHERE status=?", (status,)).fetchall()
        for release_id, folder_name in rows:
            if not os.path.isdir(os.path.join(status_path, folder_name)):
                con.execute("DELETE FROM releases WHERE id=?", (release_id,))
                removed += 1
    return removed


def main():
    statuses = DEFAULT_STATUSES
    for arg in sys.argv[1:]:
        if arg.startswith("--status"):
            _, _, value = arg.partition("=")
            if not value and len(sys.argv) > sys.argv.index(arg) + 1:
                value = sys.argv[sys.argv.index(arg) + 1]
            statuses = [s.strip() for s in value.split(",") if s.strip()]

    print(f"Indexing archive at {ARCHIVE_ROOT} into {DB_PATH}")
    print(f"Statuses: {', '.join(statuses)}\n")

    con = open_db()
    total = 0
    for status in statuses:
        n = index_status_dir(con, status)
        print(f"  {status}: {n} release(s) indexed")
        total += n

    backfill_date_added(con)

    removed = prune_removed(con, statuses)
    if removed:
        print(f"  removed {removed} stale entrie(s) no longer on disk")

    con.commit()
    con.close()
    print(f"\nDone. {total} release(s) indexed total.")


if __name__ == "__main__":
    main()
