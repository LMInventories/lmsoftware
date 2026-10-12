"""/share and /paid: the flow steps, then through the dispatcher with the app's HTTP API stubbed."""
from datetime import datetime, timedelta

import pytest

from routes import telegram_flows as flows
from routes import telegram_integration as tg

CHAT = 777


@pytest.fixture()
def reports(world):
    from models import Client, Inspection, Property, db
    world['client'].email = 'acme@example.com'
    other_client = Client(name='Beta Homes', email='b@example.com')
    db.session.add(other_client)
    db.session.flush()
    other_prop = Property(client_id=other_client.id, address='3 Other Road, Leeds LS1 1AA', bedrooms=1, bathrooms=1)
    db.session.add(other_prop)
    db.session.flush()
    now = datetime.now()
    rows = {
        'out': Inspection(property_id=world['property'].id, inspection_type='check_out', status='complete',
                          conduct_date=now - timedelta(days=9), reference_number='INS-10', tenant_email='ten@example.com',
                          report_data='{}', invoice_paid=False, pdf_import=False),
        'in': Inspection(property_id=world['property'].id, inspection_type='check_in', status='complete',
                         conduct_date=now - timedelta(days=60), reference_number='INS-11',
                         report_data='{}', invoice_paid=True, pdf_import=False),
        'draft': Inspection(property_id=world['property'].id, inspection_type='midterm', status='assigned',
                            conduct_date=now, reference_number='INS-12', pdf_import=False),
        'beta': Inspection(property_id=other_prop.id, inspection_type='check_in', status='complete',
                           conduct_date=now - timedelta(days=5), reference_number='INS-13',
                           report_data='{}', invoice_paid=False, pdf_import=False),
    }
    db.session.add_all(rows.values())
    db.session.commit()
    return {**world, **rows, 'other_client': other_client}


def _texts(replies):
    return ' | '.join(t for t, _ in replies)


def _buttons(replies):
    kb = replies[-1][1]
    return [b for row in kb['inline_keyboard'] for b in row] if kb else []


# ── /share ──────────────────────────────────────────────────────────────────

def test_share_picks_between_reports_and_toggles_recipients(reports):
    state, replies, _ = flows.start(flows.SHARE_FLOW)
    state, replies, _ = flows.handle_text(state, 'smith street')
    assert state['step'] == 'report' and len(_buttons(replies)) == 2          # the draft isn't offered
    state, replies, _ = flows.handle_callback(state, 'report', '0')           # newest = the check-out
    assert state['step'] == 'recipients' and state['data']['emails'] == []    # two addresses on file, none pre-ticked
    assert [b['text'][:1] for b in _buttons(replies)[:2]] == ['☐', '☐']

    state, replies, _ = flows.handle_callback(state, 'recipients', 'done')
    assert state['step'] == 'recipients' and 'at least one' in _texts(replies)

    state, _, _ = flows.handle_callback(state, 'recipients', '0')
    state, replies, _ = flows.handle_text(state, 'extra@example.com')
    assert state['data']['emails'] == ['acme@example.com', 'extra@example.com']
    state, replies, _ = flows.handle_text(state, 'not an email')
    assert "doesn't look like" in _texts(replies)
    state, _, _ = flows.handle_callback(state, 'recipients', 'done')
    state, replies, _ = flows.handle_text(state, 'Please find the report attached.')
    assert state['step'] == 'confirm'
    assert 'acme@example.com, extra@example.com' in _texts(replies) and 'Please find' in _texts(replies)
    assert flows.build_resolved(state)['inspection_id'] == reports['out'].id


def test_share_single_address_is_preticked_and_unknown_reports_are_refused(reports):
    state, _, _ = flows.start(flows.SHARE_FLOW)
    state, replies, _ = flows.handle_text(state, 'INS-13')
    assert state['step'] == 'recipients' and state['data']['emails'] == ['b@example.com']

    state, _, _ = flows.start(flows.SHARE_FLOW)
    state, replies, _ = flows.handle_text(state, 'INS-12')                   # not complete
    assert state['step'] == 'report' and 'No completed report' in _texts(replies)


def test_share_edit_recipients_keeps_the_report(reports):
    state, _, _ = flows.start(flows.SHARE_FLOW)
    state, _, _ = flows.handle_text(state, 'INS-13')
    state, _, _ = flows.handle_callback(state, 'recipients', 'done')
    state, _, _ = flows.handle_callback(state, 'note', 'skip')
    assert state['step'] == 'confirm'
    state, _, _ = flows.handle_callback(state, 'confirm', 'edit')
    state, replies, _ = flows.handle_callback(state, 'edit', 'recipients')
    assert state['step'] == 'recipients' and state['data']['report_id'] == reports['beta'].id


# ── /paid ───────────────────────────────────────────────────────────────────

def test_paid_add_by_reference_skips_paid_and_removes(reports):
    state, _, _ = flows.start(flows.PAID_FLOW)
    state, replies, _ = flows.handle_text(state, 'INS-11')
    assert 'already marked paid' in _texts(replies) and state['data']['items'] == []
    state, replies, _ = flows.handle_text(state, 'INS-10')
    assert [i['reference_number'] for i in state['data']['items']] == ['INS-10']
    state, replies, _ = flows.handle_text(state, 'INS-10')
    assert 'already in the list' in _texts(replies)
    state, replies, _ = flows.handle_callback(state, 'invoices', 'x0')
    assert state['data']['items'] == []
    state, replies, _ = flows.handle_callback(state, 'invoices', 'done')
    assert state['step'] == 'invoices' and 'at least one' in _texts(replies)


def test_paid_all_unpaid_and_by_client(reports):
    state, _, _ = flows.start(flows.PAID_FLOW)
    state, replies, _ = flows.handle_callback(state, 'invoices', 'all')
    assert [i['reference_number'] for i in state['data']['items']] == ['INS-10', 'INS-13']     # oldest first

    state, _, _ = flows.start(flows.PAID_FLOW)
    state, _, _ = flows.handle_callback(state, 'invoices', 'client')
    state, replies, _ = flows.handle_text(state, 'beta')
    assert [i['reference_number'] for i in state['data']['items']] == ['INS-13']
    state, replies, _ = flows.handle_callback(state, 'invoices', 'done')
    assert state['step'] == 'confirm' and 'INS-13' in _texts(replies)
    assert flows.build_resolved(state)['items'][0]['inspection_id'] == reports['beta'].id


def test_paid_ambiguous_address_shows_choices(reports):
    state, _, _ = flows.start(flows.PAID_FLOW)
    state, replies, _ = flows.handle_text(state, 'smith street')
    assert state['data']['items'] == [] and len(_buttons(replies)) == 3
    state, replies, _ = flows.handle_callback(state, 'invoices', 'o0')
    assert len(state['data']['items']) == 1


# ── Through the dispatcher ──────────────────────────────────────────────────

@pytest.fixture()
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(tg, '_telegram_call', lambda method, **params: out.append((method, params)))
    return out


def _link(world):
    from models import TelegramLink, db
    db.session.add(TelegramLink(user_id=world['manager'].id, chat_id=CHAT))
    db.session.commit()


def _say(text):
    tg._handle_text_message({'chat': {'id': CHAT}, 'text': text})


def _tap(data):
    tg._handle_callback_query({'id': 'cb', 'data': data, 'message': {'chat': {'id': CHAT}}})


def _last(sent):
    return [p['text'] for m, p in sent if m == 'sendMessage'][-1]


def test_share_posts_emails_to_the_share_endpoint(reports, sent, monkeypatch):
    _link(reports)
    monkeypatch.setenv('BACKEND_URL', 'http://backend.test')
    calls = []

    class Resp:
        status_code = 200
        content = b'{}'
        text = '{}'

        def json(self):
            return {}
    monkeypatch.setattr(tg.requests, 'request', lambda method, url, **kw: calls.append((method, url, kw)) or Resp())

    _say('/share')
    _say('INS-13')
    _tap('f:recipients:done')
    _tap('f:note:skip')
    assert not calls
    _tap('f:confirm:yes')
    method, url, kw = calls[0]
    assert (method, url) == ('POST', f"http://backend.test/api/inspections/{reports['beta'].id}/share-pdf")
    assert kw['json'] == {'emails': ['b@example.com']}
    assert 'Sending the report' in _last(sent) and 'b@example.com' in _last(sent)


def test_paid_puts_invoice_paid_for_each_item_and_reports_failures(reports, sent, monkeypatch):
    _link(reports)
    puts = []

    class Resp:
        def __init__(self, code):
            self.status_code = code

    def fake_put(url, json=None, **kw):
        puts.append((url, json))
        return Resp(500 if url.endswith(f"/{reports['beta'].id}") else 200)
    monkeypatch.setattr(tg.requests, 'put', fake_put)

    _say('/paid')
    _tap('f:invoices:all')
    _tap('f:invoices:done')
    _tap('f:confirm:yes')
    assert [p[1] for p in puts] == [{'invoice_paid': True}] * 2
    text = _last(sent)
    assert 'Marked as paid' in text and 'INS-10' in text and 'Could not update' in text and 'INS-13' in text
    assert tg._get_or_create_session(CHAT).state == 'idle'


def test_commands_are_registered_and_listed():
    assert 'share' in flows.STEPS[flows.SHARE_FLOW] or flows.SHARE_FLOW in flows.STEPS
    assert '/share' in tg._HELP_TEXT and '/paid' in tg._HELP_TEXT
