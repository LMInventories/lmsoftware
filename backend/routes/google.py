"""
routes/google.py
────────────────
Google integration — Drive + Calendar + Sheets, through one OAuth 2.0 user
connection.

The OAuth app's publishing status in Google Cloud (Google Auth Platform →
Audience) must be "In production". While it is "Testing", Google expires the
refresh token after 7 days and the account has to be reconnected.

A service account is deliberately not used: it can't own files in a personal
Google Drive, so report uploads would fail.

Endpoints:
  POST   /api/google/auth-url    → { url } of Google's consent screen (admin/manager)
  GET    /api/google/callback    → check state → exchange code → store tokens → redirect to frontend
  GET    /api/google/health      → { issues } for the admin/manager notification banner
  GET    /api/google/status      → { connected, email, has_drive, has_calendar, has_sheets }
  DELETE /api/google/disconnect  → revoke token + clear stored credentials (admin/manager)

Tokens are stored as SystemSetting rows (internal — never exposed via /api/system-settings):
  google_access_token   — short-lived (1 h)
  google_refresh_token  — long-lived; used to refresh access token automatically
  google_token_expiry   — ISO datetime of access token expiry
  google_scopes         — space-separated list of granted scopes
  google_email          — the connected Google account email (shown in UI)
  google_connected_at   — ISO datetime consent was last granted

Environment variables (set in Railway dashboard):
  GOOGLE_CLIENT_ID      — OAuth 2.0 client ID
  GOOGLE_CLIENT_SECRET  — OAuth 2.0 client secret
  GOOGLE_CALENDAR_ID    — optional; calendar to write events to (default "primary")
  BACKEND_URL           — public URL of this Flask service (e.g. https://api.lminventories.co.uk)
                          used to build the redirect_uri sent to Google
  FRONTEND_URL          — public URL of the Vue frontend (e.g. https://app.lminventories.co.uk)
                          used to redirect the browser after OAuth completes
"""

from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import Blueprint, request, jsonify, redirect
from flask_jwt_extended import jwt_required

from permissions import get_current_user, is_admin_or_manager
from services.oauth_tokens import new_state, verify_state

google_bp = Blueprint('google', __name__)

# ── OAuth config ──────────────────────────────────────────────────────────────
CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

# drive.file  — create/read only files that this app created (safer than full Drive access)
# calendar.events — create and update calendar events
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/spreadsheets',
    'openid',
    'email',
]

_AUTH_URL     = 'https://accounts.google.com/o/oauth2/v2/auth'
_TOKEN_URL    = 'https://oauth2.googleapis.com/token'
_REVOKE_URL   = 'https://oauth2.googleapis.com/revoke'
_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'

# SystemSetting keys used internally by this module
_TOKEN_KEYS = (
    'google_access_token',
    'google_refresh_token',
    'google_token_expiry',
    'google_scopes',
    'google_email',
    'google_connected_at',
)


# ── URL helpers ───────────────────────────────────────────────────────────────

def _redirect_uri() -> str:
    """
    The URI Google calls after the user grants permission.
    Must match exactly what is registered in Google Cloud Console.
    """
    backend = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').strip().rstrip('/')
    uri = f'{backend}/api/google/callback'
    print(f'[google] redirect_uri = {uri}')  # visible in Railway runtime logs
    return uri


def _frontend_url(path: str = '') -> str:
    frontend = os.environ.get('FRONTEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    return f'{frontend}{path}'


# ── Token storage helpers ─────────────────────────────────────────────────────

def _save_tokens(tokens: dict) -> None:
    """Persist a token response dict to SystemSetting rows."""
    from models import db, SystemSetting

    expiry = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(tokens.get('expires_in', 3600)))
    )
    data = {
        'google_access_token':  tokens['access_token'],
        'google_token_expiry':  expiry.isoformat(),
        'google_scopes':        tokens.get('scope', ' '.join(SCOPES)),
    }
    # Only overwrite refresh_token if a new one was supplied (Google only
    # sends it when consent is granted, not on every token refresh).
    if tokens.get('refresh_token'):
        data['google_refresh_token'] = tokens['refresh_token']
        data['google_connected_at']  = datetime.now(timezone.utc).isoformat()

    for key, value in data.items():
        row = SystemSetting.query.filter_by(key=key).first()
        if row is None:
            db.session.add(SystemSetting(key=key, value=value))
        else:
            row.value = value
    db.session.commit()


def _load_tokens() -> dict:
    """Load all google_* token rows from SystemSetting."""
    from models import SystemSetting
    rows = SystemSetting.query.filter(SystemSetting.key.in_(_TOKEN_KEYS)).all()
    return {r.key: r.value for r in rows}


def _clear_tokens() -> None:
    """Delete all google_* token rows."""
    from models import db, SystemSetting
    SystemSetting.query.filter(SystemSetting.key.in_(_TOKEN_KEYS)).delete()
    db.session.commit()


def _refresh_access_token(refresh_token: str) -> Optional[str]:
    """
    Exchange a refresh_token for a new access_token.
    Updates the stored access_token + expiry in-place.
    Returns the new access token, or None on failure.
    """
    from models import db, SystemSetting

    payload = urllib.parse.urlencode({
        'client_id':     CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type':    'refresh_token',
    }).encode()

    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f'[google] token refresh failed: {e}')
        if e.code == 400:
            # invalid_grant — refresh token was revoked or expired; clear stored
            # tokens so the next status check accurately shows disconnected
            print('[google] clearing stored tokens (invalid_grant)')
            _clear_tokens()
        return None
    except Exception as e:
        print(f'[google] token refresh failed: {e}')
        return None

    new_token = data.get('access_token')
    if not new_token:
        return None

    expiry = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(data.get('expires_in', 3600)))
    )
    for key, val in (
        ('google_access_token', new_token),
        ('google_token_expiry', expiry.isoformat()),
    ):
        row = SystemSetting.query.filter_by(key=key).first()
        if row:
            row.value = val
        else:
            db.session.add(SystemSetting(key=key, value=val))
    db.session.commit()
    return new_token


# ── Public helper (used by google_drive.py, google_calendar.py, etc.) ─────────

def get_valid_access_token() -> Optional[str]:
    """
    Return a valid Google access token, transparently refreshing if expired.
    Returns None if not connected or the refresh fails.
    """
    tokens = _load_tokens()
    if not tokens.get('google_access_token'):
        return None

    # Check expiry with a 2-minute buffer so we don't send a token
    # that expires mid-request.
    expiry_str = tokens.get('google_token_expiry', '')
    if expiry_str:
        try:
            expiry = datetime.fromisoformat(expiry_str)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expiry - timedelta(minutes=2):
                return _refresh_access_token(tokens.get('google_refresh_token', ''))
        except Exception:
            pass

    return tokens['google_access_token']


def is_connected() -> bool:
    """Quick check — True if both access and refresh tokens exist."""
    tokens = _load_tokens()
    return bool(tokens.get('google_access_token') and tokens.get('google_refresh_token'))


# ── Routes ────────────────────────────────────────────────────────────────────

@google_bp.route('', methods=['OPTIONS'])
@google_bp.route('/auth-url', methods=['OPTIONS'])
@google_bp.route('/health', methods=['OPTIONS'])
@google_bp.route('/status', methods=['OPTIONS'])
@google_bp.route('/disconnect', methods=['OPTIONS'])
@google_bp.route('/drive/force-sync', methods=['OPTIONS'])
def handle_options():
    return '', 204


@google_bp.route('/auth-url', methods=['POST'])
@jwt_required()
def google_auth_url():
    """
    Step 1 — return the URL of Google's consent screen for the frontend to open.
    Needs a signed-in admin or manager: whoever completes this flow becomes the
    account that receives the app's reports, sheet rows and calendar events.
    """
    if not is_admin_or_manager(get_current_user()):
        return jsonify({'error': 'Forbidden'}), 403
    if not CLIENT_ID:
        return jsonify({'error': 'GOOGLE_CLIENT_ID is not configured on the server'}), 500

    params = {
        'client_id':              CLIENT_ID,
        'redirect_uri':           _redirect_uri(),
        'response_type':          'code',
        'scope':                  ' '.join(SCOPES),
        'access_type':            'offline',       # request a refresh_token
        'prompt':                 'consent',        # force Google to re-issue refresh_token
        'include_granted_scopes': 'true',
        'state':                  new_state('google'),  # single use, checked by the callback
    }
    url = f'{_AUTH_URL}?{urllib.parse.urlencode(params)}'
    return jsonify({'url': url})


@google_bp.route('/callback', methods=['GET'])
def google_callback():
    """
    Step 2 — Google redirects here with ?code=... after the user consents.
    No JWT is possible on a redirect from Google, so the request must carry the
    single-use state issued by /auth-url. Exchanges the code for tokens, stores them, then redirects back to the
    frontend settings page.
    """
    error = request.args.get('error')
    if error:
        print(f'[google] OAuth error from Google: {error}')
        return redirect(_frontend_url('/settings?tab=integrations&google=error'))

    if not verify_state('google', request.args.get('state', '')):
        print('[google] callback rejected — missing, unknown or expired state')
        return redirect(_frontend_url('/settings?tab=integrations&google=error'))

    code = request.args.get('code')
    if not code:
        return redirect(_frontend_url('/settings?tab=integrations&google=error'))

    # Exchange authorization code for tokens
    payload = urllib.parse.urlencode({
        'code':          code,
        'client_id':     CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri':  _redirect_uri(),
        'grant_type':    'authorization_code',
    }).encode()

    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except Exception as e:
        print(f'[google] token exchange error: {e}')
        return redirect(_frontend_url('/settings?tab=integrations&google=error'))

    if 'access_token' not in tokens:
        print(f'[google] no access_token in response: {tokens}')
        return redirect(_frontend_url('/settings?tab=integrations&google=error'))

    _save_tokens(tokens)

    # Fetch the connected account's email address so it can be shown in the UI
    try:
        req = urllib.request.Request(
            _USERINFO_URL,
            headers={'Authorization': f'Bearer {tokens["access_token"]}'},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read())
        email = info.get('email', '')
        if email:
            from models import db, SystemSetting
            row = SystemSetting.query.filter_by(key='google_email').first()
            if row:
                row.value = email
            else:
                db.session.add(SystemSetting(key='google_email', value=email))
            db.session.commit()
            print(f'[google] connected: {email}')
    except Exception as e:
        print(f'[google] userinfo fetch failed (non-fatal): {e}')

    return redirect(_frontend_url('/settings?tab=integrations&google=connected'))


@google_bp.route('/health', methods=['GET'])
@jwt_required()
def google_health():
    """
    Lightweight integration health check — reads DB state only, no live token call.
    Returns a list of issues for the admin/manager notification banner.
    Only reports a problem when a Google-dependent feature is configured but
    the connection has been lost (tokens cleared after invalid_grant).
    """
    from models import SystemSetting

    user = get_current_user()
    if not is_admin_or_manager(user):
        return jsonify({'issues': []}), 200

    def _get(key):
        row = SystemSetting.query.filter_by(key=key).first()
        return (row.value or '').strip() if row else ''

    issues = []

    google_connected = bool(_get('google_access_token') and _get('google_refresh_token'))

    # Only warn when at least one Google feature is actively configured,
    # so a user who never set up Google doesn't see a spurious warning.
    if not google_connected and _get('google_master_sheet_id'):
        issues.append({
            'key':     'google',
            'label':   'Google',
            'message': 'Google disconnected — Sheets, Drive and Calendar sync are paused.',
        })

    return jsonify({'issues': issues})


@google_bp.route('/status', methods=['GET'])
@jwt_required()
def google_status():
    """
    Return the current Google connection state.
    Called by IntegrationsSettings.vue on mount and after OAuth redirect.
    """
    # Validate the token (auto-refreshes if expired; auto-clears if invalid_grant)
    valid_token = get_valid_access_token()
    # Re-load after potential refresh/clear so email/scopes reflect current state
    tokens = _load_tokens()
    scopes = tokens.get('google_scopes', '')
    return jsonify({
        'connected':     valid_token is not None,
        'email':         tokens.get('google_email', ''),
        'has_drive':     'drive' in scopes,
        'has_calendar':  'calendar' in scopes,
        'has_sheets':    'spreadsheets' in scopes,
    })


@google_bp.route('/disconnect', methods=['DELETE'])
@jwt_required()
def google_disconnect():
    """
    Revoke the OAuth token at Google and delete all stored credentials.
    After this the user will need to go through the consent flow again.
    """
    if not is_admin_or_manager(get_current_user()):
        return jsonify({'error': 'Forbidden'}), 403

    tokens = _load_tokens()
    # Prefer revoking the refresh_token (revokes all related access tokens too)
    token_to_revoke = tokens.get('google_refresh_token') or tokens.get('google_access_token')

    if token_to_revoke:
        try:
            revoke_url = f'{_REVOKE_URL}?token={urllib.parse.quote(token_to_revoke)}'
            req = urllib.request.Request(revoke_url, method='POST')
            urllib.request.urlopen(req, timeout=10)
            print('[google] token revoked OK')
        except Exception as e:
            # Non-fatal — clear local tokens regardless
            print(f'[google] revoke request failed (non-fatal): {e}')

    _clear_tokens()
    return jsonify({'disconnected': True})


@google_bp.route('/drive/force-sync', methods=['POST'])
@jwt_required()
def drive_force_sync():
    """
    Re-upload completed inspection PDFs to Google Drive.
    Used when sporadic failures leave reports unsynced.

    Body (optional):
      { "since": "2025-01-01" }  — only process inspections updated on or after this date
                                   defaults to the last 30 days

    Returns:
      { total, synced, failed: [{id, error}, ...] }
    """
    import datetime as dt
    import time as _time
    from routes.pdf_generator import generate_inspection_pdf
    from services.google_drive import upload_report, is_drive_connected
    from models import db, Inspection

    if not is_drive_connected():
        return jsonify({'error': 'Google Drive is not connected'}), 400

    body = request.get_json(silent=True) or {}
    since_str = body.get('since')

    if since_str:
        try:
            since = dt.datetime.fromisoformat(since_str)
            if since.tzinfo is None:
                since = since.replace(tzinfo=dt.timezone.utc)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid date — use YYYY-MM-DD'}), 400
    else:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)

    inspections = (
        Inspection.query
        .filter(Inspection.status == 'complete')
        .filter(Inspection.updated_at >= since)
        .filter(Inspection.report_data.isnot(None))
        .order_by(Inspection.updated_at.desc())
        .limit(100)
        .all()
    )

    results  = {'total': len(inspections), 'synced': 0, 'failed': [], 'truncated': False}
    deadline = _time.monotonic() + 100  # stay inside Gunicorn's timeout (gunicorn.conf.py)

    for insp in inspections:
        if _time.monotonic() > deadline:
            results['truncated'] = True
            print(f'[drive_force_sync] time budget exhausted — stopping early')
            break
        try:
            pdf_bytes = generate_inspection_pdf(insp.id, deadline=deadline)
            ok, outcome = upload_report(insp, pdf_bytes)
            if ok:
                insp.drive_file_id = outcome['file_id']
                db.session.commit()
                results['synced'] += 1
                print(f'[drive_force_sync] synced inspection {insp.id}')
            else:
                results['failed'].append({'id': insp.id, 'error': outcome})
                print(f'[drive_force_sync] failed inspection {insp.id}: {outcome}')
        except Exception as e:
            results['failed'].append({'id': insp.id, 'error': str(e)[:120]})
            print(f'[drive_force_sync] exception on inspection {insp.id}: {e}')

    return jsonify(results)


@google_bp.route('/sheets/force-sync', methods=['POST'])
@jwt_required()
def sheets_force_sync():
    """
    Re-sync inspections to the master Google Sheet.
    Used when new inspections weren't added because the connector was
    disconnected. Only inspections whose reference number isn't already
    present in the sheet are synced — existing rows are left untouched.

    Body (optional):
      { "since": "2025-01-01" }  — only process inspections created on or after this date
                                   defaults to the last 30 days

    Returns:
      { total, synced, skipped, failed: [{id, error}, ...], truncated }
    """
    import datetime as dt
    import time as _time
    from services.google_sheets import sync_inspection_row, get_existing_reference_numbers, get_sheet_layout
    from models import Inspection, SystemSetting

    if not is_connected():
        return jsonify({'error': 'Google is not connected'}), 400
    sheet_id_row = SystemSetting.query.filter_by(key='google_master_sheet_id').first()
    if not (sheet_id_row and (sheet_id_row.value or '').strip()):
        return jsonify({'error': 'Master Sheet ID is not configured'}), 400

    existing_refs, refs_err = get_existing_reference_numbers()
    if existing_refs is None:
        return jsonify({'error': f'Could not read master sheet: {refs_err}'}), 400
    layout, layout_err = get_sheet_layout()
    if layout is None:
        return jsonify({'error': f'Could not read master sheet: {layout_err}'}), 400

    body = request.get_json(silent=True) or {}
    since_str = body.get('since')

    if since_str:
        try:
            since = dt.datetime.fromisoformat(since_str)
            if since.tzinfo is None:
                since = since.replace(tzinfo=dt.timezone.utc)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid date — use YYYY-MM-DD'}), 400
    else:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)

    inspections = (
        Inspection.query
        .filter(Inspection.created_at >= since)
        .filter(Inspection.pdf_import.is_(False))
        .order_by(Inspection.created_at.desc())
        .limit(100)
        .all()
    )

    results  = {'total': len(inspections), 'synced': 0, 'skipped': 0, 'failed': [], 'truncated': False}
    deadline = _time.monotonic() + 180  # 3-minute budget — see gunicorn.conf.py timeout

    for insp in inspections:
        if _time.monotonic() > deadline:
            results['truncated'] = True
            print(f'[sheets_force_sync] time budget exhausted — stopping early')
            break

        reference = (insp.reference_number or '').strip().lower()
        if reference and reference in existing_refs:
            results['skipped'] += 1
            continue
        ok, outcome = sync_inspection_row(insp, layout)
        if ok:
            results['synced'] += 1
            print(f'[sheets_force_sync] synced inspection {insp.id}')
        else:
            results['failed'].append({'id': insp.id, 'error': outcome})
            print(f'[sheets_force_sync] failed inspection {insp.id}: {outcome}')

    return jsonify(results)
