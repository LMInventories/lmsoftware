"""Shared fixtures for the Telegram bot tests: a throwaway in-memory app + DB, not the real one."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def app():
    from flask import Flask
    from flask_jwt_extended import JWTManager
    from models import db

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY='test-secret',
        TESTING=True,
    )
    db.init_app(app)
    JWTManager(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def world(app):
    """A manager, a clerk, a client with one property."""
    from models import Client, Property, User, db

    manager = User(name='Mia Manager', email='mia@example.com', role='manager', password_hash='x')
    clerk = User(name='Sam Clerk', email='sam@example.com', role='clerk', password_hash='x')
    client = Client(name='Acme Lettings', email='acme@example.com')
    db.session.add_all([manager, clerk, client])
    db.session.flush()
    prop = Property(client_id=client.id, address='12 Smith Street, London, E1 6AN', bedrooms=2, bathrooms=1)
    db.session.add(prop)
    db.session.commit()
    return {'manager': manager, 'clerk': clerk, 'client': client, 'property': prop}
