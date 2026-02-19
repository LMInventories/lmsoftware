"""
Simple script to create template tables
Run: python create_templates_tables.py
"""
from run import app
from app import db
from app.models import Template, TemplateSection, TemplateSectionItem
from sqlalchemy import text

def main():
    with app.app_context():
        print("Dropping old template tables if they exist...")
        
        # Drop tables in reverse order (children first) using text()
        try:
            db.session.execute(text("DROP TABLE IF EXISTS template_section_items"))
            db.session.execute(text("DROP TABLE IF EXISTS template_sections"))
            db.session.execute(text("DROP TABLE IF EXISTS templates"))
            db.session.execute(text("DROP TABLE IF EXISTS room_presets"))
            db.session.commit()
            print("✅ Old tables dropped")
        except Exception as e:
            print(f"Error dropping tables: {e}")
            db.session.rollback()
        
        print("Creating new tables...")
        db.create_all()
        print("✅ Tables created")
        
        print("Creating default template...")
        
        # Create template
        template = Template(
            name='Standard 1 Bed 1 Bath',
            description='Standard template for 1 bedroom, 1 bathroom property',
            inspection_type='check_in'
        )
        db.session.add(template)
        db.session.flush()
        
        # Add fixed sections
        fixed_sections = [
            'Cover Page', 'Disclaimers', 'Condition Summary', 'Cleaning Summary',
            'Smoke & Carbon Monoxide Alarms', 'Fire Safety', 'Health & Safety', 
            'Keys', 'Utility Meters'
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
        
        # Add rooms
        rooms = [
            {
                'name': 'Entrance / Hallway', 
                'items': ['Door, Frame, Threshold & Furniture', 'Door bell receiver', 'Ceiling', 'Lighting', 'Walls / Skirting', 'Switches / Sockets', 'Flooring', 'Additional Items / Information']
            },
            {
                'name': 'Living Room', 
                'items': ['Door, Frame, Threshold & Furniture', 'Ceiling', 'Lighting', 'Walls / Skirting', 'Curtains / Blinds', 'Windows', 'Switches / Sockets', 'Flooring', 'Radiator(s)', 'Additional Items / Information']
            },
            {
                'name': 'Kitchen', 
                'items': ['Door, Frame, Threshold & Furniture', 'Ceiling', 'Lighting', 'Walls / Skirting', 'Curtains / Blinds', 'Windows', 'Switches / Sockets', 'Flooring', 'Kitchen Units, Inside and Out / Handles', 'Hob', 'Oven', 'Extractor Fan', 'Worktop(s)', 'Sink', 'Fridge / Freezer', 'Washing Machine', 'Dishwasher', 'Additional Items / Information']
            },
            {
                'name': 'Bedroom', 
                'items': ['Door, Frame, Threshold & Furniture', 'Ceiling', 'Lighting', 'Walls / Skirting', 'Curtains / Blinds', 'Windows', 'Switches / Sockets', 'Flooring', 'Radiator(s)', 'Wardrobe(s)', 'Additional Items / Information']
            },
            {
                'name': 'Bathroom', 
                'items': ['Door, Frame, Threshold & Furniture', 'Ceiling', 'Lighting', 'Walls / Skirting', 'Windows', 'Switches / Sockets', 'Flooring', 'Toilet', 'Basin', 'Bath / Bath Panels', 'Shower', 'Mirror', 'Extractor Fan', 'Additional Items']
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
        print("✅ Default template created successfully!")
        print("\n🎉 All done!")
        print("\nYou can now:")
        print("1. Start your backend: python run.py")
        print("2. Visit: http://localhost:5000/api/templates")

if __name__ == '__main__':
    main()
