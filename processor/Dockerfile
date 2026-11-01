# Incoming Processor image (enthaelt auch die Python Werkzeuge aus tools/)
#
# Build Kontext ist die Wurzel des Toolkits, nicht dieser Ordner (siehe
# docker-compose.yml: context "..").
#
# VERSIONSHISTORIE
#   1.0  2026-11-01  Erste Fassung fuer das Toolkit. Rekonstruiert aus dem
#                    Image des Originalsetups: Python 3.12, pyrescene und ein
#                    kleiner Patch in rescene/utility.py (locale.format wurde
#                    in Python 3.12 entfernt und bricht sonst srr.py).
#   1.1  2026-11-01  Build Kontext ist jetzt die Toolkit Wurzel. Das Image
#                    enthaelt zusaetzlich tools/ (archive_stats, archive_sorter,
#                    genre_stats, sync_scene_links, migrate_to_v3_layout), damit
#                    die Nachtpipeline alles im selben Container ausfuehren kann.
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir pyrescene requests mutagen \
 && sed -i "s/locale.format('%d', number, True)/format(number, ',')/g" \
      /usr/local/lib/python3.12/site-packages/rescene/utility.py \
 && test -f /usr/local/bin/srr.py

COPY processor/incoming_processor.py /app/incoming_processor.py
COPY tools/ /app/tools/

ENV PYTHONUNBUFFERED=1 \
    SRR_PY=/usr/local/bin/srr.py \
    ARCHIVE_ROOT=/archive \
    INCOMING_DIR=/archive/incoming \
    LOG_DIR=/app/logs \
    LOCKFILE=/archive/.incoming_processor.lock \
    GENRE_CACHE_FILE=/app/state/genre_stats_cache.json

CMD ["python", "/app/incoming_processor.py"]
