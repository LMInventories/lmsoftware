from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from models import db
from datetime import timedelta
import os

def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.join(basedir, 'instance')
    os.makedirs(instance_path, exist_ok=True)

    # ── Database ──────────────────────────────────────────────────────────────
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        database_url = database_url.replace('postgres://', 'postgresql+psycopg2://')
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://')
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        db_path = os.path.join(instance_path, 'inspection_system.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

    # ── CORS ──────────────────────────────────────────────────────────────────
    allowed_origins = [
        'http://localhost:5173',
        'http://localhost:3000',
        'http://localhost:8081',
        'https://app.lminventories.co.uk',
        'https://lmsoftware-tau.vercel.app',
    ]
    CORS(app, resources={
        r'/api/*': {
            'origins': allowed_origins,
            'methods': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
            'allow_headers': ['Content-Type', 'Authorization'],
            'supports_credentials': True,
        }
    })

    db.init_app(app)
    JWTManager(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from routes.auth            import auth_bp
    from routes.users           import users_bp
    from routes.clients         import clients_bp
    from routes.properties      import properties_bp
    from routes.inspections     import inspections_bp
    from routes.dashboard       import dashboard_bp
    from routes.templates       import templates_bp
    from routes.fixed_sections  import fixed_sections_bp
    from routes.ai              import ai_bp
    from routes.transcribe      import transcribe_bp
    from routes.pdf_import      import pdf_import_bp
    from routes.section_presets import section_presets_bp
    from routes.address_lookup  import address_lookup_bp
    from routes.email_service        import email_bp  # ← email notifications

    app.register_blueprint(auth_bp,            url_prefix='/api/auth')
    app.register_blueprint(users_bp,           url_prefix='/api/users')
    app.register_blueprint(clients_bp,         url_prefix='/api/clients')
    app.register_blueprint(properties_bp,      url_prefix='/api/properties')
    app.register_blueprint(inspections_bp,     url_prefix='/api/inspections')
    app.register_blueprint(dashboard_bp,       url_prefix='/api/dashboard')
    app.register_blueprint(templates_bp,       url_prefix='/api/templates')
    app.register_blueprint(fixed_sections_bp,  url_prefix='/api/fixed-sections')
    app.register_blueprint(ai_bp,              url_prefix='/api/ai')
    app.register_blueprint(transcribe_bp,      url_prefix='/api/transcribe')
    app.register_blueprint(pdf_import_bp,      url_prefix='/api/ai')
    app.register_blueprint(section_presets_bp, url_prefix='/api/section-presets')
    app.register_blueprint(address_lookup_bp,  url_prefix='/api/address')
    app.register_blueprint(email_bp,           url_prefix='/api/email')  # ← email notifications

    # Optional blueprints — register only if the file exists
    _optional = [
        ('routes.system_settings', 'system_settings_bp', '/api/system-settings'),
        ('routes.actions',         'actions_bp',          '/api/actions'),
    ]
    for module_name, bp_name, prefix in _optional:
        try:
            import importlib
            mod = importlib.import_module(module_name)
            app.register_blueprint(getattr(mod, bp_name), url_prefix=prefix)
        except (ImportError, AttributeError):
            pass

    with app.app_context():
        db.create_all()

    return app


# ── Scheduler (runs outside create_app so it starts once, not per request) ───
app = create_app()

from routes.email_notifications import schedule_clerk_summaries
schedule_clerk_summaries(app)


if __name__ == '__main__':
    app.run(debug=False)
