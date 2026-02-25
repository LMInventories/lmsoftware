# run.py — application entry point
# Render calls:  gunicorn run:app
# Local dev:     python run.py
#
# Seed logic: only runs when the users table is completely empty.
# This means your real production users are NEVER overwritten on restart.
# The demo seed only fires on a brand-new blank database.

from app import create_app
from models import db, User, Client, Property

app = create_app()

with app.app_context():
    db.create_all()

    if User.query.count() == 0:
        print("Fresh database — seeding initial accounts...")

        # ── Users ─────────────────────────────────────────────────────────────
        # These are the startup accounts. Once you've created real users through
        # the app's Users page, change these passwords or delete these accounts.
        admin = User(name='Admin', email='admin@example.com', role='admin', color='#6366f1')
        admin.set_password('admin123')

        manager = User(name='Manager', email='manager@example.com', role='manager', color='#8b5cf6')
        manager.set_password('manager123')

        clerk = User(name='Robyn Lee', email='clerk@example.com', role='clerk', color='#10b981')
        clerk.set_password('clerk123')

        typist = User(name='Sarah Typist', email='typist@example.com', role='typist', color='#f59e0b')
        typist.set_password('typist123')

        db.session.add_all([admin, manager, clerk, typist])
        db.session.flush()

        # ── Client ────────────────────────────────────────────────────────────
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

        # ── Property ──────────────────────────────────────────────────────────
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

        print("✅ Initial accounts created.")
        print("   Use the Users page to create permanent staff accounts.")
    else:
        print(f"✅ Database ready — {User.query.count()} user(s) loaded.")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
