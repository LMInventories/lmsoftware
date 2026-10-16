from datetime import date, timedelta

import pytest

from routes import telegram_flows as flows
from routes.telegram_intent import BUILD_PAYLOAD


def _cb(state, step, value):
    return flows.handle_callback(state, step, value)


def _text(state, text):
    return flows.handle_text(state, text)


def _texts(replies):
    return ' | '.join(t for t, _ in replies)


# ── Date parsing ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text, expected', [
    ('today', date(2026, 10, 12)),
    ('Tomorrow', date(2026, 10, 13)),
    ('thu', date(2026, 10, 15)),
    ('next friday', date(2026, 10, 16)),
    ('mon', date(2026, 10, 19)),          # a bare weekday is never today
    ('25/10', date(2026, 10, 25)),
    ('25/09', date(2027, 9, 25)),         # already passed this year, so next year
    ('2026-11-02', date(2026, 11, 2)),
    ('25th Sep', date(2027, 9, 25)),
    ('sep 3 2027', date(2027, 9, 3)),
    ('1/1/27', date(2027, 1, 1)),
    ('garbage', None),
    ('31/02', None),
    ('', None),
])
def test_parse_date(text, expected):
    assert flows.parse_date(text, date(2026, 10, 12)) == expected


# ── /property ───────────────────────────────────────────────────────────────

def _property_to_confirm(world):
    state, replies, _ = flows.start(flows.PROPERTY_FLOW)
    assert 'client' in _texts(replies).lower()
    state, replies, _ = _text(state, 'acme')
    assert state['step'] == 'address'
    state, replies, _ = _text(state, '10 Downing Street, London SW1A 2AA')
    assert state['step'] == 'bedrooms'
    state, _, _ = _cb(state, 'bedrooms', '3')
    state, _, _ = _text(state, '2')                       # typed bathrooms
    state, _, _ = _cb(state, 'furnished', 'p')
    state, _, _ = _cb(state, 'features', 'p')             # toggle parking
    state, _, _ = _cb(state, 'features', 'l')             # toggle lift
    state, _, _ = _cb(state, 'features', 'done')
    state, _, _ = _cb(state, 'elevation', '1')
    state, replies, _ = _cb(state, 'notes', 'skip')
    return state, replies


def test_property_flow_reaches_confirm_with_expected_payload(world):
    state, replies = _property_to_confirm(world)
    assert state['step'] == 'confirm'
    summary = _texts(replies)
    assert '10 Downing Street' in summary and 'Acme Lettings' in summary

    resolved = flows.build_resolved(state)
    payload = BUILD_PAYLOAD['create_property'](resolved)
    assert payload['client_id'] == world['client'].id
    assert (payload['bedrooms'], payload['bathrooms']) == (3, 2)
    assert payload['furnished'] == 'Part Furnished'
    assert payload['parking'] is True and payload['garden'] is False and payload['elevator'] is True
    assert payload['elevation'] == '1st Floor'

    state, replies, action = _cb(state, 'confirm', 'yes')
    assert action == 'execute'


def test_property_client_ambiguity_uses_buttons(world, app):
    from models import Client, db
    db.session.add(Client(name='Acme Estates', email='e@example.com'))
    db.session.commit()

    state, _, _ = flows.start(flows.PROPERTY_FLOW)
    state, replies, _ = _text(state, 'acme')
    assert state['step'] == 'client'
    keyboard = replies[0][1]['inline_keyboard']
    assert len(keyboard) == 2
    state, _, _ = _cb(state, 'client', '1')
    assert state['step'] == 'address' and state['data']['client_id']


def test_property_unknown_client_stays_on_step(world):
    state, _, _ = flows.start(flows.PROPERTY_FLOW)
    state, replies, _ = _text(state, 'nobody')
    assert state['step'] == 'client'
    assert 'No client matching' in _texts(replies)


def test_address_without_postcode_offers_suggestions(world, monkeypatch):
    import routes.address_lookup as address_lookup
    monkeypatch.setattr(address_lookup, 'search_suggestions',
                        lambda q: [{'address': '1 High St, Leeds LS1 1AA', 'url': 'a'}, {'address': '1 High St, York YO1 1AA', 'url': 'b'}])
    state, _, _ = flows.start(flows.PROPERTY_FLOW)
    state, _, _ = _text(state, 'acme')
    state, replies, _ = _text(state, '1 High St')
    assert state['step'] == 'address'
    labels = [b['text'] for row in replies[0][1]['inline_keyboard'] for b in row]
    assert labels[-1] == 'Keep as typed' and len(labels) == 3
    state, _, _ = _cb(state, 'address', '1')
    assert state['data']['address'] == '1 High St, York YO1 1AA'


def test_address_lookup_failure_never_blocks(world, monkeypatch):
    import routes.address_lookup as address_lookup

    def boom(q):
        raise RuntimeError('network down')
    monkeypatch.setattr(address_lookup, 'search_suggestions', boom)
    state, _, _ = flows.start(flows.PROPERTY_FLOW)
    state, _, _ = _text(state, 'acme')
    state, _, _ = _text(state, '1 High St')
    assert state['step'] == 'bedrooms' and state['data']['address'] == '1 High St'


def test_stale_button_is_ignored(world):
    state, _, _ = flows.start(flows.PROPERTY_FLOW)
    state, _, _ = _text(state, 'acme')
    before = dict(state['data'])
    state, replies, action = _cb(state, 'bedrooms', '3')   # we're on 'address'
    assert replies == [] and action is None and state['data'] == before and state['step'] == 'address'


def test_bad_number_reasks(world):
    state, _, _ = flows.start(flows.PROPERTY_FLOW)
    state, _, _ = _text(state, 'acme')
    state, _, _ = _text(state, '10 Downing Street SW1A 2AA')
    state, replies, _ = _text(state, 'lots')
    assert state['step'] == 'bedrooms' and 'number' in _texts(replies)
    state, _, _ = _text(state, 'studio')
    assert state['data']['bedrooms'] == 0 and state['step'] == 'bathrooms'


def test_edit_jumps_back_and_returns_to_confirm(world):
    state, _ = _property_to_confirm(world)
    state, replies, _ = _cb(state, 'confirm', 'edit')
    assert state['step'] == 'edit'
    state, replies, _ = _cb(state, 'edit', 'bedrooms')
    assert state['step'] == 'bedrooms'
    state, replies, _ = _cb(state, 'bedrooms', '4')
    assert state['step'] == 'confirm' and flows.build_resolved(state)['bedrooms'] == 4


def test_cancel_from_confirm(world):
    state, _ = _property_to_confirm(world)
    _, _, action = _cb(state, 'confirm', 'no')
    assert action == 'cancelled'


def test_typing_at_confirm_does_not_change_anything(world):
    state, _ = _property_to_confirm(world)
    state, replies, action = _text(state, 'make it 5 bedrooms')
    assert state['step'] == 'confirm' and action is None
    assert flows.build_resolved(state)['bedrooms'] == 3


def test_duplicate_address_warning(world):
    state, _, _ = flows.start(flows.PROPERTY_FLOW)
    state, _, _ = _text(state, 'acme')
    state, _, _ = _text(state, '12 Smith Street, London, E1 6AN')
    state, _, _ = _cb(state, 'bedrooms', '2')
    state, _, _ = _cb(state, 'bathrooms', '1')
    for step, value in (('furnished', 'skip'), ('features', 'done'), ('elevation', 'skip')):
        state, _, _ = _cb(state, step, value)
    state, replies, _ = _cb(state, 'notes', 'skip')
    assert 'already has a property' in _texts(replies)


# ── /inspection ─────────────────────────────────────────────────────────────

def _inspection_to_confirm(world, kind='check_in', clerk_value='0'):
    state, _, _ = flows.start(flows.INSPECTION_FLOW)
    state, _, _ = _text(state, 'smith')
    assert state['step'] == 'type'
    state, _, _ = _cb(state, 'type', kind)
    state, _, _ = _text(state, 'tomorrow')
    state, _, _ = _cb(state, 'time', 'am')
    assert state['step'] == 'clerk'
    state, _, _ = _cb(state, 'clerk', clerk_value)
    return state


def test_inspection_flow_skips_unneeded_steps(world):
    state = _inspection_to_confirm(world)
    # no templates and no earlier inspection, so template/source/photos were skipped silently
    assert state['step'] == 'tenant_email'
    state, _, _ = _text(state, 'tenant@example.com, other@example.com')
    state, _, _ = _cb(state, 'heads_up', 'n')
    state, replies, _ = _cb(state, 'reference', 'skip')
    assert state['step'] == 'confirm'

    resolved = flows.build_resolved(state)
    payload = BUILD_PAYLOAD['book_inspection'](resolved)
    tomorrow = flows._today_london() + timedelta(days=1)
    assert payload['property_id'] == world['property'].id
    assert payload['inspection_type'] == 'check_in'
    assert payload['conduct_date'] == f'{tomorrow.isoformat()}T00:00:00'
    assert payload['conduct_time_preference'] == 'am'
    assert payload['inspector_id'] == world['clerk'].id
    assert payload['tenant_email'] == 'tenant@example.com, other@example.com'
    assert payload['reference_number'] is None
    assert payload['create_heads_up'] is False and payload['include_photos'] is False


def test_past_date_rejected(world):
    state, _, _ = flows.start(flows.INSPECTION_FLOW)
    state, _, _ = _text(state, 'smith')
    state, _, _ = _cb(state, 'type', 'check_in')
    yesterday = (flows._today_london() - timedelta(days=1)).isoformat()
    state, replies, _ = _text(state, yesterday)
    assert state['step'] == 'date' and 'in the past' in _texts(replies)


def test_unknown_property_and_ambiguous_property(world):
    from models import Property, db
    db.session.add(Property(client_id=world['client'].id, address='14 Smith Street, London, E1 6AN', bedrooms=1, bathrooms=1))
    db.session.commit()

    state, _, _ = flows.start(flows.INSPECTION_FLOW)
    state, replies, _ = _text(state, 'zzzz')
    assert state['step'] == 'property' and 'No property matching' in _texts(replies)
    state, replies, _ = _text(state, 'smith street')
    assert state['step'] == 'property' and len(replies[0][1]['inline_keyboard']) == 2
    state, _, _ = _cb(state, 'property', '0')
    assert state['step'] == 'type'


def test_clerk_optional_only_for_midterm_and_heads_up(world):
    state, _, _ = flows.start(flows.INSPECTION_FLOW)
    state, _, _ = _text(state, 'smith')
    state, _, _ = _cb(state, 'type', 'check_out')
    state, _, _ = _text(state, 'tomorrow')
    state, replies, _ = _cb(state, 'time', 'pm')
    labels = [b['text'] for row in replies[0][1]['inline_keyboard'] for b in row]
    assert 'Unassigned' not in labels
    state, _, _ = _cb(state, 'clerk', 'none')               # refused for a check-out
    assert state['step'] == 'clerk'

    state = _inspection_to_confirm(world, kind='midterm', clerk_value='none')
    assert state['data']['inspector_id'] is None and state['step'] == 'tenant_email'


def test_clerk_availability_annotation_and_conflict_warning(world):
    from models import Inspection, db
    tomorrow = flows._today_london() + timedelta(days=1)
    from datetime import datetime
    db.session.add(Inspection(property_id=world['property'].id, inspection_type='check_in',
                              inspector_id=world['clerk'].id, conduct_date=datetime.combine(tomorrow, datetime.min.time()),
                              pdf_import=False))
    db.session.commit()

    state, _, _ = flows.start(flows.INSPECTION_FLOW)
    state, _, _ = _text(state, 'smith')
    state, _, _ = _cb(state, 'type', 'check_out')
    state, _, _ = _text(state, 'tomorrow')
    state, replies, _ = _cb(state, 'time', 'am')
    assert '1 job that day' in replies[0][1]['inline_keyboard'][0][0]['text']

    state, _, _ = _cb(state, 'clerk', '0')
    assert state['step'] == 'source'                      # the check-in above is a continuation candidate
    state, _, _ = _cb(state, 'source', 'n')
    state, _, _ = _cb(state, 'tenant_email', 'skip')
    state, _, _ = _cb(state, 'heads_up', 'n')
    state, replies, _ = _cb(state, 'reference', 'skip')
    assert 'already has 1 job' in _texts(replies)


def test_lifecycle_continuation_and_photos(world):
    from models import Inspection, db
    from datetime import datetime
    db.session.add(Inspection(property_id=world['property'].id, inspection_type='check_in',
                              conduct_date=datetime(2026, 1, 5), report_data='{}', pdf_import=False))
    db.session.commit()

    state = _inspection_to_confirm(world, kind='check_out')
    assert state['step'] == 'source'
    state, replies, _ = _cb(state, 'source', 'y')
    assert state['step'] == 'photos'
    state, replies, _ = _cb(state, 'photos', 'y')
    assert state['step'] == 'tenant_email'
    state, _, _ = _cb(state, 'tenant_email', 'skip')
    state, _, _ = _cb(state, 'heads_up', 'n')
    state, replies, _ = _cb(state, 'reference', 'skip')
    resolved = flows.build_resolved(state)
    assert resolved['source_inspection_id'] and resolved['include_photos'] is True
    assert 'Continuing from' in _texts(replies)


def test_declining_continuation_skips_photos(world):
    from models import Inspection, db
    from datetime import datetime
    db.session.add(Inspection(property_id=world['property'].id, inspection_type='check_in',
                              conduct_date=datetime(2026, 1, 5), report_data='{}', pdf_import=False))
    db.session.commit()
    state = _inspection_to_confirm(world, kind='check_out')
    state, _, _ = _cb(state, 'source', 'n')
    assert state['step'] == 'tenant_email'
    assert flows.build_resolved(state)['source_inspection_id'] is None


def test_changing_type_clears_dependent_answers_only(world):
    from models import Inspection, db
    from datetime import datetime
    db.session.add(Inspection(property_id=world['property'].id, inspection_type='check_in',
                              conduct_date=datetime(2026, 1, 5), report_data='{}', pdf_import=False))
    db.session.commit()

    state = _inspection_to_confirm(world, kind='check_out')
    state, _, _ = _cb(state, 'source', 'y')
    state, _, _ = _cb(state, 'photos', 'n')
    state, _, _ = _cb(state, 'tenant_email', 'skip')
    state, _, _ = _cb(state, 'heads_up', 'n')
    state, _, _ = _cb(state, 'reference', 'skip')
    assert state['step'] == 'confirm'

    state, _, _ = _cb(state, 'confirm', 'edit')
    state, replies, _ = _cb(state, 'edit', 'type')
    assert state['step'] == 'type'
    state, replies, _ = _cb(state, 'type', 'midterm')
    # date/time/clerk/tenant/reference are kept; the continuation answers are gone and not needed for a midterm
    assert state['step'] == 'confirm'
    resolved = flows.build_resolved(state)
    assert resolved['inspection_type'] == 'midterm' and resolved['source_inspection_id'] is None
    assert resolved['inspector_id'] == world['clerk'].id


def test_heads_up_step(world):
    state = _inspection_to_confirm(world)
    state, _, _ = _cb(state, 'tenant_email', 'skip')
    assert state['step'] == 'heads_up'
    state, _, _ = _cb(state, 'heads_up', 'y')
    state, replies, _ = _cb(state, 'reference', 'skip')
    assert state['step'] == 'confirm' and 'heads-up' in _texts(replies)
    assert BUILD_PAYLOAD['book_inspection'](flows.build_resolved(state))['create_heads_up'] is True


def test_invalid_tenant_email_reasks(world):
    state = _inspection_to_confirm(world)
    state, replies, _ = _text(state, 'not-an-email')
    assert state['step'] == 'tenant_email' and 'valid email' in _texts(replies)
