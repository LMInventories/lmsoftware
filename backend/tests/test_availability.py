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
