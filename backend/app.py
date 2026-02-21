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

    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = 'your-secret-key-change-in-production'
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

    # CORS — allow localhost AND any local network IP (192.168.x.x, 10.x.x.x, 172.x.x.x)
    # This lets mobile devices on the same WiFi network reach the API.
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })

    db.init_app(app)
    JWTManager(app)

    # Import and register blueprints
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
