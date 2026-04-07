"""
Run this once to add the report colour/orientation columns to the clients table.
These columns were defined in models.py but never migrated to Railway PostgreSQL.

Usage:
    DATABASE_URL=<your-railway-url> python migrate_report_colors.py

Or set DATABASE_URL in your environment first, then:
    python migrate_report_colors.py
"""
import os
from sqlalchemy import create_engine, text

database_url = os.environ.get('DATABASE_URL', '')
if not database_url:
    print('ERROR: DATABASE_URL env var not set')
    exit(1)

# Rewrite postgres:// or postgresql:// to the psycopg2 dialect
database_url = database_url.replace('postgres://', 'postgresql+psycopg2://')
database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://')

engine = create_engine(database_url)

MIGRATIONS = [
    ("report_header_text_color", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS report_header_text_color VARCHAR(20)"),
    ("report_body_text_color",   "ALTER TABLE clients ADD COLUMN IF NOT EXISTS report_body_text_color   VARCHAR(20)"),
    ("report_orientation",       "ALTER TABLE clients ADD COLUMN IF NOT EXISTS report_orientation       VARCHAR(20)"),
]

with engine.connect() as conn:
    for name, sql in MIGRATIONS:
        conn.execute(text(sql))
        print(f'  ✓ {name}')
    conn.commit()

print('Migration complete — report colour columns added to clients table.')
