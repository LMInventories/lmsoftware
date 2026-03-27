#!/bin/bash
# Railway entrypoint for the InspectPro backend.
# 1. Runs run.py as a module (executes migrations + seed check, but NOT the dev server)
# 2. Starts gunicorn for production
set -e

echo "==> Running database migrations and seed check..."
python3 -c "import run" || { echo "ERROR: run.py failed — see above for details"; exit 1; }

echo "==> Migrations complete. Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn app:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
