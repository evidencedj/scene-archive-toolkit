#!/usr/bin/env python3
"""
archive_sorter.py  v2.1

VERSION HISTORY (bump on every change so you always know what's current):
  v1.0  Initial symlink sorter (By_Year / By_Group / By_Artist / By_Format).
  v1.1  Portable edition: setup docstring, config block.
  v2.0  BREAKING: points at the consolidated lowercase folder layout
        (scenereleases/, _sorted_/). FLAC promoted to its own format
        category, with a fix so artists like "Roberta Flack" are not
        misclassified. Format-tag scan now goes right-to-left so the
        real Scene tag next to the year wins over title words like
        "Demos EP". Wider, paren-tolerant year detection (accepts
        pre-1970 years, "(1995)", and tags glued to a year like
        VLS2004) with Scene "unknown year" placeholders (199x, xxxx)
        reported separately from genuine gaps. VA-detection fixed to
        avoid matching "Vanilla Ice". Proper pruning: symlinks whose
        classification changed (not just deleted releases) are now
        removed and empty category folders cleaned up. DRY_RUN flag
        added.
  v2.1  Portable Edition (toolkit 1.1.0): SCENE_DIR, SORTED_DIR and DRY_RUN
        can be set via environment variables (ARCHIVE_ROOT sets both
        defaults), the startup banner shows the real version. Behaviour
        unchanged.

Creates symlinks in _sorted_/ for all scenereleases.

Structure:
  _sorted_/
    By_Year/1996/Release-Name  -> ../../scenereleases/Release-Name
    By_Group/CMS/Release-Name  -> ...
    By_Artist/A/Release-Name   -> ...
    By_Format/VLS/Release-Name -> ...

Run periodically after incoming_processor to keep sorted view up to date.
Safe to run multiple times — removes stale symlinks and adds new ones.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SETUP — edit these two paths to match your system:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SCENE_DIR  — folder containing your verified scenereleases
  SORTED_DIR — folder where sorted symlinks will be created
               (will be created automatically if it doesn't exist)

  Examples:
    Linux/Unraid:  SCENE_DIR = "/srv/archive/scenereleases"
    Windows (WSL): SCENE_DIR = "/mnt/c/Music/scenereleases"
    macOS:         SCENE_DIR = "/Volumes/Archive/scenereleases"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import unicodedata

# ---------------------------------------------------------------------------
# ★ CONFIGURATION — adjust these two paths to your setup ★
# ---------------------------------------------------------------------------

_ROOT      = os.environ.get("ARCHIVE_ROOT", "/archive")
SCENE_DIR  = os.environ.get("SCENE_DIR", os.path.join(_ROOT, "scenereleases"))   # ← your scenereleases folder
SORTED_DIR = os.environ.get("SORTED_DIR", os.path.join(_ROOT, "_sorted_"))       # ← where symlinks will be created
DRY_RUN    = os.environ.get("DRY_RUN", "0").strip().lower() in ("1", "true", "yes", "on")   # ← True: preview only
SCRIPT_VERSION = "2.1"

# ---------------------------------------------------------------------------
# Format tag grouping
# ---------------------------------------------------------------------------

FORMAT_MAP = {
    # VLS
    "VLS": "VLS",
    "(VLS)": "VLS",
    "PROMO VLS": "VLS",
    "(PROMO VLS)": "VLS",
    "FULL VLS": "VLS",
    "(FULL VLS)": "VLS",
    "VLS)": "VLS",
    "VINYL SINGLE": "VLS",
    "PROMO-VLS": "VLS",
    "TAPE SINGLE": "VLS",

    # EP
    "EP": "EP",
    "(EP)": "EP",
    "VINYL EP": "EP",

    # CD
    "CDS": "CD",
    "CDM": "CD",
    "(CDS)": "CD",
    "(CDM)": "CD",
    "PROMO CDS": "CD",
    "(PROMO CDS)": "CD",
    "2CD": "CD",
    "3CD": "CD",
    "12CD": "CD",
    "CD": "CD",
    "CDR": "CD",
    "CD RETAIL": "Retail",
    "EXPLICIT RETAIL": "Retail",
    "CD VERSION": "CD",
    "CD SINGLE": "CD",
    "FULL CDS": "CD",
    "PROMO CDM": "CD",
    "UK-CDM": "CD",
    "UK CDS": "CD",
    "BONUS CD": "CD",
    "PROMO-CDS": "CD",

    # LP
    "LP": "LP",
    "(LP)": "LP",
    "2LP": "LP",
    "3LP": "LP",
    "INSTRUMENTAL LP": "LP",

    # Vinyl
    "VINYL": "Vinyl",
    "(VINYL)": "Vinyl",
    "12 INCH": "Vinyl",
    "(12 INCH)": "Vinyl",
    "12INCH": "Vinyl",
    "7INCH": "Vinyl",
    "7 INCH": "Vinyl",
    "LIMITED EDITION VINYL": "Reissue",

    # Web
    "WEB": "Web",
    "16BIT": "Web",

    # FLAC — own category (overrides Web/CD)
    "FLAC": "FLAC",
    "WEB FLAC": "FLAC",
    "CD FLAC": "FLAC",
    "CD-FLAC": "FLAC",
    "VINYL FLAC": "FLAC",

    # Tape
    "TAPE": "Tape",
    "(TAPE)": "Tape",
    "MIXTAPE": "Tape",
    "TAPE RIP": "Tape",

    # Promo
    "PROMO": "Promo",
    "(PROMO)": "Promo",
    "ADVANCE": "Promo",
    "(ADVANCE)": "Promo",
    "ALBUM SAMPLER": "Promo",
    "SAMPLER": "Promo",
    "WHITE LABEL": "Promo",
    "ADVANCE PROMO": "Promo",

    # Retail
    "RETAIL": "Retail",
    "(RETAIL)": "Retail",
    "FULL RETAIL": "Retail",

    # Bootleg
    "BOOTLEG": "Bootleg",
    "(BOOTLEG)": "Bootleg",

    # Single
    "SINGLE": "Single",

    # Video
    "DVDRIP": "Video",
    "DVDA": "Video",
    "SVCD": "Video",
    "XVID": "Video",
    "DVD": "Video",
    "DVD REMIXES": "Video",

    # Live
    "LIVE": "Live",

    # Reissue
    "REISSUE": "Reissue",
    "CD REISSUE": "Reissue",
    "LTD.ED.": "Reissue",
    "LIMITED EDITION": "Reissue",
    "REMASTERED": "Reissue",
    "RE-RELEASE": "Reissue",
    "RE-RIP": "Reissue",

    # OST
    "OST": "OST",

    # Remix
    "REMIX": "Remix",
    "REMIXES": "Remix",
    "REMIX VLS": "Remix",
    "REMIX CDS": "Remix",

    # Album
    "INSTRUMENTALS": "Album",
    "INSTRUMENTAL": "Album",
}

# ---------------------------------------------------------------------------
# Parsers
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
    199x, 19xx, 200x, 20xx or xxxx. Reported separately from
    genuine parsing gaps in the QC list.
    """
    c = seg.strip().strip("()").strip()
    if re.fullmatch(r'(?i)(19|20)[0-9x]{2}', c) and "x" in c.lower():
        return True
    if re.fullmatch(r'(?i)x{4}', c):
        return True
    return False


def has_year_placeholder(folder_name):
    """True if the name uses a Scene 'unknown year' placeholder."""
    return any(_is_year_placeholder(p)
              for p in folder_name.replace("_", " ").split("-"))


def parse_folder(folder_name):
    """Extract artist, year, group, and format from a folder name."""
    s = folder_name.replace("_", " ")
    parts = [p.strip() for p in s.split("-") if p.strip()]

    artist = parts[0] if parts else "Unknown"

    # Find year — checks each segment via _year_from_segment, which
    # also handles years in stray parentheses (1995) and years glued
    # directly to a format tag with no separator (VLS2004, 3LP2000)
    year = None
    year_idx = None
    for i, p in enumerate(parts):
        y = _year_from_segment(p)
        if y:
            year = y
            year_idx = i
            break

    # Group = last segment after year (preserves _INT suffix)
    group = None
    if year_idx is not None and year_idx < len(parts) - 1:
        group = parts[-1].replace(" ", "_")

    # Format detection — FLAC wins over everything else
    # Check dash-separated segments only to avoid false positives like "Roberta_Flack"
    dash_parts = [p.strip().upper() for p in folder_name.replace("_", " ").split("-")]
    flac_tokens = {"FLAC", "WEB FLAC", "CD FLAC", "VINYL FLAC", "16BIT WEB FLAC", "24BIT WEB FLAC"}
    if any(p in flac_tokens or p.endswith(" FLAC") or p.startswith("FLAC ") for p in dash_parts):
        return artist, year, group, "FLAC"

    fmt = "Album"

    # Check bracket tags anywhere in the name first
    bracket_search = folder_name.replace("_", " ").upper()
    bracket_hits = re.findall(r'\(([^)]+)\)', bracket_search)
    for hit in bracket_hits:
        hit = hit.strip()
        if hit in FORMAT_MAP:
            fmt = FORMAT_MAP[hit]
            break
        for word in hit.split():
            if word in FORMAT_MAP:
                fmt = FORMAT_MAP[word]
                break
        if fmt != "Album":
            break

    # Then check middle segments between artist and year
    if fmt == "Album" and year_idx is not None and year_idx > 1:
        # scan right to left: the real format tag sits next to the year,
        # title words like "Demos EP" further left must not win
        for segment in reversed(parts[1:year_idx]):
            hit = _find_format_tag(segment)
            if hit:
                fmt = hit
                break

    return artist, year, group, fmt


def _find_format_tag(segment):
    """
    Find the longest FORMAT_MAP phrase inside a segment.
    Whole-segment matches win, then sub-phrases from longest to
    shortest sliding over the words, e.g. "JAPAN RETAIL" → Retail,
    "SOMETHING PROMO VLS" → VLS via "PROMO VLS".
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


def artist_letter(artist):
    """
    Return first letter category for artist.
    VA is only detected as a standalone token so that artists like
    Vanilla Ice or Vast Aire correctly land under V.
    Accented letters are folded to their ASCII base (É → E).
    """
    if not artist:
        return "0-9"
    first_token = artist.split()[0].upper().rstrip(".")
    if first_token in {"VA", "V.A", "VARIOUS"}:
        return "VA"
    # fold accents: É → E, Ø → O etc.
    folded = unicodedata.normalize("NFKD", artist[0])
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    first = (folded or artist[0]).upper()
    if first.isdigit():
        return "0-9"
    if "A" <= first <= "Z":
        return first
    return "0-9"


# ---------------------------------------------------------------------------
# Symlink management
# ---------------------------------------------------------------------------

_DIR_CACHE = set()  # avoids repeated makedirs syscalls on network mounts


def ensure_dir(path):
    if path in _DIR_CACHE:
        return
    if not DRY_RUN:
        os.makedirs(path, exist_ok=True)
    _DIR_CACHE.add(path)


def make_symlink(target_abs, link_path):
    """Create a relative symlink from link_path to target_abs."""
    link_dir   = os.path.dirname(link_path)
    rel_target = os.path.relpath(target_abs, link_dir)

    if os.path.islink(link_path):
        if os.readlink(link_path) == rel_target:
            return "exists"
        if not DRY_RUN:
            os.remove(link_path)

    if not DRY_RUN and os.path.exists(link_path):
        return "skipped"

    if not DRY_RUN:
        os.symlink(rel_target, link_path)
    return "created"


def prune_symlinks(sorted_root, expected_links):
    """
    Remove every symlink under sorted_root that is not in the expected
    set for this run. This covers both cases in one pass:
      1. the target release no longer exists (classic stale link)
      2. the classification changed, e.g. a release moved from Web to
         FLAC after a parser fix, leaving an outdated link behind
    Empty category directories are removed afterwards.
    """
    removed = 0
    for root, dirs, files in os.walk(sorted_root):
        for name in dirs + files:
            full = os.path.join(root, name)
            if os.path.islink(full) and full not in expected_links:
                if not DRY_RUN:
                    os.remove(full)
                removed += 1

    # remove now-empty directories, deepest first
    if not DRY_RUN:
        for root, dirs, files in os.walk(sorted_root, topdown=False):
            if root == sorted_root:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass
    return removed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    mode = " [DRY RUN]" if DRY_RUN else ""
    print(f"archive_sorter v{SCRIPT_VERSION} (portable){mode}")
    print(f"Source:  {SCENE_DIR}")
    print(f"Sorted:  {SORTED_DIR}")
    print("")

    if not os.path.isdir(SCENE_DIR):
        print(f"ERROR: SCENE_DIR not found: {SCENE_DIR}")
        print("       Please edit the CONFIGURATION section at the top of this script.")
        return

    # scandir is a single directory read incl. type info,
    # noticeably faster than listdir + isdir on network mounts
    with os.scandir(SCENE_DIR) as it:
        releases = sorted(e.name for e in it if e.is_dir())

    print(f"Releases to sort: {len(releases)}")
    print("")

    counters = {"created": 0, "exists": 0, "skipped": 0}
    expected_links = set()
    unparsed = []            # genuine parsing gaps, for the QC report
    placeholder_only = []    # Scene "unknown year" releases (199x, xxxx, ...)

    for folder in releases:
        target = os.path.join(SCENE_DIR, folder)
        artist, year, group, fmt = parse_folder(folder)
        letter = artist_letter(artist)

        if not year and has_year_placeholder(folder):
            placeholder_only.append(folder)
        elif not year or not group:
            unparsed.append((folder, "no year" if not year else "no group"))

        link_dirs = [os.path.join(SORTED_DIR, "By_Artist", letter),
                     os.path.join(SORTED_DIR, "By_Format", fmt)]
        if year:
            link_dirs.append(os.path.join(SORTED_DIR, "By_Year", year))
        if group:
            link_dirs.append(os.path.join(SORTED_DIR, "By_Group", group.upper()))

        for d in link_dirs:
            ensure_dir(d)
            link_path = os.path.join(d, folder)
            counters[make_symlink(target, link_path)] += 1
            expected_links.add(link_path)

    # Prune everything that should no longer exist:
    # dead targets AND links whose classification changed
    removed = prune_symlinks(SORTED_DIR, expected_links)

    # QC report for releases the parser could not fully classify.
    # Scene year placeholders go into a separate file since those are
    # not parsing gaps — the release group itself never recorded a
    # real year, so nothing was ever there to extract.
    if unparsed:
        report_path = os.path.join(SORTED_DIR, "_needs_review.txt")
        print(f"Releases with incomplete parse: {len(unparsed)}"
              f" (list: {report_path})")
        if not DRY_RUN:
            with open(report_path, "w", encoding="utf-8") as f:
                for name, reason in unparsed:
                    f.write(f"{reason:10s} {name}\n")

    if placeholder_only:
        placeholder_path = os.path.join(SORTED_DIR, "_year_unknown_by_group.txt")
        print(f"Releases with Scene year placeholder (199x, xxxx, ...): "
              f"{len(placeholder_only)} (list: {placeholder_path})")
        if not DRY_RUN:
            with open(placeholder_path, "w", encoding="utf-8") as f:
                for name in sorted(placeholder_only):
                    f.write(f"{name}\n")

    print("=====================================")
    print(f"  Symlinks created:  {counters['created']}")
    print(f"  Already existed:   {counters['exists']}")
    print(f"  Stale removed:     {removed}")
    print("=====================================")
    print("")

    print("By_Format distribution:")
    fmt_dir_root = os.path.join(SORTED_DIR, "By_Format")
    if os.path.isdir(fmt_dir_root):
        for fmt_name in sorted(os.listdir(fmt_dir_root)):
            fmt_path = os.path.join(fmt_dir_root, fmt_name)
            count = len(os.listdir(fmt_path))
            print(f"  {fmt_name:20s} {count:5d}")

    print("")
    print("By_Year distribution (first/last 5):")
    year_dir_root = os.path.join(SORTED_DIR, "By_Year")
    if os.path.isdir(year_dir_root):
        years = sorted(os.listdir(year_dir_root))
        if len(years) > 10:
            sample = years[:5] + ["..."] + years[-5:]
        else:
            sample = years
        for y in sample:
            if y == "...":
                print("  ...")
                continue
            yp = os.path.join(year_dir_root, y)
            print(f"  {y}  {len(os.listdir(yp)):5d} releases")


if __name__ == "__main__":
    main()