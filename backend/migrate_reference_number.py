"""
migrate_reference_number.py
───────────────────────────
Adds `reference_number` column to the inspections table.

Run once:
    python migrate_reference_number.py
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
                "ALTER TABLE inspections ADD COLUMN reference_number VARCHAR(100)"
            ))
            db.session.commit()
            print("✓ Added reference_number column to inspections table")
        except Exception as e:
            db.session.rollback()
            if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                print("↩  reference_number column already exists — skipping")
            else:
                raise

if __name__ == '__main__':
    run()
