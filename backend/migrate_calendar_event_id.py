"""
migrate_calendar_event_id.py
─────────────────────────────
Adds `calendar_event_id` column to the inspections table.

Run once (or automatically via start.sh on deploy):
    python migrate_calendar_event_id.py
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
        "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(255)"
    ))
    conn.commit()

print('✓ calendar_event_id column ensured on inspections table')
