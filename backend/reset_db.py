from app import create_app
from models import db, User, Template, Section, Item
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    print("Dropping all tables...")
    db.drop_all()
    
    print("Creating all tables...")
    db.create_all()
    
    print("Creating admin user...")
    admin = User(
        name='Admin User',
        email='admin@example.com',
        password_hash=generate_password_hash('admin123'),
        role='admin'
    )
    db.session.add(admin)
    
    # Create some sample users
    print("Creating sample clerk...")
    clerk = User(
        name='John Clerk',
        email='clerk@example.com',
        password_hash=generate_password_hash('clerk123'),
        role='clerk'
    )
    db.session.add(clerk)
    
    print("Creating sample typist...")
    typist = User(
        name='Jane Typist',
        email='typist@example.com',
        password_hash=generate_password_hash('typist123'),
        role='typist'
    )
    db.session.add(typist)
    
    # Create default template
    print("Creating default template...")
    template = Template(
        name='Standard Residential Inventory',
        description='Default template for residential properties',
        inspection_type='check_in',
        is_default=True
    )
    db.session.add(template)
    db.session.flush()  # Get template.id
    
    # Add fixed sections
    print("Adding fixed sections...")
    fixed_sections = [
        {'name': 'Property Overview', 'section_type': 'fixed', 'is_required': True, 'order_index': 0},
        {'name': 'Meter Readings', 'section_type': 'fixed', 'is_required': True, 'order_index': 1},
        {'name': 'Keys & Access', 'section_type': 'fixed', 'is_required': True, 'order_index': 2},
    ]
    
    for sec_data in fixed_sections:
        section = Section(template_id=template.id, **sec_data)
        db.session.add(section)
    
    # Add room sections
    print("Adding room sections...")
    room_sections_data = [
        {'name': 'Entrance Hall', 'order_index': 3},
        {'name': 'Living Room', 'order_index': 4},
        {'name': 'Kitchen', 'order_index': 5},
        {'name': 'Bedroom 1', 'order_index': 6},
        {'name': 'Bathroom', 'order_index': 7},
    ]
    
    for room_data in room_sections_data:
        section = Section(
            template_id=template.id,
            name=room_data['name'],
            section_type='room',
            is_required=False,
            order_index=room_data['order_index']
        )
        db.session.add(section)
        db.session.flush()
        
        # Add default items to each room
        default_items = [
            {'name': 'Walls & Ceiling', 'order_index': 0},
            {'name': 'Floor & Skirting', 'order_index': 1},
            {'name': 'Windows & Frames', 'order_index': 2},
            {'name': 'Door, Frame & Furniture', 'order_index': 3},
            {'name': 'Light Fittings & Switches', 'order_index': 4},
        ]
        
        for item_data in default_items:
            item = Item(
                section_id=section.id,
                name=item_data['name'],
                description='',
                requires_photo=True,
                requires_condition=True,
                order_index=item_data['order_index']
            )
            db.session.add(item)
    
    db.session.commit()
    
    print("\n✅ Database reset complete!")
    print("\nLogin Credentials:")
    print("Admin: admin@example.com / admin123")
    print("Clerk: clerk@example.com / clerk123")
    print("Typist: typist@example.com / typist123")
