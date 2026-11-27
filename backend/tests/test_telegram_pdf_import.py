"""Backdated Check In from a PDF via Telegram. Telegram and the AI reading of the PDF are stubbed;
the app's own API (create inspection, apply the import) is the real thing, on an in-memory database."""
import json
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

import pytest

from routes import telegram_flows as flows
from routes import telegram_integration as tg
from routes import telegram_pdf_import as imp

CHAT = 555
TODAY = date(2026, 11, 27)
PDF = b'%PDF-1.7 ' + b'x' * 5000


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(flows, '_today_london', lambda: TODAY)


@pytest.fixture()
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(tg, '_telegram_call', lambda method, **params: out.append((method, params)))
    return out


def _messages(sent):
    return [p['text'] for m, p in sent if m == 'sendMessage']


def _buttons(sent):
    keyboard = [p for m, p in sent if m == 'sendMessage'][-1].get('reply_markup') or {}
    return [b for row in keyboard.get('inline_keyboard', []) for b in row]


# ── The date question ───────────────────────────────────────────────────────

def _to_date_step(kind='check_out'):
    state, _, _ = flows.start(flows.INSPECTION_FLOW)
    state, _, _ = flows.handle_text(state, 'smith')
    state, replies, _ = flows.handle_callback(state, 'type', kind)
    assert state['step'] == 'date'
    return state, replies


@pytest.mark.parametrize('kind', ['check_in', 'check_out'])
def test_past_date_offers_an_import(world, kind):
    state, replies = _to_date_step(kind)
    assert 'backdated Check In' in replies[0][0]
    state, replies, action = flows.handle_text(state, '12/03/2026')
    assert action is None and 'Import a backdated Check In' in replies[0][0]
    value = replies[0][1]['inline_keyboard'][0][0]['callback_data'].split(':', 2)[2]
    state, _, action = flows.handle_callback(state, 'date', value)
    assert action == 'import' and state['data']['import_date'] == '2026-03-12'
    assert 'conduct_date' not in state['data']


def test_past_date_yes_and_no_can_be_typed(world):
    state, _ = _to_date_step()
    state, _, _ = flows.handle_text(state, '12/03/2026')
    state, replies, action = flows.handle_text(state, 'no')
    assert action is None and state['step'] == 'date' and 'What date?' in replies[0][0]
    state, _, _ = flows.handle_text(state, '12/03/2026')
    _, _, action = flows.handle_text(state, 'yes')
    assert action == 'import'


def test_a_different_date_after_the_offer_just_books_it(world):
    state, _ = _to_date_step()
    state, _, _ = flows.handle_text(state, '12/03/2026')
    state, _, action = flows.handle_text(state, '1 Dec')
    assert action is None and state['data']['conduct_date'] == '2026-12-01'
    assert 'import_date' not in state['data'] and 'backdate_offer' not in state['data']


@pytest.mark.parametrize('typed', ['12/03', '12 Mar', 'March 12th'])
def test_a_passed_date_without_a_year_asks_which_year(world, typed):
    state, _ = _to_date_step()
    state, replies, action = flows.handle_text(state, typed)
    assert action is None and state['step'] == 'date' and 'conduct_date' not in state['data']
    data = [row[0]['callback_data'] for row in replies[0][1]['inline_keyboard']]
    assert data == ['f:date:imp:2026-03-12', 'f:date:book:2027-03-12']
    booked, _, _ = flows.handle_callback(json.loads(json.dumps(state)), 'date', 'book:2027-03-12')
    assert booked['data']['conduct_date'] == '2027-03-12'
    _, _, action = flows.handle_callback(state, 'date', 'imp:2026-03-12')
    assert action == 'import'


@pytest.mark.parametrize('typed, today, expected', [
    ('12/03/2027', TODAY, None), ('1 Dec', TODAY, None), ('tomorrow', date(2026, 12, 31), None),
    ('fri', date(2026, 12, 30), None), ('26 Nov', TODAY, date(2026, 11, 26)), ('27 Nov', TODAY, None),
])
def test_passed_this_year(typed, today, expected):
    assert flows._passed_this_year(typed, today) == expected


@pytest.mark.parametrize('kind', ['midterm', 'damage_report', 'heads_up'])
def test_other_types_never_offer_an_import(world, kind):
    state, replies = _to_date_step(kind)
    assert 'backdated' not in replies[0][0]
    state, replies, action = flows.handle_text(state, '12/03/2026')
    assert action is None and 'in the past' in replies[0][0] and not replies[0][1]
    state, _, action = flows.handle_callback(state, 'date', 'imp:2026-03-12')
    assert action is None and 'import_date' not in state['data']
    state, _, _ = flows.handle_text(state, '12/03')                       # unchanged: next year
    assert state['data']['conduct_date'] == '2027-03-12'


# ── Upload link, upload and import ──────────────────────────────────────────

def _pdf_rooms():
    return {'rooms': [
        {'name': 'Hallway', 'items': [{'label': 'Front door', 'description': 'White', 'condition': 'Good order'}],
         '_photos': ['https://x/1.jpg']},
        {'name': 'Bedroom 1', 'items': [{'label': 'Walls', 'description': 'Magnolia', 'condition': 'Scuffed'}],
         '_photos': ['https://x/2.jpg']},
        {'name': 'Bedroom 1 (cont.)', 'items': [{'label': 'Carpet', 'description': 'Grey', 'condition': 'Worn'}],
         '_photos': ['https://x/2.jpg', 'https://x/3.jpg']},
    ], 'fixedSections': {}}


@pytest.fixture()
def web(app, world, sent, monkeypatch, tmp_path):
    """The real inspections API plus the upload endpoints; the app's calls to itself go to the test client."""
    from models import TelegramLink, db
    from routes.inspections import inspections_bp
    app.register_blueprint(inspections_bp, url_prefix='/api/inspections')
    app.register_blueprint(imp.telegram_pdf_bp, url_prefix='/api/telegram-import')
    db.session.add(TelegramLink(user_id=world['manager'].id, chat_id=CHAT))
    db.session.commit()
    client = app.test_client()
    calls = []

    class Reply:
        def __init__(self, res):
            self.status_code, self.text, self._res = res.status_code, res.get_data(as_text=True), res

        def json(self):
            return self._res.get_json()

    def request(method, url, json=None, headers=None, timeout=None):
        calls.append((method, urlsplit(url).path))
        return Reply(client.open(urlsplit(url).path, method=method, json=json, headers=headers))

    monkeypatch.setattr(imp.requests, 'request', request)
    monkeypatch.setattr(imp, 'UPLOAD_DIR', str(tmp_path))
    monkeypatch.setattr(imp, '_extract', lambda raw, filename: _pdf_rooms())
    monkeypatch.setattr(imp, '_start_processing', imp.process_import)        # run inline
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN', 'backend.test')
    client.calls = calls
    return client


def _ask_for_link(sent):
    def tap(data):
        tg._handle_callback_query({'id': 'cb', 'data': data, 'message': {'chat': {'id': CHAT}}})
    tg._handle_text_message({'chat': {'id': CHAT}, 'text': '/inspection'})
    tg._handle_text_message({'chat': {'id': CHAT}, 'text': 'smith'})
    tap('f:type:check_out')
    tg._handle_text_message({'chat': {'id': CHAT}, 'text': '12/03/2026'})
    tap('f:date:imp:2026-03-12')
    url = _buttons(sent)[0]['url']
    assert url.startswith('https://backend.test/api/telegram-import/upload#')
    return url.split('#', 1)[1]


def _upload(web, token, data=PDF, piece=2000):
    headers = {'X-Upload-Token': token}
    pieces = [data[i:i + piece] for i in range(0, len(data), piece)]
    for i, chunk in enumerate(pieces):
        assert web.put(f'/api/telegram-import/chunk/{i}', data=chunk, headers=headers).status_code == 200
    return web.post('/api/telegram-import/complete', headers=headers,
                    json={'filename': 'report.pdf', 'chunks': len(pieces), 'size': len(data)})


def test_import_creates_a_backdated_check_in_and_offers_the_check_out(web, world, sent):
    from models import Inspection, TelegramPdfImport, TelegramSession, db
    token = _ask_for_link(sent)
    assert TelegramSession.query.filter_by(chat_id=CHAT).first().state == 'idle'
    assert TelegramPdfImport.query.one().token_hash != token              # only the hash is stored
    info = web.get('/api/telegram-import/info', headers={'X-Upload-Token': token}).get_json()
    assert info['address'] == world['property'].address and info['date'] == 'Thu 12 Mar 2026'

    assert _upload(web, token).status_code == 200

    inspection = Inspection.query.one()
    assert (inspection.inspection_type, inspection.status, inspection.pdf_import) == ('check_in', 'complete', True)
    assert inspection.conduct_date == datetime(2026, 3, 12)
    assert inspection.client_email_override == 'SUPPRESS'
    # the PDF's own rooms in its own order, the continuation page folded in, photos not doubled
    sections = sorted(inspection.template.sections, key=lambda s: s.order_index)
    assert [s.name for s in sections] == ['Hallway', 'Bedroom 1']
    assert [i.name for i in sorted(sections[1].items, key=lambda i: i.order_index)] == ['Walls', 'Carpet']
    report = json.loads(inspection.report_data)
    assert report[str(sections[1].id)]['_overview']['_photos'] == ['https://x/2.jpg', 'https://x/3.jpg']

    assert '2 rooms · 3 items · 3 photos' in _messages(sent)[-1]
    review, book = _buttons(sent)
    assert review['url'] == f'https://app.lminventories.co.uk/inspections/{inspection.id}/report'

    # the link is spent
    assert web.get('/api/telegram-import/info', headers={'X-Upload-Token': token}).status_code == 410

    tg._handle_callback_query({'id': 'cb', 'data': book['callback_data'], 'message': {'chat': {'id': CHAT}}})
    state = json.loads(TelegramSession.query.filter_by(chat_id=CHAT).first().pending_action_json)
    assert state['step'] == 'date' and state['data']['inspection_type'] == 'check_out'
    state, _, _ = flows.handle_text(state, 'tomorrow')
    state, _, _ = flows.handle_callback(state, 'time', 'am')
    state, replies, _ = flows.handle_callback(state, 'clerk', '0')
    assert replies[0][1]['inline_keyboard'][0][0]['text'] == 'Work from Previous Inspection (12 Mar 2026)'


def test_book_button_waits_for_a_flow_in_progress_and_ignores_other_chats(web, world, sent):
    token = _ask_for_link(sent)
    _upload(web, token)
    book = _buttons(sent)[1]['callback_data']
    assert imp.check_out_prefill(book.split(':')[2], chat_id=999) is None
    tg._handle_text_message({'chat': {'id': CHAT}, 'text': '/property'})
    tg._handle_callback_query({'id': 'cb', 'data': book, 'message': {'chat': {'id': CHAT}}})
    assert 'Finish or /cancel' in _messages(sent)[-1]


def test_skipped_sections_are_flagged(web, sent, monkeypatch):
    monkeypatch.setattr(imp, '_extract', lambda raw, filename: {**_pdf_rooms(), '_skippedChunks': '1 of 8'})
    _upload(web, _ask_for_link(sent))
    assert '1 of 8 sections' in _messages(sent)[-1]


@pytest.mark.parametrize('outcome', [{'rooms': []}, imp.ImportFailed("The PDF couldn't be read."), ValueError('x')])
def test_unreadable_pdf_creates_nothing_and_sends_a_new_link(web, sent, monkeypatch, outcome):
    from models import Inspection

    def extract(raw, filename):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(imp, '_extract', extract)
    token = _ask_for_link(sent)
    _upload(web, token)
    assert Inspection.query.count() == 0
    assert any("didn't finish" in m for m in _messages(sent))
    assert _buttons(sent)[0]['url'].split('#')[1] != token


def test_failed_apply_removes_the_empty_check_in(web, sent, monkeypatch):
    from models import Inspection
    real = imp._api

    def api(user_id, method, path, payload=None):
        if path.endswith('/apply-pdf-import'):
            raise imp.ImportFailed("The app wouldn't save the report.")
        return real(user_id, method, path, payload)
    monkeypatch.setattr(imp, '_api', api)
    _upload(web, _ask_for_link(sent))
    assert Inspection.query.count() == 0 and ('DELETE', '/api/inspections/1') in web.calls
    assert _buttons(sent)[0]['text'] == '⬆️ Upload the PDF'


def test_stalled_import_is_reported_once(web, sent, monkeypatch):
    from models import TelegramPdfImport, db
    monkeypatch.setattr(imp, '_start_processing', lambda *a: None)           # the server "restarts"
    _upload(web, _ask_for_link(sent))
    imp.fail_stalled_imports()
    assert TelegramPdfImport.query.one().status == 'processing'              # still within its time
    TelegramPdfImport.query.update({'started_at': imp._now() - timedelta(hours=1)})
    db.session.commit()
    imp.fail_stalled_imports()
    imp.fail_stalled_imports()
    assert sum("didn't finish" in m for m in _messages(sent)) == 1
    assert [r.status for r in TelegramPdfImport.query.order_by(TelegramPdfImport.id)] == ['failed', 'waiting']


def test_upload_rejects_bad_links_and_files(web, sent):
    from models import Inspection, TelegramPdfImport, db
    assert web.get('/api/telegram-import/info').status_code == 404
    assert web.put('/api/telegram-import/chunk/0', data=b'x', headers={'X-Upload-Token': 'guess'}).status_code == 404

    token = _ask_for_link(sent)
    headers = {'X-Upload-Token': token}
    assert web.put(f'/api/telegram-import/chunk/{imp.MAX_CHUNKS}', data=b'x', headers=headers).status_code == 413
    assert web.put('/api/telegram-import/chunk/0', data=b'x' * (imp.CHUNK_BYTES + 1), headers=headers).status_code == 413
    assert _upload(web, token, data=b'not a pdf').status_code == 400
    missing = web.post('/api/telegram-import/complete', headers=headers,
                       json={'filename': 'a.pdf', 'chunks': 3, 'size': len(PDF)})
    assert missing.status_code == 400
    assert Inspection.query.count() == 0 and TelegramPdfImport.query.one().status == 'waiting'

    TelegramPdfImport.query.update({'expires_at': imp._now() - timedelta(minutes=1)})
    db.session.commit()
    assert web.get('/api/telegram-import/info', headers=headers).status_code == 410


def test_upload_page_is_served(web):
    res = web.get('/api/telegram-import/upload')
    assert res.status_code == 200 and b'Upload Check In PDF' in res.data
    assert res.headers['Cache-Control'] == 'no-store'


def test_continuation_merge_matches_the_web_app():
    rooms = [{'name': 'Kitchen', 'items': [1]}, {'name': 'KITCHEN - continued', 'items': [2]},
             {'name': 'Bathroom', 'items': [3]}, {'name': 'Kitchen', 'items': [4]}]
    merged = imp.merge_continuation_rooms(rooms)
    assert [(r['name'], r['items']) for r in merged] == [('Kitchen', [1, 2]), ('Bathroom', [3]), ('Kitchen', [4])]
    assert rooms[0]['items'] == [1]


# ── Reading the PDF (the web app's own pipeline; only the AI call is stubbed) ──

def _small_pdf():
    import io
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    for i in range(30):
        page.drawString(50, 800 - i * 20, f'Hallway item {i}: white painted wall, in good order')
    page.save()
    return buffer.getvalue()


def test_extract_runs_the_desktop_pipeline_without_a_template(monkeypatch):
    from routes import pdf_import
    prompts = []

    def claude(client, messages, max_tokens, usage_acc=None):
        prompts.append(messages[0]['content'])
        return {'rooms': [{'name': 'Hallway', 'items': [{'label': 'Walls'}]}], 'fixedSections': {}}
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(pdf_import, '_call_claude', claude)

    parsed = imp._extract(_small_pdf(), 'report.pdf')
    assert parsed['rooms'][0]['name'] == 'Hallway' and '_skippedChunks' not in parsed
    assert 'No template - infer structure from PDF' in prompts[0] and 'Hallway item 29' in prompts[0]


def test_extract_reports_unreadable_sections(monkeypatch):
    from routes import pdf_import
    replies = iter([json.JSONDecodeError('bad', '', 0)])

    def claude(client, messages, max_tokens, usage_acc=None):
        reply = next(replies, None)
        if reply:
            raise reply
        return {'rooms': [{'name': 'Hallway', 'items': [{'label': 'Walls'}]}], 'fixedSections': {}}
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(pdf_import, '_call_claude', claude)
    long_text = '\n'.join(f'line {i} of a long report' for i in range(1500))
    monkeypatch.setattr(pdf_import, '_extract_pdf_text_by_page', lambda raw: {0: long_text})

    parsed = imp._extract(_small_pdf(), 'report.pdf')
    assert parsed['_skippedChunks'].startswith('1 of ') and parsed['rooms']


def test_extract_failure_is_explained(monkeypatch):
    from routes import pdf_import

    def claude(*a, **k):
        raise RuntimeError('overloaded')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(pdf_import, '_call_claude', claude)
    with pytest.raises(imp.ImportFailed, match='overloaded'):
        imp._extract(_small_pdf(), 'report.pdf')
