#!/usr/bin/env python3
"""
archive_stats.py  v2.6

VERSION HISTORY (bump on every change so you always know what's current):
  v1.0  Initial stats report (counts, format/year/group distribution).
  v1.1  Portable edition: setup docstring, config block.
  v1.2  Chronological timeline section, NEEDS REVIEW QC section for
        releases missing a detectable year or group.
  v2.0  BREAKING: OUTPUT_DIRS points at the consolidated lowercase
        folder layout (scenereleases/, incomplete/, nomatch/,
        nomatch/_invalid/). Year and format detection now share the
        exact same logic as archive_sorter.py (right-to-left tag
        scan, paren-tolerant and pre-1970 year detection, FLAC as
        its own category). Scene "unknown year" placeholders (199x,
        xxxx) reported separately from genuine parsing gaps. Nested
        "_"-prefixed control folders (e.g. nomatch/_invalid) are no
        longer double-counted as releases. Size scan uses recursive
        scandir instead of walk+getsize for roughly half the syscalls
        on network mounts.
  v2.1  BUGFIX: extract_group() required a 2-12 character group tag,
        so a real, valid, srrDB-confirmed single-letter Scene group
        (e.g. "-a", "-E", "-i") was never recognized and every such
        release was wrongly flagged under "NEEDS REVIEW — no group
        detected". Minimum length is now 1.
  v2.2  When the folder name itself has no year, the first MP3's ID3
        year tag is now tried as a fallback (confirmed via a real
        case: 7L_and_Esoteric-Speaking_Real_Words_EP-(CD)-DSP has no
        year in its folder name but a clean "1999" in its ID3 tag).
        This is the rip/tagging date, not necessarily the original
        street date, so it's kept out of the main year-detection
        results and reported in its own separate "YEAR FROM ID3 TAG"
        section instead — transparent about where the year actually
        came from, rather than silently blending it in as if it had
        been parsed from the folder name.
  v2.3  BUGFIX: the v2.2 ID3 fallback only ever read the ID3v2 TDRC
        frame, so it found nothing for older rips that only ever got
        an ID3v1 tag (no ID3v2 at all) — confirmed in practice: real
        releases with a clean ID3v1 year, including the very
        7L_and_Esoteric example v2.2 was built for, still showed up
        under "no year" with zero entries in the new ID3 section.
        Added a raw ID3v1 reader (last 128 bytes of the file, no
        mutagen dependency) as a second fallback when ID3v2 has
        nothing, so both tag generations are covered now.
  v2.4  NEW SECTION "TOP 20 GENRES" from the ID3 genre tags of the MP3
        files, implemented in the separate module genre_stats.py (must
        sit in the same folder as this script, needs only Python 3, no
        mutagen). It only reads the small ID3 header of each MP3 and
        keeps a per-release cache (genre_stats_cache.json next to this
        script), so only the first run is slow and later nightly runs
        read just the releases that are new or changed. Controlled by
        GENRE_STATS, GENRE_DIRS and GENRE_TOP_N in the configuration
        block. If genre_stats.py is missing or fails, the rest of the
        report is still written, with one line saying why.
        OUTPUT_DIRS follows the folder layout of incoming_processor.py
        v2.33: "nomatch" is now "scenereleases_nosrr", and
        "nomatch/_invalid" is gone (those releases go to incomplete).
        Entries are listed in the same order as the processor's report:
        scenereleases, scenereleases_nosrr, dupes, incomplete, mp3s.
        Nothing else in the report was changed.
  v2.5  NEW FOLDER LAYOUT of incoming_processor.py v3.0: scenereleases_srr
        and scenereleases_nosrr hold the real folders, scenereleases holds
        only symlinks to both. RELEASES BY STATUS now lists srr and nosrr
        separately and counts the link folder in an extra line below the
        TOTAL (it is NOT added to the total, that would count every release
        twice). A check line compares the number of links with srr + nosrr.
        The detailed statistics (formats, years, groups, genres, size) still
        run over scenereleases, i.e. over all releases of both folders, via
        the links. scan_dir() now follows symlinks at the top level (before,
        links were skipped and the folder looked empty).
  v2.6  Portable Edition (toolkit 1.1.0): ARCHIVE_ROOT, STATS_FILE, GENRE_STATS
        and GENRE_TOP_N can be set via environment variables (defaults are the
        old values, behaviour unchanged). genre_stats.py is imported from the
        folder of this script, so the tools folder must stay together.

Generates ARCHIVE_STATS.txt in the archive root with current statistics.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SETUP — edit these paths to match your system:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ARCHIVE_ROOT — root folder of your archive, containing
                 scenereleases/, incomplete/ etc.
  STATS_FILE   — where the stats text file will be written
                 (defaults to ARCHIVE_ROOT/ARCHIVE_STATS.txt)

  Examples:
    Linux/Unraid:  ARCHIVE_ROOT = "/srv/archive"
    Windows (WSL): ARCHIVE_ROOT = "/mnt/c/Music/Archive"
    macOS:         ARCHIVE_ROOT = "/Volumes/Archive"

  OUTPUT_DIRS — maps subfolder names to display labels.
                The key is the actual folder name on disk,
                the value is the label shown in the report.

                If your folders have different names, just
                change the keys to match. Example:

                  "MyVerifiedReleases": "Scene Releases (verified)",
                  "incomplete":         "incomplete Scene Releases",

                Folders that don't exist on disk are silently
                skipped, so unused entries cause no errors.

                The "scenereleases" folder (first entry) is also
                used for the detailed format/year/group stats.
                If you rename it, update the key in OUTPUT_DIRS
                AND update the variable scene_path further down
                in the main() function to match.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import sys
import datetime
from collections import Counter

# ---------------------------------------------------------------------------
# ★ CONFIGURATION — adjust these to your setup ★
# ---------------------------------------------------------------------------

ARCHIVE_ROOT = os.environ.get("ARCHIVE_ROOT", "/archive")                      # ← your archive root
STATS_FILE   = os.environ.get("STATS_FILE", os.path.join(ARCHIVE_ROOT, "ARCHIVE_STATS.txt"))  # ← output file

# Subfolders to count — edit labels or remove entries as needed
OUTPUT_DIRS = {
    "scenereleases_srr":   "Scene Releases (verified, srrDB)",
    "scenereleases_nosrr": "Scene Releases (no srrDB match)",
    "dupes":               "dupes",
    "incomplete":          "incomplete Releases",
    "mp3s":                "mp3s (untagged)",
}

# v2.5: folder with symlinks to scenereleases_srr + scenereleases_nosrr.
# Used for the detailed statistics and shown once below the TOTAL.
LINK_DIR = "scenereleases"

# Genre statistics (v2.4): which folders are scanned for ID3 genres and how
# many genres are listed. GENRE_STATS = False switches the section off.
# Add "scenereleases_nosrr" to GENRE_DIRS to count those releases too.
GENRE_STATS = os.environ.get("GENRE_STATS", "1").strip().lower() in ("1", "true", "yes", "on")
GENRE_DIRS  = ["scenereleases"]
GENRE_TOP_N = int(os.environ.get("GENRE_TOP_N", "20"))

# ---------------------------------------------------------------------------
# Format tag grouping
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

MEDIA_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".ape"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MIN_YEAR, MAX_YEAR = 1900, 2035  # widened so vintage jazz/soul releases (e.g. 1958) are found


def _year_from_segment(seg):
    """
    Checks a single dash-separated segment for a year.
    Handles three cases: a plain 4-digit segment, a year wrapped in
    stray parentheses (even if the closing paren landed in a
    different dash segment), and a year glued directly to a format
    tag with no separator (VLS2004, 3LP2000). The no-space
    requirement on the glued case prevents grabbing a year out of a
    multi-word title fragment like "The 1997".
    """
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


def _is_year_placeholder(seg):
    """
    True for Scene-convention 'unknown year' placeholders such as
    199x, 19xx, 200x, 20xx or xxxx. These mean the release group
    itself did not know the exact year, so no real year can ever
    be extracted. Reported separately from genuine parsing gaps.
    """
    c = seg.strip().strip("()").strip()
    if re.fullmatch(r'(?i)(19|20)[0-9x]{2}', c) and "x" in c.lower():
        return True
    if re.fullmatch(r'(?i)x{4}', c):
        return True
    return False


def extract_year(s):
    """
    Segment-based year detection, identical to archive_sorter:
    only complete dash segments count, so a title like
    "The_1997-1998_Demos" does not hijack the year of a 2013 release.
    """
    for p in s.replace("_", " ").split("-"):
        y = _year_from_segment(p)
        if y:
            return y
    return None


def has_year_placeholder(s):
    """True if the name uses a Scene 'unknown year' placeholder."""
    return any(_is_year_placeholder(p) for p in s.replace("_", " ").split("-"))


def extract_group(s):
    # Real Scene groups can be a single letter (e.g. "-a", "-E", "-i")
    # — rare, but confirmed valid and srrDB-verified in practice, so
    # the minimum length here is 1, not 2.
    m = re.search(r'-([A-Za-z0-9_]{1,12})$', s)
    return m.group(1).upper() if m else None


def _id3v1_year(path):
    """
    Raw ID3v1 year read, entirely independent of mutagen. ID3v1 is a
    fixed-format tag in the last 128 bytes of the file: 3-byte "TAG"
    marker, then Title(30) Artist(30) Album(30) Year(4) ... — many
    older Scene rips only ever got an ID3v1 tag, never ID3v2, so
    mutagen's ID3()/TDRC lookup alone finds nothing for them even
    though a perfectly good year is sitting right there.
    """
    try:
        with open(path, "rb") as f:
            f.seek(-128, 2)
            tag = f.read(128)
        if tag[:3] != b"TAG":
            return None
        year = tag[93:97].decode("latin-1", errors="ignore").strip()
        return year if re.match(r'^\d{4}$', year) else None
    except Exception:
        return None


def id3_fallback_year(folder_path):
    """
    Reads the Year field from the first MP3's ID3 tag as a fallback
    when the folder name itself has no detectable year — this is
    the rip/tagging date the group or ripper recorded, not
    necessarily the original street date, but far better than
    nothing for sorting/chronology purposes. Tries ID3v2 (TDRC)
    first, then falls back to a raw ID3v1 read (see _id3v1_year) for
    older rips that only ever got an ID3v1 tag. Never raises; returns
    None on any failure (no MP3s, no mutagen installed, no/invalid
    tag at all, etc.) so a missing year here is always a hint, never
    a hard requirement.
    """
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
            if re.match(r'^\d{4}$', year):
                return year
        except Exception:
            pass
        return _id3v1_year(path)
    except Exception:
        return None


def _find_format_tag(segment):
    """
    Find the longest FORMAT_MAP phrase inside a segment.
    Whole-segment matches win, then sub-phrases from longest to
    shortest sliding over the words. Mirrors archive_sorter v2.0
    so both tools always report identical format numbers.
    """
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
    """Format detection identical to archive_sorter v2.0."""
    # FLAC wins over everything else. Dash segments only, so that
    # artists like Roberta Flack never trigger a false positive.
    dash_parts = [p.strip().upper() for p in folder_name.replace("_", " ").split("-")]
    if any(p == "FLAC" or p.endswith(" FLAC") or p.startswith("FLAC ") for p in dash_parts):
        return "FLAC"

    # Bracket tags anywhere in the name
    bracket_search = folder_name.replace("_", " ").upper()
    for hit in re.findall(r'\(([^)]+)\)', bracket_search):
        hit = hit.strip()
        if hit in FORMAT_MAP:
            return FORMAT_MAP[hit]
        for word in hit.split():
            if word in FORMAT_MAP:
                return FORMAT_MAP[word]

    # Middle segments between artist and year
    parts = [p.strip() for p in folder_name.replace("_", " ").split("-") if p.strip()]
    year_idx = None
    for i, p in enumerate(parts):
        if re.match(r'^\d{4}$', p) and 1970 <= int(p) <= 2030:
            year_idx = i
            break

    if year_idx is not None and year_idx > 1:
        # scan right to left: the real format tag sits next to the year,
        # title words like "Demos EP" further left must not win
        for segment in reversed(parts[1:year_idx]):
            hit = _find_format_tag(segment)
            if hit:
                return hit

    return "Album"


def _scan_tree(path):
    """
    Recursive scandir walk. Directory entries carry their stat info,
    so this needs one syscall per file instead of two, which roughly
    halves the runtime on network mounts like CIFS or NFS.
    Returns (media_files, total_size).
    """
    media_files = 0
    total_size  = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        m, s = _scan_tree(entry.path)
                        media_files += m
                        total_size  += s
                    elif entry.is_file(follow_symlinks=False):
                        total_size += entry.stat(follow_symlinks=False).st_size
                        if os.path.splitext(entry.name)[1].lower() in MEDIA_EXTENSIONS:
                            media_files += 1
                except OSError:
                    pass
    except OSError:
        pass
    return media_files, total_size


def scan_dir(path):
    """Count releases, media files and total size."""
    releases    = 0
    media_files = 0
    total_size  = 0
    with os.scandir(path) as it:
        for entry in it:
            if not entry.is_dir(follow_symlinks=True):  # v2.5: scenereleases holds links
                continue
            releases += 1
            m, s = _scan_tree(entry.path)
            media_files += m
            total_size  += s
    return releases, media_files, total_size


def human_size(size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not os.path.isdir(ARCHIVE_ROOT):
        print(f"ERROR: ARCHIVE_ROOT not found: {ARCHIVE_ROOT}")
        print("       Please edit the CONFIGURATION section at the top of this script.")
        return

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    lines.append("=" * 60)
    lines.append("  SCENE MUSIC ARCHIVE — STATISTICS")
    lines.append(f"  Generated: {now}")
    lines.append("=" * 60)
    lines.append("")

    # Release counts per directory
    lines.append("RELEASES BY STATUS")
    lines.append("-" * 60)
    total_releases = 0
    for dir_name, label in OUTPUT_DIRS.items():
        path = os.path.join(ARCHIVE_ROOT, dir_name)
        if not os.path.isdir(path):
            continue
        count = sum(1 for e in os.listdir(path)
                    if os.path.isdir(os.path.join(path, e))
                    and not e.startswith("_"))  # skip nested control dirs like _invalid
        total_releases += count
        lines.append(f"  {label:40s} {count:6d}")
    lines.append("-" * 60)
    lines.append(f"  {'TOTAL':40s} {total_releases:6d}")
    link_path = os.path.join(ARCHIVE_ROOT, LINK_DIR)
    if os.path.isdir(link_path):
        link_count = sum(1 for e in os.listdir(link_path)
                         if os.path.isdir(os.path.join(link_path, e))
                         and not e.startswith("_"))
        srr_nosrr = sum(
            sum(1 for e in os.listdir(os.path.join(ARCHIVE_ROOT, d))
                if os.path.isdir(os.path.join(ARCHIVE_ROOT, d, e))
                and not e.startswith("_"))
            for d in ("scenereleases_srr", "scenereleases_nosrr")
            if os.path.isdir(os.path.join(ARCHIVE_ROOT, d)))
        lines.append(f"  {'Scene Releases (all, via links)':40s} {link_count:6d}"
                     "   (not part of TOTAL)")
        if link_count != srr_nosrr:
            lines.append(f"  WARNING: {link_count} links but {srr_nosrr} releases in "
                         "srr + nosrr, run sync_scene_links.py")
    lines.append("")

    # scenereleases detailed stats
    scene_path = os.path.join(ARCHIVE_ROOT, "scenereleases")
    if os.path.isdir(scene_path):
        scene_folders = [
            e for e in os.listdir(scene_path)
            if os.path.isdir(os.path.join(scene_path, e))
        ]

        # Format distribution
        fmt_counter = Counter()
        for f in scene_folders:
            fmt_counter[detect_format(f)] += 1

        lines.append("SCENE RELEASES — BY FORMAT")
        lines.append("-" * 60)
        for fmt, count in sorted(fmt_counter.items(), key=lambda x: -x[1]):
            lines.append(f"  {fmt:30s} {count:6d}")
        lines.append("")

        # Year distribution
        year_counter = Counter()
        for f in scene_folders:
            y = extract_year(f)
            if y:
                year_counter[y] += 1

        lines.append("SCENE RELEASES — TOP 15 YEARS")
        lines.append("-" * 60)
        for year, count in sorted(year_counter.items(), key=lambda x: -x[1])[:15]:
            bar = "█" * (count // 10)
            lines.append(f"  {year}  {count:5d}  {bar}")
        lines.append("")

        # Chronological timeline over all years, bars scaled to the peak
        if year_counter:
            lines.append("SCENE RELEASES — TIMELINE")
            lines.append("-" * 60)
            peak = max(year_counter.values())
            scale = max(peak / 40, 1)  # widest bar = 40 chars
            for year in sorted(year_counter):
                count = year_counter[year]
                bar = "█" * max(1, int(count / scale))
                lines.append(f"  {year}  {count:5d}  {bar}")
            lines.append("")

        # Group distribution (top 25)
        group_counter = Counter()
        for f in scene_folders:
            g = extract_group(f)
            if g:
                group_counter[g] += 1

        lines.append("SCENE RELEASES — TOP 25 GROUPS")
        lines.append("-" * 60)
        for group, count in group_counter.most_common(25):
            bar = "█" * (count // 5)
            lines.append(f"  {group:20s} {count:5d}  {bar}")
        lines.append("")

        # Genres from the ID3 tags of the MP3 files (v2.4). Never allowed
        # to cost the rest of the report: any problem ends up as one line.
        if GENRE_STATS:
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import genre_stats
                lines.extend(genre_stats.genre_report_lines(
                    [os.path.join(ARCHIVE_ROOT, d) for d in GENRE_DIRS],
                    top_n=GENRE_TOP_N))
            except Exception as e:
                lines.append(f"GENRE STATISTICS skipped: {type(e).__name__}: {e}")
                lines.append("")

        # QC: releases without a detectable year or group.
        # Scene "unknown year" placeholders (199x, xxxx, ...) are
        # split out separately since those are not parsing gaps —
        # the release group itself never recorded a real year.
        # If the folder name itself has no year, the first MP3's
        # ID3 tag is tried as a fallback before giving up — this is
        # the rip/tagging date, not necessarily the real street date,
        # so releases resolved this way get their own transparency
        # section instead of silently blending into folder-name hits.
        placeholder_only = [f for f in scene_folders
                            if not extract_year(f) and has_year_placeholder(f)]

        id3_year_cache = {}

        def _year_via_id3(name):
            if name not in id3_year_cache:
                id3_year_cache[name] = id3_fallback_year(os.path.join(scene_path, name))
            return id3_year_cache[name]

        id3_resolved = [f for f in scene_folders
                        if not extract_year(f) and not has_year_placeholder(f)
                        and _year_via_id3(f)]
        unparsed = [f for f in scene_folders
                    if (not extract_year(f) and not has_year_placeholder(f)
                        and not _year_via_id3(f))
                    or not extract_group(f)]

        if unparsed:
            lines.append("NEEDS REVIEW — no year or group detected")
            lines.append("-" * 60)
            for name in sorted(unparsed)[:30]:
                reason = []
                if (not extract_year(name) and not has_year_placeholder(name)
                        and not _year_via_id3(name)):
                    reason.append("no year")
                if not extract_group(name):
                    reason.append("no group")
                lines.append(f"  {'/'.join(reason):18s} {name}")
            if len(unparsed) > 30:
                lines.append(f"  ... and {len(unparsed) - 30} more")
            lines.append(f"  TOTAL: {len(unparsed)}")
            lines.append("")

        if id3_resolved:
            lines.append("YEAR FROM ID3 TAG — not in folder name, taken from the "
                         "rip's own ID3 year (may not be the original street date)")
            lines.append("-" * 60)
            for name in sorted(id3_resolved)[:30]:
                lines.append(f"  {_year_via_id3(name):6s} {name}")
            if len(id3_resolved) > 30:
                lines.append(f"  ... and {len(id3_resolved) - 30} more")
            lines.append(f"  TOTAL: {len(id3_resolved)}")
            lines.append("")

        if placeholder_only:
            lines.append("SCENE YEAR PLACEHOLDER — year unknown by release group (199x, xxxx, ...)")
            lines.append("-" * 60)
            for name in sorted(placeholder_only)[:30]:
                lines.append(f"  {name}")
            if len(placeholder_only) > 30:
                lines.append(f"  ... and {len(placeholder_only) - 30} more")
            lines.append(f"  TOTAL: {len(placeholder_only)}")
            lines.append("")

    # File & size stats
    lines.append("SCENE RELEASES — FILES & SIZE")
    lines.append("-" * 60)
    if os.path.isdir(scene_path):
        releases, media_files, total_size = scan_dir(scene_path)
        lines.append(f"  Releases:        {releases:8d}")
        lines.append(f"  Media files:     {media_files:8d}")
        lines.append(f"  Total size:      {human_size(total_size):>12s}")
    lines.append("")

    lines.append("=" * 60)

    report = "\n".join(lines)
    print(report)

    with open(STATS_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nSaved to: {STATS_FILE}")


if __name__ == "__main__":
    main()