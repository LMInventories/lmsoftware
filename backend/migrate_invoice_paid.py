"""
migrate_invoice_paid.py
────────────────────────
Adds `invoice_paid` boolean column to the inspections table.

Run once on deploy (safe to re-run — uses ADD COLUMN IF NOT EXISTS):
    python migrate_invoice_paid.py
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
        "ALTER TABLE inspections ADD COLUMN IF NOT EXISTS invoice_paid BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    conn.commit()

print('✓ invoice_paid column ensured on inspections table')
