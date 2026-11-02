"""Property template baking: layout survives Check In -> Check Out -> Check In."""
import json

import pytest

from models import Inspection, Item, Section, Template, db
from routes.inspections import _transform_report_data
from services.property_template import bake_property_template, layout_signature, resolve_layout


@pytest.fixture()
def check_in(world):
    tpl = Template(name='Default CI', inspection_type='check_in', content='{}', is_default=True)
    db.session.add(tpl)
    db.session.flush()
    kitchen = Section(template_id=tpl.id, name='Kitchen', section_type='room', order_index=0)
    lounge = Section(template_id=tpl.id, name='Lounge', section_type='room', order_index=1)
    hall = Section(template_id=tpl.id, name='Hall', section_type='room', order_index=2)
    db.session.add_all([kitchen, lounge, hall])
    db.session.flush()
    walls, floor, oven, sofa, door = (
        Item(section_id=kitchen.id, name='Walls', order_index=0),
        Item(section_id=kitchen.id, name='Floor', order_index=1),
        Item(section_id=kitchen.id, name='Oven', order_index=2),
        Item(section_id=lounge.id, name='Sofa', order_index=0),
        Item(section_id=hall.id, name='Door', order_index=0),
    )
    db.session.add_all([walls, floor, oven, sofa, door])
    db.session.flush()

    k, l, h = str(kitchen.id), str(lounge.id), str(hall.id)
    rd = {
        '_roomNames': {l: 'Living Room'},                 # renamed
        '_hiddenRooms': [h],                              # deleted room
        '_customRooms': [{'key': 'custom_1', 'name': 'Study'}],
        '_roomOrder': ['custom_1', k, l],
        k: {
            '_deleted': [str(oven.id)],                   # deleted template item
            '_extra': [{'_eid': 'extra_1', 'name': 'Dishwasher'}],
            str(walls.id): {'description': 'Painted', 'condition': 'Good', '_photos': ['a.jpg']},
            'extra_1': {'description': 'Bosch', 'condition': 'Clean'},
        },
        l: {str(sofa.id): {'description': 'Grey', 'condition': 'Worn'}},
        'custom_1': {'_extra': [{'_eid': 'extra_2', 'name': 'Desk'}],
                     'extra_2': {'description': 'Oak', 'condition': 'Good'}},
        'fs_0_keys': {'x': 1},
    }
    insp = Inspection(property_id=world['property'].id, template_id=tpl.id, inspection_type='check_in',
                      status='complete', report_data=json.dumps(rd))
    db.session.add(insp)
    db.session.commit()
    return insp


def test_bake_preserves_rendered_layout(check_in):
    before = layout_signature(resolve_layout(check_in.template, check_in.report_data))
    assert before == [('Study', ['Desk']), ('Kitchen', ['Walls', 'Floor', 'Dishwasher']), ('Living Room', ['Sofa'])]

    new_tpl = bake_property_template(check_in)
    db.session.commit()

    assert new_tpl.is_transient and check_in.template_id == new_tpl.id
    after = layout_signature(resolve_layout(check_in.template, check_in.report_data))
    assert after == before

    rd = json.loads(check_in.report_data)
    assert not any(k in rd for k in ('_roomNames', '_hiddenRooms', '_customRooms', '_roomOrder'))
    assert rd['fs_0_keys'] == {'x': 1}
    kitchen = next(s for s in new_tpl.sections if s.name == 'Kitchen')
    walls = next(i for i in kitchen.items if i.name == 'Walls')
    assert rd[str(kitchen.id)][str(walls.id)]['_photos'] == ['a.jpg']
    dishwasher = next(i for i in kitchen.items if i.name == 'Dishwasher')
    assert rd[str(kitchen.id)][str(dishwasher.id)]['condition'] == 'Clean'


def test_bake_is_idempotent(check_in):
    bake_property_template(check_in)
    db.session.commit()
    assert bake_property_template(check_in) is None


def test_check_out_keeps_clerk_layout(check_in):
    bake_property_template(check_in)
    db.session.commit()
    sig = layout_signature(resolve_layout(check_in.template, check_in.report_data))

    co_rd = _transform_report_data('check_in', 'check_out', check_in.report_data,
                                   target_template_id=check_in.template_id)
    assert layout_signature(resolve_layout(check_in.template, co_rd)) == sig


def test_unbaked_overlay_still_carries_forward(check_in):
    """Legacy Check Ins (never baked) keep rooms, renames and deletions via the overlay."""
    sig = layout_signature(resolve_layout(check_in.template, check_in.report_data))
    co_rd = _transform_report_data('check_in', 'check_out', check_in.report_data)
    assert layout_signature(resolve_layout(check_in.template, co_rd)) == sig


def test_check_out_to_new_check_in_rebakes(world, check_in):
    """Layout changes made at Check Out become the next property template."""
    from models import Inspection
    bake_property_template(check_in)
    db.session.commit()
    kitchen = next(s for s in check_in.template.sections if s.name == 'Kitchen')

    co_rd = _transform_report_data('check_in', 'check_out', check_in.report_data,
                                   target_template_id=check_in.template_id)
    co_rd['_customRooms'] = [{'key': 'custom_9', 'name': 'Shed'}]
    co_rd['_roomNames'] = {str(kitchen.id): 'Galley'}
    co = Inspection(property_id=world['property'].id, template_id=check_in.template_id,
                    inspection_type='check_out', status='complete', report_data=json.dumps(co_rd))
    db.session.add(co)
    db.session.commit()

    ci2_rd = _transform_report_data('check_out', 'check_in', co.report_data,
                                    target_template_id=co.template_id)
    ci2 = Inspection(property_id=world['property'].id, template_id=co.template_id,
                     inspection_type='check_in', status='complete', report_data=json.dumps(ci2_rd))
    db.session.add(ci2)
    db.session.commit()
    expected = layout_signature(resolve_layout(ci2.template, ci2.report_data))
    assert ('Galley' in [r[0] for r in expected]) and ('Shed' in [r[0] for r in expected])

    new_tpl = bake_property_template(ci2)
    db.session.commit()
    assert new_tpl is not None and new_tpl.id != check_in.template_id
    assert layout_signature(resolve_layout(ci2.template, ci2.report_data)) == expected
    assert bake_property_template(ci2) is None


@pytest.mark.parametrize('src,dst', [('check_in', 'check_out'), ('check_out', 'check_in'), ('check_in', 'check_in')])
def test_room_overview_photos_follow_include_photos(src, dst):
    rd = {'7': {'_overview': {'_photos': ['o1.jpg'], '_photoTs': ['t1'], 'junk': 1},
                '9': {'description': 'x', '_photos': ['i.jpg']}}}
    on = _transform_report_data(src, dst, rd, include_photos=True)
    off = _transform_report_data(src, dst, rd, include_photos=False)
    assert on['7']['_overview'] == {'_photos': ['o1.jpg'], '_photoTs': ['t1']}
    assert on['7']['9']['_photos'] == ['i.jpg']
    assert '_overview' not in off['7'] and '_photos' not in off['7']['9']


def test_check_out_to_check_in_lists_all_conditions():
    rd = {'7': {
        '1': {'description': 'Walls', 'inventoryCondition': 'Painted white', 'checkOutCondition': 'As Inventory, scuffed',
              '_subs': [{'_sid': 's1', 'description': 'Skirting', 'inventoryCondition': 'White',
                         'checkOutCondition': 'Chipped'}]},
        '_extra': [{'_eid': 'e1', 'name': 'Lamp', 'inventoryCondition': 'New', 'checkOutCondition': 'Cracked shade'}],
    }}
    out = _transform_report_data('check_out', 'check_in', rd)['7']
    assert out['1']['condition'] == 'Painted white, scuffed'
    assert out['1']['_subs'][0]['condition'] == 'White, chipped'
    assert out['_extra'][0]['condition'] == 'New, cracked shade'
    assert 'checkOutCondition' not in out['1'] and 'inventoryCondition' not in out['1']


def test_additional_items_create_contents_when_room_has_none(check_in):
    """A room with no Contents item gets one, and it survives baking."""
    kitchen = next(s for s in check_in.template.sections if s.name == 'Kitchen')
    k = str(kitchen.id)
    co_rd = {k: {'_customItems': [{'_cid': 'c1', 'name': 'Vase', 'description': 'Blue', 'checkOutCondition': 'Broken'}]},
             'custom_1': {'_customItems': [{'_cid': 'c2', 'name': 'Lamp', 'checkOutCondition': 'Cracked'}]},
             '_customRooms': [{'key': 'custom_1', 'name': 'Study'}]}
    out = _transform_report_data('check_out', 'check_in', co_rd, target_template_id=check_in.template_id)

    for room in (k, 'custom_1'):
        eid = f'extra_contents_{room}'
        assert {'_eid': eid, 'name': 'Contents'} in out[room]['_extra']
        # No Contents existed: the first Additional Item is the lead item, not a sub-item.
        assert out[room][eid]['condition'] in ('Broken', 'Cracked')
        assert out[room][eid]['description'] in ('Vase — Blue', 'Lamp')
        assert out[room][eid].get('_subs', []) == []
    # Running it again must not add a second Contents item.
    again = _transform_report_data('check_out', 'check_in', {**co_rd, k: {**co_rd[k], '_extra': out[k]['_extra']}},
                                   target_template_id=check_in.template_id)
    assert sum(1 for e in again[k]['_extra'] if e['name'] == 'Contents') == 1

    check_in.report_data = json.dumps(out)
    new_tpl = bake_property_template(check_in)
    db.session.commit()
    names = {r['name']: [i['name'] for i in r['items']] for r in resolve_layout(new_tpl, check_in.report_data)}
    assert 'Contents' in names['Kitchen'] and names['Study'] == ['Contents']


def test_first_additional_item_leads_remaining_become_subs():
    rd = {'7': {'_customItems': [
        {'_cid': 'c1', 'name': 'Vase', 'description': 'Blue', 'checkOutCondition': 'Broken'},
        {'_cid': 'c2', 'name': 'Lamp', 'checkOutCondition': 'Cracked'},
        {'_cid': 'c3', 'name': 'Rug', 'checkOutCondition': 'Stained'}],
        'c1': {'_photos': ['v.jpg']}}}
    row = _transform_report_data('check_out', 'check_in', rd, include_photos=True)['7']['extra_contents_7']
    assert (row['description'], row['condition'], row['_photos']) == ('Vase \u2014 Blue', 'Broken', ['v.jpg'])
    assert [(s['_sid'], s['description'], s['condition']) for s in row['_subs']] == [
        ('c2', 'Lamp', 'Cracked'), ('c3', 'Rug', 'Stained')]
