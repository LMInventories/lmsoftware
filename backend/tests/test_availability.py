"""Availability API: role restrictions and the slot-coverage rules."""
from datetime import date

import pytest
from flask_jwt_extended import create_access_token

from models import User, db
from routes.availability import availability_bp
from services.availability import unavailable_user_ids


@pytest.fixture()
def client_for(app, world):
    app.register_blueprint(availability_bp, url_prefix='/api/availability')
    http = app.test_client()

    def make(role):
        u = User(name=role, email=f'{role}@x.com', role=role, password_hash='x')
        db.session.add(u)
        db.session.commit()
        return u, {'Authorization': f'Bearer {create_access_token(identity=str(u.id))}'}

    return http, make


@pytest.mark.parametrize('role,allowed', [('clerk', True), ('manager', True), ('admin', True),
                                          ('typist', False), ('client', False)])
def test_only_clerks_managers_admins_manage_availability(client_for, role, allowed):
    http, make = client_for
    _, headers = make(role)
    body = {'kind': 'repeating', 'weekday': 0, 'start_min': None, 'end_min': None}
    assert http.get('/api/availability/me', headers=headers).status_code == (200 if allowed else 403)
    assert http.post('/api/availability/me', json=body, headers=headers).status_code == (201 if allowed else 403)


def test_unavailable_clerk_detected_for_slot(client_for):
    http, make = client_for
    clerk, headers = make('clerk')
    http.post('/api/availability/me', headers=headers,
              json={'kind': 'repeating', 'weekday': 0, 'start_min': 480, 'end_min': 720})  # Mon 08-12
    monday = date(2026, 11, 9)
    assert clerk.id in unavailable_user_ids(monday, 'am')
    assert clerk.id not in unavailable_user_ids(monday, 'pm')
    assert clerk.id not in unavailable_user_ids(date(2026, 11, 10), 'am')


def _block(http, headers, user_id=None, weekday=1):
    url = '/api/availability/me' + (f'?user_id={user_id}' if user_id else '')
    return http.post(url, headers=headers,
                     json={'kind': 'repeating', 'weekday': weekday, 'start_min': None, 'end_min': None})


def test_clerk_cannot_touch_anyone_elses_availability(client_for):
    http, make = client_for
    clerk, ch = make('clerk')
    other = User(name='other', email='other@x.com', role='clerk', password_hash='x')
    db.session.add(other)
    db.session.commit()
    _, oh = make('manager')
    theirs = _block(http, oh, user_id=other.id).get_json()

    assert _block(http, ch, user_id=other.id).status_code == 403
    assert http.get(f'/api/availability/me?user_id={other.id}', headers=ch).status_code == 403
    assert http.delete(f'/api/availability/me/{theirs["id"]}', headers=ch).status_code == 404
    assert http.put(f'/api/availability/me/{theirs["id"]}', headers=ch,
                    json={'kind': 'repeating', 'weekday': 2}).status_code == 404
    assert http.get('/api/availability/team', headers=ch).status_code == 403
    # their own id is still fine
    assert _block(http, ch, user_id=clerk.id).status_code == 201


def test_manager_can_manage_a_clerks_availability_and_see_the_team(client_for):
    http, make = client_for
    clerk, _ = make('clerk')
    _, mh = make('manager')
    res = _block(http, mh, user_id=clerk.id)
    assert res.status_code == 201
    team = {u['id']: u for u in http.get('/api/availability/team', headers=mh).get_json()}
    assert clerk.id in team and len(team[clerk.id]['blocks']) == 1 and team[clerk.id]['color']
    assert http.put(f'/api/availability/me/{res.get_json()["id"]}', headers=mh,
                    json={'kind': 'repeating', 'weekday': 3}).status_code == 200
    assert http.delete(f'/api/availability/me/{res.get_json()["id"]}', headers=mh).status_code == 204
    # typists/clients can't be targeted
    typist, _ = make('typist')
    assert _block(http, mh, user_id=typist.id).status_code == 404


@pytest.mark.parametrize('role,allowed', [('admin', True), ('manager', True), ('clerk', True),
                                          ('typist', True), ('client', False)])
def test_unavailable_lookup_is_staff_only(client_for, role, allowed):
    http, make = client_for
    _, headers = make(role)
    res = http.get('/api/availability/unavailable?date=2026-11-09&time=am', headers=headers)
    assert res.status_code == (200 if allowed else 403)
