# ArchiveDB — Scene Archive Browser

Ein schlankes, read-only Webfrontend über deinem `scenereleases`
Bestand. Suche nach Künstler/Titel/Jahr/Gruppe/Format, Ergebnisliste
anklicken, Dateien des Release-Ordners ansehen — im Stil von srrDB.

## Datenquelle

ArchiveDB liest nur und verändert nichts. Es indexiert zwei Ordner unter
deinem Archiv Wurzelordner (`ARCHIVE_PATH`): `scenereleases_srr` (Releases mit
srrDB Treffer) und `scenereleases_nosrr` (saubere Releases ohne srrDB Treffer).
Der Ordner `scenereleases` mit den Symlinks wird bewusst nicht gelesen, damit
keine Release doppelt erscheint. In der Suche trennt der Filter "Source" beide
Gruppen.

Das Archiv muss für den Container als Verzeichnis erreichbar sein (lokaler
Pfad oder eingebundenes Netzlaufwerk, nur lesend reicht).

## NFO-Anzeige wie im klassischen DOS-Viewer

NFOs werden richtig als CP437 gelesen (die alte DOS-Codepage, die für
die ASCII-Art-Rahmen sorgt) statt fälschlich als Latin-1 — das
behebt die meisten verstümmelten Rahmen und Balken. Ein einzelnes
Wagenrücklauf-Zeichen (`\r` ohne `\n`), das manche aufwändig
gestaltete NFOs für überlagerte Kunst-Elemente nutzen, wird beim
Einlesen entfernt statt es als Zeilenumbruch zu behandeln, das würde
sonst eine ungewollte zusätzliche Zeile erzeugen.

Für die Schriftart wird "DejaVu Sans Mono" als echte, selbst
eingebundene Webschrift mitgeliefert (`static/fonts/DejaVuSansMono.ttf`),
zusätzlich zu "Lucida Console" als Rückfall dort wo installiert.
Ein früherer Versuch mit "Perfect DOS VGA 437" führte zu Versatz in
längeren ASCII-Art-Rahmen, weil frei im Netz kursierende
TTF-Konvertierungen solcher Bitmap-Schriften oft nicht wirklich
zeichengenau gleich breit sind — DejaVu Sans Mono wurde dagegen
direkt gemessen (jedes Zeichen exakt gleich breit) und ist eine
seriöse, offen lizenzierte Schriftart. Weil sie selbst mitgeliefert
wird statt auf eine System-Installation zu hoffen, bekommt jedes
Gerät, auch Android, dieselbe verlässliche Darstellung.

**Wichtig:** damit bereits indexierte NFOs die korrekte
CP437-Kodierung bekommen, einmal neu indexieren:

```bash
docker exec archivedb python3 /app/app/indexer.py
```

## Aufbau

- **SQLite + FTS5** als Datenbank, eine Datei unter `/data/archive.db`
- **FastAPI** Backend (`app/main.py`)
- **Jinja2 Templates**, serverseitig gerendert, responsive für
  Desktop (1440p) und Smartphone
- **indexer.py** durchsucht `ARCHIVE_ROOT/scenereleases` und befüllt
  die Datenbank; läuft einmal beim Container-Start automatisch, kann
  danach jederzeit erneut angestoßen werden

## Inbetriebnahme

1. Konfiguration anlegen und `ARCHIVE_PATH` auf deinen Archiv Wurzelordner setzen:

   ```bash
   cd archivedb
   cp .env.example .env
   nano .env
   ```

2. Bauen und starten:

   ```bash
   docker compose up -d --build
   ```

3. Im Browser aufrufen: `http://<docker-host-IP>:8000`

Der erste Start indexiert automatisch einmal komplett, das kann bei großen
Beständen einige Minuten dauern (reiner Dateisystem Scan). Währenddessen
liefert die Seite noch keine Antwort (Fehler 502 hinter einem Proxy), das ist
normal. Fortschritt: `docker logs --tail 30 -f archivedb`.

## Manuell neu indexieren

Nach größeren Änderungen am Archiv, ohne den Container neu zu
starten:

```bash
docker exec archivedb python3 /app/app/indexer.py
```

Oder über die eingebaute HTTP-Route (macht dasselbe):

```bash
curl -X POST http://localhost:8000/reindex
```

## Automatische Aktualisierung

Der Incoming Processor kann nach jedem Lauf selbst einen Reindex anstoßen.
Dazu in der Konfiguration des Processors `ARCHIVEDB_URL` setzen, zum Beispiel
`http://archivedb:8000`, sofern beide Container im selben Docker Netzwerk laufen.
Alternativ per Cron: `curl -X POST http://localhost:8000/reindex`

## Grenzen der aktuellen Version

- Reine Lesefunktion, keine Löschen/Verschieben-Aktionen aus dem
  Webfrontend heraus
- Künstler/Titel-Trennung ist eine Heuristik über den Scene-Ordnernamen,
  gelegentlich landen einzelne Format-/Jahres-Wörter noch mit im
  Titel-Feld — stört die Suche nicht, ist aber kosmetisch nicht perfekt
- Indexiert standardmäßig nur `scenereleases_srr` und `scenereleases_nosrr`

## Statistik und Genre (ab indexer 1.3, main 1.4)

- `/stats` zeigt Formate, Jahre, Zeitleiste, Top 25 Gruppen, Top 20 Genres und
  den Zugang pro Monat, alles live aus dem SQLite Index. Jeder Eintrag ist ein
  Link auf die gefilterte Suche.
- Das Genre kommt aus den ID3 Tags der MP3s (`app/genre_stats.py`), pro Release
  wird das haeufigste Genre gespeichert und ist in der Suche filterbar.
- Nach dem Update einmal neu indexieren, danach sind die Genres gefuellt:
  `curl -X POST http://localhost:8000/reindex`
