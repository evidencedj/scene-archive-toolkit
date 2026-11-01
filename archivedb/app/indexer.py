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

VERSION HISTORY
  1.0  first release of the ArchiveDB indexer.
  1.1  2026-09-24  Added gdrive_folder_id column (migration in open_db()),
                   for the "open in Google Drive" button in release.html.
                   (The button was removed again later, the column stays unused.)
  1.2  2026-10-01  Added date_added column: set only on the very first
                   INSERT of a release folder (never on an update), derived
                   from the folder mtime. Releases that were indexed before
                   and have no date_added (NULL) get a one-time backfill via
                   backfill_date_added(), also from the folder mtime.
  1.5  2026-10-21  New folder structure (incoming_processor.py v3.0): by
                   default two sources are indexed, "scenereleases" (folder
                   with srrDB verified releases) and "scenereleases_nosrr".
                   The status stays in releases.status. If a name exists in
                   both folders, srr wins: a nosrr entry is not created, and
                   an existing entry becomes srr (the order of the status
                   folders matters for this).
  1.6  2026-11-01  Portable edition: the two source folders can be set via
                   environment variables (SRR_FOLDER, default "scenereleases_srr";
                   NOSRR_FOLDER, default "scenereleases_nosrr"). The status
                   names in the database stay "scenereleases" (= srr) and
                   "scenereleases_nosrr", so existing databases and the
                   filters in the web UI keep working unchanged.
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
except Exception:  # genre is optional, the indexer must never fail because of it
    genre_stats = None

ARCHIVE_ROOT = os.environ.get("ARCHIVE_ROOT", "/archive")
DB_PATH = os.environ.get("DB_PATH", "/data/archive.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Folder names under ARCHIVE_ROOT. The status in the DB stays "scenereleases"
# (srr) or "scenereleases_nosrr", the real folder is configurable here.
SRR_FOLDER = os.environ.get("SRR_FOLDER", "scenereleases_srr").strip().strip("/")
NOSRR_FOLDER = os.environ.get("NOSRR_FOLDER", "scenereleases_nosrr").strip().strip("/")
STATUS_FOLDERS = {"scenereleases": SRR_FOLDER, "scenereleases_nosrr": NOSRR_FOLDER}


def status_dir(status):
    return os.path.join(ARCHIVE_ROOT, STATUS_FOLDERS.get(status, status))

DEFAULT_STATUSES = ["scenereleases", "scenereleases_nosrr"]   # srr first: srr wins when the name is the same

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
    Best available approximation of when a release folder entered the
    archive: the mtime of the folder itself. A real birth time
    (stat -c %w) would be more precise, but depending on the filesystem or
    mount it is not reliably available, so mtime is the robust default.
    Returns None if the folder no longer exists (e.g. because of a race
    condition during the scan).
    """
    try:
        ts = os.path.getmtime(release_path)
    except OSError:
        return None
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def backfill_date_added(con):
    """
    One-time backfill for releases that were indexed before the
    date_added column existed (currently NULL). Fetches the folder mtime
    for each affected release. After the first run the query stays empty
    and the function is a cheap no-op.
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
        print(f"  Backfill: date_added filled in for {filled} existing release(s) from the folder mtime")
    return filled


def read_release_genre(release_path):
    """
    Most frequent genre of a release from the ID3 tags of its MP3s.
    Returns (genre, genre_key), both None if nothing is tagged or
    genre_stats is not available. genre is the most frequent original
    spelling, genre_key the normalised form that is used later for
    filtering and counting (so "Hip-Hop" and "Hip Hop" count as one genre).
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

    # srr wins: a name that is already indexed as an srr release is not
    # overwritten by the nosrr copy.
    if row and status == "scenereleases_nosrr":
        cur_status = con.execute("SELECT status FROM releases WHERE id = ?", (row[0],)).fetchone()[0]
        if cur_status == "scenereleases":
            return

    # Only re-read the genre if the folder is new or its mtime changed.
    # Otherwise keep the stored value.
    try:
        folder_mtime = int(os.stat(release_path).st_mtime)
    except OSError:
        folder_mtime = None
    if row and row[3] is not None and row[3] == folder_mtime:
        genre, genre_key = row[1], row[2]
    else:
        genre, genre_key = read_release_genre(release_path)

    if row:
        # date_added is deliberately NOT part of the UPDATE: the field is
        # set only once, on the very first INSERT of a folder, and never
        # touched again, not even by daily reindex runs.
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
