import os
from app import create_app
from models import db, User, Client, Property
from sqlalchemy import text

app = create_app()

with app.app_context():
    # ── Step 1: Create any missing tables ───────────────────────────────────
    db.create_all()

    # ── Step 2: Column migrations (safe on every restart) ───────────────────
    # db.create_all() only creates missing TABLES, not missing COLUMNS.
    # Any time we add a column to a model we must also handle it here so that
    # existing live databases get the new column without needing Flask-Migrate.

    def _is_sqlite():
        return 'sqlite' in str(db.engine.url)

    def column_exists(table, column):
        if _is_sqlite():
            rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
            return any(row[1] == column for row in rows)
        else:
            row = db.session.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"
            ), {'t': table, 'c': column}).fetchone()
            return row is not None

    # users.is_ai — added when AI Typist feature was introduced
    if not column_exists('users', 'is_ai'):
        print("Migrating database: adding users.is_ai column...")
        default = "0" if _is_sqlite() else "FALSE"
        db.session.execute(
            text(f"ALTER TABLE users ADD COLUMN is_ai BOOLEAN NOT NULL DEFAULT {default}")
        )
        db.session.commit()
        print("✅ users.is_ai column added.")

    # ── Step 3: Seed data (only on empty database) ───────────────────────────
    if User.query.count() == 0:
        print("Fresh database detected — seeding demo data...")

        # Human users
        admin = User(name='Admin', email='admin@example.com', role='admin', color='#6366f1')
        admin.set_password('admin123')

        manager = User(name='Manager', email='manager@example.com', role='manager', color='#8b5cf6')
        manager.set_password('manager123')

        clerk = User(name='Robyn Lee', email='clerk@example.com', role='clerk', color='#10b981')
        clerk.set_password('clerk123')

        typist = User(name='Sarah Typist', email='typist@example.com', role='typist', color='#f59e0b')
        typist.set_password('typist123')

        # AI Typist system account — triggers automatic transcription when assigned.
        # Random unguessable password; this account cannot log in.
        ai_typist = User(
            name='AI Typist',
            email='ai.typist@system.local',
            role='typist',
            color='#6366f1',
            is_ai=True
        )
        ai_typist.set_password('system-' + os.urandom(16).hex())

        db.session.add_all([admin, manager, clerk, typist, ai_typist])
        db.session.flush()

        # Client
        client = Client(
            name='Yellands Estates',
            email='info@yellands.co.uk',
            phone='020 1234 5678',
            company='Yellands Estates',
            primary_color='#1E3A8A',
            report_disclaimer=(
                'This report has been prepared with reasonable care and skill. '
                'The contents of this report are confidential to the instructing parties. '
                'All measurements are approximate.'
            )
        )
        db.session.add(client)
        db.session.flush()

        # Example property
        prop = Property(
            client_id=client.id,
            address='15 Cam Green, South Ockendon, RM15 5QN',
            property_type='residential',
            bedrooms=2,
            bathrooms=1,
            furnished=False,
            parking=True,
            garden=True,
        )
        db.session.add(prop)
        db.session.commit()

        print("\n✅ Database seeded successfully!")
        print("─" * 40)
        print("  Admin:     admin@example.com    / admin123")
        print("  Manager:   manager@example.com  / manager123")
        print("  Clerk:     clerk@example.com    / clerk123")
        print("  Typist:    typist@example.com   / typist123")
        print("  AI Typist: ai.typist@system.local (system account — cannot log in)")
        print("─" * 40)
        print("  Client:   Yellands Estates")
        print("  Property: 15 Cam Green, South Ockendon, RM15 5QN")
        print("─" * 40)

    else:
        # Existing database — check if AI Typist account is missing
        ai_exists = User.query.filter_by(email='ai.typist@system.local').first()
        if not ai_exists:
            print("Adding AI Typist system account to existing database...")
            ai_typist = User(
                name='AI Typist',
                email='ai.typist@system.local',
                role='typist',
                color='#6366f1',
                is_ai=True
            )
            ai_typist.set_password('system-' + os.urandom(16).hex())
            db.session.add(ai_typist)
            db.session.commit()
            print("✅ AI Typist system account created.")
        else:
            print("Database ready.")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
