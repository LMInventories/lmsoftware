#!/bin/bash
# Railway entrypoint for the InspectPro backend.
# DB migrations and seeding are handled inside create_app() on first boot.
set -e

echo "==> Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn app:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
