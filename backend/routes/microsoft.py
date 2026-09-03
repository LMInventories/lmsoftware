"""
routes/microsoft.py
────────────────────
Microsoft integration — Outlook/365 Calendar + Microsoft Teams + OneDrive/SharePoint,
all via one Microsoft Graph OAuth 2.0 connection (multi-tenant "common" endpoint, so
any customer's Microsoft 365 organisation can connect).

Endpoints:
  GET    /api/microsoft/auth         → redirect to Microsoft's consent screen
  GET    /api/microsoft/callback     → exchange code → store tokens → redirect to frontend
  GET    /api/microsoft/status       → { connected, email, has_calendar, has_teams, has_onedrive }
  DELETE /api/microsoft/disconnect   → clear stored credentials

Tokens are stored as SystemSetting rows (internal — never exposed via /api/system-settings):
  microsoft_access_token, microsoft_refresh_token, microsoft_token_expiry,
  microsoft_scopes, microsoft_email, microsoft_connected_at

Environment variables (set in Railway dashboard):
  MICROSOFT_CLIENT_ID      — Entra ID (Azure AD) app registration's Application (client) ID
  MICROSOFT_CLIENT_SECRET  — a client secret created for that app registration
  BACKEND_URL / FRONTEND_URL — reused from the Google integration's env vars

Note: the Teams scope (ChannelMessage.Send) may require the customer's Microsoft 365
tenant admin to grant consent, even though the app itself needs no admin action to
register — this is surfaced in the Teams card's UI copy, not handled specially here.
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import Blueprint, request, jsonify, redirect
from flask_jwt_extended import jwt_required

from services.oauth_tokens import save_tokens, load_tokens, clear_tokens, new_state, verify_state

microsoft_bp = Blueprint('microsoft', __name__)

PREFIX = 'microsoft'

CLIENT_ID     = os.environ.get('MICROSOFT_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('MICROSOFT_CLIENT_SECRET', '')

# offline_access — refresh token
# User.Read — identity, for the connected-account email shown in the UI
# Calendars.ReadWrite — Outlook/365 Calendar card
# Files.ReadWrite — OneDrive/SharePoint card
# ChannelMessage.Send — Microsoft Teams card
SCOPES = [
    'offline_access',
    'User.Read',
    'Calendars.ReadWrite',
    'Files.ReadWrite',
    'ChannelMessage.Send',
]

_AUTH_URL     = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
_TOKEN_URL    = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
_USERINFO_URL = 'https://graph.microsoft.com/v1.0/me'

_TOKEN_FIELDS = (
    'access_token', 'refresh_token', 'token_expiry', 'scopes', 'email', 'connected_at',
)


def _redirect_uri() -> str:
    backend = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').strip().rstrip('/')
    return f'{backend}/api/microsoft/callback'


def _frontend_url(path: str = '') -> str:
    frontend = os.environ.get('FRONTEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    return f'{frontend}{path}'


def _save_tokens(tokens: dict) -> None:
    expiry = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(tokens.get('expires_in', 3600)))
    )
    data = {
        'access_token': tokens['access_token'],
        'token_expiry': expiry.isoformat(),
        'scopes':       tokens.get('scope', ' '.join(SCOPES)),
    }
    # Microsoft returns a refresh_token on every successful exchange when
    # offline_access was requested (unlike Google, which only sends it on
    # first consent) — but only overwrite connected_at when we actually get one.
    if tokens.get('refresh_token'):
        data['refresh_token'] = tokens['refresh_token']
        data['connected_at']  = datetime.now(timezone.utc).isoformat()
    save_tokens(PREFIX, data)


def _refresh_access_token(refresh_token: str) -> Optional[str]:
    payload = urllib.parse.urlencode({
        'client_id':     CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type':    'refresh_token',
        'scope':         ' '.join(SCOPES),
    }).encode()

    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f'[microsoft] token refresh failed: {e}')
        return None

    new_token = data.get('access_token')
    if not new_token:
        print(f'[microsoft] no access_token in refresh response: {data}')
        return None

    expiry = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(data.get('expires_in', 3600)))
    )
    save_data = {'access_token': new_token, 'token_expiry': expiry.isoformat()}
    # Microsoft may rotate the refresh token too — keep it if a new one comes back
    if data.get('refresh_token'):
        save_data['refresh_token'] = data['refresh_token']
    save_tokens(PREFIX, save_data)
    return new_token


def get_valid_access_token() -> Optional[str]:
    """Return a valid Microsoft Graph access token, transparently refreshing if expired."""
    tokens = load_tokens(PREFIX, _TOKEN_FIELDS)
    if not tokens.get('access_token'):
        return None

    expiry_str = tokens.get('token_expiry', '')
    if expiry_str:
        try:
            expiry = datetime.fromisoformat(expiry_str)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expiry - timedelta(minutes=2):
                return _refresh_access_token(tokens.get('refresh_token', ''))
        except Exception:
            pass

    return tokens['access_token']


def is_connected() -> bool:
    tokens = load_tokens(PREFIX, _TOKEN_FIELDS)
    return bool(tokens.get('access_token') and tokens.get('refresh_token'))


# ── Routes ────────────────────────────────────────────────────────────────────

@microsoft_bp.route('', methods=['OPTIONS'])
@microsoft_bp.route('/auth', methods=['OPTIONS'])
@microsoft_bp.route('/status', methods=['OPTIONS'])
@microsoft_bp.route('/disconnect', methods=['OPTIONS'])
def handle_options():
    return '', 204


@microsoft_bp.route('/auth', methods=['GET'])
def microsoft_auth():
    """Step 1 — redirect the user's browser to Microsoft's consent screen."""
    if not CLIENT_ID:
        return jsonify({'error': 'MICROSOFT_CLIENT_ID is not configured on the server'}), 500

    params = {
        'client_id':     CLIENT_ID,
        'redirect_uri':  _redirect_uri(),
        'response_type': 'code',
        'response_mode': 'query',
        'scope':         ' '.join(SCOPES),
        'state':         new_state(PREFIX),
        'prompt':        'consent',
    }
    url = f'{_AUTH_URL}?{urllib.parse.urlencode(params)}'
    return redirect(url)


@microsoft_bp.route('/callback', methods=['GET'])
def microsoft_callback():
    """Step 2 — Microsoft redirects here with ?code=&state= after consent."""
    error = request.args.get('error')
    if error:
        print(f'[microsoft] OAuth error from Microsoft: {error}')
        return redirect(_frontend_url('/settings?tab=integrations&microsoft=error'))

    code = request.args.get('code')
    state = request.args.get('state', '')
    if not code or not verify_state(PREFIX, state):
        print('[microsoft] missing code or invalid/expired state')
        return redirect(_frontend_url('/settings?tab=integrations&microsoft=error'))

    payload = urllib.parse.urlencode({
        'code':          code,
        'client_id':     CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri':  _redirect_uri(),
        'grant_type':    'authorization_code',
        'scope':         ' '.join(SCOPES),
    }).encode()

    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except Exception as e:
        print(f'[microsoft] token exchange error: {e}')
        return redirect(_frontend_url('/settings?tab=integrations&microsoft=error'))

    if 'access_token' not in tokens:
        print(f'[microsoft] no access_token in response: {tokens}')
        return redirect(_frontend_url('/settings?tab=integrations&microsoft=error'))

    _save_tokens(tokens)

    try:
        req = urllib.request.Request(
            _USERINFO_URL,
            headers={'Authorization': f'Bearer {tokens["access_token"]}'},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read())
        email = info.get('mail') or info.get('userPrincipalName') or ''
        if email:
            save_tokens(PREFIX, {'email': email})
            print(f'[microsoft] connected: {email}')
    except Exception as e:
        print(f'[microsoft] userinfo fetch failed (non-fatal): {e}')

    return redirect(_frontend_url('/settings?tab=integrations&microsoft=connected'))


@microsoft_bp.route('/status', methods=['GET'])
@jwt_required()
def microsoft_status():
    valid_token = get_valid_access_token()
    tokens = load_tokens(PREFIX, _TOKEN_FIELDS)
    scopes = tokens.get('scopes', '')
    return jsonify({
        'connected':    valid_token is not None,
        'email':        tokens.get('email', ''),
        'has_calendar': 'Calendars' in scopes,
        'has_teams':    'ChannelMessage' in scopes,
        'has_onedrive': 'Files' in scopes,
    })


@microsoft_bp.route('/disconnect', methods=['DELETE'])
@jwt_required()
def microsoft_disconnect():
    clear_tokens(PREFIX, _TOKEN_FIELDS)
    return jsonify({'disconnected': True})
