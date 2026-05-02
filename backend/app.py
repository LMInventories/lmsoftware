from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_compress import Compress
from models import db
from datetime import timedelta
import os
import json


def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.join(basedir, 'instance')
    os.makedirs(instance_path, exist_ok=True)

    # ── Database ──────────────────────────────────────────────────────────────
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        database_url = database_url.replace('postgres://', 'postgresql+psycopg://')
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg://')
        database_url = database_url.replace('postgresql+psycopg2://', 'postgresql+psycopg://')
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        db_path = os.path.join(instance_path, 'inspection_system.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ── Connection pool ───────────────────────────────────────────────────────
    # pool_pre_ping    — test each connection before use; discards stale sockets
    # pool_recycle     — replace connections after 5 min (before Railway kills them)
    # pool_use_lifo    — prefer freshest connections; cold connections are more
    #                    likely to have been silently closed by the server
    # connect_args     — TCP keepalives every 60s so the SSL session survives
    #                    Railway's idle timeout without an unexpected EOF
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size':       10,
        'max_overflow':     5,
        'pool_recycle':   300,   # seconds
        'pool_pre_ping':  True,
        'pool_timeout':    30,
        'pool_use_lifo':  True,
        'connect_args': {
            'keepalives':          1,
            'keepalives_idle':    60,
            'keepalives_interval': 10,
            'keepalives_count':    5,
        },
    }

    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
    # Allow large sync payloads (150+ compressed photos + audio).
    # Photos are compressed on device to ~120KB each; 200 photos ≈ 25MB.
    # We set 150MB as a generous ceiling — if even this is hit, photos need
    # separate upload endpoints rather than inline base64.
    app.config['MAX_CONTENT_LENGTH'] = 150 * 1024 * 1024  # 150 MB

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Base origins always allowed (localhost for dev, custom domain for prod)
    allowed_origins = [
        'http://localhost:5173',
        'http://localhost:3000',
        'http://localhost:8081',
        'https://app.lminventories.co.uk',
    ]
    # CORS_ORIGINS env var: comma-separated extra origins (set to your Railway
    # frontend URL in the Railway dashboard, e.g. https://xxx.up.railway.app)
    extra_origins = os.environ.get('CORS_ORIGINS', '')
    for origin in extra_origins.split(','):
        origin = origin.strip()
        if origin:
            allowed_origins.append(origin)

    CORS(app, resources={
        r'/api/*': {
            'origins': allowed_origins,
            'methods': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
            'allow_headers': ['Content-Type', 'Authorization'],
            'supports_credentials': True,
        }
    })

    # ── Health check (used by Railway, load balancers, uptime monitors) ───────
    @app.route('/health')
    def health():
        return {'status': 'ok'}, 200

    # ── Global error handlers ─────────────────────────────────────────────────
    import traceback
    import logging

    @app.errorhandler(Exception)
    def handle_unhandled_exception(e):
        # Let Flask's built-in HTTP exceptions (404, 405, etc.) pass through
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        tb = traceback.format_exc()
        logging.error('Unhandled exception:\n%s', tb)
        return {'error': 'Internal server error', 'detail': str(e)}, 500

    @app.errorhandler(500)
    def handle_500(e):
        tb = traceback.format_exc()
        logging.error('500 error:\n%s', tb)
        return {'error': 'Internal server error', 'detail': str(e)}, 500

    db.init_app(app)
    JWTManager(app)

    # ── Gzip compression ──────────────────────────────────────────────────────
    # Compresses JSON API responses before sending to the client.
    # Inspection reports embed base64 photos so payloads can be 500KB–5MB.
    # Gzip typically achieves 60-80% reduction on JSON/base64 text, meaning a
    # 2MB inspection download becomes 400-800KB — a 2-4× speed improvement on
    # the wire, especially noticeable on mobile or slower connections.
    app.config['COMPRESS_REGISTER'] = True
    app.config['COMPRESS_LEVEL'] = 6        # good balance of speed vs ratio
    app.config['COMPRESS_MIN_SIZE'] = 1000  # only compress responses > 1KB
    Compress(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from routes.auth            import auth_bp
    from routes.auth_reset      import auth_reset_bp
    from routes.users           import users_bp
    from routes.clients         import clients_bp
    from routes.properties      import properties_bp
    from routes.inspections     import inspections_bp
    from routes.dashboard       import dashboard_bp
    from routes.templates       import templates_bp
    from routes.fixed_sections  import fixed_sections_bp, midterm_sections_bp
    from routes.ai              import ai_bp
    from routes.transcribe      import transcribe_bp
    from routes.pdf_import      import pdf_import_bp
    from routes.section_presets import section_presets_bp
    from routes.address_lookup  import address_lookup_bp
    from routes.email_notifications  import email_bp
    from routes.gallery              import gallery_bp
    from routes.photos               import photos_bp

    app.register_blueprint(auth_bp,            url_prefix='/api/auth')
    app.register_blueprint(auth_reset_bp,      url_prefix='/api/auth')
    app.register_blueprint(users_bp,           url_prefix='/api/users')
    app.register_blueprint(clients_bp,         url_prefix='/api/clients')
    app.register_blueprint(properties_bp,      url_prefix='/api/properties')
    app.register_blueprint(inspections_bp,     url_prefix='/api/inspections')
    app.register_blueprint(dashboard_bp,       url_prefix='/api/dashboard')
    app.register_blueprint(templates_bp,       url_prefix='/api/templates')
    app.register_blueprint(fixed_sections_bp,   url_prefix='/api/fixed-sections')
    app.register_blueprint(midterm_sections_bp, url_prefix='/api/midterm-sections')
    app.register_blueprint(ai_bp,              url_prefix='/api/ai')
    app.register_blueprint(transcribe_bp,      url_prefix='/api/transcribe')
    app.register_blueprint(pdf_import_bp,      url_prefix='/api/ai')
    app.register_blueprint(section_presets_bp, url_prefix='/api/section-presets')
    app.register_blueprint(address_lookup_bp,  url_prefix='/api/address')
    app.register_blueprint(email_bp,           url_prefix='/api/email')
    app.register_blueprint(gallery_bp,         url_prefix='/api')
    app.register_blueprint(photos_bp,          url_prefix='/api/photos')

    # Optional blueprints — register only if the file exists
    _optional = [
        ('routes.system_settings', 'system_settings_bp', '/api/system-settings'),
        ('routes.actions',         'actions_bp',          '/api/actions'),
        ('routes.google',          'google_bp',           '/api/google'),
    ]
    import importlib
    for module_name, bp_name, prefix in _optional:
        try:
            mod = importlib.import_module(module_name)
            app.register_blueprint(getattr(mod, bp_name), url_prefix=prefix)
            print(f'✅ Optional blueprint registered: {module_name} → {prefix}')
        except Exception as e:
            print(f'⚠️  Optional blueprint FAILED: {module_name} — {type(e).__name__}: {e}')

    # ── DB setup: tables + column migrations + seed ───────────────────────────
    # Runs every boot — all operations are safe/idempotent on an existing DB.
    with app.app_context():
        _setup_database()

    return app


def _setup_database():
    """Create tables, run column migrations, and seed a fresh database."""
    from models import User, Client, Property, SystemSetting
    from sqlalchemy import text

    db.create_all()

    # ── Column migrations (safe to run on every boot) ────────────────────────
    def _is_sqlite():
        return 'sqlite' in str(db.engine.url)

    def column_exists(table, column):
        if _is_sqlite():
            rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
            return any(row[1] == column for row in rows)
        else:
            row = db.session.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"
            ), {'t': table, 'c': column}).fetchone()
            return row is not None

    def _alter_column(label: str, alter_sql: str):
        """
        Run an ALTER TABLE with retry + lock-timeout on PostgreSQL.

        During a Railway blue-green deploy the old pod's SQLAlchemy connection
        pool may hold ACCESS SHARE locks on the table, blocking the ACCESS
        EXCLUSIVE lock that ALTER TABLE needs.

        Strategy:
          • Set lock_timeout = 3 s so each attempt fails fast instead of hanging.
          • Retry up to 7 times with increasing delays (total ≈ 38 s wait, well
            within Railway's 300 s healthcheck window).
          • If all retries fail, RAISE so gunicorn never starts, the healthcheck
            fails, and Railway keeps the old deployment live — the operator can
            simply redeploy once traffic has drained.  This is the safe outcome:
            the app never runs with a mismatched schema.
        """
        import time
        print(f"Migrating: {label}...")
        # pre-attempt delay in seconds: first try is immediate, then back-off
        retry_schedule = [0, 2, 4, 8, 8, 8, 8]   # sum of waits = 38 s

        for attempt, pre_delay in enumerate(retry_schedule):
            if pre_delay:
                print(f"  ↻ {label}: lock contention, retrying in {pre_delay}s "
                      f"(attempt {attempt + 1}/{len(retry_schedule)})…")
                time.sleep(pre_delay)
            try:
                if not _is_sqlite():
                    # Fail fast per attempt — never hang more than 3 s at a time.
                    db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
                db.session.execute(text(alter_sql))
                db.session.commit()
                print(f"✅ {label}")
                return True
            except Exception as exc:
                db.session.rollback()
                if attempt < len(retry_schedule) - 1:
                    print(f"  ⚠ {label} attempt {attempt + 1} failed: {exc}")
                else:
                    # All retries exhausted.  Abort so Railway keeps the old
                    # deployment live and the operator can retry the deploy.
                    raise RuntimeError(
                        f"Migration '{label}' could not acquire a lock after "
                        f"{len(retry_schedule)} attempts (~{sum(retry_schedule)}s total). "
                        f"Aborting startup — redeploy once lock contention clears."
                    ) from exc

    # users.is_ai — added when AI Typist feature was introduced
    if not column_exists('users', 'is_ai'):
        default = "0" if _is_sqlite() else "FALSE"
        _alter_column("users.is_ai",
                      f"ALTER TABLE users ADD COLUMN is_ai BOOLEAN NOT NULL DEFAULT {default}")

    # users.typist_mode — 'ai_instant' | 'ai_room' | 'human' | null
    if not column_exists('users', 'typist_mode'):
        _alter_column("users.typist_mode",
                      "ALTER TABLE users ADD COLUMN typist_mode VARCHAR(20)")

    # inspections.typist_mode — per-inspection override of clerk-level typist_mode
    if not column_exists('inspections', 'typist_mode'):
        _alter_column("inspections.typist_mode",
                      "ALTER TABLE inspections ADD COLUMN typist_mode VARCHAR(20)")

    # inspections.tenant_name — tenant's full name for AIIC-compliant cover page
    if not column_exists('inspections', 'tenant_name'):
        _alter_column("inspections.tenant_name",
                      "ALTER TABLE inspections ADD COLUMN tenant_name VARCHAR(255)")

    # inspections.landlord_email — landlord email for report distribution
    if not column_exists('inspections', 'landlord_email'):
        _alter_column("inspections.landlord_email",
                      "ALTER TABLE inspections ADD COLUMN landlord_email VARCHAR(255)")

    # inspections.reference_number — links inspection to an invoice/billing reference
    if not column_exists('inspections', 'reference_number'):
        _alter_column("inspections.reference_number",
                      "ALTER TABLE inspections ADD COLUMN reference_number VARCHAR(100)")

    # ── Deposit / Depositary fields ───────────────────────────────────────────
    for _col, _ddl in [
        ('deposit_amount',        'NUMERIC(10,2)'),
        ('deposit_scheme',        'VARCHAR(50)'),
        ('deposit_ref',           'VARCHAR(255)'),
        ('depositary_tenancy_id', 'VARCHAR(255)'),
        ('depositary_pushed_at',  'TIMESTAMP'),
    ]:
        if not column_exists('inspections', _col):
            _alter_column(f"inspections.{_col}",
                          f"ALTER TABLE inspections ADD COLUMN {_col} {_ddl}")

    # items.answer_options — JSON array of selectable answers for question-type template items
    if not column_exists('items', 'answer_options'):
        _alter_column("items.answer_options",
                      "ALTER TABLE items ADD COLUMN answer_options TEXT DEFAULT ''")

    # templates.is_transient — PDF-import templates are hidden from the Templates UI
    if not column_exists('templates', 'is_transient'):
        default = "0" if _is_sqlite() else "FALSE"
        _alter_column("templates.is_transient",
                      f"ALTER TABLE templates ADD COLUMN is_transient BOOLEAN DEFAULT {default}")

    # clients.logo_inverted — pre-made white/inverted logo for coloured PDF cover footer
    if not column_exists('clients', 'logo_inverted'):
        _alter_column("clients.logo_inverted",
                      "ALTER TABLE clients ADD COLUMN logo_inverted TEXT")

    # clients.invert_logo — use inverted logo on PDF cover footer
    if not column_exists('clients', 'invert_logo'):
        default = "0" if _is_sqlite() else "FALSE"
        _alter_column("clients.invert_logo",
                      f"ALTER TABLE clients ADD COLUMN invert_logo BOOLEAN DEFAULT {default}")

    # clients.report_footer_text_color — custom colour for footer company name + email text
    if not column_exists('clients', 'report_footer_text_color'):
        _alter_column("clients.report_footer_text_color",
                      "ALTER TABLE clients ADD COLUMN report_footer_text_color VARCHAR(7)")

    # inspections.completion_email_sent — prevents auto email re-sending on re-completion
    if not column_exists('inspections', 'completion_email_sent'):
        default = "0" if _is_sqlite() else "FALSE"
        _alter_column("inspections.completion_email_sent",
                      f"ALTER TABLE inspections ADD COLUMN completion_email_sent BOOLEAN NOT NULL DEFAULT {default}")

    # ── Reset midterm_sections to v2 defaults if still on old v1 schema ───────
    # The original defaults used "Property Condition Overview" / "Safety & Alarms";
    # the v2 defaults match the industry-standard midterm format (Overview, Keys,
    # Smoke & CO). Reset only if the stored data still has the old first section name.
    _ms = SystemSetting.query.filter_by(key='midterm_sections').first()
    if _ms and _ms.value:
        try:
            _ms_data = json.loads(_ms.value)
            if _ms_data and _ms_data[0].get('name') in ('Property Condition Overview', 'Safety & Alarms'):
                from routes.fixed_sections import DEFAULT_MIDTERM_SECTIONS as _DMS
                _ms.value = json.dumps(_DMS)
                db.session.commit()
                print('✅ Migrated midterm_sections to v2 defaults.')
        except Exception:
            pass

    # ── Performance indexes ──────────────────────────────────────────────────
    # CREATE INDEX IF NOT EXISTS is safe to run on every boot — a no-op when the
    # index already exists. These cover the most frequent filter/join columns so
    # that list queries and dashboard aggregations don't do full table scans.
    _indexes = [
        'CREATE INDEX IF NOT EXISTS idx_inspections_property_id  ON inspections(property_id)',
        'CREATE INDEX IF NOT EXISTS idx_inspections_inspector_id ON inspections(inspector_id)',
        'CREATE INDEX IF NOT EXISTS idx_inspections_typist_id    ON inspections(typist_id)',
        'CREATE INDEX IF NOT EXISTS idx_inspections_status       ON inspections(status)',
        'CREATE INDEX IF NOT EXISTS idx_inspections_conduct_date ON inspections(conduct_date)',
        'CREATE INDEX IF NOT EXISTS idx_inspections_created_at   ON inspections(created_at)',
        'CREATE INDEX IF NOT EXISTS idx_properties_client_id     ON properties(client_id)',
    ]
    for idx_sql in _indexes:
        try:
            db.session.execute(text(idx_sql))
        except Exception:
            db.session.rollback()
    db.session.commit()

    # ── Seed standard midterm room section presets ───────────────────────────
    # These presets appear in the template editor "From Preset" picker and give
    # clerks a one-click starting point for each midterm room section.
    _MIDTERM_PRESETS = [
        {
            'name': 'Standard Midterm Room',
            'description': 'Core condition checks for any room — walls, furnishings, flooring, decorative standard, cleanliness.',
            'items': [
                {'name': 'Overview Photos',          'description': 'Room overview', 'requires_photo': True,  'requires_condition': False, 'answer_options': ''},
                {'name': 'Any damage to walls?',     'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to furnishings?','description': '',             'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to flooring?',  'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Decorative standard',      'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
                {'name': 'Cleanliness & Tidiness',   'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
            ],
        },
        {
            'name': 'Midterm Bathroom / Ensuite',
            'description': 'Standard midterm room items plus sanitary ware check.',
            'items': [
                {'name': 'Overview Photos',             'description': 'Room overview', 'requires_photo': True,  'requires_condition': False, 'answer_options': ''},
                {'name': 'Any damage to walls?',        'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to furnishings?',  'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to flooring?',     'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any issues with sanitary ware?', 'description': '',           'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Decorative standard',         'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
                {'name': 'Cleanliness & Tidiness',      'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
            ],
        },
        {
            'name': 'Midterm Kitchen',
            'description': 'Standard midterm room items plus appliances and sanitary ware checks.',
            'items': [
                {'name': 'Overview Photos',             'description': 'Room overview', 'requires_photo': True,  'requires_condition': False, 'answer_options': ''},
                {'name': 'Any damage to walls?',        'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to furnishings?',  'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to flooring?',     'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any issues with sanitary ware?', 'description': '',           'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Appliances',                  'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Decorative standard',         'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
                {'name': 'Cleanliness & Tidiness',      'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
            ],
        },
        {
            'name': 'Midterm Balcony / Terrace',
            'description': 'Outdoor area checks — walls, furnishings, flooring, decorative standard, cleanliness.',
            'items': [
                {'name': 'Overview Photos',             'description': 'Area overview', 'requires_photo': True,  'requires_condition': False, 'answer_options': ''},
                {'name': 'Any damage to walls?',        'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to furnishings?',  'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Any damage to flooring?',     'description': '',              'requires_photo': True,  'requires_condition': True,  'answer_options': ''},
                {'name': 'Decorative standard',         'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
                {'name': 'Cleanliness & Tidiness',      'description': '',              'requires_photo': False, 'requires_condition': True,  'answer_options': ''},
            ],
        },
    ]

    from models import SectionPreset
    import json as _json
    for _preset_data in _MIDTERM_PRESETS:
        exists = SectionPreset.query.filter_by(name=_preset_data['name']).first()
        if not exists:
            _preset = SectionPreset(
                name=_preset_data['name'],
                description=_preset_data['description'],
                category='room',
                items_json=_json.dumps(_preset_data['items']),
            )
            db.session.add(_preset)
            print(f"Seeded section preset: {_preset_data['name']}")
    db.session.commit()

    # ── Seed (only on a completely empty database) ───────────────────────────
    if User.query.count() == 0:
        print("Fresh database — seeding demo data...")

        admin = User(name='Admin', email='admin@example.com', role='admin', color='#6366f1')
        admin.set_password('admin123')

        manager = User(name='Manager', email='manager@example.com', role='manager', color='#8b5cf6')
        manager.set_password('manager123')

        clerk = User(name='Robyn Lee', email='clerk@example.com', role='clerk', color='#10b981')
        clerk.set_password('clerk123')

        typist = User(name='Sarah Typist', email='typist@example.com', role='typist', color='#f59e0b')
        typist.set_password('typist123')

        ai_typist = User(
            name='AI Typist',
            email='ai.typist@system.local',
            role='typist',
            color='#6366f1',
            is_ai=True,
        )
        ai_typist.set_password('system-' + os.urandom(16).hex())

        db.session.add_all([admin, manager, clerk, typist, ai_typist])
        db.session.flush()

        client = Client(
            name='Yellands Estates',
            email='info@yellands.co.uk',
            phone='020 1234 5678',
            company='Yellands Estates',
            primary_color='#1E3A8A',
            report_disclaimer=(
                'This report has been prepared with reasonable care and skill. '
                'The contents of this report are confidential to the instructing parties. '
                'All measurements are approximate.'
            )
        )
        db.session.add(client)
        db.session.flush()

        prop = Property(
            client_id=client.id,
            address='15 Cam Green, South Ockendon, RM15 5QN',
            property_type='residential',
            bedrooms=2,
            bathrooms=1,
            furnished=False,
            parking=True,
            garden=True,
        )
        db.session.add(prop)
        db.session.commit()
        print("✅ Database seeded.")

    else:
        # Existing DB — ensure AI Typist system account exists
        if not User.query.filter_by(email='ai.typist@system.local').first():
            print("Adding AI Typist system account...")
            ai_typist = User(
                name='AI Typist',
                email='ai.typist@system.local',
                role='typist',
                color='#6366f1',
                is_ai=True,
            )
            ai_typist.set_password('system-' + os.urandom(16).hex())
            db.session.add(ai_typist)
            db.session.commit()
            print("✅ AI Typist account created.")
        else:
            print("Database ready.")


# ── Scheduler (runs outside create_app so it starts once, not per worker) ────
app = create_app()

from routes.email_notifications import schedule_clerk_summaries  # noqa
schedule_clerk_summaries(app)


if __name__ == '__main__':
    app.run(debug=False)
