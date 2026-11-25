"""PATCH /api/auth/me: floating camera transparency default."""
import pytest
from flask_jwt_extended import create_access_token

from routes.auth import auth_bp


@pytest.fixture()
def http(app, world):
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    token = create_access_token(identity=str(world['clerk'].id))
    return app.test_client(), {'Authorization': f'Bearer {token}'}


@pytest.mark.parametrize('sent,stored', [(50, 50), (20, 20), (99, 99), (100, None), (19, None), (0, None),
                                         (None, None), ('50', None), (True, None), (50.5, None)])
def test_opacity_is_validated(http, sent, stored):
    c, h = http
    r = c.patch('/api/auth/me', headers=h, json={'floating_camera_opacity': sent})
    assert r.status_code == 200 and r.get_json()['floating_camera_opacity'] == stored
    assert c.get('/api/auth/me', headers=h).get_json()['floating_camera_opacity'] == stored


def test_other_defaults_untouched_when_opacity_omitted(http):
    c, h = http
    c.patch('/api/auth/me', headers=h, json={'floating_camera_opacity': 60, 'camera_option': 'floating'})
    r = c.patch('/api/auth/me', headers=h, json={'typist_mode': 'human'})
    body = r.get_json()
    assert body['floating_camera_opacity'] == 60 and body['camera_option'] == 'floating' and body['typist_mode'] == 'human'
