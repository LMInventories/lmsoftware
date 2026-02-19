"""
Add templates, template sections, items, and room presets tables
Run from backend directory: python migrations/add_templates.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def setup_db():
    """Setup database connection"""
    from app import create_app, db
    
    app = create_app()
    
    with app.app_context():
        return db, app

def upgrade():
    """Create tables and seed default data"""
    db, app = setup_db()
    
    print("Creating tables...")
    
    # Create templates table
    db.session.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            inspection_type VARCHAR(50) NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create template_sections table
    db.session.execute("""
        CREATE TABLE IF NOT EXISTS template_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            section_type VARCHAR(50) NOT NULL,
            order_index INTEGER DEFAULT 0,
            is_required BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
        )
    """)
    
    # Create template_section_items table
    db.session.execute("""
        CREATE TABLE IF NOT EXISTS template_section_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            order_index INTEGER DEFAULT 0,
            requires_photo BOOLEAN DEFAULT 0,
            requires_condition BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (section_id) REFERENCES template_sections(id) ON DELETE CASCADE
        )
    """)
    
    # Create room_presets table
    db.session.execute("""
        CREATE TABLE IF NOT EXISTS room_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            is_active BOOLEAN DEFAULT 1,
            items TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    db.session.commit()
    print("✅ All tables created successfully")
    
    # Seed default template
    seed_default_template(db)

def seed_default_template(db):
    """Create a default template with common rooms"""
    from app.models import Template, TemplateSection, TemplateSectionItem
    
    # Check if template already exists
    existing = Template.query.filter_by(name='Standard 1 Bed 1 Bath').first()
    if existing:
        print("ℹ️  Default template already exists - skipping seed")
        return
    
    print("Seeding default template...")
    
    # Create template
    template = Template(
        name='Standard 1 Bed 1 Bath',
        description='Standard template for 1 bedroom, 1 bathroom property',
        inspection_type='check_in'
    )
    db.session.add(template)
    db.session.flush()
    
    # Fixed sections
    fixed_sections = [
        'Cover Page',
        'Disclaimers',
        'Condition Summary',
        'Cleaning Summary',
        'Smoke & Carbon Monoxide Alarms',
        'Fire Safety',
        'Health & Safety',
        'Keys',
        'Utility Meters'
    ]
    
    for idx, section_name in enumerate(fixed_sections):
        section = TemplateSection(
            template_id=template.id,
            name=section_name,
            section_type='fixed',
            order_index=idx,
            is_required=True
        )
        db.session.add(section)
    
    # Room sections with items
    rooms = [
        {
            'name': 'Entrance / Hallway',
            'items': [
                'Door, Frame, Threshold & Furniture',
                'Door bell receiver',
                'Ceiling',
                'Lighting',
                'Walls / Skirting',
                'Switches / Sockets',
                'Flooring',
                'Additional Items / Information'
            ]
        },
        {
            'name': 'Living Room',
            'items': [
                'Door, Frame, Threshold & Furniture',
                'Ceiling',
                'Lighting',
                'Walls / Skirting',
                'Curtains / Blinds',
                'Windows',
                'Switches / Sockets',
                'Flooring',
                'Radiator(s)',
                'Additional Items / Information'
            ]
        },
        {
            'name': 'Kitchen',
            'items': [
                'Door, Frame, Threshold & Furniture',
                'Ceiling',
                'Lighting',
                'Walls / Skirting',
                'Curtains / Blinds',
                'Windows',
                'Switches / Sockets',
                'Flooring',
                'Kitchen Units, Inside and Out / Handles',
                'Hob',
                'Oven',
                'Extractor Fan',
                'Worktop(s)',
                'Sink',
                'Fridge / Freezer',
                'Washing Machine',
                'Dishwasher',
                'Additional Items / Information'
            ]
        },
        {
            'name': 'Bedroom',
            'items': [
                'Door, Frame, Threshold & Furniture',
                'Ceiling',
                'Lighting',
                'Walls / Skirting',
                'Curtains / Blinds',
                'Windows',
                'Switches / Sockets',
                'Flooring',
                'Radiator(s)',
                'Wardrobe(s)',
                'Additional Items / Information'
            ]
        },
        {
            'name': 'Bathroom',
            'items': [
                'Door, Frame, Threshold & Furniture',
                'Ceiling',
                'Lighting',
                'Walls / Skirting',
                'Windows',
                'Switches / Sockets',
                'Flooring',
                'Toilet',
                'Basin',
                'Bath / Bath Panels',
                'Shower',
                'Mirror',
                'Extractor Fan',
                'Additional Items'
            ]
        }
    ]
    
    order_offset = len(fixed_sections)
    
    for room_idx, room in enumerate(rooms):
        section = TemplateSection(
            template_id=template.id,
            name=room['name'],
            section_type='room',
            order_index=order_offset + room_idx,
            is_required=False
        )
        db.session.add(section)
        db.session.flush()
        
        for item_idx, item_name in enumerate(room['items']):
            item = TemplateSectionItem(
                section_id=section.id,
                name=item_name,
                order_index=item_idx,
                requires_photo=True,
                requires_condition=True
            )
            db.session.add(item)
    
    db.session.commit()
    print("✅ Default template seeded successfully")


if __name__ == '__main__':
    try:
        upgrade()
        print("\n🎉 Migration completed successfully!")
    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
