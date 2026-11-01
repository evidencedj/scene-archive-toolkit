# Incoming Processor

Verarbeitet alle Ordner in `incoming/` in Stufen:

| Stufe | Vorgehen |
|---|---|
| 0 | genauer Ordnername gegen srrDB |
| 1 | Suche über Dateinamen (NFO, SFV, M3U) |
| 1b | Audio CRC Abgleich, wenn mehrere Kandidaten passen |
| 2 | unscharfe Suche über Ordnernamen (braucht ein Jahr) |
| 3 | ID3 und NFO Angaben (Album, Jahr, Gruppe) |

Bei einem Treffer: Metadaten prüfen, SRR laden und entpacken falls nötig, Audio CRCs prüfen, Release
umbenennen und nach `scenereleases_srr` verschieben (mit Symlink in `scenereleases`). Ohne Treffer:
saubere Scene Releases nach `scenereleases_nosrr`, fehlerhafte nach `incomplete`, Doppelte nach `dupes`,
lose Audiodateien nach `mp3s`.

## Einrichten

```bash
cp .env.example .env     # ARCHIVE_PATH setzen
docker compose build
docker compose run --rm processor python incoming_processor.py --dry-run   # Vorschau
docker compose run --rm processor                                          # echter Lauf
```

Die Einstellungen stehen in `.env.example` mit Erklärung. Protokolle liegen unter `LOG_PATH`
(`incoming_processor_*.log` und `incoming_results_*.log`).

## Ohne Docker

```bash
pip install requests mutagen pyrescene
# Python 3.12: in rescene/utility.py die Zeile  locale.format('%d', number, True)
# durch  format(number, ',')  ersetzen (siehe Dockerfile)
export ARCHIVE_ROOT=/pfad/zum/archiv INCOMING_DIR=/pfad/zum/archiv/incoming \
       SRR_PY=$(which srr.py) LOG_DIR=./logs LOCKFILE=/tmp/incoming_processor.lock
python3 incoming_processor.py --dry-run
```

## Hinweise

- Das Archiv muss lokal liegen (Symlinks). Altes Layout: siehe `../docs/UPGRADE_FROM_2.2.md`.
- Läuft pro Archiv nur einmal gleichzeitig (Lockdatei `.incoming_processor.lock` im Archiv Ordner).
- `Strg+C` bzw. SIGTERM beendet den Lauf sauber nach der aktuellen Release.
- Sperrt srrDB die eigene IP (HTTP 403, 429, 503), bricht der Lauf ab. Mit `VPN_PROXY_URL` schaltet er
  stattdessen auf den Proxy um.
