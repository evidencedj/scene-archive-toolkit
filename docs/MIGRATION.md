# Migration from Incoming Processor 2.x to 3.x

Only needed for an archive that has been used with version 2.x so far. A fresh installation
starts directly with the v3 layout and does not need this page.

## What changed

| | Version 2.x | Version 3.x |
|---|---|---|
| Verified releases | `scenereleases/` (real folders) | `scenereleases_srr/` (real folders) |
| Releases without an srrDB match | `nomatch/` | `scenereleases_nosrr/` |
| Unusable releases | `nomatch/_invalid/` | `incomplete/` (the folder `_invalid` is gone) |
| `scenereleases/` | everything | symlinks to the two folders above only |
| Database | SQLite history (removed in 2.14) | none |
| Settings | edit the script | environment variables (`.env`) |

Other changes since 2.2, roughly: stage 1b (audio CRC search), better stage 3 (album tag and artist,
also FLAC), protection against wrong matches (correct SFV for the CRC check), handling of SMB quirks,
removal of usenet junk, Discord report, direct access to srrDB with a proxy only after a block. The
complete list is in the header of `processor/incoming_processor.py`.

## Requirement: local filesystem

The archive has to be where the processor runs, as a normal folder. A drive mounted over SMB/CIFS does
not work (no symlinks). In that case the processor refuses to start.

## Steps

1. **Back up.** At least a copy of `scenereleases` and `nomatch`, or a snapshot. The migration deletes
   nothing, but caution costs nothing.
2. **Stop everything** that works on the archive (old processor, cron jobs, sorting scripts).
3. **Get the toolkit** and build the processor:

   ```bash
   cd processor
   cp .env.example .env     # set ARCHIVE_PATH
   docker compose build
   ```

4. **Dry run of the migration** (changes nothing) and read the output:

   ```bash
   python3 ../tools/migrate_to_v3_layout.py --archive /path/to/archive
   ```

5. **Run the migration**:

   ```bash
   python3 ../tools/migrate_to_v3_layout.py --archive /path/to/archive --apply
   ```

   Afterwards there are `scenereleases_srr`, `scenereleases_nosrr` and `scenereleases` with symlinks.
   Under "TO CHECK" the script reports name conflicts. They are not overwritten but stay where they are
   and have to be decided by hand. The empty folder `nomatch` may be deleted afterwards.
6. **Dry run of the processor**:

   ```bash
   docker compose run --rm processor python incoming_processor.py --dry-run
   ```

7. **Real run** (`docker compose run --rm processor`) and set up cron again.
8. **Repair after manual changes**: if you move folders by hand, afterwards run
   `python3 tools/sync_scene_links.py --archive /path/to/archive --apply`.

## If something is wrong

- *"does not exist: the archive still has the old layout"*: the migration (step 5) is missing.
- *"contains a real folder"*: `scenereleases` still holds a real folder. Run the migration again
  or move the folder to `scenereleases_srr`, then `sync_scene_links.py --apply`.
- Error while creating symlinks: the archive is on a network drive. Run processor and migration
  where the folder is local.
