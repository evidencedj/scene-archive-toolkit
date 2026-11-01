#!/bin/sh
set -e

echo "Initial index run..."
python3 -u /app/app/indexer.py || echo "Initial index failed — starting anyway, retry via /reindex or docker exec"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
