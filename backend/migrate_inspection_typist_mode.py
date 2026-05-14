"""
migrate_inspection_typist_mode.py
──────────────────────────────────
Adds `typist_mode` column to the inspections table and back-fills it from
each inspection's assigned clerk so existing records inherit the old
global setting as their starting value.

Run once (or automatically via start.sh on deploy):
    python migrate_inspection_typist_mode.py
"""

import os
from sqlalchemy import create_engine, text

database_url = os.environ.get('DATABASE_URL', '')
if not database_url:
    print('ERROR: DATABASE_URL env var not set')
    exit(1)

database_url = database_url.replace('postgres://', 'postgresql+psycopg2://')
database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://')

engine = create_engine(database_url)

with engine.connect() as conn:
    conn.execute(text(
        "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS typist_mode VARCHAR(20)"
    ))

    result = conn.execute(text("""
        UPDATE inspections
        SET typist_mode = (
            SELECT u.typist_mode
            FROM users u
            WHERE u.id = inspections.inspector_id
              AND u.typist_mode IS NOT NULL
        )
        WHERE typist_mode IS NULL
          AND inspector_id IS NOT NULL
    """))
    conn.commit()

print(f'✓ typist_mode column ensured on inspections table')
