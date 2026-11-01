#!/usr/bin/env python3
"""
main.py — Scene Archive Browser web app (FastAPI)

Read-only web frontend over the SQLite database built by indexer.py.
Search page -> result list -> click a release -> see its files,
mirroring the srrDB browsing flow the user asked for.

VERSION HISTORY
  1.0  first release of the ArchiveDB web app.
  1.1  2026-09-24  Added /gdrive-ids endpoint (takes "ID|folder_name/" lines
                   from "rclone lsf --format ip" and stores them in
                   releases.gdrive_folder_id); release_detail() hands a ready
                   made gdrive_url to the template. (Removed again in 1.7.)
  1.2  2026-10-01  Added "added" sorting (date_added) and selected date_added
                   in the result list, for the new "Added" column in
                   search.html.
  1.3  2026-10-01  A-Z jump bar: build_alphabet_index() finds, per letter
                   (folders starting with a digit are grouped under "#"),
                   the page and release ID where it starts in alphabetical
                   order, so a click jumps straight to the matching row in
                   search.html.
  1.4  2026-10-06  Statistics page /stats (formats, years, timeline, top
                   groups, top genres, additions per month), all computed
                   from the SQLite index, every entry links to the filtered
                   search. New genre filter in the search (parameter "genre",
                   filters on releases.genre_key); the genre is also shown on
                   the detail page.
  1.5  2026-10-06  Fix: bars in the top lists were invisible (span without
                   display:block, fixed in base.html). Years outside 1900 to
                   2035 (e.g. broken ID3 tags like "0199") are ignored in the
                   statistics.
  1.6  2026-10-16  "Open on Storage Box" button: release_detail() builds the
                   address from FILES_BASE_URL (e.g. https://files.example.org),
                   FILES_FOLDER (default "scenereleases") and the URL encoded
                   folder_name and passes it to release.html as box_url.
                   Without FILES_BASE_URL no button is shown.
  1.7  2026-10-21  New folder structure: source filter "src" (srr = status
                   scenereleases, nosrr = status scenereleases_nosrr) in the
                   search, "no srr" badge in the result list, two cards on the
                   statistics page. The web link uses the matching folder per
                   release (FILES_FOLDER for srr, FILES_FOLDER_NOSRR for
                   nosrr). Google Drive removed: /gdrive-ids and the button
                   are gone, the column gdrive_folder_id stays unused in the
                   database.
  1.8  2026-10-28  Button text "Open in Storagebox" (release.html). The address
                   can point straight at a Storage Box web UI by setting
                   FILES_BASE_URL to https://<account>.your-storagebox.de/index.html#
                   (docker-compose.yml). No code change.
  1.9  2026-11-01  Portable edition: UNC_BASE_PATH has no fixed default any
                   more. If empty, "Open in Explorer" and "Copy folder path"
                   are hidden on the detail page. FILES_FOLDER now defaults to
                   "scenereleases_srr". No database change.
"""

import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter

import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DB_PATH = os.environ.get("DB_PATH", "/data/archive.db")
BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="Scene Archive Browser")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "..", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "..", "templates"))


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def human_size(n):
    if not n:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


SEARCH_SCOPES = {
    "all":          None,             # searches every indexed column
    "artist":       "artist",
    "title":        "title",
    "folder_name":  "folder_name",
    "release_group": "release_group",
    "nfo_text":     "nfo_text",
}


def fts_query(raw, scope="all"):
    """
    Turns free-text user input into a safe FTS5 query: each word
    becomes a prefix-wildcard AND term, so "gang starr" behaves like
    "gang* AND starr*" — forgiving of partial words, still precise.
    Any raw FTS5 syntax characters the user might type are stripped
    so they can't break the query or do something unexpected.

    If scope names one specific column (e.g. "artist"), every term
    is prefixed with "column:" so the match is restricted to that
    field only — "dilated" under the Artist scope then only hits
    releases where Dilated is actually the artist, not any release
    that merely mentions the word somewhere (in the NFO, say).
    """
    words = re.findall(r'[A-Za-z0-9]+', raw)
    if not words:
        return None
    column = SEARCH_SCOPES.get(scope)
    if column:
        return " AND ".join(f'{column}:{w}*' for w in words)
    return " AND ".join(f'{w}*' for w in words)


SORT_COLUMNS = {
    "name": "folder_name",
    "year": "year",
    "group": "release_group",
    "size": "total_size",
    "added": "date_added",
}


def build_order_by(sort, order):
    column = SORT_COLUMNS.get(sort, "folder_name")
    direction = "DESC" if order == "desc" else "ASC"
    if column in ("folder_name", "release_group"):
        return f"{column} COLLATE NOCASE {direction}"
    return f"{column} {direction}"


# Source filter: URL value -> value in releases.status
SRC_STATUS = {"srr": "scenereleases", "nosrr": "scenereleases_nosrr"}

PAGE_SIZE_OPTIONS = [30, 50, 100, 200]


ALPHABET_LETTERS = ["#"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]


def classify_letter(folder_name):
    """First-character bucket for the A-Z jump bar. Scene folder names
    often start with a digit (e.g. "108-Popular_Demand...", "3582-...),
    those all land in one "#" bucket ahead of A rather than being
    scattered as their own single-entry buckets."""
    c = (folder_name or "")[:1].upper()
    return c if "A" <= c <= "Z" else "#"


def build_alphabet_index(con, where_sql, params, page_size):
    """
    For the CURRENT filtered result set (same where_sql/params as the
    main query), finds where each letter bucket first appears under
    plain alphabetical order — regardless of what sort/order the page
    is actually showing right now, since the jump always forces
    sort=name&order=asc. Returns {letter: {"page": N, "release_id": id}}
    only for letters that actually occur, so the template can grey out
    the rest.
    """
    rows = con.execute(
        f"SELECT id, folder_name FROM releases WHERE {where_sql} ORDER BY folder_name COLLATE NOCASE ASC",
        params
    ).fetchall()
    index = {}
    for i, row in enumerate(rows):
        letter = classify_letter(row["folder_name"])
        if letter not in index:
            index[letter] = {"page": i // page_size + 1, "release_id": row["id"]}
    return index


def build_page_list(current, total_pages, window=2):
    """
    Builds a compact list of page tokens to render as links: always
    shows the first and last page, a window around the current page,
    and "…" for any gap in between — so a 400-page result set doesn't
    turn into 400 clickable numbers.
    """
    if total_pages <= 1:
        return [1]
    pages = {1, total_pages}
    for p in range(current - window, current + window + 1):
        if 1 <= p <= total_pages:
            pages.add(p)
    ordered = sorted(pages)
    result = []
    for i, p in enumerate(ordered):
        if i > 0 and p - ordered[i - 1] > 1:
            result.append("…")
        result.append(p)
    return result


def genre_display_map(con):
    """
    {genre_key: (display_name, count)} over all releases with a genre. The
    display name is the most frequent original spelling of the respective
    normalised key.
    """
    counts = Counter()
    spellings = {}
    for key, name, n in con.execute(
            "SELECT genre_key, genre, COUNT(*) FROM releases "
            "WHERE genre_key IS NOT NULL GROUP BY genre_key, genre"):
        counts[key] += n
        spellings.setdefault(key, Counter())[name] += n
    return {k: (spellings[k].most_common(1)[0][0], counts[k]) for k in counts}


def genre_choices(con):
    """Genre choices for the search filter: [(key, "Name (n)")], most frequent first."""
    gm = genre_display_map(con)
    ordered = sorted(gm.items(), key=lambda kv: (-kv[1][1], kv[1][0].lower()))
    return [(k, f"{name} ({n})") for k, (name, n) in ordered]


@app.get("/", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", scope: str = "folder_name", year: str = "",
                group: str = "", fmt: str = "", genre: str = "", src: str = "", sort: str = "name", order: str = "asc",
                page: int = 1, page_size: int = 30):
    con = get_db()
    if page_size not in PAGE_SIZE_OPTIONS:
        page_size = 30
    page = max(page, 1)
    offset = (page - 1) * page_size

    if sort not in SORT_COLUMNS:
        sort = "name"
    if order not in ("asc", "desc"):
        order = "asc"

    if scope not in SEARCH_SCOPES:
        scope = "all"

    where = ["1=1"]
    params = []

    if q.strip():
        fq = fts_query(q, scope)
        release_ids = [r[0] for r in con.execute(
            "SELECT rowid FROM releases_fts WHERE releases_fts MATCH ?", (fq,)
        ).fetchall()] if fq else []
        if not release_ids:
            release_ids = [-1]
        where.append(f"id IN ({','.join('?' * len(release_ids))})")
        params.extend(release_ids)

    if year:
        where.append("year = ?")
        params.append(year)
    if group:
        where.append("release_group = ?")
        params.append(group.upper())
    if fmt:
        where.append("format = ?")
        params.append(fmt)
    if genre:
        where.append("genre_key = ?")
        params.append(genre)

    if src in SRC_STATUS:
        where.append("status = ?")
        params.append(SRC_STATUS[src])
    else:
        src = ""

    where_sql = " AND ".join(where)

    order_sql = build_order_by(sort, order)

    total = con.execute(f"SELECT COUNT(*) FROM releases WHERE {where_sql}", params).fetchone()[0]
    rows = con.execute(f"""
        SELECT id, folder_name, artist, title, year, release_group, format,
               track_count, total_size, has_cover, date_added, status
        FROM releases WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """, params + [page_size, offset]).fetchall()

    alphabet = build_alphabet_index(con, where_sql, params, page_size)

    years = [r[0] for r in con.execute(
        "SELECT DISTINCT year FROM releases WHERE year IS NOT NULL AND year BETWEEN '1900' AND '2035' ORDER BY year DESC").fetchall()]
    groups = [r[0] for r in con.execute(
        "SELECT DISTINCT release_group FROM releases WHERE release_group IS NOT NULL "
        "ORDER BY release_group").fetchall()]
    formats = [r[0] for r in con.execute(
        "SELECT DISTINCT format FROM releases ORDER BY format").fetchall()]

    genres = genre_choices(con)

    con.close()

    total_pages = max(1, (total + page_size - 1) // page_size)
    page_list = build_page_list(page, total_pages)

    return templates.TemplateResponse("search.html", {
        "request": request, "q": q, "scope": scope, "year": year, "group": group, "fmt": fmt,
        "genre": genre, "genres": genres, "src": src,
        "sort": sort, "order": order,
        "results": rows, "total": total, "page": page, "page_size": page_size,
        "page_size_options": PAGE_SIZE_OPTIONS,
        "total_pages": total_pages, "page_list": page_list,
        "has_more": offset + page_size < total,
        "years": years, "groups": groups, "formats": formats,
        "search_scopes": SEARCH_SCOPES,
        "human_size": human_size,
        "alphabet": alphabet, "alphabet_letters": ALPHABET_LETTERS,
    })


def bar_rows(pairs, link_fn, limit=None):
    """[(label, count)] -> rows with bar width as a percentage of the maximum."""
    pairs = pairs[:limit] if limit else pairs
    top = max((n for _, n in pairs), default=1) or 1
    return [{"label": label, "count": n, "pct": round(100 * n / top, 1), "href": link_fn(label)}
            for label, n in pairs]


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    """
    Statistics over the whole index (all indexed status folders).
    Computed live from SQLite, which takes milliseconds for a few tens of
    thousands of rows. Every entry links to the filtered search.
    """
    con = get_db()
    one = lambda sql: con.execute(sql).fetchone()[0]
    total = one("SELECT COUNT(*) FROM releases")
    totals = {
        "releases": total,
        "tracks": one("SELECT COALESCE(SUM(track_count),0) FROM releases"),
        "size": human_size(one("SELECT COALESCE(SUM(total_size),0) FROM releases")),
        "groups": one("SELECT COUNT(DISTINCT release_group) FROM releases"),
        "srr": one("SELECT COUNT(*) FROM releases WHERE status = 'scenereleases'"),
        "nosrr": one("SELECT COUNT(*) FROM releases WHERE status = 'scenereleases_nosrr'"),
        "with_genre": one("SELECT COUNT(*) FROM releases WHERE genre_key IS NOT NULL"),
        "no_year": one("SELECT COUNT(*) FROM releases WHERE year IS NULL OR year NOT BETWEEN '1900' AND '2035'"),
    }
    q = lambda sql: [(r[0], r[1]) for r in con.execute(sql).fetchall()]

    formats = q("SELECT format, COUNT(*) c FROM releases GROUP BY format ORDER BY c DESC")
    groups = q("SELECT release_group, COUNT(*) c FROM releases WHERE release_group IS NOT NULL "
               "GROUP BY release_group ORDER BY c DESC, release_group LIMIT 25")
    years_top = q("SELECT year, COUNT(*) c FROM releases WHERE year IS NOT NULL AND year BETWEEN '1900' AND '2035' "
                  "GROUP BY year ORDER BY c DESC LIMIT 15")
    years_all = q("SELECT year, COUNT(*) c FROM releases WHERE year IS NOT NULL AND year BETWEEN '1900' AND '2035' "
                  "GROUP BY year ORDER BY year")
    added = q("SELECT substr(date_added,1,7) m, COUNT(*) c FROM releases "
              "WHERE date_added IS NOT NULL GROUP BY m ORDER BY m DESC LIMIT 12")
    added.reverse()
    gm = genre_display_map(con)
    genres = sorted(((k, v[0], v[1]) for k, v in gm.items()), key=lambda t: (-t[2], t[1].lower()))[:20]
    con.close()

    genre_rows = []
    gtop = genres[0][2] if genres else 1
    for key, name, n in genres:
        genre_rows.append({"label": name, "count": n, "pct": round(100 * n / gtop, 1),
                           "href": f"/?genre={requests.utils.quote(key)}"})

    return templates.TemplateResponse("stats.html", {
        "request": request, "totals": totals,
        "formats": bar_rows(formats, lambda l: f"/?fmt={requests.utils.quote(str(l))}"),
        "groups": bar_rows(groups, lambda l: f"/?group={requests.utils.quote(str(l))}"),
        "years_top": bar_rows(years_top, lambda l: f"/?year={l}"),
        "timeline": bar_rows(years_all, lambda l: f"/?year={l}"),
        "added": bar_rows(added, lambda l: "/?sort=added&order=desc"),
        "genres": genre_rows,
    })


# Windows share of the srr folder, e.g. \\\\server\\share\\scenereleases_srr
# (double backslashes as in a .env file). Empty = the buttons
# "Open in Explorer" and "Copy folder path" are not shown.
UNC_BASE_PATH = os.environ.get("UNC_BASE_PATH", "").strip().rstrip("\\")

# Optional web link to the files (e.g. a Hetzner Storage Box with an
# index.html, or any other web server): base address and the folder that
# holds the releases. FILES_BASE_URL empty = no "Open in Storagebox" button.
FILES_BASE_URL = os.environ.get("FILES_BASE_URL", "").strip().rstrip("/")
FILES_FOLDER = os.environ.get("FILES_FOLDER", "scenereleases_srr").strip().strip("/")
# Folder for releases without an srrDB match
FILES_FOLDER_NOSRR = os.environ.get("FILES_FOLDER_NOSRR", "scenereleases_nosrr").strip().strip("/")

METADATA_EXTENSIONS = {".nfo", ".m3u", ".sfv", ".jpg", ".jpeg", ".png", ".srr", ".srs"}


def unc_to_file_uri(unc_path):
    r"""\\server\share\path -> file://server/share/path — works only
    with a browser extension or configuration that explicitly allows
    it; plain browsers block file:// navigation from an http(s) page
    for security reasons, especially over HTTPS."""
    p = unc_path.lstrip("\\").replace("\\", "/")
    return f"file://{p}"


@app.get("/release/{release_id}", response_class=HTMLResponse)
def release_detail(request: Request, release_id: int):
    con = get_db()
    release = con.execute("SELECT * FROM releases WHERE id = ?", (release_id,)).fetchone()
    if not release:
        con.close()
        return HTMLResponse("Release not found", status_code=404)

    files = con.execute(
        "SELECT filename, relpath, size, extension FROM files WHERE release_id = ? ORDER BY relpath",
        (release_id,)
    ).fetchall()
    con.close()

    metadata_files = [f for f in files if f["extension"].lower() in METADATA_EXTENSIONS]
    media_files = [f for f in files if f["extension"].lower() not in METADATA_EXTENSIONS]

    unc_path = f"{UNC_BASE_PATH}\\{release['folder_name']}" if UNC_BASE_PATH else None

    display_format = release["format"]
    if release["is_flac"] and release["container"]:
        display_format = f"{release['container']} (FLAC)"

    # Everything except letters, digits and _.-~ is encoded (brackets, commas,
    # #, ?, % ...) so the release name cannot break the link. The trailing
    # slash gives the folder view on the box.
    box_url = None
    if FILES_BASE_URL:
        box_folder = FILES_FOLDER_NOSRR if release["status"] == "scenereleases_nosrr" else FILES_FOLDER
        parts = [requests.utils.quote(box_folder, safe="/")] if box_folder else []
        parts.append(requests.utils.quote(release["folder_name"], safe=""))
        box_url = f"{FILES_BASE_URL}/" + "/".join(parts) + "/"

    return templates.TemplateResponse("release.html", {
        "request": request, "release": release,
        "metadata_files": metadata_files, "media_files": media_files,
        "total_file_count": len(files),
        "display_format": display_format,
        "human_size": human_size,
        "unc_path": unc_path, "file_uri": unc_to_file_uri(unc_path) if unc_path else None,
        "is_nosrr": release["status"] == "scenereleases_nosrr",
        "box_url": box_url,
    })


@app.post("/release/{release_id}/srrdb")
def srrdb_check(release_id: int):
    """
    On-demand srrDB lookup, triggered by a button click on the detail
    page — deliberately NOT automatic on every page view, so browsing
    the local archive stays fast and doesn't hammer srrDB. Tries the
    exact release name first, falls back to the tolerant search API
    if that fails (folder names here are never auto-renamed to match
    srrDB, so drift is expected and normal, not an error).
    """
    con = get_db()
    row = con.execute("SELECT folder_name FROM releases WHERE id = ?", (release_id,)).fetchone()
    con.close()
    if not row:
        return {"found": False}

    folder_name = row["folder_name"]
    headers = {"User-Agent": "archivedb/1.0"}

    def fetch_details(name):
        try:
            r = requests.get(
                f"https://api.srrdb.com/v1/details/{requests.utils.quote(name)}",
                headers=headers, timeout=10
            )
            if r.status_code != 200:
                return None
            data = r.json()
            return data if data and "files" in data else None
        except Exception:
            return None

    details = fetch_details(folder_name)
    canonical = folder_name
    exact = True

    if details is None:
        exact = False
        try:
            r = requests.get(
                f"https://api.srrdb.com/v1/search/{requests.utils.quote(folder_name)}",
                headers=headers, timeout=10
            )
            results = r.json().get("results", []) if r.status_code == 200 else []
        except Exception:
            results = []
        if len(results) == 1:
            canonical = results[0]["release"]
            details = fetch_details(canonical)
        elif results:
            for res in results:
                if res.get("release", "").lower() == folder_name.lower():
                    canonical = res["release"]
                    details = fetch_details(canonical)
                    exact = True
                    break

    if details is None:
        return {"found": False}

    return {
        "found": True,
        "exact_match": exact,
        "canonical_name": canonical,
        "srrdb_url": f"https://www.srrdb.com/release/details/{canonical}",
        "file_count": len(details.get("files", [])),
    }


@app.post("/reindex")
def trigger_reindex():
    """Manual reindex trigger — runs indexer.py in-place. Intended
    for a button in the UI or a curl call after processing new
    releases, not for frequent polling."""
    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "indexer.py")],
        capture_output=True, text=True
    )
    return {"ok": result.returncode == 0, "output": result.stdout, "error": result.stderr}
