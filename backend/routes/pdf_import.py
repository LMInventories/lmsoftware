"""
pdf_import.py — Parse a PDF inspection report with Claude.

Architecture: background thread + polling.
  POST /pdf-import  — accepts the PDF, starts a daemon thread, returns {job_id} immediately
                      (completes in < 1 second — immune to gunicorn worker timeouts)
  GET  /pdf-import-status/<job_id> — returns {status: processing|done|error, result?, error?}

The daemon thread calls Anthropic (no time pressure) and writes the result to a temp file.
Both gunicorn workers share the same filesystem, so any worker can serve the status poll.
"""

import os
import io
import json
import uuid
import base64
import threading
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

pdf_import_bp = Blueprint('pdf_import', __name__)

JOBS_DIR = '/tmp/pdf_import_jobs'
os.makedirs(JOBS_DIR, exist_ok=True)

MIN_TEXT_CHARS = 500

PROMPT_TEMPLATE = """You are parsing a UK property inspection report (inventory or check-in) to extract structured data for a Check Out system.

Template structure available to match against:
__TEMPLATE_STRUCTURE__

Extract ALL rooms and items. For each item:
- label: the item name — use the EXACT label from the template where a match exists
- description: physical description of the item
- condition: condition at time of check-in
- _subs: array of sub-items (only when the PDF contains sub-items beneath this item — see below)

The report format is typically: [Room/Item Name] [Description] [Condition at Check In]
Some reports use columns: Item | Description | Condition at Check In | Condition at Check Out

IMPORTANT RULES:
- Extract condition at CHECK IN only (not check out, even if present)
- Preserve exact wording — this is a legal document
- If an item has no description or condition, still include it with empty strings
- Match room names to the template structure where possible
- Match item labels to the template item labels — do NOT invent new items for things that are sub-items of a template item

SUB-ITEMS — this is critical:
Many inspection reports list sub-items beneath a parent item. They appear as:
  • Items indented under a parent heading
  • Items prefixed with the parent name and a dash or colon, e.g. "Contents - Bedside Table", "Contents: Wardrobe"
  • A group of individual pieces listed under a heading like "Contents:" followed by a list

When you see this pattern:
1. Identify the PARENT item and match it to the template (e.g. "Contents" matches template item "Contents")
2. Place each sub-item inside "_subs" on that parent item — do NOT create a separate top-level item for each sub-item
3. Set the parent item's "label" to the matched template label
4. Set the parent item's "description" and "condition" from any overview text for that heading (or leave empty)
5. Each sub-item entry has only: "description" (what the sub-item is + its description) and "condition"

Example — PDF has:
  "Contents - Bedside Table: Oak veneer / In good order"
  "Contents - Wardrobe: White gloss / In good order"
→ Return ONE item with label "Contents" and _subs:
  { "label": "Contents", "description": "", "condition": "",
    "_subs": [
      { "description": "Oak veneer bedside table", "condition": "In good order" },
      { "description": "White gloss wardrobe",     "condition": "In good order" }
    ]
  }
NOT as two separate items "Contents - Bedside Table" and "Contents - Wardrobe".

Return ONLY valid JSON - no markdown, no explanation:
{
  "rooms": [
    {
      "name": "Lounge",
      "items": [
        {
          "label": "Door, Frame & Furniture",
          "description": "White painted panel door",
          "condition": "Good condition"
        },
        {
          "label": "Contents",
          "description": "",
          "condition": "",
          "_subs": [
            { "description": "Oak coffee table", "condition": "Good condition" },
            { "description": "3-seater grey fabric sofa", "condition": "Good condition" }
          ]
        }
      ]
    }
  ],
  "fixedSections": {
    "condition_summary": [{ "name": "General Condition", "condition": "Good overall" }],
    "keys": [{ "name": "Front Door Key", "description": "2 x Yale, 1 x Deadlock" }],
    "meter_readings": [{ "name": "Gas Meter", "locationSerial": "Under stairs", "reading": "12345.6" }],
    "cleaning_summary": [{ "name": "General Cleanliness", "cleanliness": "Professionally Cleaned", "cleanlinessNotes": "" }]
  }
}"""


# ── Job file helpers ──────────────────────────────────────────────────────────

def _job_path(job_id):
    return os.path.join(JOBS_DIR, job_id + '.json')

def _write_job(job_id, data):
    with open(_job_path(job_id), 'w') as f:
        json.dump(data, f)

def _read_job(job_id):
    path = _job_path(job_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)

def _delete_job(job_id):
    try:
        os.remove(_job_path(job_id))
    except OSError:
        pass


# ── PDF text extraction ───────────────────────────────────────────────────────

def _extract_pdf_text(raw_bytes):
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=3, y_tolerance=3)
                if t:
                    parts.append(t)
        return '\n'.join(parts)
    except Exception as e:
        print('[pdf-import] pdfplumber failed: ' + str(e))
        return ''

def _build_prompt(template_structure):
    return PROMPT_TEMPLATE.replace('__TEMPLATE_STRUCTURE__', template_structure)


# ── Background worker ─────────────────────────────────────────────────────────

def _run_import_job(job_id, api_key, messages, use_text_mode):
    """Runs in a daemon thread. Writes result to a temp file when complete."""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        print('[pdf-import] job ' + job_id + ' calling Anthropic (non-streaming)')

        message = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=8192,
            messages=messages,
        )
        full_text = message.content[0].text.strip()
        full_text = full_text.replace('```json', '').replace('```', '').strip()

        parsed = json.loads(full_text)
        room_count = len(parsed.get('rooms', []))
        item_count = sum(len(r.get('items', [])) for r in parsed.get('rooms', []))
        mode = 'text' if use_text_mode else 'document'
        print('[pdf-import] job ' + job_id + ' done: ' + str(room_count) + ' rooms, ' + str(item_count) + ' items (mode=' + mode + ')')

        _write_job(job_id, {'status': 'done', 'result': parsed})

    except json.JSONDecodeError as e:
        print('[pdf-import] job ' + job_id + ' JSON error: ' + str(e))
        _write_job(job_id, {'status': 'error', 'error': 'Claude returned invalid JSON: ' + str(e)})

    except Exception as e:
        import traceback
        print('[pdf-import] job ' + job_id + ' error: ' + str(e))
        print(traceback.format_exc())
        _write_job(job_id, {'status': 'error', 'error': str(e)})


# ── Routes ────────────────────────────────────────────────────────────────────

@pdf_import_bp.route('/pdf-import', methods=['POST'])
@jwt_required()
def pdf_import():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # Accept multipart/form-data or legacy JSON
    raw_bytes = None
    pdf_b64 = None

    if request.content_type and 'multipart/form-data' in request.content_type:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file_obj = request.files['file']
        raw_bytes = file_obj.read()
        if not raw_bytes:
            return jsonify({'error': 'Uploaded file is empty'}), 400
        template_structure = request.form.get('templateStructure') or 'No template - infer structure from PDF'
        print('[pdf-import] received file via multipart: ' + repr(file_obj.filename) + ', ' + str(len(raw_bytes)) + ' bytes')
    else:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        pdf_b64 = data.get('pdf')
        template_structure = data.get('templateStructure') or 'No template - infer structure from PDF'
        if not pdf_b64:
            return jsonify({'error': 'No PDF data provided'}), 400
        raw_bytes = base64.b64decode(pdf_b64)

    # Text extraction
    extracted_text = _extract_pdf_text(raw_bytes)
    use_text_mode = len(extracted_text) >= MIN_TEXT_CHARS
    prompt = _build_prompt(template_structure)

    if use_text_mode:
        print('[pdf-import] text extraction OK: ' + str(len(extracted_text)) + ' chars - text mode')
        messages = [{'role': 'user', 'content': prompt + '\n\n---\nPDF TEXT CONTENT:\n' + extracted_text}]
    else:
        print('[pdf-import] text extraction insufficient - document mode')
        if pdf_b64 is None:
            pdf_b64 = base64.b64encode(raw_bytes).decode('utf-8')
        messages = [
            {
                'role': 'user',
                'content': [
                    {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': pdf_b64}},
                    {'type': 'text', 'text': prompt},
                ],
            }
        ]

    # Start background job and return immediately
    job_id = str(uuid.uuid4())
    _write_job(job_id, {'status': 'processing'})

    thread = threading.Thread(
        target=_run_import_job,
        args=(job_id, api_key, messages, use_text_mode),
        daemon=True,
    )
    thread.start()

    print('[pdf-import] started job ' + job_id)
    return jsonify({'job_id': job_id})


@pdf_import_bp.route('/pdf-import-status/<job_id>', methods=['GET'])
@jwt_required()
def pdf_import_status(job_id):
    # Validate job_id looks like a UUID
    if not job_id or len(job_id) > 40:
        return jsonify({'error': 'Invalid job ID'}), 400

    job = _read_job(job_id)
    if not job:
        return jsonify({'status': 'not_found'}), 404

    status = job.get('status')
    if status == 'processing':
        return jsonify({'status': 'processing'})
    elif status == 'done':
        _delete_job(job_id)
        return jsonify({'status': 'done', 'result': job['result']})
    else:
        _delete_job(job_id)
        return jsonify({'status': 'error', 'error': job.get('error', 'Unknown error')})
