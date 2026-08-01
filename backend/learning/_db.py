"""
backend/learning/_db.py
────────────────────────
Shared DATABASE_URL/engine helper for the prompt-learning pipeline scripts.
Uses a raw SQLAlchemy engine (not the Flask-SQLAlchemy `db` object) so these
scripts stay standalone-runnable without booting the full Flask app
(blueprints, scheduler jobs, etc.) — same convention as migrate_*.py.
"""

import os
from sqlalchemy import create_engine


def get_engine():
    database_url = os.environ.get('DATABASE_URL', '')
    if not database_url:
        raise RuntimeError('DATABASE_URL env var not set')

    database_url = database_url.replace('postgres://', 'postgresql+psycopg://')
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg://')

    return create_engine(database_url)
