# init_db.py  — run this ONCE to seed a fresh database
# WARNING: This drops and recreates all tables. Do not run in production.

from app import create_app
from models import db, User, Client

app = create_app()

with app.app_context():
    print("Dropping existing tables...")
    db.drop_all()
    print("Creating tables...")
    db.create_all()

    admin = User(name='Admin User', email='admin@example.com', role='admin')
    admin.set_password('admin123')

    manager = User(name='Manager User', email='manager@example.com', role='manager')
    manager.set_password('manager123')

    clerk = User(name='Robyn Lee', email='clerk@example.com', role='clerk')
    clerk.set_password('clerk123')

    typist = User(name='Typist User', email='typist@example.com', role='typist')
    typist.set_password('typist123')

    client = Client(
        name='Yellands Estates',
        email='info@yellands.co.uk',
        phone='020 1234 5678',
        company='Yellands Estates'
    )

    db.session.add_all([admin, manager, clerk, typist, client])
    db.session.commit()

    print("\nDatabase seeded successfully.")
    print("Admin:   admin@example.com / admin123")
    print("Manager: manager@example.com / manager123")
    print("Clerk:   clerk@example.com / clerk123")
    print("Typist:  typist@example.com / typist123")