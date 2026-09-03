"""
routes/dropbox_integration.py
──────────────────────────────
Dropbox integration — push completed reports to a connected Dropbox account.
Single-purpose OAuth 2.0 connection (Document Management only, no scope sharing).

Endpoints:
  GET    /api/dropbox/auth         → redirect to Dropbox's consent screen
  GET    /api/dropbox/callback     → exchange code → store tokens → redirect to frontend
  GET    /api/dropbox/status       → { connected, email }
  DELETE /api/dropbox/disconnect   → clear stored credentials

Tokens are stored as SystemSetting rows (internal — never exposed via /api/system-settings):
  dropbox_access_token, dropbox_refresh_token, dropbox_token_expiry,
  dropbox_email, dropbox_connected_at

Environment variables (set in Railway dashboard):
  DROPBOX_CLIENT_ID      — the app's App key (Dropbox App Console)
  DROPBOX_CLIENT_SECRET  — the app's App secret
  BACKEND_URL / FRONTEND_URL — reused from the Google integration's env vars

Note: Dropbox access tokens are always short-lived (~4h) even with a refresh
token present — token_access_type=offline is what makes the initial exchange
return a refresh_token at all.
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

dropbox_bp = Blueprint('dropbox_integration', __name__)

PREFIX = 'dropbox'

CLIENT_ID     = os.environ.get('DROPBOX_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('DROPBOX_CLIENT_SECRET', '')

_AUTH_URL      = 'https://www.dropbox.com/oauth2/authorize'
_TOKEN_URL     = 'https://api.dropboxapi.com/oauth2/token'
_ACCOUNT_URL   = 'https://api.dropboxapi.com/2/users/get_current_account'

_TOKEN_FIELDS = (
    'access_token', 'refresh_token', 'token_expiry', 'email', 'connected_at',
)


def _redirect_uri() -> str:
    backend = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').strip().rstrip('/')
    return f'{backend}/api/dropbox/callback'


def _frontend_url(path: str = '') -> str:
    frontend = os.environ.get('FRONTEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    return f'{frontend}{path}'


def _save_tokens(tokens: dict) -> None:
    expiry = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(tokens.get('expires_in', 14400)))
    )
    data = {
        'access_token': tokens['access_token'],
        'token_expiry': expiry.isoformat(),
    }
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
    }).encode()

    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f'[dropbox] token refresh failed: {e}')
        return None

    new_token = data.get('access_token')
    if not new_token:
        print(f'[dropbox] no access_token in refresh response: {data}')
        return None

    expiry = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(data.get('expires_in', 14400)))
    )
    save_tokens(PREFIX, {'access_token': new_token, 'token_expiry': expiry.isoformat()})
    return new_token


def get_valid_access_token() -> Optional[str]:
    """Return a valid Dropbox access token, transparently refreshing if expired."""
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

@dropbox_bp.route('', methods=['OPTIONS'])
@dropbox_bp.route('/auth', methods=['OPTIONS'])
@dropbox_bp.route('/status', methods=['OPTIONS'])
@dropbox_bp.route('/disconnect', methods=['OPTIONS'])
def handle_options():
    return '', 204


@dropbox_bp.route('/auth', methods=['GET'])
def dropbox_auth():
    """Step 1 — redirect the user's browser to Dropbox's consent screen."""
    if not CLIENT_ID:
        return jsonify({'error': 'DROPBOX_CLIENT_ID is not configured on the server'}), 500

    params = {
        'client_id':          CLIENT_ID,
        'redirect_uri':       _redirect_uri(),
        'response_type':      'code',
        'token_access_type':  'offline',   # request a refresh_token
        'state':              new_state(PREFIX),
    }
    url = f'{_AUTH_URL}?{urllib.parse.urlencode(params)}'
    return redirect(url)


@dropbox_bp.route('/callback', methods=['GET'])
def dropbox_callback():
    """Step 2 — Dropbox redirects here with ?code=&state= after consent."""
    error = request.args.get('error')
    if error:
        print(f'[dropbox] OAuth error from Dropbox: {error}')
        return redirect(_frontend_url('/settings?tab=integrations&dropbox=error'))

    code = request.args.get('code')
    state = request.args.get('state', '')
    if not code or not verify_state(PREFIX, state):
        print('[dropbox] missing code or invalid/expired state')
        return redirect(_frontend_url('/settings?tab=integrations&dropbox=error'))

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
        print(f'[dropbox] token exchange error: {e}')
        return redirect(_frontend_url('/settings?tab=integrations&dropbox=error'))

    if 'access_token' not in tokens:
        print(f'[dropbox] no access_token in response: {tokens}')
        return redirect(_frontend_url('/settings?tab=integrations&dropbox=error'))

    _save_tokens(tokens)

    try:
        req = urllib.request.Request(
            _ACCOUNT_URL,
            headers={
                'Authorization': f'Bearer {tokens["access_token"]}',
                'Content-Type':  'application/json',
            },
            data=b'null',
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read())
        email = (info.get('email') or '').strip()
        if email:
            save_tokens(PREFIX, {'email': email})
            print(f'[dropbox] connected: {email}')
    except Exception as e:
        print(f'[dropbox] account fetch failed (non-fatal): {e}')

    return redirect(_frontend_url('/settings?tab=integrations&dropbox=connected'))


@dropbox_bp.route('/status', methods=['GET'])
@jwt_required()
def dropbox_status():
    valid_token = get_valid_access_token()
    tokens = load_tokens(PREFIX, _TOKEN_FIELDS)
    return jsonify({
        'connected': valid_token is not None,
        'email':     tokens.get('email', ''),
    })


@dropbox_bp.route('/disconnect', methods=['DELETE'])
@jwt_required()
def dropbox_disconnect():
    clear_tokens(PREFIX, _TOKEN_FIELDS)
    return jsonify({'disconnected': True})
