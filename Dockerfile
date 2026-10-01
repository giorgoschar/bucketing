FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# pg_dump for the pre-migration backup in entrypoint.sh (Debian 13 ships v17,
# which can dump the Postgres 16 server).
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer cache — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create runtime directories and drop root. /app/uploads and /backups are owned
# by the app user so fresh named volumes mounted there inherit that ownership.
RUN mkdir -p uploads static/icons /backups \
    && chmod +x entrypoint.sh scripts/backup.sh \
    && useradd -r -u 10001 app \
    && chown -R app /app /backups

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
