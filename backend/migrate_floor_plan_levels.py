"""
migrate_floor_plan_levels.py
─────────────────────────────
Creates the floor_plan_levels and floor_plan_rooms tables (see
models.py::FloorPlanLevel / FloorPlanRoom) — the multi-floor, multi-room
manual floor-plan tool, replacing the earlier single-room floor_plans
table (left in place, unused — no real data existed in it worth migrating).

Run once (or automatically via start.sh on deploy):
    python migrate_floor_plan_levels.py
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
        CREATE TABLE IF NOT EXISTS floor_plan_levels (
            id             SERIAL PRIMARY KEY,
            inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
            name           VARCHAR(100) NOT NULL,
            order_index    INTEGER NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_floor_plan_levels_inspection_id ON floor_plan_levels (inspection_id)"
    ))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS floor_plan_rooms (
            id             SERIAL PRIMARY KEY,
            level_id       INTEGER NOT NULL REFERENCES floor_plan_levels(id) ON DELETE CASCADE,
            name           VARCHAR(100) NOT NULL,
            data           TEXT NOT NULL,
            order_index    INTEGER NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_floor_plan_rooms_level_id ON floor_plan_rooms (level_id)"
    ))
    conn.commit()

print('OK floor_plan_levels and floor_plan_rooms tables ensured')
