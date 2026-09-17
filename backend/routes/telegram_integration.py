"""
routes/telegram_integration.py
─────────────────────────────────
Lets staff book inspections, create properties, reschedule inspections, and
share completed reports by texting a Telegram bot in free text (or via the
/property, /inspection, /share commands). Unlike Google/Microsoft/Dropbox/
Slack/Zapier (all outbound, OAuth or self-issued-key authenticated), this
module owns the one genuinely public, unauthenticated-by-JWT endpoint in the
app: Telegram's webhook POSTs here directly. It's gated instead by a secret
path segment AND Telegram's
`X-Telegram-Bot-Api-Secret-Token` header, both checked with a constant-time
compare before anything else runs.

Endpoints:
  POST   /api/telegram/webhook/<secret_path>  → Telegram's webhook receiver
  POST   /api/telegram/link-code              → (JWT) generate a one-time linking code
  GET    /api/telegram/status                 → (JWT) is the caller linked?
  DELETE /api/telegram/unlink                 → (JWT) remove the caller's link

Env vars:
  TELEGRAM_BOT_TOKEN      — from BotFather. Both the app secret and the bot's
                            access token in one — never store it in SystemSetting.
  TELEGRAM_WEBHOOK_SECRET — random string, e.g. secrets.token_urlsafe(32).
  TELEGRAM_BOT_USERNAME   — optional, shown in link-code instructions.
  BACKEND_URL             — reused from the Google/Slack integrations' env vars;
                            base URL used for the internal self-call that
                            actually creates the property/inspection.

Every write goes through a human-in-the-loop confirmation (see telegram_intent.py
for the parsing/resolution logic) and then an ordinary internal HTTP call to
this app's own /api/properties or /api/inspections, authenticated with a
short-lived JWT minted for the linked user — so all existing role checks,
validation, and side effects (Sheet sync, Calendar push) apply unchanged.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, create_access_token

from permissions import get_current_user
from routes.telegram_intent import (
    parse_message,
    RESOLVERS,
    SUMMARIZERS,
    BUILD_PAYLOAD,
    ACTION_CONFIG,
    WIZARD_STEPS,
    coerce_wizard_answer,
    READ_ONLY_TOOLS,
    ANSWERERS,
)

telegram_bp = Blueprint('telegram', __name__)

_AFFIRMATIVE = {'yes', 'y', 'confirm', 'confirmed', 'ok', 'okay', 'yep', 'yeah'}
_NEGATIVE = {'no', 'n', 'cancel', 'nah'}
_STALE_SESSION_AFTER = timedelta(minutes=15)


# ── Telegram API helpers ──────────────────────────────────────────────────

def _telegram_call(method: str, **params):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        print('[telegram] TELEGRAM_BOT_TOKEN not set — skipping API call')
        return None
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/{method}',
            json=params,
            timeout=10,
        )
        if not resp.ok:
            print(f'[telegram] {method} failed: {resp.status_code} {resp.text[:200]}')
        return resp
    except requests.RequestException as e:
        print(f'[telegram] {method} error (non-fatal): {e}')
        return None


def _send_message(chat_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        params['reply_markup'] = reply_markup
    _telegram_call('sendMessage', **params)


def _answer_callback_query(callback_query_id):
    _telegram_call('answerCallbackQuery', callback_query_id=callback_query_id)


def _confirm_keyboard():
    return {
        'inline_keyboard': [[
            {'text': '✅ Confirm', 'callback_data': 'confirm'},
            {'text': '✏️ Edit', 'callback_data': 'edit'},
            {'text': '❌ Cancel', 'callback_data': 'cancel'},
        ]]
    }


# ── Session helpers ────────────────────────────────────────────────────────

def _get_or_create_session(chat_id):
    from models import db, TelegramSession
    session = TelegramSession.query.filter_by(chat_id=chat_id).first()
    if session is None:
        session = TelegramSession(chat_id=chat_id, state='idle')
        db.session.add(session)
        db.session.commit()
    return session


def _reset_session(session):
    from models import db
    session.state = 'idle'
    session.pending_tool = None
    session.pending_action_json = None
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def _advance_session(session, tool_name, raw_args):
    """Merge newly-extracted args into the session, resolve, and either ask a
    follow-up question or move to confirmation."""
    from models import db

    existing = {}
    if session.pending_tool == tool_name and session.pending_action_json:
        try:
            existing = json.loads(session.pending_action_json)
        except (TypeError, ValueError):
            existing = {}
    merged = {**existing, **{k: v for k, v in raw_args.items() if v not in (None, '')}}

    resolved, question = RESOLVERS[tool_name](merged)

    if question:
        session.state = 'awaiting_field'
        session.pending_tool = tool_name
        session.pending_action_json = json.dumps(merged)
        session.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        _send_message(session.chat_id, question)
        return

    session.state = 'awaiting_confirmation'
    session.pending_tool = tool_name
    session.pending_action_json = json.dumps(resolved)
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    _send_message(session.chat_id, SUMMARIZERS[tool_name](resolved), reply_markup=_confirm_keyboard())


def _execute_pending_action(session, user):
    tool_name = session.pending_tool
    try:
        resolved = json.loads(session.pending_action_json or '{}')
    except (TypeError, ValueError):
        resolved = {}

    config = ACTION_CONFIG[tool_name]
    payload = BUILD_PAYLOAD[tool_name](resolved)
    backend_url = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    token = create_access_token(identity=str(user.id), expires_delta=timedelta(minutes=2))

    try:
        resp = requests.request(
            config['method'],
            f"{backend_url}{config['path'](resolved)}",
            json=payload,
            headers={'Authorization': f'Bearer {token}'},
            timeout=15,
        )
    except requests.RequestException as e:
        print(f'[telegram] internal API call failed: {e}')
        _send_message(session.chat_id, 'Something went wrong reaching the app — try confirming again in a moment.')
        return

    if 200 <= resp.status_code < 300:
        body = resp.json() if resp.content else {}
        _reset_session(session)
        if tool_name == 'create_property':
            _send_message(session.chat_id, f"✅ Property created: {body.get('address', payload.get('address'))}")
        elif tool_name == 'book_inspection':
            ref = body.get('reference_number') or f"#{body.get('id')}"
            _send_message(session.chat_id, f"✅ Inspection booked: {ref} at {body.get('property_address', resolved.get('property_address'))}")
        elif tool_name == 'update_inspection':
            _send_message(session.chat_id, f"✅ Inspection updated at {resolved.get('property_address')}.")
        else:
            _send_message(session.chat_id, f"✅ Report sent to {', '.join(resolved.get('emails', []))}.")
    elif resp.status_code in (401, 403):
        _reset_session(session)
        _send_message(session.chat_id, "You don't have permission to do that.")
    elif resp.status_code == 400:
        _reset_session(session)
        _send_message(session.chat_id, f'That didn\'t go through: {resp.text[:200]}')
    else:
        _send_message(session.chat_id, 'Something went wrong on the server — try confirming again in a moment.')


# ── Guided forms (/property, /inspection) ───────────────────────────────────
# A wizard walks WIZARD_STEPS[tool_name] one field at a time (session.state =
# 'wizard', with the collected fields plus a '_step' cursor stashed in
# pending_action_json). Once every step is answered, the collected fields are
# handed to _advance_session exactly like a free-text parse — so ambiguous
# matches (e.g. two clients with a similar name) fall back into the same
# awaiting_field question flow, and both entry points share one confirmation
# step and one write path.

def _wizard_keyboard(step):
    if not step.get('options'):
        return None
    buttons = [{'text': opt, 'callback_data': f'wz:{opt}'} for opt in step['options']]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    return {'inline_keyboard': rows}


def _send_wizard_step(session, tool_name, step_index):
    step = WIZARD_STEPS[tool_name][step_index]
    _send_message(session.chat_id, step['prompt'], reply_markup=_wizard_keyboard(step))


def _start_wizard(session, tool_name):
    from models import db
    session.state = 'wizard'
    session.pending_tool = tool_name
    session.pending_action_json = json.dumps({'_step': 0})
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    _send_wizard_step(session, tool_name, 0)


def _handle_wizard_answer(session, user, raw_text):
    from models import db

    tool_name = session.pending_tool
    steps = WIZARD_STEPS[tool_name]
    try:
        state = json.loads(session.pending_action_json or '{}')
    except (TypeError, ValueError):
        state = {}
    step_index = state.get('_step', 0)
    step = steps[step_index]

    answer = coerce_wizard_answer(step, raw_text)
    if answer.error:
        _send_message(session.chat_id, answer.error)
        _send_wizard_step(session, tool_name, step_index)
        return

    if not answer.skipped:
        state[step['field']] = answer.value

    next_index = step_index + 1
    if next_index < len(steps):
        state['_step'] = next_index
        session.pending_action_json = json.dumps(state)
        session.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        _send_wizard_step(session, tool_name, next_index)
        return

    collected = {k: v for k, v in state.items() if k != '_step'}
    session.pending_action_json = None  # drop the wizard's '_step' cursor before merging into _advance_session
    _advance_session(session, tool_name, collected)


# ── Commands ─────────────────────────────────────────────────────────────────

_HELP_TEXT = (
    'I can help you manage inspections and properties. Try:\n'
    '• Just tell me what you need, e.g. "book an inspection at 12 Smith St for Thursday"\n'
    '• /property — step-by-step form to create a property with full details\n'
    '• /inspection — step-by-step form to book an inspection\n'
    '• To reschedule or change an inspection, just tell me, e.g. "move the check-out '
    'at 12 Smith St to next Friday"\n'
    '• /share — send a completed report\'s PDF to the client and/or tenant\n'
    '• Ask me things like "what\'s on today?", "is 12 Smith St\'s report done?", or '
    '"who\'s free tomorrow?"\n'
    '• /cancel — cancel whatever we\'re doing'
)


def _handle_command(session, text):
    """Returns True if `text` was a recognized command (and has already been
    fully handled), False if the caller should fall through to normal
    message handling."""
    cmd = text.split()[0].lower()
    if cmd in ('/start', '/help'):
        _reset_session(session)
        _send_message(session.chat_id, _HELP_TEXT)
        return True
    if cmd == '/cancel':
        _reset_session(session)
        _send_message(session.chat_id, 'Cancelled.')
        return True
    if cmd == '/property':
        _start_wizard(session, 'create_property')
        return True
    if cmd == '/inspection':
        _start_wizard(session, 'book_inspection')
        return True
    if cmd == '/share':
        # No wizard needed — share_report's own resolver already asks for the
        # property and then who to send to, one question at a time.
        _advance_session(session, 'share_report', {})
        return True
    return False


# ── Linking ────────────────────────────────────────────────────────────────

def _handle_unlinked(chat_id, text, message):
    if text.startswith('/link'):
        parts = text.split(maxsplit=1)
        code = parts[1].strip().upper() if len(parts) > 1 else ''
        _try_link(chat_id, code, message)
        return
    _send_message(
        chat_id,
        'Hi! To use this bot, link it to your InspectPro account first: open the app, '
        'go to Settings → Link Telegram, and send me the code it gives you (e.g. /link ABCD1234).'
    )


def _try_link(chat_id, code, message):
    from models import db, TelegramLinkCode, TelegramLink, User

    if not code:
        _send_message(chat_id, 'Send it as /link YOURCODE')
        return

    row = TelegramLinkCode.query.filter_by(code=code, used_at=None).first()
    if not row or row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        _send_message(chat_id, 'That code is invalid or expired — generate a new one from Settings → Link Telegram.')
        return

    if TelegramLink.query.filter_by(chat_id=chat_id).first():
        _send_message(chat_id, 'This Telegram chat is already linked to an account.')
        return
    if TelegramLink.query.filter_by(user_id=row.user_id).first():
        _send_message(chat_id, 'That account is already linked to a different Telegram chat — unlink it first from Settings → Link Telegram.')
        return

    from_user = message.get('from', {})
    db.session.add(TelegramLink(
        user_id=row.user_id,
        chat_id=chat_id,
        telegram_username=from_user.get('username'),
        telegram_first_name=from_user.get('first_name'),
    ))
    row.used_at = datetime.now(timezone.utc)
    db.session.commit()

    user = db.session.get(User, row.user_id)
    _send_message(chat_id, f'Linked as {user.name} ({user.role}). You can now ask me to create a property or book an inspection.')


# ── Message / callback handling ────────────────────────────────────────────

def _handle_confirmation_reply(session, user, text):
    normalized = text.strip().lower()
    if normalized in _AFFIRMATIVE:
        _execute_pending_action(session, user)
        return
    if normalized in _NEGATIVE:
        _reset_session(session)
        _send_message(session.chat_id, 'Cancelled.')
        return
    # Treat anything else as a correction — re-parse against the same tool and merge.
    intent = parse_message(text, forced_tool=session.pending_tool)
    if intent.tool_name:
        _advance_session(session, intent.tool_name, intent.args)
    else:
        _send_message(session.chat_id, 'Reply YES to confirm, NO to cancel, or tell me what to change.')


def _handle_text_message(message):
    chat_id = message['chat']['id']
    text = (message.get('text') or '').strip()
    if not text:
        return

    from models import TelegramLink

    link = TelegramLink.query.filter_by(chat_id=chat_id).first()
    if not link:
        _handle_unlinked(chat_id, text, message)
        return

    user = link.user
    session = _get_or_create_session(chat_id)

    if text.startswith('/') and _handle_command(session, text):
        return

    if session.state != 'idle' and session.updated_at:
        age = datetime.now(timezone.utc) - session.updated_at.replace(tzinfo=timezone.utc)
        if age > _STALE_SESSION_AFTER:
            _reset_session(session)

    if session.state == 'awaiting_confirmation':
        _handle_confirmation_reply(session, user, text)
        return

    if session.state == 'wizard':
        _handle_wizard_answer(session, user, text)
        return

    forced_tool = session.pending_tool if session.state == 'awaiting_field' else None

    # A bare number while update_inspection/share_report is disambiguating
    # "which inspection?" is a pick, not free text to re-parse — re-parsing
    # "2" would just make the model guess a nonsense property address out of
    # a single digit.
    if forced_tool in ('update_inspection', 'share_report') and text.strip().isdigit():
        _advance_session(session, forced_tool, {'_pick': text.strip()})
        return

    intent = parse_message(text, forced_tool=forced_tool)

    if intent.tool_name is None:
        _send_message(chat_id, intent.reply_text)
        return

    if intent.tool_name in READ_ONLY_TOOLS:
        # Reads have no side effects — answer immediately, no session/confirm
        # step. Only reachable here (idle-state, auto tool_choice): forced_tool
        # during awaiting_field is always a write-tool name, so a query tool
        # can never surface mid-flow.
        _send_message(chat_id, ANSWERERS[intent.tool_name](intent.args, user))
        return

    _advance_session(session, intent.tool_name, intent.args)


def _handle_callback_query(cq):
    chat_id = cq['message']['chat']['id']
    data = cq.get('data', '')
    _answer_callback_query(cq['id'])

    from models import TelegramLink

    link = TelegramLink.query.filter_by(chat_id=chat_id).first()
    if not link:
        return
    session = _get_or_create_session(chat_id)

    if session.state == 'wizard' and data.startswith('wz:'):
        _handle_wizard_answer(session, link.user, data[len('wz:'):])
        return

    if session.state != 'awaiting_confirmation':
        return

    if data == 'confirm':
        _execute_pending_action(session, link.user)
    elif data == 'cancel':
        _reset_session(session)
        _send_message(chat_id, 'Cancelled.')
    elif data == 'edit':
        _send_message(chat_id, 'Tell me what to change.')
        # Stays in awaiting_confirmation — the next text message is treated as a correction.


# ── Routes ──────────────────────────────────────────────────────────────────

@telegram_bp.route('/webhook/<secret_path>', methods=['POST'])
def webhook(secret_path):
    configured_secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
    header_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if (
        not configured_secret
        or not secrets.compare_digest(secret_path, configured_secret)
        or not secrets.compare_digest(header_secret, configured_secret)
    ):
        return '', 403

    update = request.get_json(silent=True) or {}

    try:
        if 'callback_query' in update:
            _handle_callback_query(update['callback_query'])
        elif 'message' in update and 'text' in update['message']:
            _handle_text_message(update['message'])
        # Other update types (photos, stickers, edited messages, ...) are ignored.
    except Exception as e:
        print(f'[telegram] webhook handler error (non-fatal): {e}')

    return '', 200


@telegram_bp.route('/link-code', methods=['OPTIONS'])
@telegram_bp.route('/status', methods=['OPTIONS'])
@telegram_bp.route('/unlink', methods=['OPTIONS'])
def handle_options():
    return '', 204


@telegram_bp.route('/link-code', methods=['POST'])
@jwt_required()
def create_link_code():
    from models import db, TelegramLinkCode, TelegramLink

    user = get_current_user()
    if TelegramLink.query.filter_by(user_id=user.id).first():
        return jsonify({'error': 'Already linked'}), 400

    TelegramLinkCode.query.filter_by(user_id=user.id, used_at=None).delete(synchronize_session=False)

    code = secrets.token_hex(4).upper()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.session.add(TelegramLinkCode(code=code, user_id=user.id, expires_at=expires_at))
    db.session.commit()

    return jsonify({
        'code': code,
        'expires_at': expires_at.isoformat(),
        'bot_username': os.environ.get('TELEGRAM_BOT_USERNAME', ''),
    })


@telegram_bp.route('/status', methods=['GET'])
@jwt_required()
def status():
    from models import TelegramLink

    user = get_current_user()
    link = TelegramLink.query.filter_by(user_id=user.id).first()
    if not link:
        return jsonify({'linked': False})
    return jsonify({'linked': True, **link.to_dict()})


@telegram_bp.route('/unlink', methods=['DELETE'])
@jwt_required()
def unlink():
    from models import db, TelegramLink

    user = get_current_user()
    TelegramLink.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'unlinked': True})
