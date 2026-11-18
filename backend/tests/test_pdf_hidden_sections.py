"""Whole fixed sections the clerk deleted on the phone (report_data._hiddenFixed) must not reach the PDF."""
import json

from routes.pdf_generator import _PDFBuilder

SECTIONS = [
    {'name': 'Condition Summary', 'enabled': True, 'columns': ['name', 'condition'], 'items': [{'name': 'Walls', 'condition': ''}]},
    {'name': 'Fire Door Safety', 'enabled': True, 'columns': ['name', 'answer', 'condition'], 'items': [{'name': 'Front Door', 'answer': 'Yes', 'condition': ''}]},
    {'name': 'Health & Safety', 'enabled': True, 'columns': ['name', 'answer', 'description'], 'items': [{'name': 'Consumer Unit', 'answer': 'Yes', 'description': ''}]},
    {'name': 'Keys', 'enabled': True, 'columns': ['name', 'description'], 'items': [{'name': 'Full Sets', 'description': ''}]},
]


def _builder(world, report_data):
    from models import Inspection, SystemSetting, db
    db.session.add(SystemSetting(key='fixed_sections', value=json.dumps(SECTIONS)))
    insp = Inspection(property_id=world['property'].id, inspection_type='check_in', status='active',
                      report_data=json.dumps(report_data))
    db.session.add(insp)
    db.session.commit()
    return _PDFBuilder(insp)


def test_all_enabled_sections_present_by_default(world):
    b = _builder(world, {})
    assert [s['name'] for s in b.fixed_sections] == ['Condition Summary', 'Fire Door Safety', 'Health & Safety', 'Keys']


def test_sections_deleted_on_the_phone_are_dropped(world):
    b = _builder(world, {'_hiddenFixed': ['fs_1_fire_door_safety', 'fs_2_health___safety']})
    assert [s['name'] for s in b.fixed_sections] == ['Condition Summary', 'Keys']
    # ids keep their original index, so report_data lookups for the survivors still line up
    assert [s['id'] for s in b.fixed_sections] == ['fs_0_condition_summary', 'fs_3_keys']


def test_deleted_sections_not_built_into_the_story(world):
    b = _builder(world, {'_hiddenFixed': ['fs_1_fire_door_safety', 'fs_2_health___safety']})
    text = ' '.join(getattr(f, 'text', '') or '' for f in b._fixed_sections())
    assert 'Fire Door' not in text and 'Consumer Unit' not in text
    assert [s['id'] for s in b.fixed_sections if 'anchor_' + s['id'] in {'anchor_fs_1_fire_door_safety', 'anchor_fs_2_health___safety'}] == []
