# Changelog

Das Toolkit folgt Semantic Versioning (Hauptversion.Nebenversion.Fehlerkorrektur).
Die Einzelkomponenten haben zusätzlich ihre eigene Versionshistorie in den Dateiköpfen.

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
