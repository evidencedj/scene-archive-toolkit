# Changelog

Das Toolkit folgt Semantic Versioning (Hauptversion.Nebenversion.Fehlerkorrektur).
Die Einzelkomponenten haben zusätzlich ihre eigene Versionshistorie in den Dateiköpfen.

## [1.1.0] 2026-11-01

Nachtpipeline ergänzt (ohne Cloud und Hetzner Anbindung).

- **Pipeline** (`pipeline/`): `scene_nightly.sh` 1.1.0 führt nacheinander Processor, Link Abgleich,
  optionalen Mirror, Statistik und Sortierer aus. Mit Sperre (`flock`), Statusanzeige (`--status`),
  `--only`, `--skip`, `--list`, `--dry-run`, Discord Zusammenfassung, optionalem Haken nach dem Lauf.
  Dazu `run_incoming_processor.sh` 2.0.0 und `wait_for_processor.sh` 2.0.0 für Hand Läufe.
  Einstellungen in `pipeline/pipeline.env`.
- **Werkzeuge**: `archive_stats.py` 2.6, `archive_sorter.py` 2.1 und `genre_stats.py` 1.1 sind
  über Umgebungsvariablen konfigurierbar und laufen im Processor Image.
- **Processor Image** (Dockerfile 1.1, Compose 1.1): Build aus dem Toolkit Wurzelordner, enthält
  `tools/`, neuer Ordner `processor/state` für den Genre Cache.

## [1.0.0] 2026-11-01

Erste Ausgabe als eigenständiges Paket.

Enthalten:
- **Incoming Processor 3.2** (`processor/`): Verarbeitung neuer Releases gegen srrDB in
  den Stufen 0, 1, 1b, 2 und 3, Sortierung in `scenereleases_srr`, `scenereleases_nosrr`,
  `incomplete`, `dupes` und `mp3s`, Symlink Sammlung `scenereleases`, optional Discord Bericht
  und ArchiveDB Reindex. Neu in 3.2: Konfiguration über Umgebungsvariablen, Option `--dry-run`,
  Docker Setup mit pyrescene, bereinigte Anleitung im Dateikopf.
- **ArchiveDB** (`archivedb/`, App 1.9, Indexer 1.6): Suchoberfläche über das Archiv mit
  Statistik, Genre Filter und NFO Anzeige. Neu: Quellordner und optionale Links (Storagebox,
  Windows Explorer) über `.env` einstellbar, Docker Compose ohne feste Pfade.
- **Werkzeuge** (`tools/`, 1.0.0): `migrate_to_v3_layout.py` (altes Layout nach v3, Probelauf
  als Standard) und `sync_scene_links.py` (Symlinks abgleichen und reparieren).

Nicht enthalten (folgt später): nächtliche Pipeline (`scene_nightly.sh`) mit Statistik,
Sortierer, Link Abgleich und Cloud Sync.
