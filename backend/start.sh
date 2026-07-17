#!/bin/bash
# Railway entrypoint for the InspectPro backend.
# All idempotent column migrations run here before Gunicorn starts so every
# deploy automatically brings the schema up to date.
# DO NOT add migrate_photos_to_s3.py — that is a one-time data migration.
set -e

echo "==> Running DB migrations..."
python3 migrate_photo_settings.py            || echo "migrate_photo_settings: skipped or already done"
python3 migrate_report_colors.py             || echo "migrate_report_colors: skipped or already done"
python3 migrate_inspection_typist_mode.py    || echo "migrate_inspection_typist_mode: skipped or already done"
python3 migrate_transient_templates.py       || echo "migrate_transient_templates: skipped or already done"
python3 migrate_item_answer_options.py       || echo "migrate_item_answer_options: skipped or already done"
python3 migrate_reference_number.py          || echo "migrate_reference_number: skipped or already done"
python3 migrate_calendar_event_id.py         || echo "migrate_calendar_event_id: skipped or already done"
python3 migrate_invoice_paid.py              || echo "migrate_invoice_paid: skipped or already done"
python3 migrate_drive_file_id.py              || echo "migrate_drive_file_id: skipped or already done"

echo "==> Starting Gunicorn..."
exec gunicorn app:app --config gunicorn.conf.py
