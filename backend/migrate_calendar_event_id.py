"""
migrate_calendar_event_id.py
─────────────────────────────
Adds `calendar_event_id` column to the inspections table.

Run once:
    python migrate_calendar_event_id.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import db
from sqlalchemy import text

def run():
    app = create_app()
    with app.app_context():
        try:
            db.session.execute(text(
                "ALTER TABLE inspections ADD COLUMN calendar_event_id VARCHAR(255)"
            ))
            db.session.commit()
            print("✓ Added calendar_event_id column to inspections table")
        except Exception as e:
            db.session.rollback()
            if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                print("↩  calendar_event_id column already exists — skipping")
            else:
                raise

if __name__ == '__main__':
    run()
