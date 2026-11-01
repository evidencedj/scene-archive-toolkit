#!/usr/bin/env python3
"""
migrate_to_v3_layout.py  v1.0.0

Wandelt ein Archiv im alten Layout (Incoming Processor bis v2.x) in das v3 Layout um.

VERSIONSHISTORIE
  1.0.0  2026-11-01  Erste Fassung fuer das Toolkit. Standard ist ein Probelauf.

ALT (bis v2.x)                      NEU (ab v3.0)
  scenereleases/   echte Ordner  ->   scenereleases_srr/   echte Ordner
  nomatch/         echte Ordner  ->   scenereleases_nosrr/ echte Ordner
  nomatch/_invalid/*             ->   incomplete/
  (nichts)                       ->   scenereleases/       nur relative Symlinks

Ablauf (mit --apply):
  1. scenereleases_srr: ist der Ordner noch nicht da, wird scenereleases
     umbenannt (schnell, ein einziger Vorgang). Sonst werden die Ordner einzeln
     verschoben, Namenskonflikte werden gemeldet und uebersprungen.
  2. scenereleases_nosrr: ebenso aus nomatch.
  3. nomatch/_invalid/* wandert nach incomplete (Konflikte werden gemeldet).
  4. scenereleases wird neu angelegt und mit Symlinks gefuellt.
  Es wird nichts geloescht. Das Skript kann gefahrlos mehrfach laufen.

WICHTIG:
  - Vorher den Incoming Processor und alles andere stoppen, das im Archiv arbeitet.
  - Das Archiv muss auf einem lokalen Dateisystem liegen (Symlinks gehen nicht ueber SMB).
  - Zuerst ohne --apply starten und das Ergebnis lesen.

Aufruf:
  python3 migrate_to_v3_layout.py --archive /pfad/zum/archiv            # Probelauf
  python3 migrate_to_v3_layout.py --archive /pfad/zum/archiv --apply    # ausfuehren
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_scene_links as sl                       # noqa: E402

SCRIPT_VERSION = "1.0.0"


def subdirs(path):
    if not os.path.isdir(path):
        return []
    with os.scandir(path) as it:
        return sorted(e.name for e in it if e.is_dir(follow_symlinks=False))


def has_real_dirs(path):
    return any(not n.startswith("_") for n in subdirs(path))


def move_all(src, dst, apply, skip=(), label=""):
    """Verschiebt jeden Unterordner von src nach dst. Gibt (verschoben, Konflikte) zurueck."""
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
    ap = argparse.ArgumentParser(description="Archiv ins v3 Layout umbauen")
    ap.add_argument("--archive", default=os.environ.get("ARCHIVE_ROOT"), help="Archiv Wurzelordner")
    ap.add_argument("--apply", action="store_true", help="Aenderungen wirklich ausfuehren (sonst Probelauf)")
    a = ap.parse_args()
    root = a.archive
    if not root or not os.path.isdir(root):
        print("Archiv Wurzelordner fehlt oder existiert nicht (--archive oder ARCHIVE_ROOT).")
        return 2
    p = lambda n: os.path.join(root, n)
    print(f"migrate_to_v3_layout v{SCRIPT_VERSION} [{'APPLY' if a.apply else 'DRY RUN'}] {root}\n")

    # Sicherheit: Symlinks muessen hier funktionieren
    if a.apply:
        probe = os.path.join(root, ".symlink_probe")
        try:
            if os.path.lexists(probe):
                os.unlink(probe)
            os.symlink("x", probe)
            os.unlink(probe)
        except OSError as e:
            print(f"ABBRUCH: Auf diesem Dateisystem lassen sich keine Symlinks anlegen ({e}).")
            print("Das Archiv muss lokal liegen, nicht ueber SMB/CIFS eingebunden sein.")
            return 2

    errors = 0
    issues = []

    # 1. scenereleases -> scenereleases_srr
    old_real = [n for n in subdirs(p("scenereleases")) if not n.startswith("_")]
    if old_real:
        if not os.path.exists(p("scenereleases_srr")):
            print(f"1. scenereleases ({len(old_real)} Ordner) -> scenereleases_srr: Ordner wird umbenannt")
            if a.apply:
                os.rename(p("scenereleases"), p("scenereleases_srr"))
        else:
            m, c = move_all(p("scenereleases"), p("scenereleases_srr"), a.apply)
            print(f"1. scenereleases -> scenereleases_srr: {m} verschoben, {len(c)} Konflikte")
            issues += [f"scenereleases/{n} existiert schon in scenereleases_srr" for n in c]
    else:
        print("1. scenereleases: keine echten Ordner (nichts zu tun)")

    # 2. nomatch -> scenereleases_nosrr (ohne _invalid)
    old_nm = [n for n in subdirs(p("nomatch")) if n != "_invalid"]
    if old_nm:
        if not os.path.exists(p("scenereleases_nosrr")) and not os.path.isdir(p("nomatch") + "/_invalid"):
            print(f"2. nomatch ({len(old_nm)} Ordner) -> scenereleases_nosrr: Ordner wird umbenannt")
            if a.apply:
                os.rename(p("nomatch"), p("scenereleases_nosrr"))
        else:
            m, c = move_all(p("nomatch"), p("scenereleases_nosrr"), a.apply, skip=("_invalid",))
            print(f"2. nomatch -> scenereleases_nosrr: {m} verschoben, {len(c)} Konflikte")
            issues += [f"nomatch/{n} existiert schon in scenereleases_nosrr" for n in c]
    else:
        print("2. nomatch: keine Ordner (nichts zu tun)")

    # 3. nomatch/_invalid -> incomplete
    inv = p("nomatch/_invalid")
    if os.path.isdir(inv):
        m, c = move_all(inv, p("incomplete"), a.apply)
        print(f"3. nomatch/_invalid -> incomplete: {m} verschoben, {len(c)} Konflikte")
        issues += [f"nomatch/_invalid/{n} existiert schon in incomplete" for n in c]
    else:
        print("3. nomatch/_invalid: nicht vorhanden (nichts zu tun)")

    # 4. Symlinks
    print("\n4. Symlinks in scenereleases:")
    if a.apply:
        os.makedirs(p("scenereleases"), exist_ok=True)
        os.makedirs(p("scenereleases_srr"), exist_ok=True)
        os.makedirs(p("scenereleases_nosrr"), exist_ok=True)
    r = sl.sync(root, a.apply) if (a.apply or os.path.isdir(p("scenereleases_srr"))) else None
    if r is None:
        print("   (Probelauf: Links werden erst nach dem Umbenennen angelegt)")
    else:
        errors += r["errors"]
        print(f"   angelegt: {r['created']}  korrigiert: {r['fixed']}  entfernt: {r['removed']}  in Ordnung: {r['ok']}")
        if r["both"]:
            issues.append(f"{len(r['both'])} Name(n) in srr UND nosrr, srr gewinnt: " + ", ".join(r["both"][:5]))
        if r["real_in_links"]:
            issues.append(f"{len(r['real_in_links'])} echter Ordner noch in scenereleases: " + ", ".join(r["real_in_links"][:5]))

    print()
    if issues:
        print("ZU PRUEFEN:")
        for i in issues:
            print("  - " + i)
    if not a.apply:
        print("\nProbelauf: nichts wurde geaendert. Mit --apply ausfuehren.")
    else:
        print("\nFertig. Es wurde nichts geloescht. Danach den Incoming Processor wieder starten.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
