# Changelog

The toolkit follows Semantic Versioning (major.minor.patch). The individual components also keep
their own version history in the file headers.

## [1.2.0] 2026-11-01

Everything is in English now, so the toolkit can be shared with other people.

- **Language:** all documentation, comments, script output, notifications and the Discord report are
  English. `docs/UPGRADE_FROM_2.2.md` is now `docs/MIGRATION.md` and is marked as optional (a fresh
  installation does not need it).
- **README:** the quick start is written for a fresh installation and includes the nightly pipeline.
- **Component versions:** Incoming Processor 3.3 (Discord report and layout hints in English, the layout
  check now names the correct script `migrate_to_v3_layout.py`), `scene_nightly.sh` 1.2.0,
  `run_incoming_processor.sh` and `wait_for_processor.sh` 2.1.0, `sync_scene_links.py` and
  `migrate_to_v3_layout.py` 1.1.0.
- **Note for existing users:** the hook script (`AFTER_HOOK`) now receives the result as `OK`,
  `WITH WARNINGS` or `ERROR` (before: `OK`, `MIT HINWEISEN`, `FEHLER`).

## [1.1.0] 2026-11-01

Nightly pipeline added (without cloud and Hetzner sync).

- **Pipeline** (`pipeline/`): `scene_nightly.sh` runs processor, link sync, optional mirror,
  statistics and sorter one after the other. With lock (`flock`), status display (`--status`),
  `--only`, `--skip`, `--list`, `--dry-run`, Discord summary and an optional hook after the run.
  Plus `run_incoming_processor.sh` and `wait_for_processor.sh` for manual runs.
  Settings in `pipeline/pipeline.env`.
- **Tools:** `archive_stats.py` 2.6, `archive_sorter.py` 2.1 and `genre_stats.py` 1.1 can be configured
  through environment variables and run inside the processor image.
- **Processor image** (Dockerfile 1.1, Compose 1.1): built from the toolkit root, contains `tools/`,
  new folder `processor/state` for the genre cache.

## [1.0.0] 2026-11-01

First release as a standalone package.

Included:
- **Incoming Processor 3.2** (`processor/`): processing of new releases against srrDB in stages 0, 1,
  1b, 2 and 3, sorting into `scenereleases_srr`, `scenereleases_nosrr`, `incomplete`, `dupes` and
  `mp3s`, symlink collection `scenereleases`, optional Discord report and ArchiveDB reindex. New in 3.2:
  configuration through environment variables, option `--dry-run`, Docker setup with pyrescene,
  cleaned up setup notes in the file header.
- **ArchiveDB** (`archivedb/`, app 1.9, indexer 1.6): search UI over the archive with statistics,
  genre filter and NFO display. New: source folders and optional links (Storage Box, Windows Explorer)
  configurable through `.env`, Docker Compose without fixed paths.
- **Tools** (`tools/`, 1.0.0): `migrate_to_v3_layout.py` (old layout to v3, dry run by default) and
  `sync_scene_links.py` (sync and repair symlinks).
