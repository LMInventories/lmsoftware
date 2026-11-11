"""Availability guard on inspection create/update (override: admin/manager only) and /change staging."""
from datetime import date, datetime

import pytest
from flask_jwt_extended import create_access_token

from models import Inspection, User, UserUnavailability, db
from routes.inspections import inspections_bp
import routes.telegram_change as change


@pytest.fixture()
def setup(app, world):
    app.register_blueprint(inspections_bp, url_prefix='/api/inspections')
    monday = date(2026, 11, 16)  # a Monday
    db.session.add(UserUnavailability(user_id=world['clerk'].id, kind='holiday', start_date=monday, end_date=monday))
    other = User(name='Pat Clerk', email='pat@x.com', role='clerk', password_hash='x')
    db.session.add(other)
    insp = Inspection(property_id=world['property'].id, inspection_type='check_in', status='assigned',
                      inspector_id=world['clerk'].id, conduct_date=datetime(2026, 11, 17), reference_number='INS-1',
                      pdf_import=False)
    db.session.add(insp)
    db.session.commit()

    def headers(u):
        return {'Authorization': f'Bearer {create_access_token(identity=str(u.id))}'}
    return {**world, 'other': other, 'insp': insp, 'monday': monday, 'http': app.test_client(), 'headers': headers}


def test_moving_onto_unavailable_day_is_refused_with_warning(setup):
    r = setup['http'].put(f"/api/inspections/{setup['insp'].id}", json={'conduct_date': '2026-11-16T00:00:00'},
                          headers=setup['headers'](setup['manager']))
    assert r.status_code == 422
    body = r.get_json()
    assert body['code'] == 'clerk_unavailable' and body['can_override'] and 'Sam Clerk' in body['error']
    assert db.session.get(Inspection, setup['insp'].id).conduct_date == datetime(2026, 11, 17)


def test_manager_can_override(setup):
    r = setup['http'].put(f"/api/inspections/{setup['insp'].id}",
                          json={'conduct_date': '2026-11-16T00:00:00', 'override_availability': True},
                          headers=setup['headers'](setup['manager']))
    assert r.status_code == 200
    assert db.session.get(Inspection, setup['insp'].id).conduct_date == datetime(2026, 11, 16)


def test_clerk_cannot_override(setup):
    r = setup['http'].put(f"/api/inspections/{setup['insp'].id}",
                          json={'conduct_date': '2026-11-16T00:00:00', 'override_availability': True},
                          headers=setup['headers'](setup['clerk']))
    assert r.status_code == 403


def test_unchanged_values_do_not_trigger_the_guard(setup):
    insp = db.session.get(Inspection, setup['insp'].id)
    insp.conduct_date = datetime(2026, 11, 16)  # already on the blocked day
    db.session.commit()
    r = setup['http'].put(f"/api/inspections/{insp.id}", json={'conduct_date': '2026-11-16T00:00:00', 'tenant_email': 'a@b.co'},
                          headers=setup['headers'](setup['manager']))
    assert r.status_code == 200


def test_create_refuses_then_allows_override(setup):
    body = {'property_id': setup['property'].id, 'inspection_type': 'midterm',
            'inspector_id': setup['clerk'].id, 'conduct_date': '2026-11-16T00:00:00'}
    h = setup['headers'](setup['manager'])
    assert setup['http'].post('/api/inspections', json=body, headers=h).status_code == 422
    assert setup['http'].post('/api/inspections', json={**body, 'override_availability': True},
                              headers=h).status_code == 201


def test_propose_change_offers_alternatives_then_stages_override(setup):
    ctx = change.ChangeContext()
    res = change.propose_change(setup['manager'], ctx, setup['insp'].id, conduct_date='2026-11-16')
    assert res['status'] == 'clerk_unavailable' and ctx.pending is None
    assert [c['name'] for c in res['available_clerks']] == ['Pat Clerk', 'Mia Manager'] or \
        {c['name'] for c in res['available_clerks']} == {'Pat Clerk', 'Mia Manager'}

    res = change.propose_change(setup['manager'], ctx, setup['insp'].id, conduct_date='2026-11-16',
                                override_availability=True)
    assert res['status'] == 'awaiting_confirmation'
    assert ctx.pending['payload']['override_availability'] is True and ctx.pending['warnings']


def test_propose_change_with_new_clerk_needs_no_override(setup):
    ctx = change.ChangeContext()
    res = change.propose_change(setup['manager'], ctx, setup['insp'].id, conduct_date='2026-11-16', clerk_name='Pat')
    assert res['status'] == 'awaiting_confirmation'
    assert ctx.pending['payload']['inspector_id'] == setup['other'].id
    assert 'override_availability' not in ctx.pending['payload']
