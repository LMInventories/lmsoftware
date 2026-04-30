"""
Migration: add answer_options column to items table.

Run once against the production database:
    cd backend && python migrate_item_answer_options.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db

def run():
    app = create_app()
    with app.app_context():
        with db.engine.connect() as conn:
            # Check whether the column already exists
            from sqlalchemy import text, inspect as sa_inspect
            inspector = sa_inspect(db.engine)
            cols = [c['name'] for c in inspector.get_columns('items')]
            if 'answer_options' in cols:
                print('answer_options column already exists — nothing to do.')
                return

            conn.execute(text("ALTER TABLE items ADD COLUMN answer_options TEXT DEFAULT ''"))
            conn.commit()
            print('Migration complete: items.answer_options added.')

if __name__ == '__main__':
    run()
