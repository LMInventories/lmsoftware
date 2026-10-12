"""Dispatcher tests: webhook gating, roles, command routing, dedupe, execution, and /lookup memory.
Telegram and the app's own HTTP API are stubbed; the database is an in-memory SQLite."""
import json

import pytest

from routes import telegram_integration as tg

CHAT = 555


@pytest.fixture()
def sent(monkeypatch):
    """Capture everything the bot would send to Telegram."""
    out = []
    monkeypatch.setattr(tg, '_telegram_call', lambda method, **params: out.append((method, params)))
    return out


def _messages(sent):
    return [p['text'] for m, p in sent if m == 'sendMessage']


def _link(world, user_key='manager', chat_id=CHAT):
    from models import TelegramLink, db
    db.session.add(TelegramLink(user_id=world[user_key].id, chat_id=chat_id))
    db.session.commit()


def _say(text, update_id=None, chat_id=CHAT):
    tg._handle_text_message({'chat': {'id': chat_id}, 'text': text}, update_id)


def _tap(data, update_id=None, chat_id=CHAT):
    tg._handle_callback_query({'id': 'cb', 'data': data, 'message': {'chat': {'id': chat_id}}}, update_id)


def _session():
    from models import TelegramSession
    return TelegramSession.query.filter_by(chat_id=CHAT).first()


# ── Webhook gating ──────────────────────────────────────────────────────────

def test_webhook_rejects_wrong_secret(app, monkeypatch):
    monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET', 'right')
    app.register_blueprint(tg.telegram_bp, url_prefix='/api/telegram')
    client = app.test_client()
    assert client.post('/api/telegram/webhook/wrong', json={}, headers={'X-Telegram-Bot-Api-Secret-Token': 'right'}).status_code == 403
    assert client.post('/api/telegram/webhook/right', json={}, headers={'X-Telegram-Bot-Api-Secret-Token': 'nope'}).status_code == 403
    assert client.post('/api/telegram/webhook/right', json={}, headers={'X-Telegram-Bot-Api-Secret-Token': 'right'}).status_code == 200


def test_webhook_reports_unexpected_errors_to_the_user(app, monkeypatch, sent):
    monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET', 's')
    app.register_blueprint(tg.telegram_bp, url_prefix='/api/telegram')

    def boom(*a, **k):
        raise RuntimeError('db exploded')
    monkeypatch.setattr(tg, '_handle_text_message', boom)
    resp = app.test_client().post(
        '/api/telegram/webhook/s', headers={'X-Telegram-Bot-Api-Secret-Token': 's'},
        json={'update_id': 1, 'message': {'chat': {'id': CHAT}, 'text': 'hi'}})
    assert resp.status_code == 200
    assert 'Something went wrong' in _messages(sent)[-1]


# ── Linking and roles ───────────────────────────────────────────────────────

def test_unlinked_chat_is_told_to_link(world, sent):
    _say('hello')
    assert 'link it to your InspectPro account' in _messages(sent)[0]


def test_non_office_roles_are_refused(world, sent):
    _link(world, 'clerk')
    _say('/property')
    assert 'office staff' in _messages(sent)[-1]
    assert _session().state == 'idle'


def test_idle_text_points_at_commands(world, sent):
    _link(world)
    _say('book me an inspection tomorrow')
    assert '/property' in _messages(sent)[-1] and '/lookup' in _messages(sent)[-1]


def test_help_and_cancel(world, sent):
    _link(world)
    _say('/help')
    assert '/lookup' in _messages(sent)[-1]
    _say('/property')
    assert _session().state == 'flow'
    _say('/cancel')
    assert _session().state == 'idle' and _messages(sent)[-1] == 'Cancelled.'


def test_command_with_bot_suffix(world, sent):
    _link(world)
    _say('/property@LMInspectBot')
    assert _session().state == 'flow'


# ── Flow through the dispatcher ─────────────────────────────────────────────

def test_property_flow_end_to_end_posts_to_the_app(world, sent, monkeypatch):
    _link(world)
    monkeypatch.setenv('BACKEND_URL', 'http://backend.test')
    calls = []

    class Resp:
        status_code = 201
        content = b'{}'
        text = '{}'

        def json(self):
            return {'id': 9, 'address': '10 Downing Street, London SW1A 2AA'}

    monkeypatch.setattr(tg.requests, 'request', lambda method, url, **kw: calls.append((method, url, kw)) or Resp())

    _say('/property', update_id=1)
    _say('acme', update_id=2)
    _say('10 Downing Street, London SW1A 2AA', update_id=3)
    _tap('f:bedrooms:3', update_id=4)
    _tap('f:bathrooms:2', update_id=5)
    _tap('f:furnished:skip', update_id=6)
    _tap('f:features:done', update_id=7)
    _tap('f:elevation:skip', update_id=8)
    _tap('f:notes:skip', update_id=9)
    assert 'Create this property?' in _messages(sent)[-1]
    assert not calls

    _tap('f:confirm:yes', update_id=10)
    assert len(calls) == 1
    method, url, kw = calls[0]
    assert (method, url) == ('POST', 'http://backend.test/api/properties')
    assert kw['json']['client_id'] == world['client'].id and kw['json']['bedrooms'] == 3
    assert kw['headers']['Authorization'].startswith('Bearer ')
    assert 'Property created' in _messages(sent)[-1]
    assert _session().state == 'idle'


def test_api_rejection_is_reported_and_clears_the_flow(world, sent, monkeypatch):
    _link(world)

    class Resp:
        status_code = 400
        content = b'x'
        text = 'address missing'
    monkeypatch.setattr(tg.requests, 'request', lambda *a, **k: Resp())

    _say('/property')
    _say('acme')
    _say('10 Downing Street SW1A 2AA')
    for data in ('f:bedrooms:1', 'f:bathrooms:1', 'f:furnished:skip', 'f:features:done', 'f:elevation:skip', 'f:notes:skip', 'f:confirm:yes'):
        _tap(data)
    assert "didn't go through: address missing" in _messages(sent)[-1]
    assert _session().state == 'idle'


def test_server_error_keeps_the_confirm_card_retryable(world, sent, monkeypatch):
    _link(world)

    class Resp:
        status_code = 500
        content = b''
        text = 'boom'
    monkeypatch.setattr(tg.requests, 'request', lambda *a, **k: Resp())

    _say('/property')
    _say('acme')
    _say('10 Downing Street SW1A 2AA')
    for data in ('f:bedrooms:1', 'f:bathrooms:1', 'f:furnished:skip', 'f:features:done', 'f:elevation:skip', 'f:notes:skip', 'f:confirm:yes'):
        _tap(data)
    assert 'tap Confirm again' in _messages(sent)[-1]
    assert _session().state == 'flow'
    assert json.loads(_session().pending_action_json)['step'] == 'confirm'


def test_stale_button_gets_a_toast_and_no_changes(world, sent):
    _link(world)
    _tap('f:bedrooms:3')   # no flow running
    assert any(m == 'answerCallbackQuery' and p.get('text') == 'That button has expired.' for m, p in sent)
    assert not _messages(sent)


def test_redelivered_update_is_ignored(world, sent):
    _link(world)
    _say('/property', update_id=10)
    n = len(sent)
    _say('/property', update_id=10)       # Telegram retry
    _say('/property', update_id=9)        # older than what we've seen
    assert len(sent) == n


def test_stale_flow_expires(world, sent):
    from datetime import datetime, timedelta, timezone
    from models import db
    _link(world)
    _say('/property')
    s = _session()
    s.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.session.commit()
    _say('acme')
    assert _session().state == 'idle'
    assert '/property' in _messages(sent)[-1]


# ── /lookup ─────────────────────────────────────────────────────────────────

def test_lookup_conversation_remembers_earlier_turns(world, sent, monkeypatch):
    _link(world)
    seen = []

    def fake_answer(question, user, history):
        seen.append((question, list(history)))
        return f'answer to: {question}', f'answer to: {question}\n[looked at: property_id 1]'

    import routes.telegram_lookup as lookup
    monkeypatch.setattr(lookup, 'answer_lookup', fake_answer)

    _say('/lookup who is the client at 12 Smith St?')
    assert _session().state == 'lookup'
    assert _messages(sent)[-1] == 'answer to: who is the client at 12 Smith St?'

    _say('and their email?')                                     # no command needed in lookup mode
    question, history = seen[1]
    assert question == 'and their email?'
    assert [h['role'] for h in history] == ['user', 'assistant']
    assert 'property_id 1' in history[1]['content']

    _say('/property')                                           # leaving lookup starts the flow
    assert _session().state == 'flow'


def test_lookup_without_question_shows_intro(world, sent):
    _link(world)
    _say('/lookup')
    assert _session().state == 'lookup' and 'Ask me anything' in _messages(sent)[-1]


def test_lookup_api_failure_is_apologised_for_and_not_remembered(world, sent, monkeypatch):
    import anthropic
    import httpx
    import routes.telegram_lookup as lookup
    _link(world)

    def fail(*a, **k):
        raise anthropic.APIConnectionError(request=httpx.Request('POST', 'http://x'))
    monkeypatch.setattr(lookup, 'answer_lookup', fail)
    _say('/lookup anything')
    assert "couldn't look that up" in _messages(sent)[-1]
    assert not _session().lookup_history_json


def test_lookup_memory_is_budgeted(world, monkeypatch):
    from models import db
    _link(world)
    session = tg._get_or_create_session(CHAT)
    big = 'x' * 6000
    for i in range(6):
        tg._remember_lookup(session, f'q{i} {big}', f'a{i} {big}')
    msgs = tg._lookup_messages(session)
    assert msgs[0]['role'] == 'user'
    assert sum(len(m['content']) for m in msgs) <= tg._LOOKUP_MEMORY_CHARS + 6100
    assert msgs[-1]['content'].startswith('a5')


def test_old_format_history_is_ignored(world):
    session = tg._get_or_create_session(CHAT)
    session.lookup_history_json = json.dumps([{'q': 'old', 'a': 'old', 'at': '2026-01-01T00:00:00+00:00'}])
    assert tg._lookup_messages(session) == []
