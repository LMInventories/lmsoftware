"""
routes/telegram_integration.py
─────────────────────────────────
Staff (admin / manager) drive the app from a Telegram bot with these commands:

  /property    guided, button-driven flow that adds a property
  /inspection  guided, button-driven flow that books an inspection
  /share       guided flow that emails a completed report's PDF
  /paid        guided flow that marks one or more invoices paid
  /lookup      conversational, read-only questions about properties, inspections,
               clients, the schedule and unpaid invoices (Claude, with memory of
               the conversation until /cancel or 30 idle minutes)

This module owns the one genuinely public, unauthenticated-by-JWT endpoint in the
app: Telegram's webhook POSTs here directly. It's gated by a secret path segment
AND Telegram's `X-Telegram-Bot-Api-Secret-Token` header, both checked with a
constant-time compare before anything else runs.

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
  BACKEND_URL             — base URL for the internal self-call that actually
                            creates the property/inspection.
  ANTHROPIC_API_KEY       — /lookup only.

Every write goes through a confirm card and then an ordinary internal HTTP call to
this app's own /api/properties, /api/inspections or share-pdf endpoint, authenticated with a
short-lived JWT minted for the linked user — so all existing role checks,
validation, and side effects (Sheet sync, Calendar push) apply unchanged.

Session (TelegramSession) states: idle | flow | lookup. In 'flow',
pending_tool is the flow name and pending_action_json the flow engine's state
(see telegram_flows.py); in 'lookup', lookup_history_json is the conversation.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, create_access_token

from permissions import get_current_user, is_admin_or_manager
from routes import telegram_flows
from routes.telegram_intent import ACTION_CONFIG, BUILD_PAYLOAD

telegram_bp = Blueprint('telegram', __name__)
log = logging.getLogger(__name__)

_STALE_SESSION_AFTER = timedelta(minutes=30)
_LOOKUP_MEMORY_CHARS = 14000  # rough cap on replayed conversation


# ── Telegram API helpers ──────────────────────────────────────────────────

def _telegram_call(method: str, **params):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        log.warning('[telegram] TELEGRAM_BOT_TOKEN not set — skipping API call')
        return None
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/{method}',
            json=params,
            timeout=10,
        )
        if not resp.ok:
            log.warning('[telegram] %s failed: %s %s', method, resp.status_code, resp.text[:200])
        return resp
    except requests.RequestException as e:
        log.warning('[telegram] %s error (non-fatal): %s', method, e)
        return None


def _send_message(chat_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        params['reply_markup'] = reply_markup
    _telegram_call('sendMessage', **params)


def _send_replies(chat_id, replies):
    for text, keyboard in replies:
        _send_message(chat_id, text, reply_markup=keyboard)


def _send_typing(chat_id):
    _telegram_call('sendChatAction', chat_id=chat_id, action='typing')


def _answer_callback_query(callback_query_id, text=None):
    params = {'callback_query_id': callback_query_id}
    if text:
        params['text'] = text
    _telegram_call('answerCallbackQuery', **params)


# ── Session helpers ────────────────────────────────────────────────────────

def _get_or_create_session(chat_id):
    from models import db, TelegramSession
    from sqlalchemy.exc import IntegrityError
    session = TelegramSession.query.filter_by(chat_id=chat_id).first()
    if session is None:
        session = TelegramSession(chat_id=chat_id, state='idle')
        db.session.add(session)
        try:
            db.session.commit()
        except IntegrityError:  # a concurrent worker created it first
            db.session.rollback()
            session = TelegramSession.query.filter_by(chat_id=chat_id).first()
    return session


def _is_duplicate_update(session, update_id) -> bool:
    """Telegram redelivers an update when a webhook is slow to answer. The atomic
    UPDATE only succeeds for the first worker to see a given update_id."""
    if update_id is None:
        return False
    from models import db, TelegramSession
    claimed = (
        TelegramSession.query
        .filter(TelegramSession.id == session.id,
                (TelegramSession.last_update_id.is_(None)) | (TelegramSession.last_update_id < update_id))
        .update({'last_update_id': update_id}, synchronize_session=False)
    )
    db.session.commit()
    if claimed:
        db.session.refresh(session)
    return not claimed


def _reset_session(session):
    from models import db
    session.state = 'idle'
    session.pending_tool = None
    session.pending_action_json = None
    session.lookup_history_json = None
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def _touch(session):
    from models import db
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def _expire_if_stale(session):
    if session.state != 'idle' and session.updated_at:
        age = datetime.now(timezone.utc) - session.updated_at.replace(tzinfo=timezone.utc)
        if age > _STALE_SESSION_AFTER:
            _reset_session(session)


# ── Flows (/property, /inspection) ─────────────────────────────────────────

def _save_flow(session, state):
    from models import db
    session.state = 'flow'
    session.pending_tool = state['flow']
    session.pending_action_json = json.dumps(state)
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def _load_flow(session):
    try:
        state = json.loads(session.pending_action_json or '')
    except (TypeError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get('flow') in telegram_flows.STEPS else None


def _start_flow(session, flow_name):
    state, replies, _ = telegram_flows.start(flow_name)
    session.lookup_history_json = None
    _save_flow(session, state)
    _send_replies(session.chat_id, replies)


def _continue_flow(session, user, result):
    """Persist the engine's new state, send its replies, and act on 'execute'/'cancelled'."""
    state, replies, action = result
    _save_flow(session, state)
    _send_replies(session.chat_id, replies)
    if action == 'cancelled':
        _reset_session(session)
        _send_message(session.chat_id, 'Cancelled.')
    elif action == 'execute':
        _execute_flow(session, user, state)


def _execute_flow(session, user, state):
    tool_name = state['flow']
    resolved = telegram_flows.build_resolved(state)
    if tool_name == telegram_flows.PAID_FLOW:
        _execute_mark_invoice_paid(session, user, resolved)
        return
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
        log.warning('[telegram] internal API call failed: %s', e)
        _send_message(session.chat_id, 'Something went wrong reaching the app — tap Confirm again in a moment.',
                      reply_markup=telegram_flows._confirm_reply(state)[1])
        return

    if 200 <= resp.status_code < 300:
        body = resp.json() if resp.content else {}
        _reset_session(session)
        if tool_name == 'create_property':
            _send_message(session.chat_id, f"✅ Property created: {body.get('address', payload.get('address'))}")
        elif tool_name == 'share_report':
            _send_message(session.chat_id, f"✅ Sending the report for {resolved['property_address']} to "
                                           f"{', '.join(resolved['emails'])}. It can take a minute or two to arrive.")
        else:
            ref = body.get('reference_number') or f"#{body.get('id')}"
            _send_message(session.chat_id, f"✅ Inspection booked: {ref} at {body.get('property_address', resolved.get('property_address'))}")
    elif resp.status_code in (401, 403):
        _reset_session(session)
        _send_message(session.chat_id, "You don't have permission to do that.")
    elif resp.status_code == 400:
        _reset_session(session)
        _send_message(session.chat_id, f"That didn't go through: {resp.text[:200]}")
    else:
        log.warning('[telegram] internal API call returned %s: %s', resp.status_code, resp.text[:200])
        _send_message(session.chat_id, 'Something went wrong on the server — tap Confirm again in a moment.',
                      reply_markup=telegram_flows._confirm_reply(state)[1])


def _execute_mark_invoice_paid(session, user, resolved):
    """mark_invoice_paid's confirmed items each need their own PUT — this doesn't fit
    ACTION_CONFIG's single method+path shape, so it's a dedicated executor rather than
    a generic one forced to handle N targets."""
    items = resolved.get('items', [])
    backend_url = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    token = create_access_token(identity=str(user.id), expires_delta=timedelta(minutes=2))

    succeeded, failed = [], []
    for item in items:
        label = f"{item['reference_number']} — {item['property_address']}"
        try:
            resp = requests.put(
                f"{backend_url}/api/inspections/{item['inspection_id']}",
                json={'invoice_paid': True},
                headers={'Authorization': f'Bearer {token}'},
                timeout=15,
            )
        except requests.RequestException as e:
            log.warning('[telegram] internal API call failed for inspection %s: %s', item['inspection_id'], e)
            failed.append(f'{label}: connection error')
            continue

        if 200 <= resp.status_code < 300:
            succeeded.append(label)
        elif resp.status_code in (401, 403):
            failed.append(f'{label}: no permission')
        else:
            log.warning('[telegram] mark paid for inspection %s returned %s', item['inspection_id'], resp.status_code)
            failed.append(f'{label}: server error')

    _reset_session(session)
    lines = []
    if succeeded:
        lines.append('✅ Marked as paid:')
        lines += [f'• {s}' for s in succeeded]
    if failed:
        if lines:
            lines.append('')
        lines.append('⚠️ Could not update:')
        lines += [f'• {f}' for f in failed]
    _send_message(session.chat_id, '\n'.join(lines) or 'Nothing was updated.')


# ── Lookup (/lookup) ───────────────────────────────────────────────────────

def _lookup_messages(session):
    """The stored conversation as [{'role', 'content'}], newest turns kept within a
    character budget so a long chat never blows the context window."""
    try:
        turns = json.loads(session.lookup_history_json or '[]')
    except (TypeError, ValueError):
        return []
    kept, budget = [], _LOOKUP_MEMORY_CHARS
    for t in reversed(turns):
        if not isinstance(t, dict) or 'role' not in t or 'content' not in t:
            continue
        budget -= len(t['content'])
        if budget < 0 and kept:
            break
        kept.append({'role': t['role'], 'content': t['content']})
    kept.reverse()
    while kept and kept[0]['role'] != 'user':  # a conversation must open with the user
        kept.pop(0)
    return kept


def _remember_lookup(session, question, stored_answer):
    from models import db
    try:
        turns = json.loads(session.lookup_history_json or '[]')
    except (TypeError, ValueError):
        turns = []
    turns += [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': stored_answer}]
    session.lookup_history_json = json.dumps(turns[-40:])
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()


def _lookup_turn(session, user, text):
    import anthropic
    from routes.telegram_lookup import answer_lookup

    _send_typing(session.chat_id)  # the lookup loop takes a few seconds
    try:
        reply, stored = answer_lookup(text, user, _lookup_messages(session))
    except anthropic.APIError as e:
        log.warning('[telegram] lookup API error: %s', e)
        _send_message(session.chat_id, "Sorry, I couldn't look that up just now — please try again in a moment.")
        return
    _send_message(session.chat_id, reply)
    _remember_lookup(session, text, stored)


def _start_lookup(session, user, question):
    from models import db
    if session.state != 'lookup':  # a fresh conversation
        session.lookup_history_json = None
    session.state = 'lookup'
    session.pending_tool = None
    session.pending_action_json = None
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    if question:
        _lookup_turn(session, user, question)
    else:
        _send_message(session.chat_id, _LOOKUP_INTRO)


# ── Commands ─────────────────────────────────────────────────────────────────

_HELP_TEXT = (
    'I can add properties and inspections, email reports, mark invoices paid and answer questions. Commands:\n'
    "• /property — add a property (I'll ask you step by step)\n"
    '• /inspection — book an inspection\n'
    '• /share — email a completed report to the client, tenant or anyone else\n'
    '• /paid — mark one or more invoices as paid\n'
    '• /lookup — ask about a property, inspection, client, the schedule or unpaid '
    "invoices; I remember what we've talked about, so follow-ups work\n"
    "• /cancel — stop whatever we're doing"
)

_LOOKUP_INTRO = (
    'Ask me anything about properties, inspections, clients, the schedule or unpaid invoices — '
    'e.g. "what\'s on tomorrow?", "who\'s the tenant at 12 Smith St?", "what has Acme not paid yet?". '
    "Follow-up questions work. /cancel when you're done."
)


def _handle_command(session, user, text):
    """True if `text` was a recognised command (already fully handled)."""
    head, _, rest = text.partition(' ')
    cmd = head.split('@')[0].lower()
    if cmd in ('/start', '/help'):
        _reset_session(session)
        _send_message(session.chat_id, _HELP_TEXT)
        return True
    if cmd == '/cancel':
        _reset_session(session)
        _send_message(session.chat_id, 'Cancelled.')
        return True
    if cmd == '/property':
        _start_flow(session, telegram_flows.PROPERTY_FLOW)
        return True
    if cmd == '/inspection':
        _start_flow(session, telegram_flows.INSPECTION_FLOW)
        return True
    if cmd == '/share':
        _start_flow(session, telegram_flows.SHARE_FLOW)
        return True
    if cmd == '/paid':
        _start_flow(session, telegram_flows.PAID_FLOW)
        return True
    if cmd == '/lookup':
        _start_lookup(session, user, rest.strip())
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

_REFUSAL = "Sorry — this bot is for office staff (admins and managers) only."


def _handle_text_message(message, update_id=None):
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
    if _is_duplicate_update(session, update_id):
        return
    if not is_admin_or_manager(user):
        _send_message(chat_id, _REFUSAL)
        return

    _expire_if_stale(session)

    if text.startswith('/') and _handle_command(session, user, text):
        return

    if session.state == 'flow':
        state = _load_flow(session)
        if state is None:
            _reset_session(session)
            _send_message(chat_id, 'That got lost — please start again with the command you were using.')
            return
        _continue_flow(session, user, telegram_flows.handle_text(state, text))
    elif session.state == 'lookup':
        _lookup_turn(session, user, text)
    else:
        _send_message(chat_id, 'Use /property, /inspection, /share, /paid or /lookup — or /help to see what I can do.')


def _handle_callback_query(cq, update_id=None):
    chat_id = cq['message']['chat']['id']
    data = cq.get('data', '')

    from models import TelegramLink

    link = TelegramLink.query.filter_by(chat_id=chat_id).first()
    if not link or not is_admin_or_manager(link.user):
        _answer_callback_query(cq['id'])
        return
    session = _get_or_create_session(chat_id)
    if _is_duplicate_update(session, update_id):
        return

    parts = data.split(':', 2)
    state = _load_flow(session) if session.state == 'flow' else None
    if len(parts) != 3 or parts[0] != 'f' or state is None:
        _answer_callback_query(cq['id'], 'That button has expired.')
        return
    _answer_callback_query(cq['id'])
    _expire_if_stale(session)
    if session.state != 'flow':
        _send_message(chat_id, 'That timed out — please start again with the command you were using.')
        return
    _continue_flow(session, link.user, telegram_flows.handle_callback(state, parts[1], parts[2]))


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
    update_id = update.get('update_id')

    try:
        if 'callback_query' in update:
            _handle_callback_query(update['callback_query'], update_id)
        elif 'message' in update and 'text' in update['message']:
            _handle_text_message(update['message'], update_id)
        # Other update types (photos, stickers, edited messages, ...) are ignored.
    except Exception:
        log.exception('[telegram] webhook handler error (non-fatal)')
        _tell_user_it_failed(update)

    return '', 200


def _tell_user_it_failed(update):
    """Never leave the user with silence after an unexpected error."""
    try:
        from models import db
        db.session.rollback()
        msg = update.get('message') or (update.get('callback_query') or {}).get('message') or {}
        chat_id = (msg.get('chat') or {}).get('id')
        if chat_id:
            _send_message(chat_id, 'Something went wrong on my side — please try again, or /cancel to start over.')
    except Exception:
        log.exception('[telegram] could not report failure to user')


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
