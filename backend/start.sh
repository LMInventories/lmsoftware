#!/bin/bash
# Railway entrypoint for the InspectPro backend.
# All idempotent column migrations run here before Gunicorn starts so every
# deploy automatically brings the schema up to date. A failing migration fails
# the deploy (set -e) — never mask failures with `|| echo`, or new code ships
# against an un-migrated schema and breaks at runtime instead. Every script
# here must therefore be safe to re-run (IF NOT EXISTS, guarded UPDATEs).
# DO NOT add migrate_photos_to_s3.py — that is a one-time data migration.
set -e

echo "==> Running DB migrations..."
python3 migrate_photo_settings.py
python3 migrate_report_colors.py
python3 migrate_inspection_typist_mode.py
python3 migrate_transient_templates.py
python3 migrate_item_answer_options.py
python3 migrate_reference_number.py
python3 migrate_calendar_event_id.py
python3 migrate_invoice_paid.py
python3 migrate_drive_file_id.py
python3 migrate_source_pdf_drive_file_id.py
python3 migrate_learning_tables.py
python3 migrate_floor_plan_scans.py
python3 migrate_floor_plans.py
python3 migrate_floor_plan_levels.py
python3 migrate_inspection_activity.py
python3 migrate_telegram.py

echo "==> Starting Gunicorn..."
exec gunicorn app:app --config gunicorn.conf.py
