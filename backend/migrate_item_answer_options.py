"""
migrate_item_answer_options.py
──────────────────────────────
Adds `answer_options` column to the items table.

Run once (or automatically via start.sh on deploy):
    python migrate_item_answer_options.py
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
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS answer_options TEXT DEFAULT ''"
    ))
    conn.commit()

print("✓ answer_options column ensured on items table")
