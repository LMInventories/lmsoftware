"""
migrate_floor_plans.py
───────────────────────
Creates the floor_plans table (see models.py::FloorPlan) — the manually-
measured floor plan tool, not the ARCore scan pipeline (floor_plan_scans).

Run once (or automatically via start.sh on deploy):
    python migrate_floor_plans.py
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
        CREATE TABLE IF NOT EXISTS floor_plans (
            id             SERIAL PRIMARY KEY,
            inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
            corners        TEXT NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_floor_plans_inspection_id ON floor_plans (inspection_id)"
    ))
    conn.commit()

print('OK floor_plans table ensured')
