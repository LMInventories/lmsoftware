"""
email_notifications.py — Flask blueprint for email notification settings and triggers.

Routes:
  GET  /api/email/settings              → global system settings (clerk summary toggle)
  PUT  /api/email/settings              → save global settings
  GET  /api/email/client/<id>/settings  → per-client notification prefs
  PUT  /api/email/client/<id>/settings  → save per-client notification prefs
  POST /api/email/test                  → send a test email
  POST /api/email/clerk-summary/run     → manually trigger clerk summaries (admin)

Scheduler: call schedule_clerk_summaries(app) after create_app() to register the 6pm daily job.
Requires: APScheduler  →  pip install apscheduler
"""

import json
from datetime import datetime, date, timedelta
from flask import Blueprint, jsonify, request
from models import db, User, Client, Inspection, Property

email_bp = Blueprint('email', __name__)

# ── Default per-client notification prefs ───────────────────────────────────
DEFAULT_CLIENT_PREFS = {
    'inspection_created':   True,
    'inspection_updated':   True,
    'inspection_completed': True,
    'inspection_reminder':  True,
}

# ── Global system settings (stored as a simple JSON file on disk / env) ─────
# For simplicity we store global settings in a small JSON sidecar. In a larger
# system you'd use a SystemSettings db table.
import os
_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), 'email_global_settings.json')

def _load_global():
    try:
        with open(_SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {'clerk_summary_enabled': True, 'clerk_summary_time': '18:00'}

def _save_global(data):
    with open(_SETTINGS_PATH, 'w') as f:
        json.dump(data, f)


# ── Routes ───────────────────────────────────────────────────────────────────

@email_bp.route('/api/email/settings', methods=['GET'])
def get_global_settings():
    return jsonify(_load_global())

@email_bp.route('/api/email/settings', methods=['PUT'])
def save_global_settings():
    data = request.get_json() or {}
    current = _load_global()
    current.update({
        'clerk_summary_enabled': bool(data.get('clerk_summary_enabled', current.get('clerk_summary_enabled', True))),
        'clerk_summary_time':    data.get('clerk_summary_time', current.get('clerk_summary_time', '18:00')),
    })
    _save_global(current)
    return jsonify({'success': True, 'settings': current})


@email_bp.route('/api/email/client/<int:client_id>/settings', methods=['GET'])
def get_client_email_settings(client_id):
    client = Client.query.get_or_404(client_id)
    prefs = DEFAULT_CLIENT_PREFS.copy()
    if client.email_notifications:
        try:
            saved = json.loads(client.email_notifications)
            prefs.update(saved)
        except Exception:
            pass
    return jsonify({'client_id': client_id, 'client_name': client.name,
                    'email': client.email, 'prefs': prefs})


@email_bp.route('/api/email/client/<int:client_id>/settings', methods=['PUT'])
def save_client_email_settings(client_id):
    client = Client.query.get_or_404(client_id)
    data = request.get_json() or {}
    prefs = DEFAULT_CLIENT_PREFS.copy()
    for key in DEFAULT_CLIENT_PREFS:
        if key in data:
            prefs[key] = bool(data[key])
    client.email_notifications = json.dumps(prefs)
    db.session.commit()
    return jsonify({'success': True, 'client_id': client_id, 'prefs': prefs})


@email_bp.route('/api/email/test', methods=['POST'])
def send_test_email():
    from email_service import _send, _wrap
    data = request.get_json() or {}
    to   = data.get('to', '')
    if not to:
        return jsonify({'success': False, 'error': 'No recipient provided'}), 400
    body = _wrap('<h2>Test Email</h2><p>If you received this, InspectPro email is configured correctly.</p>', 'Test Email')
    ok, err = _send(
        os.environ.get('SMTP_FROM', 'no-reply@lminventories.co.uk'),
        to, 'InspectPro — Test Email', body
    )
    return jsonify({'success': ok, 'error': err})


@email_bp.route('/api/email/clerk-summary/run', methods=['POST'])
def run_clerk_summaries_now():
    """Manually trigger clerk summaries — useful for testing."""
    count, errors = _send_all_clerk_summaries()
    return jsonify({'success': True, 'sent': count, 'errors': errors})


# ── Notification trigger (called from inspections routes) ────────────────────

def trigger_inspection_notification(event, inspection):
    """
    Call this from your inspections blueprint after create/update/complete.
    event: 'created' | 'updated' | 'completed' | 'reminder'
    """
    try:
        from email_service import send_inspection_notification
        client   = inspection.client if hasattr(inspection, 'client') else \
                   Client.query.get(inspection.property.client_id) if inspection.property else None
        prop     = inspection.property
        if not client or not client.email:
            return

        # Check per-client prefs
        prefs = DEFAULT_CLIENT_PREFS.copy()
        if client.email_notifications:
            try:
                prefs.update(json.loads(client.email_notifications))
            except Exception:
                pass

        key_map = {
            'created': 'inspection_created', 'updated': 'inspection_updated',
            'completed': 'inspection_completed', 'reminder': 'inspection_reminder',
        }
        if not prefs.get(key_map.get(event, ''), True):
            return  # disabled for this client

        send_inspection_notification(event, inspection, client, prop)
    except Exception as e:
        print(f'[email] notification error ({event}): {e}')


# ── Clerk daily summary logic ────────────────────────────────────────────────

def _send_all_clerk_summaries():
    """Find all clerks and send them their next-day schedule."""
    from email_service import send_clerk_daily_summary
    tomorrow = date.today() + timedelta(days=1)
    clerks   = User.query.filter_by(role='clerk').all()
    sent     = 0
    errors   = []

    for clerk in clerks:
        if not clerk.email:
            continue
        # Find inspections assigned to this clerk tomorrow
        inspections = (
            Inspection.query
            .filter(
                Inspection.inspector_id == clerk.id,
                db.func.date(
                    db.func.coalesce(Inspection.conduct_date, Inspection.scheduled_date)
                ) == tomorrow,
                Inspection.status.notin_(['cancelled'])
            )
            .order_by(Inspection.conduct_time_preference)
            .all()
        )
        if not inspections:
            continue  # no work tomorrow — don't send empty email

        tuples = []
        for insp in inspections:
            prop   = insp.property
            client = prop.client if prop else None
            tuples.append((insp, prop, client))

        ok, err = send_clerk_daily_summary(clerk, tuples)
        if ok:
            sent += 1
        else:
            errors.append(f'{clerk.name}: {err}')

    return sent, errors


# ── APScheduler registration ──────────────────────────────────────────────────

def schedule_clerk_summaries(app):
    """
    Register the 6pm daily clerk summary job.
    Call this once after create_app():
        from email_notifications import schedule_clerk_summaries
        schedule_clerk_summaries(app)
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone='Europe/London')

        def job():
            settings = _load_global()
            if not settings.get('clerk_summary_enabled', True):
                return
            t = settings.get('clerk_summary_time', '18:00')
            # Job always fires at configured time; check handled in _load_global
            with app.app_context():
                sent, errors = _send_all_clerk_summaries()
                print(f'[email] clerk summaries: {sent} sent, errors: {errors}')

        # Parse HH:MM from settings at startup; default 18:00
        settings = _load_global()
        t = settings.get('clerk_summary_time', '18:00').split(':')
        hour, minute = int(t[0]), int(t[1]) if len(t) > 1 else 0

        scheduler.add_job(job, CronTrigger(hour=hour, minute=minute, timezone='Europe/London'))
        scheduler.start()
        print(f'[email] clerk summary scheduler started — fires at {hour:02d}:{minute:02d} Europe/London')
        return scheduler
    except ImportError:
        print('[email] APScheduler not installed — clerk summaries disabled. Run: pip install apscheduler')
        return None
