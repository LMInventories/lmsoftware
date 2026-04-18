"""
Run this once to add the is_transient column to the templates table.

PDF-import templates are marked is_transient=True so they are functional
(inspections can reference them) but hidden from the Templates management UI.

Usage:
    DATABASE_URL=<your-railway-url> python migrate_transient_templates.py

Or set DATABASE_URL in your environment first, then:
    python migrate_transient_templates.py
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
    (
        "templates.is_transient",
        "ALTER TABLE templates ADD COLUMN IF NOT EXISTS is_transient BOOLEAN DEFAULT FALSE",
    ),
]

with engine.connect() as conn:
    for name, sql in MIGRATIONS:
        conn.execute(text(sql))
        print(f'  ✓ {name}')
    conn.commit()

print('Migration complete — is_transient column added to templates table.')
print()
print('Existing "PDF Import" templates can be back-filled if desired:')
print('  UPDATE templates SET is_transient = TRUE WHERE name LIKE \'PDF Import%\';')
