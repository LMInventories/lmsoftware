"""
routes/slack_integration.py
─────────────────────────────
Slack integration — post inspection notifications to a Slack channel via a
workspace-level "Add to Slack" bot-token installation.

Endpoints:
  GET    /api/slack/auth         → redirect to Slack's "Add to Slack" consent screen
  GET    /api/slack/callback     → exchange code → store bot token → redirect to frontend
  GET    /api/slack/status       → { connected, team_name }
  DELETE /api/slack/disconnect   → revoke token + clear stored credentials

Tokens are stored as SystemSetting rows (internal — never exposed via /api/system-settings):
  slack_bot_token, slack_team_id, slack_team_name, slack_connected_at

The destination channel is stored separately as a normal (exposed) SystemSetting
row, `slack_channel_id`, configured from a small panel on the Slack card —
see routes/system_settings.py's ALLOWED_KEYS.

Environment variables (set in Railway dashboard):
  SLACK_CLIENT_ID      — the Slack app's Client ID (api.slack.com/apps → Basic Information)
  SLACK_CLIENT_SECRET  — the Slack app's Client Secret
  BACKEND_URL / FRONTEND_URL — reused from the Google integration's env vars

Note: unlike Google/Microsoft/Dropbox, Slack bot tokens don't expire and Slack
does not issue a refresh_token in the default (non token-rotation) OAuth flow
used here — so there's no refresh step, just store-and-use.
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, request, jsonify, redirect
from flask_jwt_extended import jwt_required

from services.oauth_tokens import save_tokens, load_tokens, clear_tokens, new_state, verify_state

slack_bp = Blueprint('slack_integration', __name__)

PREFIX = 'slack'

CLIENT_ID     = os.environ.get('SLACK_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('SLACK_CLIENT_SECRET', '')

# chat:write — post messages; channels:read — list channels for the config panel;
# team:read — workspace name, shown in the UI
SCOPES = ['chat:write', 'channels:read', 'team:read']

_AUTH_URL   = 'https://slack.com/oauth/v2/authorize'
_TOKEN_URL  = 'https://slack.com/api/oauth.v2.access'
_REVOKE_URL = 'https://slack.com/api/auth.revoke'

_TOKEN_FIELDS = ('bot_token', 'team_id', 'team_name', 'connected_at')


def _redirect_uri() -> str:
    backend = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').strip().rstrip('/')
    return f'{backend}/api/slack/callback'


def _frontend_url(path: str = '') -> str:
    frontend = os.environ.get('FRONTEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    return f'{frontend}{path}'


def get_bot_token() -> Optional[str]:
    """Return the stored bot token, or None if Slack isn't connected."""
    tokens = load_tokens(PREFIX, _TOKEN_FIELDS)
    return tokens.get('bot_token') or None


def is_connected() -> bool:
    return get_bot_token() is not None


# ── Routes ────────────────────────────────────────────────────────────────────

@slack_bp.route('', methods=['OPTIONS'])
@slack_bp.route('/auth', methods=['OPTIONS'])
@slack_bp.route('/status', methods=['OPTIONS'])
@slack_bp.route('/disconnect', methods=['OPTIONS'])
def handle_options():
    return '', 204


@slack_bp.route('/auth', methods=['GET'])
def slack_auth():
    """Step 1 — redirect the user's browser to Slack's 'Add to Slack' consent screen."""
    if not CLIENT_ID:
        return jsonify({'error': 'SLACK_CLIENT_ID is not configured on the server'}), 500

    params = {
        'client_id':    CLIENT_ID,
        'redirect_uri': _redirect_uri(),
        'scope':        ','.join(SCOPES),
        'state':        new_state(PREFIX),
    }
    url = f'{_AUTH_URL}?{urllib.parse.urlencode(params)}'
    return redirect(url)


@slack_bp.route('/callback', methods=['GET'])
def slack_callback():
    """Step 2 — Slack redirects here with ?code=&state= after the workspace admin consents."""
    error = request.args.get('error')
    if error:
        print(f'[slack] OAuth error from Slack: {error}')
        return redirect(_frontend_url('/settings?tab=integrations&slack=error'))

    code = request.args.get('code')
    state = request.args.get('state', '')
    if not code or not verify_state(PREFIX, state):
        print('[slack] missing code or invalid/expired state')
        return redirect(_frontend_url('/settings?tab=integrations&slack=error'))

    payload = urllib.parse.urlencode({
        'code':          code,
        'client_id':     CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri':  _redirect_uri(),
    }).encode()

    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f'[slack] token exchange error: {e}')
        return redirect(_frontend_url('/settings?tab=integrations&slack=error'))

    if not data.get('ok') or not data.get('access_token'):
        print(f'[slack] token exchange failed: {data}')
        return redirect(_frontend_url('/settings?tab=integrations&slack=error'))

    team = data.get('team') or {}
    save_tokens(PREFIX, {
        'bot_token':    data['access_token'],
        'team_id':      team.get('id', ''),
        'team_name':    team.get('name', ''),
        'connected_at': datetime.now(timezone.utc).isoformat(),
    })
    print(f'[slack] connected: {team.get("name", "")}')

    return redirect(_frontend_url('/settings?tab=integrations&slack=connected'))


@slack_bp.route('/status', methods=['GET'])
@jwt_required()
def slack_status():
    tokens = load_tokens(PREFIX, _TOKEN_FIELDS)
    return jsonify({
        'connected': bool(tokens.get('bot_token')),
        'team_name': tokens.get('team_name', ''),
    })


@slack_bp.route('/disconnect', methods=['DELETE'])
@jwt_required()
def slack_disconnect():
    token = get_bot_token()
    if token:
        try:
            req = urllib.request.Request(
                _REVOKE_URL,
                headers={'Authorization': f'Bearer {token}'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                json.loads(resp.read())
            print('[slack] token revoked OK')
        except Exception as e:
            print(f'[slack] revoke request failed (non-fatal): {e}')

    clear_tokens(PREFIX, _TOKEN_FIELDS)
    return jsonify({'disconnected': True})
