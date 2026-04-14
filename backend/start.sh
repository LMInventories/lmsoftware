#!/bin/bash
# Railway entrypoint for the InspectPro backend.
# DB migrations and seeding are handled inside create_app() on first boot.
set -e

echo "==> Running DB migrations..."
python3 migrate_photo_settings.py            || echo "migrate_photo_settings: skipped or already done"
python3 migrate_report_colors.py             || echo "migrate_report_colors: skipped or already done"
python3 migrate_inspection_typist_mode.py    || echo "migrate_inspection_typist_mode: skipped or already done"

echo "==> Starting Gunicorn on port ${PORT:-8000}..."
exec python3 -m gunicorn app:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
