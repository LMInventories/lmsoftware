# run.py
from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    db.create_all()

    # Auto-create admin if no users exist (safe on every restart)
    if User.query.count() == 0:
        print("No users found — seeding default admin...")
        admin = User(name='Admin', email='admin@example.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Default admin created: admin@example.com / admin123")
    else:
        print("Database ready.")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)