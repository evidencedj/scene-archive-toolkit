# Incoming Processor

Processes every folder in `incoming/` in stages:

| Stage | Method |
|---|---|
| 0 | exact folder name against srrDB |
| 1 | search by file names (NFO, SFV, M3U) |
| 1b | audio CRC lookup when several candidates match |
| 2 | fuzzy search by folder name (needs a year) |
| 3 | ID3 and NFO data (album, year, group) |

On a match: check metadata, download and unpack the SRR if needed, verify the audio CRCs, rename the
release and move it to `scenereleases_srr` (with a symlink in `scenereleases`). Without a match:
clean scene releases go to `scenereleases_nosrr`, broken ones to `incomplete`, duplicates to `dupes`,
loose audio files to `mp3s`.

## Setup

```bash
cp .env.example .env     # set ARCHIVE_PATH
docker compose build
docker compose run --rm processor python incoming_processor.py --dry-run   # preview
docker compose run --rm processor                                          # real run
```

The settings are explained in `.env.example`. Logs are written to `LOG_PATH`
(`incoming_processor_*.log` and `incoming_results_*.log`).

## Without Docker

```bash
pip install requests mutagen pyrescene
# Python 3.12: in rescene/utility.py replace the line  locale.format('%d', number, True)
# with  format(number, ',')  (see the Dockerfile)
export ARCHIVE_ROOT=/path/to/archive INCOMING_DIR=/path/to/archive/incoming \
       SRR_PY=$(which srr.py) LOG_DIR=./logs LOCKFILE=/tmp/incoming_processor.lock
python3 incoming_processor.py --dry-run
```

## Notes

- The archive must be local (symlinks). Old layout: see `../docs/MIGRATION.md`.
- Only one run per archive at a time (lock file `.incoming_processor.lock` in the archive folder).
- `Ctrl+C` or SIGTERM ends the run cleanly after the current release.
- If srrDB blocks your IP (HTTP 403, 429, 503) the run aborts. With `VPN_PROXY_URL` set, it switches
  to the proxy instead.
