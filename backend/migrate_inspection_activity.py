"""
migrate_inspection_activity.py
────────────────────────────
Creates the inspection_activity table backing the per-inspection Activity
Log card (InspectionDetailView.vue) — created/details_added/fetched/started/
synced/completed events. See models.InspectionActivity.

Run once on deploy (safe to re-run — uses CREATE TABLE IF NOT EXISTS):
    python migrate_inspection_activity.py
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

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS inspection_activity (
        id             SERIAL PRIMARY KEY,
        inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
        event_type     VARCHAR(30) NOT NULL,
        user_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
        detail         VARCHAR(255),
        created_at     TIMESTAMP NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_inspection_activity_inspection_id ON inspection_activity (inspection_id)",
]

with engine.connect() as conn:
    for stmt in STATEMENTS:
        conn.execute(text(stmt))
    conn.commit()

print('✓ inspection_activity table ensured')
