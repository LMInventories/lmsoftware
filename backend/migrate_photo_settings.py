"""
Run this once to add the report_photo_settings column to the clients table.
Usage: python migrate_photo_settings.py
"""
import os
from sqlalchemy import create_engine, text

database_url = os.environ.get('DATABASE_URL', '')
if not database_url:
    print('ERROR: DATABASE_URL env var not set')
    exit(1)

# Render provides postgres:// — rewrite to postgresql+psycopg2://
database_url = database_url.replace('postgres://', 'postgresql+psycopg2://')
database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://')

engine = create_engine(database_url)

with engine.connect() as conn:
    conn.execute(text(
        'ALTER TABLE clients ADD COLUMN IF NOT EXISTS report_photo_settings TEXT'
    ))
    conn.commit()
    print('Migration complete — report_photo_settings column added.')
