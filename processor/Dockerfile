# Incoming Processor image
#
# VERSIONSHISTORIE
#   1.0  2026-11-01  Erste Fassung fuer das Toolkit. Rekonstruiert aus dem
#                    Image des Originalsetups: Python 3.12, pyrescene und ein
#                    kleiner Patch in rescene/utility.py (locale.format wurde
#                    in Python 3.12 entfernt und bricht sonst srr.py).
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir pyrescene requests mutagen \
 && sed -i "s/locale.format('%d', number, True)/format(number, ',')/g" \
      /usr/local/lib/python3.12/site-packages/rescene/utility.py \
 && test -f /usr/local/bin/srr.py

COPY incoming_processor.py /app/incoming_processor.py

ENV PYTHONUNBUFFERED=1 \
    SRR_PY=/usr/local/bin/srr.py \
    ARCHIVE_ROOT=/archive \
    INCOMING_DIR=/archive/incoming \
    LOG_DIR=/app/logs \
    LOCKFILE=/archive/.incoming_processor.lock

CMD ["python", "/app/incoming_processor.py"]
