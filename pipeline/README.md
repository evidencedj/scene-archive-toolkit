# Nightly pipeline

`scene_nightly.sh` starts all steps one after the other. Every step waits for the previous one,
there are no fixed times per job.

| Step | What happens |
|---|---|
| `processor` | process `incoming/` (skipped if empty) |
| `links` | sync the symlinks in `scenereleases/` (`tools/sync_scene_links.py`) |
| `mirror` | optional, your own script (`MIRROR_SCRIPT`), skipped otherwise |
| `stats` | rewrite `ARCHIVE_STATS.txt` (`tools/archive_stats.py`) |
| `sorter` | rebuild `_sorted_/` (`tools/archive_sorter.py`) |

Not included: cloud and Hetzner synchronisation.

## Setup (on the machine that holds the archive)

1. Set up the processor, see `processor/README.md`, and run `docker compose build` once.
2. `cp pipeline/pipeline.env.example pipeline/pipeline.env` and set `ARCHIVE`
   (the same folder as `ARCHIVE_PATH` in `processor/.env`).
3. Try it: `pipeline/scene_nightly.sh --list` and `pipeline/scene_nightly.sh --dry-run`.
4. Real run: `pipeline/scene_nightly.sh`.
5. Schedule it with cron, for example every night at 02:00:
   `0 2 * * * /srv/scene-archive-toolkit/pipeline/scene_nightly.sh >/dev/null 2>&1`

Requirements: Linux with bash, `flock`, `curl`, Docker with Compose. The archive must be on a
local filesystem (symlinks).

## Usage

```
scene_nightly.sh                      all steps
scene_nightly.sh --only stats,sorter  only these steps
scene_nightly.sh --skip mirror        everything except these
scene_nightly.sh --list               steps and settings
scene_nightly.sh --dry-run            execute nothing
scene_nightly.sh --status             is something running, last run
```

Exit code: 0 ok, 1 with warnings, 2 with errors, 3 not started.

## Manual processor run

`run_incoming_processor.sh` starts the processor by hand. If the pipeline is running it aborts; if it
is running itself, the pipeline waits up to `LOCK_WAIT_MIN` minutes. `wait_for_processor.sh [minutes]`
waits for a running processor to finish and then stops it cleanly with SIGTERM.

## Mirror and hook

- `MIRROR_SCRIPT`: any script, return code 0 ok, 2 ok with a warning, anything else is an error.
- `AFTER_HOOK` (default `pipeline/after_pipeline.sh`, if it exists): receives the result
  (`OK`, `WITH WARNINGS`, `ERROR`) as an argument.

State and logs are in `pipeline/state/` (not in Git).
