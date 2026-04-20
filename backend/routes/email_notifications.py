"""
email_notifications.py — Flask blueprint for email notification settings and triggers.

Routes:
  GET  /api/email/settings              → global system settings (clerk summary toggle)
  PUT  /api/email/settings              → save global settings
  GET  /api/email/client/<id>/settings  → per-client notification prefs
  PUT  /api/email/client/<id>/settings  → save per-client notification prefs
  POST /api/email/test                  → send a test email
  POST /api/email/clerk-summary/run     → manually trigger clerk summaries (admin)
  POST /api/email/confirmation/run      → manually trigger confirmation emails (admin)

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

_CONFIRMATION_DEFAULTS = {
    'confirmation_enabled':  False,
    'confirmation_days':     [1, 2],
    'confirmation_template': '',
}

def _load_global():
    try:
        with open(_SETTINGS_PATH) as f:
            data = json.load(f)
    except Exception:
        data = {}
    merged = {'clerk_summary_enabled': True, 'clerk_summary_time': '18:00'}
    merged.update(_CONFIRMATION_DEFAULTS)
    merged.update(data)
    return merged

def _save_global(data):
    with open(_SETTINGS_PATH, 'w') as f:
        json.dump(data, f, indent=2)


# ── Routes ───────────────────────────────────────────────────────────────────

@email_bp.route('/settings', methods=['GET'])
def get_global_settings():
    return jsonify(_load_global())

@email_bp.route('/settings', methods=['PUT'])
def save_global_settings():
    data = request.get_json() or {}
    current = _load_global()
    current.update({
        'clerk_summary_enabled': bool(data.get('clerk_summary_enabled', current.get('clerk_summary_enabled', True))),
        'clerk_summary_time':    data.get('clerk_summary_time', current.get('clerk_summary_time', '18:00')),
    })
    # Confirmation email settings
    if 'confirmation_enabled' in data:
        current['confirmation_enabled'] = bool(data['confirmation_enabled'])
    if 'confirmation_days' in data:
        days = data['confirmation_days']
        if isinstance(days, list):
            current['confirmation_days'] = [int(d) for d in days if str(d).isdigit() or isinstance(d, int)]
    if 'confirmation_template' in data:
        current['confirmation_template'] = str(data['confirmation_template'])
    _save_global(current)
    return jsonify({'success': True, 'settings': current})


@email_bp.route('/client/<int:client_id>/settings', methods=['GET'])
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


@email_bp.route('/client/<int:client_id>/settings', methods=['PUT'])
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


@email_bp.route('/test', methods=['POST'])
def send_test_email():
    from routes.email_service import _send, _wrap
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


@email_bp.route('/clerk-summary/run', methods=['POST'])
def run_clerk_summaries_now():
    """Manually trigger clerk summaries — useful for testing."""
    count, errors = _send_all_clerk_summaries()
    return jsonify({'success': True, 'sent': count, 'errors': errors})


@email_bp.route('/confirmation/run', methods=['POST'])
def run_confirmation_emails_now():
    """Manually trigger confirmation emails — useful for testing."""
    settings = _load_global()
    if not settings.get('confirmation_enabled', False):
        return jsonify({'success': False, 'error': 'Confirmation emails are disabled'}), 400
    count, errors = _send_all_pending_confirmations(settings)
    return jsonify({'success': True, 'sent': count, 'errors': errors})


# ── Notification trigger (called from inspections routes) ────────────────────

def trigger_inspection_notification(event, inspection):
    """
    Call this from your inspections blueprint after create/update/complete.
    event: 'created' | 'updated' | 'completed' | 'reminder'
    """
    try:
        from routes.email_service import send_inspection_notification
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


# ── Welcome email triggers ────────────────────────────────────────────────────

def trigger_welcome_user(user, plain_password):
    """Call from users route immediately after creating a new user."""
    try:
        from routes.email_service import send_welcome_user
        send_welcome_user(user, plain_password)
    except Exception as e:
        print(f'[email] welcome user error: {e}')


def trigger_welcome_client(client, plain_password):
    """Call from clients route immediately after creating a new client."""
    try:
        from routes.email_service import send_welcome_client
        send_welcome_client(client, plain_password)
    except Exception as e:
        print(f'[email] welcome client error: {e}')


def trigger_typist_assignment(inspection):
    """
    Call from inspections route when status changes to 'processing'.
    Notifies the assigned typist that the report is ready for them.
    """
    try:
        from routes.email_service import send_typist_assignment
        typist = inspection.typist if getattr(inspection, 'typist', None) else                  User.query.get(inspection.typist_id) if inspection.typist_id else None
        if not typist or not typist.email:
            return
        prop   = inspection.property
        client = prop.client if prop else None
        send_typist_assignment(typist, inspection, prop, client)
    except Exception as e:
        print(f'[email] typist assignment error: {e}')



# ── Confirmation email logic ─────────────────────────────────────────────────

def _resolve_confirmation_recipient(inspection):
    """
    Return (email, name) for whoever holds the keys for this inspection.
    Driven by inspection.key_location (structured dropdown value).
    Falls back to client email if no specific holder found.
    """
    key_location = getattr(inspection, 'key_location', None) or ''
    prop = inspection.property
    client = prop.client if prop else None

    if key_location == 'With Tenant':
        email = getattr(inspection, 'tenant_email', None) or ''
        name  = getattr(inspection, 'tenant_name',  None) or 'Tenant'
        if email:
            return email, name

    if key_location in ('With Landlord',):
        # Future: landlord has separate email field. For now fall through to client.
        pass

    if key_location == 'With Agent':
        # Agent = client (the letting agent who booked)
        if client and client.email:
            return client.email, client.name or 'Agent'

    # Default: client email covers 'With Agent', 'At Property', 'At Concierge',
    # 'In Key Safe', 'With Landlord' (until landlord field exists), and unknown values.
    if client and client.email:
        return client.email, client.name or 'Client'

    return None, None


def _send_all_pending_confirmations(settings=None):
    """
    For each enabled lead-day, find inspections scheduled exactly that many days
    from today and send a confirmation email to the key holder.
    Skips inspections with status cancelled or complete.
    """
    from routes.email_service import send_confirmation_email
    if settings is None:
        settings = _load_global()

    days_list = settings.get('confirmation_days', [1, 2])
    template  = settings.get('confirmation_template', '') or None
    today     = date.today()
    sent      = 0
    errors    = []

    for days_before in days_list:
        target_date = today + timedelta(days=int(days_before))

        inspections = (
            Inspection.query
            .filter(
                db.func.date(
                    db.func.coalesce(Inspection.conduct_date, Inspection.scheduled_date)
                ) == target_date,
                Inspection.status.notin_(['cancelled', 'complete'])
            )
            .all()
        )

        for insp in inspections:
            prop = insp.property
            recipient_email, recipient_name = _resolve_confirmation_recipient(insp)
            if not recipient_email:
                continue
            try:
                ok, err = send_confirmation_email(
                    recipient_email, recipient_name, insp, prop,
                    days_before=days_before, template=template
                )
                if ok:
                    sent += 1
                else:
                    errors.append(f'Insp #{insp.id} ({days_before}d): {err}')
            except Exception as e:
                errors.append(f'Insp #{insp.id} ({days_before}d): {e}')

    return sent, errors


# ── Clerk daily summary logic ────────────────────────────────────────────────

def _send_all_clerk_summaries():
    """Find all clerks and send them their next-day schedule."""
    from routes.email_service import send_clerk_daily_summary
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
    Register the daily jobs: clerk summaries and confirmation emails.
    Call this once after create_app():
        from email_notifications import schedule_clerk_summaries
        schedule_clerk_summaries(app)
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone='Europe/London')

        def clerk_job():
            settings = _load_global()
            if not settings.get('clerk_summary_enabled', True):
                return
            with app.app_context():
                sent, errors = _send_all_clerk_summaries()
                print(f'[email] clerk summaries: {sent} sent, errors: {errors}')

        # Parse HH:MM from settings at startup; default 18:00
        settings = _load_global()
        t = settings.get('clerk_summary_time', '18:00').split(':')
        hour, minute = int(t[0]), int(t[1]) if len(t) > 1 else 0

        scheduler.add_job(clerk_job, CronTrigger(hour=hour, minute=minute, timezone='Europe/London'))

        # Confirmation emails fire at 8am daily
        def confirmation_job():
            conf_settings = _load_global()
            if not conf_settings.get('confirmation_enabled', False):
                return
            with app.app_context():
                sent, errors = _send_all_pending_confirmations(conf_settings)
                print(f'[email] confirmation emails: {sent} sent, errors: {errors}')

        scheduler.add_job(confirmation_job, CronTrigger(hour=8, minute=0, timezone='Europe/London'))

        # ── Keep-alive ping ───────────────────────────────────────────────────
        # Railway (and similar PaaS platforms) will sleep the container after
        # ~15 minutes of inactivity on lower-tier plans. The first request after
        # sleep triggers a cold start that can take 10-30 seconds — exactly the
        # "takes forever to load" symptom. Pinging /health every 8 minutes keeps
        # the process warm at all times.
        import requests as _req
        import os as _os

        def _keepalive_job():
            url = _os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
            if not url:
                return   # skip in local dev / environments without a public URL
            if not url.startswith('http'):
                url = 'https://' + url
            try:
                _req.get(f'{url}/health', timeout=10)
            except Exception:
                pass  # silent — this is best-effort only

        from apscheduler.triggers.interval import IntervalTrigger
        scheduler.add_job(_keepalive_job, IntervalTrigger(minutes=8))

        scheduler.start()
        print(f'[email] clerk summary scheduler started — fires at {hour:02d}:{minute:02d} Europe/London')
        print(f'[email] confirmation email scheduler started — fires at 08:00 Europe/London')
        print('[email] keep-alive ping scheduled every 8 minutes')
        return scheduler
    except ImportError:
        print('[email] APScheduler not installed — scheduled emails disabled. Run: pip install apscheduler')
        return None
