#!/usr/bin/env python3
"""
migrate_to_v3_layout.py  v1.0.0

Converts an archive in the old layout (Incoming Processor up to v2.x) to the v3 layout.
Only needed if you come from an older setup. A fresh installation does not need it.

VERSION HISTORY
  1.0.0  2026-11-01  First version for the toolkit. Default is a dry run.
  1.1.0  2026-11-01  Output and comments translated to English.

OLD (up to v2.x)                    NEW (from v3.0)
  scenereleases/   real folders  ->   scenereleases_srr/   real folders
  nomatch/         real folders  ->   scenereleases_nosrr/ real folders
  nomatch/_invalid/*             ->   incomplete/
  (nothing)                      ->   scenereleases/       relative symlinks only

Procedure (with --apply):
  1. scenereleases_srr: if the folder does not exist yet, scenereleases is
     renamed (fast, a single operation). Otherwise the folders are moved one
     by one, name conflicts are reported and skipped.
  2. scenereleases_nosrr: the same from nomatch.
  3. nomatch/_invalid/* moves to incomplete (conflicts are reported).
  4. scenereleases is created again and filled with symlinks.
  Nothing is deleted. The script can safely run several times.

IMPORTANT:
  - Stop the Incoming Processor and everything else that works on the archive first.
  - The archive must be on a local filesystem (symlinks do not work over SMB).
  - Run without --apply first and read the result.

Usage:
  python3 migrate_to_v3_layout.py --archive /path/to/archive            # dry run
  python3 migrate_to_v3_layout.py --archive /path/to/archive --apply    # execute
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_scene_links as sl                       # noqa: E402

SCRIPT_VERSION = "1.1.0"


def subdirs(path):
    if not os.path.isdir(path):
        return []
    with os.scandir(path) as it:
        return sorted(e.name for e in it if e.is_dir(follow_symlinks=False))


def has_real_dirs(path):
    return any(not n.startswith("_") for n in subdirs(path))


def move_all(src, dst, apply, skip=(), label=""):
    """Moves every subfolder from src to dst. Returns (moved, conflicts)."""
    moved, conflicts = 0, []
    if apply:
        os.makedirs(dst, exist_ok=True)
    for n in subdirs(src):
        if n in skip:
            continue
        t = os.path.join(dst, n)
        if os.path.lexists(t):
            conflicts.append(n)
            continue
        if apply:
            os.rename(os.path.join(src, n), t)
        moved += 1
    return moved, conflicts


def main():
    ap = argparse.ArgumentParser(description="Convert an archive to the v3 layout")
    ap.add_argument("--archive", default=os.environ.get("ARCHIVE_ROOT"), help="archive root folder")
    ap.add_argument("--apply", action="store_true", help="really apply the changes (otherwise dry run)")
    a = ap.parse_args()
    root = a.archive
    if not root or not os.path.isdir(root):
        print("Archive root folder is missing or does not exist (--archive or ARCHIVE_ROOT).")
        return 2
    p = lambda n: os.path.join(root, n)
    print(f"migrate_to_v3_layout v{SCRIPT_VERSION} [{'APPLY' if a.apply else 'DRY RUN'}] {root}\n")

    # Safety: symlinks have to work here
    if a.apply:
        probe = os.path.join(root, ".symlink_probe")
        try:
            if os.path.lexists(probe):
                os.unlink(probe)
            os.symlink("x", probe)
            os.unlink(probe)
        except OSError as e:
            print(f"ABORT: symlinks cannot be created on this filesystem ({e}).")
            print("The archive must be local, not mounted over SMB/CIFS.")
            return 2

    errors = 0
    issues = []

    # 1. scenereleases -> scenereleases_srr
    old_real = [n for n in subdirs(p("scenereleases")) if not n.startswith("_")]
    if old_real:
        if not os.path.exists(p("scenereleases_srr")):
            print(f"1. scenereleases ({len(old_real)} folders) -> scenereleases_srr: folder is renamed")
            if a.apply:
                os.rename(p("scenereleases"), p("scenereleases_srr"))
        else:
            m, c = move_all(p("scenereleases"), p("scenereleases_srr"), a.apply)
            print(f"1. scenereleases -> scenereleases_srr: {m} moved, {len(c)} conflicts")
            issues += [f"scenereleases/{n} already exists in scenereleases_srr" for n in c]
    else:
        print("1. scenereleases: no real folders (nothing to do)")

    # 2. nomatch -> scenereleases_nosrr (ohne _invalid)
    old_nm = [n for n in subdirs(p("nomatch")) if n != "_invalid"]
    if old_nm:
        if not os.path.exists(p("scenereleases_nosrr")) and not os.path.isdir(p("nomatch") + "/_invalid"):
            print(f"2. nomatch ({len(old_nm)} folders) -> scenereleases_nosrr: folder is renamed")
            if a.apply:
                os.rename(p("nomatch"), p("scenereleases_nosrr"))
        else:
            m, c = move_all(p("nomatch"), p("scenereleases_nosrr"), a.apply, skip=("_invalid",))
            print(f"2. nomatch -> scenereleases_nosrr: {m} moved, {len(c)} conflicts")
            issues += [f"nomatch/{n} already exists in scenereleases_nosrr" for n in c]
    else:
        print("2. nomatch: no folders (nothing to do)")

    # 3. nomatch/_invalid -> incomplete
    inv = p("nomatch/_invalid")
    if os.path.isdir(inv):
        m, c = move_all(inv, p("incomplete"), a.apply)
        print(f"3. nomatch/_invalid -> incomplete: {m} moved, {len(c)} conflicts")
        issues += [f"nomatch/_invalid/{n} already exists in incomplete" for n in c]
    else:
        print("3. nomatch/_invalid: not present (nothing to do)")

    # 4. Symlinks
    print("\n4. Symlinks in scenereleases:")
    if a.apply:
        os.makedirs(p("scenereleases"), exist_ok=True)
        os.makedirs(p("scenereleases_srr"), exist_ok=True)
        os.makedirs(p("scenereleases_nosrr"), exist_ok=True)
    r = sl.sync(root, a.apply) if (a.apply or os.path.isdir(p("scenereleases_srr"))) else None
    if r is None:
        print("   (dry run: links are only created after the rename)")
    else:
        errors += r["errors"]
        print(f"   created: {r['created']}  fixed: {r['fixed']}  removed: {r['removed']}  ok: {r['ok']}")
        if r["both"]:
            issues.append(f"{len(r['both'])} name(s) in srr AND nosrr, srr wins: " + ", ".join(r["both"][:5]))
        if r["real_in_links"]:
            issues.append(f"{len(r['real_in_links'])} real folder(s) still in scenereleases: " + ", ".join(r["real_in_links"][:5]))

    print()
    if issues:
        print("TO CHECK:")
        for i in issues:
            print("  - " + i)
    if not a.apply:
        print("\nDry run: nothing was changed. Run with --apply to execute.")
    else:
        print("\nDone. Nothing was deleted. Now start the Incoming Processor again.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
