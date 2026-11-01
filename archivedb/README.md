# ArchiveDB: Scene Archive Browser

A lean, read-only web frontend over your scene release archive. Search by artist, title, year,
group or format, click a result, and look at the files of the release folder, in the style of srrDB.

## Data source

ArchiveDB only reads and changes nothing. It indexes two folders below your archive root
(`ARCHIVE_PATH`): `scenereleases_srr` (releases with an srrDB match) and `scenereleases_nosrr`
(clean releases without an srrDB match). The folder `scenereleases` with the symlinks is deliberately
not read, so no release appears twice. In the search, the filter "Source" separates the two groups.

The archive must be reachable as a directory for the container (a local path or a mounted network
drive, read only is enough).

## NFO display like the classic DOS viewer

NFOs are read correctly as CP437 (the old DOS code page that produces the ASCII art frames) instead
of wrongly as Latin-1. This fixes most garbled frames and bars. A single carriage return character
(`\r` without `\n`), which some elaborate NFOs use for overlaid art elements, is removed while reading
instead of being treated as a line break, which would otherwise create an unwanted extra line.

The font "DejaVu Sans Mono" is shipped as a real, self-hosted web font
(`static/fonts/DejaVuSansMono.ttf`), with "Lucida Console" as a fallback where it is installed.
An earlier attempt with "Perfect DOS VGA 437" caused misalignment in longer ASCII art frames, because
TTF conversions of such bitmap fonts found on the net are often not truly monospaced. DejaVu Sans
Mono was measured directly (every character exactly the same width) and is a reputable, openly
licensed font. Because it is shipped with the app instead of relying on a system installation, every
device, Android included, gets the same reliable rendering.

**Important:** to give NFOs that were indexed earlier the correct CP437 encoding, reindex once:

```bash
docker exec archivedb python3 /app/app/indexer.py
```

## Structure

- **SQLite + FTS5** as the database, a single file at `/data/archive.db`
- **FastAPI** backend (`app/main.py`)
- **Jinja2 templates**, rendered server side, responsive for desktop (1440p) and smartphone
- **indexer.py** scans `scenereleases_srr` and `scenereleases_nosrr` below `ARCHIVE_ROOT` and fills
  the database; it runs once automatically at container start and can be triggered again at any time

## Getting started

1. Create the configuration and set `ARCHIVE_PATH` to your archive root:

   ```bash
   cd archivedb
   cp .env.example .env
   nano .env
   ```

2. Build and start:

   ```bash
   docker compose up -d --build
   ```

3. Open in a browser: `http://<docker-host-IP>:8000`

The first start indexes everything once, which can take a few minutes for large archives (a pure
filesystem scan). Meanwhile the page does not answer yet (error 502 behind a proxy), which is normal.
Progress: `docker logs --tail 30 -f archivedb`.

## Reindex manually

After larger changes to the archive, without restarting the container:

```bash
docker exec archivedb python3 /app/app/indexer.py
```

Or via the built-in HTTP route (does the same):

```bash
curl -X POST http://localhost:8000/reindex
```

## Automatic updates

The Incoming Processor can trigger a reindex itself after every run. To do so set `ARCHIVEDB_URL` in
the processor configuration, for example `http://archivedb:8000`, as long as both containers run in the
same Docker network. Alternatively with cron: `curl -X POST http://localhost:8000/reindex`

## Limits of the current version

- Read only, no delete or move actions from the web frontend
- The artist/title split is a heuristic over the scene folder name; occasionally single format or
  year words still end up in the title field. This does not hurt the search but is cosmetically not perfect
- By default only `scenereleases_srr` and `scenereleases_nosrr` are indexed

## Statistics and genre

- `/stats` shows formats, years, timeline, top 25 groups, top 20 genres and additions per month, all
  live from the SQLite index. Every entry links to the filtered search.
- The genre comes from the ID3 tags of the MP3s (`app/genre_stats.py`); the most frequent genre per
  release is stored and can be filtered in the search.
- After an update reindex once, then the genres are filled: `curl -X POST http://localhost:8000/reindex`
