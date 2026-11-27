"""Connecting Google: only admins/managers can start it, and the callback only accepts their state."""
import json
from urllib.parse import parse_qs, urlparse

import pytest
from flask_jwt_extended import create_access_token

from routes import google


@pytest.fixture()
def web(app, world, monkeypatch):
    app.register_blueprint(google.google_bp, url_prefix='/api/google')
    monkeypatch.setattr(google, 'CLIENT_ID', 'client-id')
    return app.test_client()


@pytest.fixture()
def exchanged(monkeypatch):
    """Stand in for Google's token and userinfo endpoints; records every call."""
    calls = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600,
                               'email': 'office@example.com'}).encode()

    monkeypatch.setattr(google.urllib.request, 'urlopen', lambda req, timeout=0: calls.append(req) or Reply())
    return calls


def _auth(user):
    return {'Authorization': f'Bearer {create_access_token(identity=str(user.id))}'}


def _state(web, user):
    res = web.post('/api/google/auth-url', headers=_auth(user))
    assert res.status_code == 200
    return parse_qs(urlparse(res.get_json()['url']).query)['state'][0]


def test_auth_url_needs_an_admin_or_manager(web, world):
    assert web.post('/api/google/auth-url').status_code == 401
    assert web.post('/api/google/auth-url', headers=_auth(world['clerk'])).status_code == 403
    assert web.get('/api/google/auth').status_code == 404     # the open redirect is gone


@pytest.mark.parametrize('query', ['code=x', 'code=x&state=made-up'])
def test_callback_without_a_valid_state_stores_nothing(web, world, exchanged, query):
    _state(web, world['manager'])                             # a real sign-in is pending
    res = web.get(f'/api/google/callback?{query}')
    assert res.status_code == 302 and 'google=error' in res.headers['Location']
    assert not exchanged and not google.is_connected()


def test_callback_with_the_issued_state_connects_once(web, world, exchanged):
    state = _state(web, world['manager'])
    res = web.get(f'/api/google/callback?code=x&state={state}')
    assert 'google=connected' in res.headers['Location']
    assert google.is_connected() and google.get_valid_access_token() == 'a'

    replay = web.get(f'/api/google/callback?code=y&state={state}')
    assert 'google=error' in replay.headers['Location']


def test_disconnect_needs_an_admin_or_manager(web, world, exchanged):
    state = _state(web, world['manager'])
    web.get(f'/api/google/callback?code=x&state={state}')
    assert web.delete('/api/google/disconnect', headers=_auth(world['clerk'])).status_code == 403
    assert google.is_connected()
    assert web.delete('/api/google/disconnect', headers=_auth(world['manager'])).status_code == 200
    assert not google.is_connected()


def test_health_warns_only_when_disconnected(web, world, exchanged):
    from models import SystemSetting, db
    db.session.add(SystemSetting(key='google_master_sheet_id', value='sheet'))
    db.session.commit()
    headers = _auth(world['manager'])
    assert web.get('/api/google/health', headers=headers).get_json()['issues'][0]['key'] == 'google'

    state = _state(web, world['manager'])
    web.get(f'/api/google/callback?code=x&state={state}')
    # an old connection is no longer reported as "expiring"
    SystemSetting.query.filter_by(key='google_connected_at').one().value = '2020-01-01T00:00:00+00:00'
    db.session.commit()
    assert web.get('/api/google/health', headers=headers).get_json()['issues'] == []
