from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from models import db
from datetime import timedelta
import os
from dotenv import load_dotenv
load_dotenv()

def create_app():
    app = Flask(__name__)

    # ── Database ────────────────────────────────────────────────────────────
    # Render (and any proper host) sets DATABASE_URL for a Postgres instance.
    # Locally we fall back to a SQLite file.
    database_url = os.environ.get('DATABASE_URL')

    if database_url:
        # Render gives postgres:// but SQLAlchemy needs postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        # Use psycopg3 driver (supports Python 3.14)
        if 'postgresql://' in database_url and '+psycopg' not in database_url:
            database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        # Local dev — SQLite
        basedir = os.path.abspath(os.path.dirname(__file__))
        instance_path = os.path.join(basedir, 'instance')
        os.makedirs(instance_path, exist_ok=True)
        db_path = os.path.join(instance_path, 'inspection_system.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ── Security ────────────────────────────────────────────────────────────
    # Set JWT_SECRET_KEY as an env var in Render dashboard. Never commit the real value.
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'dev-only-secret-change-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

    # ── CORS ────────────────────────────────────────────────────────────────
    # Explicit origins are more reliable than "*" when Authorization headers are involved.
    # Add your Vercel URL to ALLOWED_ORIGINS env var in Render, e.g.:
    #   ALLOWED_ORIGINS=https://your-app.vercel.app,https://your-app-git-main.vercel.app
    allowed_origins_env = os.environ.get('ALLOWED_ORIGINS', '')
    allowed_origins = [o.strip() for o in allowed_origins_env.split(',') if o.strip()]

    # Always include localhost for local dev
    allowed_origins += [
        'http://localhost:5173',
        'http://localhost:3000',
        'http://localhost:5000',
    ]

    CORS(app, resources={
        r'/api/*': {
            'origins':           allowed_origins,
            'methods':           ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
            'allow_headers':     ['Content-Type', 'Authorization'],
            'supports_credentials': True,
        }
    })

    db.init_app(app)
    JWTManager(app)

    # ── Blueprints ───────────────────────────────────────────────────────────
    from routes.auth        import auth_bp
    from routes.users       import users_bp
    from routes.clients     import clients_bp
    from routes.properties  import properties_bp
    from routes.inspections import inspections_bp
    from routes.dashboard   import dashboard_bp
    from routes.templates   import templates_bp
    from routes.transcribe  import transcribe_bp

    app.register_blueprint(auth_bp,         url_prefix='/api/auth')
    app.register_blueprint(users_bp,        url_prefix='/api/users')
    app.register_blueprint(clients_bp,      url_prefix='/api/clients')
    app.register_blueprint(properties_bp,   url_prefix='/api/properties')
    app.register_blueprint(inspections_bp,  url_prefix='/api/inspections')
    app.register_blueprint(dashboard_bp,    url_prefix='/api/dashboard')
    app.register_blueprint(templates_bp,    url_prefix='/api/templates')
    app.register_blueprint(transcribe_bp,   url_prefix='/api/transcribe')

    with app.app_context():
        db.create_all()

    return app
