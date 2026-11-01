FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV ARCHIVE_ROOT=/archive
ENV DB_PATH=/data/archive.db

EXPOSE 8000

CMD ["./entrypoint.sh"]
