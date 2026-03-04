from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from models import db
from datetime import timedelta
import os

def create_app():
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.join(basedir, "instance")
    os.makedirs(instance_path, exist_ok=True)

    # Database: prefer DATABASE_URL (Render PostgreSQL) over local SQLite
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        db_path = os.path.join(instance_path, "inspection_system.db")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "change-in-production")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)

    # CORS
    allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "")
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()] if allowed_origins_env else []
    allowed_origins += ["http://localhost:5173", "http://localhost:3000", "http://localhost:8081"]

    CORS(app, resources={
        r"/api/*": {
            "origins": allowed_origins,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    })

    db.init_app(app)
    JWTManager(app)

    from routes.auth        import auth_bp
    from routes.users       import users_bp
    from routes.clients     import clients_bp
    from routes.properties  import properties_bp
    from routes.inspections import inspections_bp
    from routes.dashboard   import dashboard_bp
    from routes.templates   import templates_bp
    from routes.ai          import ai_bp
    from routes.section_presets import section_presets_bp
    from routes.fixed_sections import fixed_sections_bp

    app.register_blueprint(auth_bp,        url_prefix="/api/auth")
    app.register_blueprint(users_bp,       url_prefix="/api/users")
    app.register_blueprint(clients_bp,     url_prefix="/api/clients")
    app.register_blueprint(properties_bp,  url_prefix="/api/properties")
    app.register_blueprint(inspections_bp, url_prefix="/api/inspections")
    app.register_blueprint(dashboard_bp,   url_prefix="/api/dashboard")
    app.register_blueprint(templates_bp,   url_prefix="/api/templates")
    app.register_blueprint(ai_bp,          url_prefix="/api/ai")
    app.register_blueprint(section_presets_bp, url_prefix='/api/section-presets')
    app.register_blueprint(fixed_sections_bp,   url_prefix='/api/fixed-sections')

    try:
        from routes.system_settings import system_settings_bp
        app.register_blueprint(system_settings_bp, url_prefix="/api/system-settings")
    except ImportError:
        pass

    with app.app_context():
        db.create_all()

    return app
