# Incoming Processor image (also contains the Python tools from tools/)
#
# The build context is the toolkit root, not this folder (see
# docker-compose.yml: context "..").
#
# VERSION HISTORY
#   1.0  2026-11-01  First version for the toolkit. Reconstructed from the
#                    original setup image: Python 3.12, pyrescene and a small
#                    patch in rescene/utility.py (locale.format was removed in
#                    Python 3.12 and would otherwise break srr.py).
#   1.1  2026-11-01  The build context is now the toolkit root. The image also
#                    contains tools/ (archive_stats, archive_sorter,
#                    genre_stats, sync_scene_links, migrate_to_v3_layout) so
#                    the nightly pipeline can run everything in one container.
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
