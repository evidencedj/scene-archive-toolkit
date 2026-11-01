#!/usr/bin/env python3
"""
genre_stats.py  v1.1

VERSION HISTORY:
  v1.0  Initial version. Counts the genres found in the ID3 tags of the
        MP3 files in the archive and returns the TOP N as a report
        section for archive_stats.py (also runnable on its own).

        Cost model, because this is the part that matters: the existing
        stats only list directories and stat() files, this has to OPEN
        every MP3. That is I/O, not CPU, and over the CIFS mount the
        I/O is what costs time. Three things keep it cheap:
          1. Only the ID3v2 header and the frame HEADERS are read. The
             TCON (genre) frame is located by seeking from frame to
             frame, so embedded cover art and other big frames are
             skipped without being read. Only if a tag uses an unusual
             feature (unsynchronisation, compressed/encrypted frame)
             does it fall back to mutagen for that one file.
          2. ID3v1 (last 128 bytes) is only consulted when the file has
             no usable ID3v2 genre.
          3. A per-release cache (genre_stats_cache.json next to this
             script, i.e. on the local disk, not on the CIFS share).
             A release is only re-read when its folder mtime changed or
             it is new. After the first full run a nightly run touches
             only the releases that arrived since the day before.
        Raw genre strings are cached, normalisation happens at report
        time, so changing the normalisation never needs a rescan.

  v1.1  Portable Edition (toolkit 1.1.0): the cache file location can be set
        with the environment variable GENRE_CACHE_FILE (default as before:
        next to this script). Needed in a container, where the script folder
        is read only or thrown away after every run.

        Normalisation: ID3v1 numeric references ("(17)", "17") are
        resolved to names; spelling variants that differ only in case or
        punctuation are merged ("Hip-Hop", "Hip Hop", "hip hop"), shown
        under their most frequent spelling; "HipHop" is merged into that
        too. Nothing else is merged on purpose: "Rap" and "Hip-Hop/Rap"
        stay their own entries.
        A file with several genres counts once for EACH of them.

USAGE:
    python genre_stats.py /archive/scenereleases            # top 20
    python genre_stats.py /archive/scenereleases --top 30
    python genre_stats.py /archive/scenereleases --rebuild  # ignore cache

    From archive_stats.py: genre_report_lines([dirs], top_n=20)

REQUIRES: mutagen (included in the Docker image of the toolkit).
"""

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

try:
    from mutagen.id3 import ID3, TCON
    GENRES = list(TCON.GENRES)
    HAVE_MUTAGEN = True
except ImportError:  # pragma: no cover
    ID3 = None
    GENRES = []
    HAVE_MUTAGEN = False

CACHE_FILE = os.environ.get("GENRE_CACHE_FILE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "genre_stats_cache.json")
CACHE_VERSION = 1

# Spelling variants that normalise to the same key but are not caught by
# the generic "lowercase, punctuation -> space" rule.
_ALIASES = {"hiphop": "hip hop", "rnb": "r b"}


# ---------------------------------------------------------------------------
# Reading the genre of ONE mp3 (header-only)
# ---------------------------------------------------------------------------

class _Unsupported(Exception):
    pass


def _synchsafe(b):
    return (b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | (b[3] & 0x7F)


def _decode_text_frame(data):
    if not data:
        return []
    enc, body = data[0], data[1:]
    try:
        if enc == 0:
            text = body.decode("latin-1")
        elif enc == 1:
            text = body.decode("utf-16")
        elif enc == 2:
            text = body.decode("utf-16-be")
        elif enc == 3:
            text = body.decode("utf-8")
        else:
            return []
    except UnicodeDecodeError:
        return []
    return [p.strip() for p in text.split("\x00") if p.strip()]


def _read_tcon_v2(f):
    """
    Raw strings of the TCON/TCO frame; [] if the tag has none; None if
    the file has no ID3v2 header. Reads headers only and seeks over every
    frame body that is not the genre frame. Raises _Unsupported for tag
    features this walker deliberately does not handle.
    """
    head = f.read(10)
    if len(head) < 10 or head[:3] != b"ID3":
        return None
    major, flags = head[3], head[5]
    if major not in (2, 3, 4):
        raise _Unsupported("version")
    if flags & 0x80:                       # unsynchronisation
        raise _Unsupported("unsync")
    if major == 2 and flags & 0x40:        # v2.2 compression
        raise _Unsupported("v2.2 compression")
    end = 10 + _synchsafe(head[6:10])
    pos = 10
    if major >= 3 and flags & 0x40:        # extended header
        ext = f.read(4)
        if len(ext) < 4:
            return []
        ext_size = int.from_bytes(ext, "big") if major == 3 else _synchsafe(ext) - 4
        f.seek(ext_size, 1)
        pos += 4 + ext_size

    id_len, hdr_len = (3, 6) if major == 2 else (4, 10)
    target = b"TCO" if major == 2 else b"TCON"
    while pos + hdr_len <= end:
        fh = f.read(hdr_len)
        if len(fh) < hdr_len or fh[0] == 0:        # padding / EOF
            break
        if major == 2:
            fsize = int.from_bytes(fh[3:6], "big")
        elif major == 3:
            fsize = int.from_bytes(fh[4:8], "big")
        else:
            fsize = _synchsafe(fh[4:8])
        if fsize <= 0 or pos + hdr_len + fsize > end:
            break                                   # corrupt, stop here
        if fh[:id_len] == target:
            if major == 3 and fh[9] & 0xE0:
                raise _Unsupported("frame flags")
            if major == 4 and fh[9] & 0x4F:
                raise _Unsupported("frame flags")
            return _decode_text_frame(f.read(fsize))
        f.seek(fsize, 1)                            # skip body WITHOUT reading it
        pos += hdr_len + fsize
    return []


def _mutagen_tcon(path):
    """Fallback for unusual tags: let mutagen parse the whole tag."""
    if not HAVE_MUTAGEN:
        return []
    try:
        out = []
        for fr in ID3(path).getall("TCON"):
            out.extend(str(t) for t in fr.text)
        return out
    except Exception:
        return []


_V1_REF = re.compile(r"^\((\d{1,3}|RX|CR)\)(.*)$")


def _resolve(raw_list):
    """'(17)', '17', '(17)Rock', 'Hip-Hop' -> display names."""
    out = []

    def add(name):
        if name and name.lower() not in (o.lower() for o in out):
            out.append(name)

    for raw in raw_list:
        s = raw.strip()
        while True:
            m = _V1_REF.match(s)
            if not m:
                break
            ref, s = m.group(1), m.group(2).strip()
            if ref == "RX":
                add("Remix")
            elif ref == "CR":
                add("Cover")
            elif int(ref) < len(GENRES):
                add(GENRES[int(ref)])
        if s:
            add(GENRES[int(s)] if s.isdigit() and int(s) < len(GENRES) else s)
    return out


def _read_v1(f):
    try:
        f.seek(-128, 2)
    except OSError:
        return []
    d = f.read(128)
    if len(d) == 128 and d[:3] == b"TAG" and d[127] < len(GENRES):
        return [GENRES[d[127]]]
    return []


def read_file_genres(path):
    """Genre names of one file ([] = no genre tag), None = unreadable."""
    try:
        with open(path, "rb") as f:
            try:
                raw = _read_tcon_v2(f)
            except _Unsupported:
                raw = _mutagen_tcon(path)
            genres = _resolve(raw or [])
            if not genres:
                genres = _read_v1(f)
            return genres
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Per-release scan + cache
# ---------------------------------------------------------------------------

def scan_release(release_path):
    raw = Counter()
    mp3 = tagged = unreadable = 0
    for root, _, files in os.walk(release_path):
        for fn in files:
            if not fn.lower().endswith(".mp3"):
                continue
            mp3 += 1
            g = read_file_genres(os.path.join(root, fn))
            if g is None:
                unreadable += 1
            elif g:
                tagged += 1
                for name in g:
                    raw[name] += 1
    return {"mp3": mp3, "tagged": tagged, "unreadable": unreadable, "genres": dict(raw)}


def _load_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("version") == CACHE_VERSION:
            return data.get("releases", {})
    except (OSError, ValueError):
        pass
    return {}


def _save_cache(path, releases):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": CACHE_VERSION, "releases": releases}, fh)
        os.replace(tmp, path)
    except OSError as e:
        print(f"  genre cache could not be written ({e}), next run rescans.")


def _norm_key(name):
    k = re.sub(r"[^0-9a-z]+", " ", name.lower()).strip()
    return _ALIASES.get(k.replace(" ", ""), _ALIASES.get(k, k))


def collect(dirs, cache_file=CACHE_FILE, rebuild=False, log=print):
    """Scans the release folders in `dirs` (cache-aware). Returns (releases, stats)."""
    cache = {} if rebuild else _load_cache(cache_file)
    result, scanned, t0 = {}, 0, time.time()
    todo = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if os.path.isdir(p):
                todo.append((f"{os.path.basename(d)}/{name}", p))

    for i, (key, p) in enumerate(todo, 1):
        try:
            mtime = int(os.stat(p).st_mtime)
        except OSError:
            continue
        hit = cache.get(key)
        if hit and hit.get("mtime") == mtime:
            result[key] = hit
            continue
        entry = scan_release(p)
        entry["mtime"] = mtime
        result[key] = entry
        scanned += 1
        if scanned % 500 == 0:
            log(f"  genre scan: {scanned} release(s) read so far ({i}/{len(todo)} checked, "
                f"{time.time() - t0:.0f}s)")

    if result != cache:
        _save_cache(cache_file, result)
    return result, {"releases": len(todo), "scanned": scanned,
                    "seconds": time.time() - t0}


def genre_report_lines(dirs, top_n=20, cache_file=CACHE_FILE, rebuild=False, log=print):
    """Report section as a list of lines (same style as archive_stats.py)."""
    lines = [f"SCENE RELEASES — TOP {top_n} GENRES (ID3 tags, per MP3 file)", "-" * 60]
    if not HAVE_MUTAGEN:
        lines += ["  mutagen is not installed, genre statistics skipped.", ""]
        return lines
    releases, st = collect(dirs, cache_file, rebuild, log)

    totals = Counter()
    spellings = defaultdict(Counter)
    mp3 = tagged = unreadable = 0
    for e in releases.values():
        mp3 += e["mp3"]
        tagged += e["tagged"]
        unreadable += e["unreadable"]
        for raw, n in e["genres"].items():
            k = _norm_key(raw)
            if not k:
                continue
            totals[k] += n
            spellings[k][raw] += n

    if not totals:
        lines += ["  (no genre tags found)", ""]
        return lines
    top = totals.most_common(top_n)
    biggest = top[0][1]
    for k, n in top:
        shown = spellings[k].most_common(1)[0][0]
        pct = 100.0 * n / tagged if tagged else 0.0
        lines.append(f"  {shown[:30]:30s} {n:7d} {pct:5.1f}%  {'█' * max(1, round(20 * n / biggest))}")
    lines.append("")
    lines.append(f"  MP3 files: {mp3}, with genre tag: {tagged} "
                 f"({100.0 * tagged / mp3 if mp3 else 0:.1f}%), "
                 f"without: {mp3 - tagged - unreadable}, unreadable: {unreadable}")
    lines.append(f"  Distinct genres after merging spellings: {len(totals)}. "
                 f"A file with several genres counts for each.")
    lines.append(f"  Scan: {st['scanned']} of {st['releases']} releases read this run "
                 f"({st['seconds']:.1f}s), the rest came from the cache.")
    lines.append("")
    return lines


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    top = 20
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
        args = [a for a in args if a != str(top)]
    print("\n".join(genre_report_lines(args, top_n=top, rebuild="--rebuild" in sys.argv)))
