from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from models import db
from datetime import timedelta
import os

def create_app():
    app = Flask(__name__)

    basedir      = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.join(basedir, 'instance')
    os.makedirs(instance_path, exist_ok=True)

    # ── Database ─────────────────────────────────────────────────────────────
    # Production: set DATABASE_URL env var on Render to your PostgreSQL URL.
    # Local dev:  falls back to SQLite in instance/.
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        # Render gives postgres:// but SQLAlchemy needs postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        db_path = os.path.join(instance_path, 'inspection_system.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'dev-secret-change-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

    # ── CORS ──────────────────────────────────────────────────────────────────
    allowed_origins = os.environ.get('ALLOWED_ORIGINS', '')
    origins = [o.strip() for o in allowed_origins.split(',') if o.strip()] or [
        'http://localhost:5173',
        'http://localhost:3000',
    ]
    CORS(app, resources={
        r"/api/*": {
            "origins": origins,
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    })

    db.init_app(app)
    JWTManager(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from routes.auth        import auth_bp
    from routes.users       import users_bp
    from routes.clients     import clients_bp
    from routes.properties  import properties_bp
    from routes.inspections import inspections_bp
    from routes.dashboard   import dashboard_bp
    from routes.templates   import templates_bp
    from routes.actions     import actions_bp

    app.register_blueprint(auth_bp,        url_prefix='/api/auth')
    app.register_blueprint(users_bp,       url_prefix='/api/users')
    app.register_blueprint(clients_bp,     url_prefix='/api/clients')
    app.register_blueprint(properties_bp,  url_prefix='/api/properties')
    app.register_blueprint(inspections_bp, url_prefix='/api/inspections')
    app.register_blueprint(dashboard_bp,   url_prefix='/api/dashboard')
    app.register_blueprint(templates_bp,   url_prefix='/api/templates')
    app.register_blueprint(actions_bp,     url_prefix='/api/actions')

    # ── Create tables (no-op if they already exist) ───────────────────────────
    with app.app_context():
        db.create_all()

    return app
