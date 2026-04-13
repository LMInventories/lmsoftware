"""
migrate_inspection_typist_mode.py
──────────────────────────────────
Adds `typist_mode` column to the inspections table.

This moves typist mode from a clerk-level setting (User.typist_mode)
to a per-inspection setting (Inspection.typist_mode), so clerks can
choose AI Instant / AI by Room / Human per report rather than globally.

Run once:
    python migrate_inspection_typist_mode.py
"""

import sys
import os

# ── Make sure we can find the app modules ────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import db
from sqlalchemy import text

def run():
    app = create_app()
    with app.app_context():
        try:
            db.session.execute(text(
                "ALTER TABLE inspections ADD COLUMN typist_mode VARCHAR(20)"
            ))
            db.session.commit()
            print("✓ Added typist_mode column to inspections table")
        except Exception as e:
            db.session.rollback()
            if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                print("↩  typist_mode column already exists — skipping")
            else:
                raise

        # Back-fill: for each inspection, copy the inspector's (clerk's) typist_mode
        # so existing records inherit the old global setting as their starting value.
        result = db.session.execute(text("""
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
        db.session.commit()
        print(f"✓ Back-filled typist_mode on {result.rowcount} inspections from clerk profile")

if __name__ == '__main__':
    run()
