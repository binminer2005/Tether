#!/bin/sh
set -eu

if [ -z "${SECRET_KEY:-}" ]; then
  echo "SECRET_KEY must be set in production" >&2
  exit 1
fi

exec gunicorn \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --access-logfile - \
  --error-logfile - \
  app:app
