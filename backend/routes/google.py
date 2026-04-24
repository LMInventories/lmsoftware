"""
routes/google.py
────────────────
Google OAuth 2.0 integration — Drive + Calendar.

Endpoints:
  GET    /api/google/auth         → redirect to Google consent screen
  GET    /api/google/callback     → exchange code → store tokens → redirect to frontend
  GET    /api/google/status       → { connected, email, has_drive, has_calendar }
  DELETE /api/google/disconnect   → revoke token + clear stored credentials

Tokens are stored as SystemSetting rows (internal — never exposed via /api/system-settings):
  google_access_token   — short-lived (1 h)
  google_refresh_token  — long-lived; used to refresh access token automatically
  google_token_expiry   — ISO datetime of access token expiry
  google_scopes         — space-separated list of granted scopes
  google_email          — the connected Google account email (shown in UI)

Environment variables required (set in Railway dashboard):
  GOOGLE_CLIENT_ID      — OAuth 2.0 client ID
  GOOGLE_CLIENT_SECRET  — OAuth 2.0 client secret
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

google_bp = Blueprint('google', __name__)

# ── OAuth config ──────────────────────────────────────────────────────────────
CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

# drive.file  — create/read only files that this app created (safer than full Drive access)
# calendar.events — create and update calendar events
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/calendar.events',
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
    # sends it on first authorisation, not on every token refresh).
    if tokens.get('refresh_token'):
        data['google_refresh_token'] = tokens['refresh_token']

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
    Returns None if Google is not connected or refresh fails.
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
@google_bp.route('/auth', methods=['OPTIONS'])
@google_bp.route('/status', methods=['OPTIONS'])
@google_bp.route('/disconnect', methods=['OPTIONS'])
def handle_options():
    return '', 204


@google_bp.route('/auth', methods=['GET'])
def google_auth():
    """
    Step 1 — redirect the user's browser to Google's consent screen.
    Called from the frontend when the user clicks "Connect Google".
    No JWT required — this is a browser redirect, not an XHR call, so the
    Authorization header cannot be sent. Access is implicitly restricted
    because only logged-in users can reach the Settings page that calls it.
    """
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
    }
    url = f'{_AUTH_URL}?{urllib.parse.urlencode(params)}'
    return redirect(url)


@google_bp.route('/callback', methods=['GET'])
def google_callback():
    """
    Step 2 — Google redirects here with ?code=... after the user consents.
    No JWT required — this is an open redirect endpoint called by Google.
    Exchanges the code for tokens, stores them, then redirects back to the
    frontend settings page.
    """
    error = request.args.get('error')
    if error:
        print(f'[google] OAuth error from Google: {error}')
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


@google_bp.route('/status', methods=['GET'])
@jwt_required()
def google_status():
    """
    Return the current Google connection state.
    Called by IntegrationsSettings.vue on mount and after OAuth redirect.
    """
    tokens  = _load_tokens()
    scopes  = tokens.get('google_scopes', '')
    connected = bool(
        tokens.get('google_access_token') and tokens.get('google_refresh_token')
    )
    return jsonify({
        'connected':    connected,
        'email':        tokens.get('google_email', ''),
        'has_drive':    'drive' in scopes,
        'has_calendar': 'calendar' in scopes,
    })


@google_bp.route('/disconnect', methods=['DELETE'])
@jwt_required()
def google_disconnect():
    """
    Revoke the OAuth token at Google and delete all stored credentials.
    After this the user will need to go through the consent flow again.
    """
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
