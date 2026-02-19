from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    # Check if admin already exists
    admin = User.query.filter_by(email='admin@example.com').first()
    
    if admin:
        print("Admin user already exists!")
    else:
        # Create admin user
        admin = User(
            name='Admin',
            email='admin@example.com',
            phone='',
            role='admin',
            color='#6366f1'
        )
        admin.set_password('admin123')  # Change this password!
        
        db.session.add(admin)
        db.session.commit()
        
        print("Admin user created successfully!")
        print("Email: admin@example.com")
        print("Password: admin123")
