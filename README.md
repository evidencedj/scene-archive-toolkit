# Scene Archive Toolkit

Werkzeuge für ein Scene Musikarchiv: neue Releases automatisch gegen srrDB prüfen, benennen
und einsortieren, und das Archiv in einer Weboberfläche durchsuchen.

Version: siehe Datei `VERSION` und `CHANGELOG.md`.

## Bestandteile

| Ordner | Was es tut |
|---|---|
| `processor/` | Incoming Processor: verarbeitet alles in `incoming/` (srrDB Abgleich, CRC Prüfung, Umbenennen, Sortieren) |
| `archivedb/` | ArchiveDB: Suchoberfläche über das Archiv (SQLite, FastAPI, nur lesend) |
| `tools/` | Migration vom alten Layout und Reparatur der Symlinks |
| `docs/` | Umstieg von Version 2.2 und weitere Hinweise |

## Ordnerstruktur des Archivs (v3 Layout)

```
<ARCHIVE_ROOT>/
  incoming/             neue Releases landen hier
  scenereleases_srr/    echte Ordner: Releases mit srrDB Treffer
  scenereleases_nosrr/  echte Ordner: saubere Releases, die srrDB nicht kennt
  scenereleases/        nur relative Symlinks auf die beiden Ordner darüber
  incomplete/           CRC Fehler oder fehlende Dateien
  dupes/                Doppelte und abgelöste Versionen
  mp3s/                 lose Audiodateien ohne SFV
```

Das Archiv muss auf einem **lokalen Dateisystem** liegen, weil die Symlinks über SMB/CIFS nicht
funktionieren. Der Processor und die Migration laufen daher auf dem Rechner, der die Platten besitzt
(oder in einem Container, der den Ordner lokal eingebunden hat).

## Schnellstart

Voraussetzung: Docker mit Compose.

1. **Processor einrichten und einmal testen**

   ```bash
   cd processor
   cp .env.example .env        # ARCHIVE_PATH auf den Archiv Ordner setzen
   docker compose build
   docker compose run --rm processor python incoming_processor.py --dry-run
   ```

   Der Probelauf verschiebt nichts. Wenn das Ergebnis passt: `docker compose run --rm processor`.

2. **ArchiveDB einrichten**

   ```bash
   cd archivedb
   cp .env.example .env        # ARCHIVE_PATH setzen
   docker compose up -d --build
   ```

   Aufruf im Browser: `http://<host>:8000`

3. **Regelmäßig laufen lassen**: Der Processor ist ein Einzellauf, kein Dauerdienst. Per Cron oder
   Aufgabenplaner starten, zum Beispiel jede Nacht:

   ```
   0 23 * * *  cd /pfad/zu/processor && docker compose run --rm processor
   ```

   Mit `ARCHIVEDB_URL` in der Processor `.env` (und beiden Containern im selben Docker Netzwerk)
   aktualisiert sich die ArchiveDB nach jedem Lauf selbst.

## Aktualisieren

```bash
git pull
cd processor && docker compose build && cd ..
cd archivedb && docker compose up -d --build
```

Wer noch das alte Layout hat (Ordner `nomatch`, echte Ordner in `scenereleases`), liest zuerst
`docs/UPGRADE_FROM_2.2.md`.

## Hinweise

- Alle Skripte tragen eine Versionshistorie im Dateikopf. Die Versionsnummer steht auch im Startbanner.
- Zugangsdaten (Discord Webhook, Proxy) gehören nur in die `.env`, die nicht ins Git kommt.
- srrDB wird anonym abgefragt, ein Login ist nicht nötig. Bitte `REQUEST_DELAY` nicht zu klein wählen.
- Schriftart `DejaVuSansMono.ttf` in `archivedb/static/fonts/`: freie Lizenz (Bitstream Vera / DejaVu).
