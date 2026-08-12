"""
migrate_floor_plan_scans.py
─────────────────────────────
Creates the floor_plan_scans table (see models.py::FloorPlanScan).

Run once (or automatically via start.sh on deploy):
    python migrate_floor_plan_scans.py
"""

import os
from sqlalchemy import create_engine, text

database_url = os.environ.get('DATABASE_URL', '')
if not database_url:
    print('ERROR: DATABASE_URL env var not set')
    exit(1)

database_url = database_url.replace('postgres://', 'postgresql+psycopg://')
database_url = database_url.replace('postgresql://', 'postgresql+psycopg://')

engine = create_engine(database_url)

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS floor_plan_scans (
            id             SERIAL PRIMARY KEY,
            inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
            scan_uuid      VARCHAR(64) NOT NULL,
            status         VARCHAR(30) NOT NULL DEFAULT 'UPLOADING',
            s3_key         VARCHAR(512),
            frame_count    INTEGER,
            error_message  TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_floor_plan_scans_inspection_id ON floor_plan_scans (inspection_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_floor_plan_scans_scan_uuid ON floor_plan_scans (scan_uuid)"
    ))
    conn.commit()

print('OK floor_plan_scans table ensured')
