#!/usr/bin/env python3
"""
sync_scene_links.py  v1.0.0

Haelt den Ordner "scenereleases" (nur relative Symlinks) im Gleichklang mit den
beiden echten Ordnern "scenereleases_srr" und "scenereleases_nosrr".

VERSIONSHISTORIE
  1.0.0  2026-11-01  Erste Fassung fuer das Toolkit. Standard ist ein Probelauf,
                     erst mit --apply wird etwas geaendert.

Was geprueft wird:
  - fehlender Link              -> wird angelegt (../scenereleases_srr/<Name>)
  - Link mit falschem Ziel      -> wird korrigiert
  - Link ohne Ziel (haengend)   -> wird entfernt (nur der Link, nie ein Ordner)
  - echter Ordner in scenereleases -> nur gemeldet, nie angefasst
  Gibt es einen Namen in beiden echten Ordnern, gewinnt scenereleases_srr.
  Ordner, deren Name mit "_" beginnt, werden ignoriert.

Aufruf:
  python3 sync_scene_links.py --archive /pfad/zum/archiv            # Probelauf
  python3 sync_scene_links.py --archive /pfad/zum/archiv --apply    # ausfuehren
"""

import argparse
import os
import sys

SCRIPT_VERSION = "1.0.0"
SRR, NOSRR, LINKS = "scenereleases_srr", "scenereleases_nosrr", "scenereleases"


def real_dirs(path):
    """Namen der echten Unterordner (keine Links, keine "_" Ordner)."""
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
                # Ziel gibt es nicht mehr: nur den Link entfernen
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
    ap = argparse.ArgumentParser(description="Symlinks in scenereleases/ abgleichen")
    ap.add_argument("--archive", default=os.environ.get("ARCHIVE_ROOT"), help="Archiv Wurzelordner")
    ap.add_argument("--apply", action="store_true", help="Aenderungen wirklich ausfuehren (sonst Probelauf)")
    a = ap.parse_args()
    if not a.archive or not os.path.isdir(a.archive):
        print("Archiv Wurzelordner fehlt oder existiert nicht (--archive oder ARCHIVE_ROOT).")
        return 2
    print(f"sync_scene_links v{SCRIPT_VERSION} [{'APPLY' if a.apply else 'DRY RUN'}] {a.archive}")
    r = sync(a.archive, a.apply)
    print(f"\nangelegt: {r['created']}  korrigiert: {r['fixed']}  entfernt: {r['removed']}  "
          f"in Ordnung: {r['ok']}  Fehler: {r['errors']}")
    if r["both"]:
        print(f"HINWEIS: {len(r['both'])} Name(n) in srr UND nosrr (srr gewinnt): " + ", ".join(r["both"][:10]))
    if r["real_in_links"]:
        print(f"WARNUNG: {len(r['real_in_links'])} echter Ordner in scenereleases (nicht angefasst): "
              + ", ".join(r["real_in_links"][:10]))
        print("  -> migrate_to_v3_layout.py ausfuehren oder die Ordner von Hand verschieben.")
    if not a.apply:
        print("\nProbelauf: nichts wurde geaendert. Mit --apply ausfuehren.")
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
