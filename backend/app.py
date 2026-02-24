from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from models import db
from datetime import timedelta
import os


def create_app():
    app = Flask(__name__)

    # Get absolute path to backend directory
    basedir = os.path.abspath(os.path.dirname(__file__))

    # Create instance folder if it doesn't exist
    instance_path = os.path.join(basedir, 'instance')
    os.makedirs(instance_path, exist_ok=True)

    # Database path - use absolute path
    db_path = os.path.join(instance_path, 'inspection_system.db')

    # ── Configuration ────────────────────────────────────────────────────────
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

    # ── CORS Configuration ───────────────────────────────────────────────────
    # Allowed origins for CORS:
    # - Production: Vercel frontend
    # - Local dev: localhost on common ports
    # - Mobile dev: Allow all origins (Capacitor apps)
    #
    # For tighter security in production, set ALLOWED_ORIGINS env var to a
    # comma-separated list of allowed domains.

    allowed_origins = os.environ.get('ALLOWED_ORIGINS')

    if allowed_origins:
        # Production: Use explicit list from environment variable
        origins = [origin.strip() for origin in allowed_origins.split(',')]
    else:
        # Development: Allow localhost and common dev origins
        origins = [
            "http://localhost:5173",      # Vite default
            "http://localhost:3000",      # Common React port
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
            "https://lmsoftware-tau.vercel.app",  # Your Vercel production URL
        ]

    CORS(app, resources={
        r"/api/*": {
            "origins": origins,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True
        }
    })

    db.init_app(app)
    JWTManager(app)

    # ── Register Blueprints ──────────────────────────────────────────────────
    from routes.auth import auth_bp
    from routes.users import users_bp
    from routes.clients import clients_bp
    from routes.properties import properties_bp
    from routes.inspections import inspections_bp
    from routes.dashboard import dashboard_bp
    from routes.templates import templates_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(clients_bp, url_prefix='/api/clients')
    app.register_blueprint(properties_bp, url_prefix='/api/properties')
    app.register_blueprint(inspections_bp, url_prefix='/api/inspections')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(templates_bp, url_prefix='/api/templates')

    # Create tables
    with app.app_context():
        db.create_all()

    return app
