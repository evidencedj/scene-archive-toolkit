# Umstieg vom Incoming Processor 2.2 auf 3.2

Diese Anleitung gilt für ein Archiv, das bisher mit Version 2.2 (oder einer anderen 2.x Version) lief.

## Was sich geändert hat

| | Version 2.x | Version 3.x |
|---|---|---|
| Geprüfte Releases | `scenereleases/` (echte Ordner) | `scenereleases_srr/` (echte Ordner) |
| Releases ohne srrDB Treffer | `nomatch/` | `scenereleases_nosrr/` |
| Unbrauchbare Releases | `nomatch/_invalid/` | `incomplete/` (der Ordner `_invalid` entfällt) |
| `scenereleases/` | alles | nur Symlinks auf die beiden Ordner oben |
| Datenbank | SQLite Verlauf (ab 2.14 entfernt) | keine |
| Einstellungen | im Skript bearbeiten | Umgebungsvariablen (`.env`) |

Weitere Neuerungen seit 2.2, grob zusammengefasst: Stage 1b (Audio CRC Suche), bessere Stage 3
(Album Tag und Interpret, auch FLAC), Schutz vor falschen Zuordnungen (richtige SFV für die CRC Prüfung),
Behandlung von SMB Eigenheiten, Entfernen von Usenet Müll, Discord Bericht, Zugriff auf srrDB direkt mit
Proxy erst bei einer Sperre. Die vollständige Liste steht im Dateikopf von `processor/incoming_processor.py`.

## Voraussetzung: lokales Dateisystem

Das Archiv muss dort liegen, wo der Processor läuft, als normaler Ordner. Ein per SMB/CIFS eingebundenes
Laufwerk geht nicht (keine Symlinks). Der Processor verweigert in diesem Fall den Start.

## Schritte

1. **Sicherung.** Mindestens eine Kopie von `scenereleases` und `nomatch` oder ein Snapshot. Die Migration
   löscht nichts, aber Vorsicht kostet nichts.
2. **Alles stoppen**, was im Archiv arbeitet (alter Processor, Cron Jobs, Sortierskripte).
3. **Toolkit holen** und den Processor bauen:

   ```bash
   cd processor
   cp .env.example .env     # ARCHIVE_PATH setzen
   docker compose build
   ```

4. **Probelauf der Migration** (ändert nichts) und Ausgabe lesen:

   ```bash
   python3 ../tools/migrate_to_v3_layout.py --archive /pfad/zum/archiv
   ```

5. **Migration ausführen**:

   ```bash
   python3 ../tools/migrate_to_v3_layout.py --archive /pfad/zum/archiv --apply
   ```

   Danach gibt es `scenereleases_srr`, `scenereleases_nosrr` und `scenereleases` mit Symlinks.
   Unter "ZU PRÜFEN" meldet das Skript Namenskonflikte. Diese werden nicht überschrieben, sondern
   bleiben liegen und müssen von Hand entschieden werden. Der leere Ordner `nomatch` darf danach gelöscht werden.
6. **Probelauf des Processors**:

   ```bash
   docker compose run --rm processor python incoming_processor.py --dry-run
   ```

7. **Echter Lauf** (`docker compose run --rm processor`) und Cron neu einrichten.
8. **Reparatur nach manuellen Eingriffen**: Wer Ordner von Hand verschiebt, startet danach
   `python3 tools/sync_scene_links.py --archive /pfad/zum/archiv --apply`.

## Wenn etwas nicht stimmt

- *"does not exist: the archive still has the old layout"*: Migration (Schritt 5) fehlt.
- *"contains a real folder"*: In `scenereleases` liegt noch ein echter Ordner. Migration erneut ausführen
  oder den Ordner nach `scenereleases_srr` verschieben, dann `sync_scene_links.py --apply`.
- Fehler beim Anlegen von Symlinks: Das Archiv liegt auf einem Netzlaufwerk. Processor und Migration dort
  ausführen, wo der Ordner lokal ist.
