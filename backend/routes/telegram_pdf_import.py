"""
routes/telegram_pdf_import.py
───────────────────────────────
Backdated Check In from another clerk's PDF, started from Telegram's /inspection.

The bot sends a private upload link: Telegram bots can only download files up to
20 MB and inventory PDFs are often larger. The page sends the PDF in small pieces,
so a slow phone connection never holds one request open for long. A background
thread then does what the web app's "Keep PDF layout" import does: read the PDF
(routes/pdf_import.py), create the completed backdated Check In, apply it without
redistribution, store the original on Drive, and message the user.

Endpoints (no login; the link's single-use token is sent in a header):
  GET  /api/telegram-import/upload         → the upload page (token is in the URL
                                             fragment, so it never reaches access logs)
  GET  /api/telegram-import/info           → what the link is for
  PUT  /api/telegram-import/chunk/<index>  → one piece of the file
  POST /api/telegram-import/complete       → assemble, check and start the import
                                             (photos only with include_photos: true)
"""
from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
import re
import secrets
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import create_access_token

from permissions import is_admin_or_manager

telegram_pdf_bp = Blueprint('telegram_pdf_import', __name__)
log = logging.getLogger(__name__)

CHUNK_BYTES = 4 * 1024 * 1024
MAX_PDF_BYTES = 150 * 1024 * 1024
MAX_CHUNKS = math.ceil(MAX_PDF_BYTES / CHUNK_BYTES)
LINK_LIFETIME = timedelta(hours=24)
STALLED_AFTER = timedelta(minutes=25)  # a 45 MB report takes about 5 minutes
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), 'telegram_pdf_uploads')
_NO_TEMPLATE = 'No template - infer structure from PDF'  # what the web app's backdated import sends
_RUNNING = ('processing', 'saving')


class ImportFailed(Exception):
    """A reason that is safe to show to the user."""


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _upload_base() -> str:
    """The backend's own public address (what the web app uploads to), else the app's."""
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip().rstrip('/')
    if domain:
        return domain if domain.startswith('http') else f'https://{domain}'
    return os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').rstrip('/')


def _send(chat_id, text, buttons=None):
    from routes.telegram_integration import _send_message
    _send_message(chat_id, text, reply_markup={'inline_keyboard': buttons} if buttons else None)


# ── Telegram side ───────────────────────────────────────────────────────────

def offer_upload(chat_id, user, property_id: int, conduct_date):
    """Create a single-use upload link and send it to the chat."""
    from models import Inspection, Property, TelegramPdfImport, db
    from routes.telegram_intent import _day_bounds

    prop = db.session.get(Property, property_id)
    token = secrets.token_urlsafe(32)
    db.session.add(TelegramPdfImport(
        token_hash=_hash(token), user_id=user.id, chat_id=chat_id, property_id=property_id,
        conduct_date=conduct_date, status='waiting', expires_at=_now() + LINK_LIFETIME))
    db.session.commit()

    lines = ['Backdated Check In',
             f'• Property: {prop.address}',
             f'• Report date: {conduct_date.strftime("%a %d %b %Y")}',
             '',
             'Tap below and choose the PDF. The link works for one report and expires in 24 hours.']
    start, end = _day_bounds(conduct_date)
    if Inspection.query.filter(Inspection.property_id == property_id, Inspection.inspection_type == 'check_in',
                               Inspection.conduct_date >= start, Inspection.conduct_date < end).first():
        lines.append('⚠️ There is already a Check In at this property on that date.')
    _send(chat_id, '\n'.join(lines),
          [[{'text': '⬆️ Upload the PDF', 'url': f'{_upload_base()}/api/telegram-import/upload#{token}'}]])


def check_out_prefill(import_id, chat_id) -> dict | None:
    """Answers to seed /inspection with after an import, or None if the button no longer applies."""
    from models import Inspection, Property, TelegramPdfImport, db
    try:
        record = db.session.get(TelegramPdfImport, int(import_id))
    except ValueError:
        return None
    if record is None or record.chat_id != chat_id or record.status != 'done':
        return None
    prop = db.session.get(Property, record.property_id)
    if prop is None or db.session.get(Inspection, record.inspection_id) is None:
        return None
    return {'property_id': prop.id, 'property_address': prop.address, 'inspection_type': 'check_out'}


# ── Upload page and endpoints ───────────────────────────────────────────────

def _record_for_request():
    """(record, None) for a usable link, else (None, error response)."""
    from models import TelegramPdfImport
    token = request.headers.get('X-Upload-Token', '')
    record = TelegramPdfImport.query.filter_by(token_hash=_hash(token)).first() if token else None
    if record is None:
        return None, (jsonify({'error': "This upload link isn't valid."}), 404)
    if record.status != 'waiting':
        return None, (jsonify({'error': 'This link has already been used. The bot will message you with the result.'}), 410)
    if record.expires_at < _now():
        return None, (jsonify({'error': 'This link has expired. Start /inspection again in Telegram.'}), 410)
    return record, None


def _chunk_dir(record) -> str:
    return os.path.join(UPLOAD_DIR, str(record.id))


@telegram_pdf_bp.after_request
def _never_cache(response):
    # Every link shares these addresses (the token is in a header), and browsers keep a
    # 410 or 404 indefinitely unless told not to: one used link would break all later ones.
    response.headers['Cache-Control'] = 'no-store'
    return response


@telegram_pdf_bp.route('/upload', methods=['GET'])
def upload_page():
    return Response(_PAGE, mimetype='text/html', headers={'Referrer-Policy': 'no-referrer'})


@telegram_pdf_bp.route('/info', methods=['GET'])
def upload_info():
    from models import Property, db
    record, error = _record_for_request()
    if error:
        return error
    prop = db.session.get(Property, record.property_id)
    return jsonify({'address': prop.address if prop else 'Unknown property',
                    'date': record.conduct_date.strftime('%a %d %b %Y'),
                    'chunk_bytes': CHUNK_BYTES, 'max_bytes': MAX_PDF_BYTES})


@telegram_pdf_bp.route('/chunk/<int:index>', methods=['PUT'])
def upload_chunk(index):
    record, error = _record_for_request()
    if error:
        return error
    if index >= MAX_CHUNKS or (request.content_length or 0) > CHUNK_BYTES:
        return jsonify({'error': 'That file is too large.'}), 413
    data = request.get_data(cache=False)
    if not data or len(data) > CHUNK_BYTES:
        return jsonify({'error': 'That part of the file was empty or too large.'}), 400
    os.makedirs(_chunk_dir(record), exist_ok=True)
    with open(os.path.join(_chunk_dir(record), f'{index}.part'), 'wb') as f:
        f.write(data)
    return jsonify({'ok': True})


@telegram_pdf_bp.route('/complete', methods=['POST'])
def upload_complete():
    from models import TelegramPdfImport, db
    record, error = _record_for_request()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    chunks, size = body.get('chunks'), body.get('size')
    filename = str(body.get('filename') or 'report.pdf')[:200]
    include_photos = body.get('include_photos') is True  # photos are opt-in
    if not isinstance(chunks, int) or not 0 < chunks <= MAX_CHUNKS:
        return jsonify({'error': 'The upload was incomplete — please try again.'}), 400
    paths = [os.path.join(_chunk_dir(record), f'{i}.part') for i in range(chunks)]
    if not all(os.path.exists(p) for p in paths):
        return jsonify({'error': 'The upload was incomplete — please try again.'}), 400
    parts = []
    for path in paths:
        with open(path, 'rb') as f:
            parts.append(f.read())
    raw = b''.join(parts)
    if len(raw) != size or len(raw) > MAX_PDF_BYTES:
        return jsonify({'error': 'The upload was incomplete — please try again.'}), 400
    if not raw.startswith(b'%PDF'):
        return jsonify({'error': "That file isn't a PDF."}), 400

    claimed = (TelegramPdfImport.query
               .filter(TelegramPdfImport.id == record.id, TelegramPdfImport.status == 'waiting')
               .update({'status': 'processing', 'started_at': _now()}, synchronize_session=False))
    db.session.commit()
    if not claimed:
        return jsonify({'error': 'This link has already been used.'}), 410
    shutil.rmtree(_chunk_dir(record), ignore_errors=True)

    without = '' if include_photos else ' without photos'
    _send(record.chat_id, f'📄 Received "{filename}". Building the Check In{without} — '
                          'this usually takes 2–5 minutes.')
    _start_processing(current_app._get_current_object(), record.id, raw, filename, include_photos)
    return jsonify({'ok': True})


# ── Processing ──────────────────────────────────────────────────────────────

def _start_processing(app, import_id, raw, filename, include_photos):
    # Not a daemon thread: a worker being recycled should let it finish if it can.
    threading.Thread(target=process_import, args=(app, import_id, raw, filename, include_photos),
                     daemon=False).start()


def process_import(app, import_id: int, raw: bytes, filename: str, include_photos: bool = False):
    with app.app_context():
        from models import db
        try:
            _run_import(import_id, raw, filename, include_photos)
        except ImportFailed as e:
            _fail(import_id, str(e))
        except Exception:
            log.exception('[telegram-import] import %s failed', import_id)
            db.session.rollback()
            _fail(import_id, 'Something went wrong while importing it.')
        finally:
            db.session.remove()


def _extract(raw: bytes, filename: str, include_photos: bool = True) -> dict:
    """The same extraction the web app's PDF import runs, called directly."""
    from routes import pdf_import
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ImportFailed('PDF reading is not configured on the server.')
    page_texts = pdf_import._extract_pdf_text_by_page(raw)
    text = '\n'.join(page_texts[i] for i in sorted(page_texts))
    use_text = len(text) >= pdf_import.MIN_TEXT_CHARS
    pdf_b64 = None if use_text else base64.b64encode(raw).decode('utf-8')
    job_id = str(uuid.uuid4())
    # The PDF's bytes are only used there to pull photos out, so leaving them off means
    # no photos are extracted or uploaded at all.
    pdf_import._run_import_job(job_id, api_key, text, pdf_b64, _NO_TEMPLATE, use_text, '', filename,
                               page_texts, raw if include_photos else None)
    job = pdf_import._read_job(job_id) or {}
    pdf_import._delete_job(job_id)
    if job.get('status') != 'done':
        raise ImportFailed(f"The PDF couldn't be read. {str(job.get('error') or '')[:200]}".strip())
    return job['result']


# "- continued" first: the second pattern alone would strip the word and leave the dash behind.
_CONTINUATION = (re.compile(r"\s*[-–—]\s*cont(?:inued|'?d)?\.?\s*$", re.I),
                 re.compile(r"\s*\(?\s*cont(?:inued|'?d)?\.?\s*\)?\s*$", re.I))


def _room_key(name) -> str:
    key = (name or '').lower().strip()
    for pattern in _CONTINUATION:
        key = pattern.sub('', key)
    return key.strip()


def merge_continuation_rooms(rooms: list) -> list:
    """The web app's default for "Keep PDF layout" (usePdfHeaderReview.js): a room that is a
    continuation of the one before it ("Bedroom 1 (cont)") is folded into it."""
    out = []
    for room in rooms:
        key = _room_key(room.get('name'))
        if not out or not key or key != _room_key(out[-1].get('name')):
            out.append(dict(room, items=list(room.get('items') or [])))
            continue
        target = out[-1]
        target['items'] += room.get('items') or []
        photos = list(target.get('_photos') or [])
        refs = list(target.get('_photoRefs') or [None] * len(photos))
        new_refs = room.get('_photoRefs') or []
        for i, url in enumerate(room.get('_photos') or []):
            if url not in photos:  # both pages can be given the same photos
                photos.append(url)
                refs.append(new_refs[i] if i < len(new_refs) else None)
        if photos:
            target['_photos'], target['_photoRefs'] = photos, refs
    return out


def _api(user_id: int, method: str, path: str, payload=None):
    """Call the app's own API as the user, so an import behaves exactly like one made on the web."""
    base = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    token = create_access_token(identity=str(user_id), expires_delta=timedelta(minutes=5))
    try:
        resp = requests.request(method, f'{base}{path}', json=payload,
                                headers={'Authorization': f'Bearer {token}'}, timeout=120)
    except requests.RequestException as e:
        log.warning('[telegram-import] %s %s failed: %s', method, path, e)
        raise ImportFailed("I couldn't reach the app to save the report.")
    if not 200 <= resp.status_code < 300:
        log.warning('[telegram-import] %s %s returned %s: %s', method, path, resp.status_code, resp.text[:300])
        raise ImportFailed("The app wouldn't save the report.")
    return resp


def _move(import_id: int, from_status: str, **values) -> bool:
    """Atomically update an import still in `from_status`; False if something else moved it on."""
    from models import TelegramPdfImport, db
    moved = (TelegramPdfImport.query
             .filter(TelegramPdfImport.id == import_id, TelegramPdfImport.status == from_status)
             .update(values, synchronize_session=False))
    db.session.commit()
    return bool(moved)


def _run_import(import_id: int, raw: bytes, filename: str, include_photos: bool):
    from models import TelegramPdfImport, User, db

    record = db.session.get(TelegramPdfImport, import_id)
    user = db.session.get(User, record.user_id)
    if not user or not is_admin_or_manager(user):
        raise ImportFailed("You don't have permission to import reports.")
    user_id, chat_id = user.id, record.chat_id
    property_id, conduct_date = record.property_id, record.conduct_date
    db.session.commit()  # don't hold a database transaction open while the PDF is read

    parsed = _extract(raw, filename, include_photos)
    rooms = merge_continuation_rooms(parsed.get('rooms') or [])
    if not any(room['items'] for room in rooms):
        raise ImportFailed('No rooms or items could be read from that PDF.')

    if not _move(import_id, 'processing', status='saving'):
        return  # already reported as stalled
    created = _api(user_id, 'POST', '/api/inspections', {
        'property_id': property_id,
        'inspection_type': 'check_in',
        'status': 'complete',
        'source_inspection_id': None,
        'client_email_override': 'SUPPRESS',  # backdated: no client emails
        'pdf_import': True,                   # no Sheet row or calendar event
        'conduct_date': f'{conduct_date.isoformat()}T00:00:00',
    }).json()
    inspection_id = created['id']
    _move(import_id, 'saving', inspection_id=inspection_id)
    _api(user_id, 'POST', f'/api/inspections/{inspection_id}/apply-pdf-import',
         {**parsed, 'rooms': rooms, 'redistributeItems': False, '_fileName': filename})
    if not _move(import_id, 'saving', status='done'):
        return

    _send_result(chat_id, import_id, created, rooms, parsed, include_photos)
    _store_original(inspection_id, raw)


def _send_result(chat_id, import_id, created, rooms, parsed, include_photos):
    items = sum(len(r['items']) for r in rooms)
    photos = sum(len(r.get('_photos') or []) for r in rooms) + sum(
        len(parsed.get(k) or []) for k in ('_overviewPhotos', '_keysPhotos', '_meterPhotos'))
    lines = [f"✅ Backdated Check In created: {created.get('reference_number') or '#' + str(created['id'])}",
             f'• {len(rooms)} rooms · {items} items · '
             + (f'{photos} photos' if include_photos else 'photos not imported')]
    if parsed.get('_skippedChunks'):
        lines.append(f"⚠️ {parsed['_skippedChunks']} sections of the PDF couldn't be read — "
                     'check for missing rooms and items.')
    lines.append('Please review it against the PDF before relying on it.')
    app_url = os.environ.get('FRONTEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
    _send(chat_id, '\n'.join(lines), [
        [{'text': '🔍 Review the report', 'url': f"{app_url}/inspections/{created['id']}/report"}],
        [{'text': '➕ Book the Check Out', 'callback_data': f'i:co:{import_id}'}],
    ])


def _store_original(inspection_id: int, raw: bytes):
    """Keep the source PDF on Drive alongside the report. Never fails an import."""
    from models import Inspection, db
    try:
        from services.google_drive import is_drive_connected, upload_source_pdf
        inspection = db.session.get(Inspection, inspection_id)
        if inspection and is_drive_connected():
            ok, result = upload_source_pdf(inspection, raw)
            if ok:
                inspection.source_pdf_drive_file_id = result['file_id']
                db.session.commit()
    except Exception:
        log.exception('[telegram-import] could not store the original PDF for inspection %s', inspection_id)
        db.session.rollback()


def _fail(import_id: int, reason: str):
    """Mark a running import as failed, remove any empty report it left, and offer a new link."""
    from models import Inspection, TelegramPdfImport, User, db
    record = db.session.get(TelegramPdfImport, import_id)
    if record is None:
        return
    db.session.refresh(record)
    status = record.status
    if status not in _RUNNING or not _move(import_id, status, status='failed'):
        return
    db.session.refresh(record)
    user = db.session.get(User, record.user_id)
    inspection = db.session.get(Inspection, record.inspection_id) if record.inspection_id else None
    if inspection is not None:
        if inspection.report_data:  # the content was saved after all
            app_url = os.environ.get('FRONTEND_URL', 'https://app.lminventories.co.uk').rstrip('/')
            _send(record.chat_id, f'⚠️ {reason} A report was saved, so check it before trying again:\n'
                                  f'{app_url}/inspections/{inspection.id}/report')
            return
        # An empty completed Check In would be picked up as the source for the next Check Out.
        try:
            _api(record.user_id, 'DELETE', f'/api/inspections/{inspection.id}')
        except ImportFailed:
            reason += f' An empty Check In (#{inspection.id}) was left behind — please delete it.'
    _send(record.chat_id, f"❌ The PDF import didn't finish. {reason}")
    if user and is_admin_or_manager(user):
        offer_upload(record.chat_id, user, record.property_id, record.conduct_date)


# ── Stalled imports (e.g. the server restarted mid-way) ─────────────────────

def fail_stalled_imports():
    from models import TelegramPdfImport
    for record in TelegramPdfImport.query.filter(TelegramPdfImport.status.in_(_RUNNING),
                                                 TelegramPdfImport.started_at < _now() - STALLED_AFTER).all():
        _fail(record.id, 'It stopped part-way, possibly because the server restarted.')
    # Tidy up pieces of uploads that were never finished.
    if os.path.isdir(UPLOAD_DIR):
        cutoff = datetime.now().timestamp() - LINK_LIFETIME.total_seconds()
        for name in os.listdir(UPLOAD_DIR):
            path = os.path.join(UPLOAD_DIR, name)
            if os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)


def schedule_stalled_import_check(app):
    """Check every 5 minutes. Call once after create_app()."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        print('[telegram-import] APScheduler not installed — stalled imports will not be reported')
        return None

    def job():
        with app.app_context():
            from models import db
            try:
                fail_stalled_imports()
            except Exception:
                log.exception('[telegram-import] stalled import check failed')
            finally:
                db.session.remove()
                db.engine.dispose()  # this runs in the gunicorn master: leave no connection for forks to share

    scheduler = BackgroundScheduler(timezone='Europe/London')
    scheduler.add_job(job, IntervalTrigger(minutes=5))
    scheduler.start()
    return scheduler


# ── The page ────────────────────────────────────────────────────────────────

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Upload Check In PDF | InspectPro</title>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #f1f5f9; color: #0f172a; }
  main { max-width: 420px; margin: 0 auto; padding: 32px 20px; }
  h1 { font-size: 20px; margin: 0 0 16px; }
  .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; }
  p { margin: 0 0 12px; line-height: 1.5; }
  input[type=file] { display: block; width: 100%; margin: 8px 0 16px; font-size: 15px; }
  .toggle { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 16px;
            padding: 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-weight: 600; }
  .toggle input { appearance: none; -webkit-appearance: none; flex-shrink: 0; position: relative; margin: 0;
                  width: 44px; height: 26px; border-radius: 13px; background: #cbd5e1; transition: background .2s; }
  .toggle input::after { content: ''; position: absolute; top: 3px; left: 3px; width: 20px; height: 20px;
                         border-radius: 50%; background: #fff; transition: transform .2s; }
  .toggle input:checked { background: #22c55e; }
  .toggle input:checked::after { transform: translateX(18px); }
  button { width: 100%; padding: 14px; border: 0; border-radius: 8px; background: #6366f1; color: #fff;
           font-size: 16px; font-weight: 600; }
  button:disabled { opacity: .5; }
  progress { width: 100%; height: 12px; margin-top: 16px; }
  #status { margin: 12px 0 0; font-weight: 600; }
  .error { color: #b91c1c; }
  [hidden] { display: none; }
</style>
</head>
<body>
<main>
  <h1>Upload Check In PDF</h1>
  <div class="card">
    <p id="what">Checking your link…</p>
    <form id="form" hidden>
      <input id="file" type="file" accept="application/pdf,.pdf" required>
      <label class="toggle">Import photos from the PDF
        <input id="photos" type="checkbox" role="switch">
      </label>
      <button id="send" type="submit">Upload</button>
    </form>
    <progress id="bar" max="100" value="0" hidden></progress>
    <p id="status" role="status"></p>
  </div>
</main>
<script>
(function () {
  var token = location.hash.slice(1)
  var el = function (id) { return document.getElementById(id) }
  var limits = null

  function say(message, isError) {
    el('status').textContent = message
    el('status').className = isError ? 'error' : ''
  }

  function call(path, options) {
    options = options || {}
    options.cache = 'no-store'  // also skips any reply the browser saved before
    options.headers = Object.assign({ 'X-Upload-Token': token }, options.headers || {})
    return fetch(path, options).then(function (res) {
      return res.json().catch(function () { return {} }).then(function (body) {
        if (res.ok) return body
        var error = new Error(body.error || 'The upload failed (' + res.status + ').')
        error.final = res.status < 500
        throw error
      })
    })
  }

  function sendPiece(index, blob, attempt) {
    return call('chunk/' + index, { method: 'PUT', body: blob, headers: { 'Content-Type': 'application/octet-stream' } })
      .catch(function (error) {
        if (error.final || attempt >= 4) throw error
        say('Connection problem — retrying…')
        return new Promise(function (resolve) { setTimeout(resolve, attempt * 2000) })
          .then(function () { return sendPiece(index, blob, attempt + 1) })
      })
  }

  call('info').then(function (info) {
    limits = info
    el('what').textContent = info.address + ' — report dated ' + info.date
    el('form').hidden = false
  }).catch(function (error) {
    el('what').textContent = ''
    say(error.message, true)
  })

  el('form').addEventListener('submit', function (event) {
    event.preventDefault()
    var file = el('file').files[0]
    if (!file) return
    if (file.size > limits.max_bytes) { say('That PDF is over 150 MB.', true); return }
    var count = Math.ceil(file.size / limits.chunk_bytes)
    var includePhotos = el('photos').checked
    el('send').disabled = el('file').disabled = el('photos').disabled = true
    el('bar').hidden = false

    var chain = Promise.resolve()
    for (let i = 0; i < count; i++) {
      chain = chain.then(function () {
        say('Uploading… ' + Math.round(i / count * 100) + '%')
        el('bar').value = i / count * 100
        return sendPiece(i, file.slice(i * limits.chunk_bytes, (i + 1) * limits.chunk_bytes), 1)
      })
    }
    chain.then(function () {
      return call('complete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ filename: file.name, chunks: count, size: file.size,
                                                       include_photos: includePhotos }) })
    }).then(function () {
      el('bar').value = 100
      el('form').hidden = true
      say('Uploaded. You can close this page — the bot will message you when the report is ready.')
    }).catch(function (error) {
      el('send').disabled = el('file').disabled = el('photos').disabled = false
      say(error.message + ' Please try again.', true)
    })
  })
})()
</script>
</body>
</html>
"""
