# Nachtpipeline

`scene_nightly.sh` startet alle Schritte nacheinander. Jeder Schritt wartet auf den vorherigen,
es gibt keine festen Uhrzeiten pro Job mehr.

| Schritt | Was passiert |
|---|---|
| `processor` | `incoming/` verarbeiten (wird übersprungen, wenn leer) |
| `links` | Symlinks in `scenereleases/` abgleichen (`tools/sync_scene_links.py`) |
| `mirror` | optional, eigenes Skript (`MIRROR_SCRIPT`), sonst übersprungen |
| `stats` | `ARCHIVE_STATS.txt` neu schreiben (`tools/archive_stats.py`) |
| `sorter` | `_sorted_/` neu aufbauen (`tools/archive_sorter.py`) |

Nicht enthalten: Cloud und Hetzner Synchronisation.

## Einrichtung (auf dem Rechner, auf dem das Archiv liegt)

1. Processor einrichten, siehe `processor/README.md`, und einmal `docker compose build`.
2. `cp pipeline/pipeline.env.example pipeline/pipeline.env` und `ARCHIVE` eintragen
   (derselbe Ordner wie `ARCHIVE_PATH` in `processor/.env`).
3. Probelauf: `pipeline/scene_nightly.sh --list` und `pipeline/scene_nightly.sh --dry-run`.
4. Echter Lauf: `pipeline/scene_nightly.sh`.
5. Zeitplan per Cron, zum Beispiel jede Nacht um 02:00:
   `0 2 * * * /srv/scene-archive-toolkit/pipeline/scene_nightly.sh >/dev/null 2>&1`

Voraussetzungen: Linux mit bash, `flock`, `curl`, Docker mit Compose. Das Archiv muss ein lokales
Dateisystem sein (Symlinks).

## Aufruf

```
scene_nightly.sh                      alle Schritte
scene_nightly.sh --only stats,sorter  nur diese Schritte
scene_nightly.sh --skip mirror        alles außer diesen
scene_nightly.sh --list               Schritte und Einstellungen
scene_nightly.sh --dry-run            nichts ausführen
scene_nightly.sh --status             läuft gerade etwas, letzter Lauf
```

Exit Code: 0 ok, 1 mit Hinweisen, 2 mit Fehlern, 3 nicht gestartet.

## Hand Lauf des Processors

`run_incoming_processor.sh` startet den Processor von Hand. Läuft die Pipeline, bricht er ab; läuft er
selbst, wartet die Pipeline bis zu `LOCK_WAIT_MIN` Minuten. `wait_for_processor.sh [Minuten]` wartet auf
das Ende eines laufenden Processors und beendet ihn danach sauber per SIGTERM.

## Mirror und Haken

- `MIRROR_SCRIPT`: beliebiges Skript, Rückgabe 0 ok, 2 ok mit Hinweis, sonst Fehler.
- `AFTER_HOOK` (Standard `pipeline/after_pipeline.sh`, falls vorhanden): bekommt das Ergebnis
  (`OK`, `MIT HINWEISEN`, `FEHLER`) als Argument.

Status und Protokolle liegen in `pipeline/state/` (nicht im Git).
