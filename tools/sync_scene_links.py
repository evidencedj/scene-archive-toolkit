#!/usr/bin/env python3
"""
sync_scene_links.py  v1.0.0

Keeps the folder "scenereleases" (relative symlinks only) in sync with the
two real folders "scenereleases_srr" and "scenereleases_nosrr".

VERSION HISTORY
  1.0.0  2026-11-01  First version for the toolkit. Default is a dry run,
                     nothing is changed without --apply.
  1.1.0  2026-11-01  Output and comments translated to English.

What is checked:
  - missing link                -> created (../scenereleases_srr/<name>)
  - link with the wrong target  -> corrected
  - link without a target (dangling) -> removed (only the link, never a folder)
  - real folder inside scenereleases -> only reported, never touched
  If a name exists in both real folders, scenereleases_srr wins.
  Folders whose name starts with "_" are ignored.

Usage:
  python3 sync_scene_links.py --archive /path/to/archive            # dry run
  python3 sync_scene_links.py --archive /path/to/archive --apply    # execute
"""

import argparse
import os
import sys

SCRIPT_VERSION = "1.1.0"
SRR, NOSRR, LINKS = "scenereleases_srr", "scenereleases_nosrr", "scenereleases"


def real_dirs(path):
    """Names of the real subfolders (no links, no "_" folders)."""
    out = set()
    if not os.path.isdir(path):
        return out
    with os.scandir(path) as it:
        for e in it:
            if e.name.startswith("_") or e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=False):
                out.add(e.name)
    return out


def sync(archive, apply):
    srr_dir = os.path.join(archive, SRR)
    nosrr_dir = os.path.join(archive, NOSRR)
    link_dir = os.path.join(archive, LINKS)
    res = {"created": 0, "fixed": 0, "removed": 0, "ok": 0, "real_in_links": [], "both": [], "errors": 0}

    srr = real_dirs(srr_dir)
    nosrr = real_dirs(nosrr_dir)
    res["both"] = sorted(srr & nosrr)
    want = {n: os.path.join("..", SRR, n) for n in srr}
    for n in nosrr - srr:
        want[n] = os.path.join("..", NOSRR, n)

    if apply:
        os.makedirs(link_dir, exist_ok=True)
    existing = {}
    if os.path.isdir(link_dir):
        with os.scandir(link_dir) as it:
            for e in it:
                existing[e.name] = e

    for name, e in sorted(existing.items()):
        if name.startswith("_") or name.startswith("."):
            continue
        if e.is_symlink():
            if name not in want:
                # target is gone: remove only the link
                print(f"  REMOVE dangling link: {name}")
                if apply:
                    try:
                        os.unlink(e.path)
                    except OSError as ex:
                        print(f"    ERROR: {ex}")
                        res["errors"] += 1
                        continue
                res["removed"] += 1
            elif os.readlink(e.path) != want[name]:
                print(f"  FIX link target: {name}  ({os.readlink(e.path)} -> {want[name]})")
                if apply:
                    try:
                        os.unlink(e.path)
                        os.symlink(want[name], e.path)
                    except OSError as ex:
                        print(f"    ERROR: {ex}")
                        res["errors"] += 1
                        continue
                res["fixed"] += 1
            else:
                res["ok"] += 1
        elif e.is_dir(follow_symlinks=False):
            res["real_in_links"].append(name)

    for name in sorted(want):
        if name in existing:
            continue
        print(f"  CREATE link: {name} -> {want[name]}")
        if apply:
            try:
                os.symlink(want[name], os.path.join(link_dir, name))
            except OSError as ex:
                print(f"    ERROR: {ex}")
                res["errors"] += 1
                continue
        res["created"] += 1
    return res


def main():
    ap = argparse.ArgumentParser(description="Sync the symlinks in scenereleases/")
    ap.add_argument("--archive", default=os.environ.get("ARCHIVE_ROOT"), help="archive root folder")
    ap.add_argument("--apply", action="store_true", help="really apply the changes (otherwise dry run)")
    a = ap.parse_args()
    if not a.archive or not os.path.isdir(a.archive):
        print("Archive root folder is missing or does not exist (--archive or ARCHIVE_ROOT).")
        return 2
    print(f"sync_scene_links v{SCRIPT_VERSION} [{'APPLY' if a.apply else 'DRY RUN'}] {a.archive}")
    r = sync(a.archive, a.apply)
    print(f"\ncreated: {r['created']}  fixed: {r['fixed']}  removed: {r['removed']}  "
          f"ok: {r['ok']}  errors: {r['errors']}")
    if r["both"]:
        print(f"NOTE: {len(r['both'])} name(s) in srr AND nosrr (srr wins): " + ", ".join(r["both"][:10]))
    if r["real_in_links"]:
        print(f"WARNING: {len(r['real_in_links'])} real folder(s) in scenereleases (not touched): "
              + ", ".join(r["real_in_links"][:10]))
        print("  -> run migrate_to_v3_layout.py or move the folders by hand.")
    if not a.apply:
        print("\nDry run: nothing was changed. Run with --apply to execute.")
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
