"""
pdf_import.py — Parse a PDF inspection report with Claude.

Architecture: background thread + polling.
  POST /pdf-import  — accepts the PDF, starts a daemon thread, returns {job_id} immediately
                      (completes in < 1 second — immune to gunicorn worker timeouts)
  GET  /pdf-import-status/<job_id> — returns {status: processing|done|error, result?, error?}

The daemon thread calls Anthropic (no time pressure) and writes the result to a temp file.
Both gunicorn workers share the same filesystem, so any worker can serve the status poll.

Large PDF strategy:
  - Under CHUNK_THRESHOLD chars → single call with max_tokens=8192
  - Over threshold → split at room boundaries into chunks, process each separately,
    merge results server-side. This avoids JSON truncation for large inventories.
"""

import os
import io
import re
import json
import uuid
import base64
import threading
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

pdf_import_bp = Blueprint('pdf_import', __name__)

JOBS_DIR = '/tmp/pdf_import_jobs'
os.makedirs(JOBS_DIR, exist_ok=True)

MIN_TEXT_CHARS   = 500
CHUNK_THRESHOLD  = 12_000   # chars — above this we chunk
MAX_CHUNK_CHARS  = 9_000    # target chars per chunk
MAX_TOKENS_SINGLE = 8192
MAX_TOKENS_CHUNK  = 4096    # smaller chunks → smaller responses

# Room-like headings used to detect section boundaries in UK inventory reports
_ROOM_HEADER_RE = re.compile(
    r'^(?:HALLWAY|HALL|ENTRANCE|RECEPTION|LOUNGE|LIVING\s*ROOM|SITTING\s*ROOM|'
    r'KITCHEN|KITCHEN[/ ]*DINER|DINING\s*ROOM|BEDROOM|MASTER\s*BEDROOM|SPARE\s*BEDROOM|'
    r'BATHROOM|BATHROOM\s*\d|EN[- ]?SUITE|WC|TOILET|CLOAKROOM|LANDING|STAIRS?|'
    r'STAIRCASE|GARAGE|UTILITY\s*ROOM|STUDY|OFFICE|CONSERVATORY|GARDEN|LOFT|'
    r'CELLAR|BASEMENT|STORAGE|CUPBOARD|PORCH|LOBBY)[\s\d]*$',
    re.IGNORECASE,
)


PROMPT_TEMPLATE = """You are extracting structured data from a UK property inspection report (inventory or check-in) for a Check Out system.

Template structure to match against:
__TEMPLATE_STRUCTURE__

═══════════════════════════════════════
GOLDEN RULE — COPY, DO NOT REWRITE
═══════════════════════════════════════
Copy text from the PDF VERBATIM into description and condition fields.
• Do NOT summarise, paraphrase, abbreviate, or reformat anything.
• Do NOT merge sentences or remove any words.
• If the PDF spans multiple lines for one item, join them with \\n (a literal newline character in the JSON string).
• Preserve every detail exactly as written — this is a legal document.

═══════════════════════════════════════
MATCHING ALGORITHM — READ THIS CAREFULLY
═══════════════════════════════════════
Process the PDF line by line, for each room section:

1. Try to match the line to a template item label (case-insensitive, partial match OK).
   → If it matches: this line's data goes into that template item (label, description, condition).
      Remember this as the "current parent item".

2. If the line does NOT match any template item label:
   → It is a SUB-ITEM of the current parent item.
   → Add it to "_subs" on the current parent item.
   → Do NOT create a new top-level item for it.

3. Common sub-item patterns — these are ALWAYS sub-items, never top-level items:
   • "Contents - Bedside Table: Oak veneer / In good order"
     → parent = "Contents", sub = { description: "Bedside Table: Oak veneer", condition: "In good order" }
   • "Contents: Wardrobe — white gloss" followed by "In good order"
     → parent = "Contents", sub = { description: "Wardrobe — white gloss", condition: "In good order" }
   • Any line prefixed with the parent item name and a dash, colon, or slash

4. If NO template is provided (template says "No template"), infer structure from the PDF rooms/items directly — but still apply the sub-item rules above.

═══════════════════════════════════════
FIELD RULES
═══════════════════════════════════════
- label: EXACT label from the template where matched; otherwise use the PDF heading text as-is
- description: Copy verbatim from PDF. Multi-line → join with \\n. Empty string if not present.
- condition: Copy verbatim from PDF (CHECK IN column only — ignore Check Out). Empty string if not present.
- _subs: Array present only when the item has sub-items. Each sub-item has only "description" and "condition" (both verbatim).

═══════════════════════════════════════
FIXED SECTIONS
═══════════════════════════════════════
Extract these if present in the PDF. Copy all text verbatim.
- condition_summary: overall condition notes
- keys: key types and quantities handed over
- meter_readings: gas/electric/water meter readings with location/serial
- cleaning_summary: cleanliness notes

Return ONLY valid JSON — no markdown, no explanation:
{
  "rooms": [
    {
      "name": "Lounge",
      "items": [
        {
          "label": "Door, Frame & Furniture",
          "description": "White painted solid panel door with chrome lever handle\\nDoor frame painted white",
          "condition": "Good clean condition throughout"
        },
        {
          "label": "Contents",
          "description": "",
          "condition": "",
          "_subs": [
            { "description": "Bedside Table — oak veneer with single drawer", "condition": "Good order, minor surface scratch to top" },
            { "description": "Wardrobe — white gloss, double door with hanging rail", "condition": "Good clean condition" }
          ]
        }
      ]
    }
  ],
  "fixedSections": {
    "condition_summary": [{ "name": "General Condition", "condition": "Good overall condition throughout" }],
    "keys": [{ "name": "Front Door Key", "description": "2 x Yale, 1 x Deadlock" }],
    "meter_readings": [{ "name": "Gas Meter", "locationSerial": "Under stairs / Serial 12345", "reading": "12345.6" }],
    "cleaning_summary": [{ "name": "General Cleanliness", "cleanliness": "Professionally Cleaned", "cleanlinessNotes": "" }]
  }
}"""

CHUNK_PROMPT_TEMPLATE = """You are extracting structured data from a section of a UK property inspection report.

Template structure:
__TEMPLATE_STRUCTURE__

GOLDEN RULE: Copy text VERBATIM. Do NOT summarise or paraphrase. Multi-line → join with \\n.

For each room section found in the text below:
- label: match template item label where possible; otherwise use PDF heading as-is
- description: verbatim from PDF, empty string if absent
- condition: verbatim from PDF (CHECK IN column only), empty string if absent
- _subs: array of { description, condition } for sub-items (items prefixed with parent label)

Also extract any of these fixed sections if present in this chunk:
- condition_summary, keys, meter_readings, cleaning_summary

Return ONLY valid JSON, no markdown:
{
  "rooms": [ { "name": "...", "items": [ { "label": "...", "description": "...", "condition": "..." } ] } ],
  "fixedSections": {
    "condition_summary": [],
    "keys": [],
    "meter_readings": [],
    "cleaning_summary": []
  }
}

PDF TEXT SECTION:
__CHUNK_TEXT__"""


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


# ── Text chunking ─────────────────────────────────────────────────────────────

def _split_into_chunks(text, max_chars=MAX_CHUNK_CHARS):
    """
    Split extracted PDF text into chunks, trying to break at room/section
    boundaries so each chunk is self-contained. Falls back to hard splits
    at paragraph breaks if no room header is found within a window.
    """
    lines = text.split('\n')
    chunks = []
    current_lines = []
    current_size = 0

    for line in lines:
        line_size = len(line) + 1

        # If we're over the limit, try to cut here if this line looks like a room heading
        if current_size + line_size > max_chars and current_lines:
            is_boundary = (
                _ROOM_HEADER_RE.match(line.strip())
                or (line.strip() == '' and current_size > max_chars * 0.6)
            )
            if is_boundary:
                chunks.append('\n'.join(current_lines))
                current_lines = [line] if line.strip() else []
                current_size = line_size if line.strip() else 0
                continue

        # Hard split if we're way over
        if current_size + line_size > max_chars * 1.5 and current_lines:
            chunks.append('\n'.join(current_lines))
            current_lines = [line]
            current_size = line_size
            continue

        current_lines.append(line)
        current_size += line_size

    if current_lines:
        chunks.append('\n'.join(current_lines))

    # Filter out trivially small chunks (page headers/footers only)
    return [c for c in chunks if len(c.strip()) > 100]


# ── Claude call helpers ───────────────────────────────────────────────────────

def _call_claude(client, messages, max_tokens):
    """Single Claude call, returns parsed JSON dict or raises."""
    response = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=max_tokens,
        messages=messages,
    )
    raw = response.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(raw)


def _merge_results(results):
    """Merge a list of {rooms, fixedSections} dicts into one."""
    merged_rooms = []
    merged_fixed = {
        'condition_summary': [],
        'keys': [],
        'meter_readings': [],
        'cleaning_summary': [],
    }

    seen_room_names = {}  # name.lower() → index in merged_rooms

    for result in results:
        for room in result.get('rooms', []):
            name_key = room.get('name', '').lower().strip()
            if name_key in seen_room_names:
                # Merge items into the existing room entry
                idx = seen_room_names[name_key]
                merged_rooms[idx]['items'].extend(room.get('items', []))
            else:
                seen_room_names[name_key] = len(merged_rooms)
                merged_rooms.append({
                    'name': room.get('name', ''),
                    'items': list(room.get('items', [])),
                })

        fs = result.get('fixedSections', {})
        for key in merged_fixed:
            items = fs.get(key, [])
            if items:
                merged_fixed[key].extend(items)

    return {'rooms': merged_rooms, 'fixedSections': merged_fixed}


# ── Background worker ─────────────────────────────────────────────────────────

def _run_import_job(job_id, api_key, extracted_text, pdf_b64, template_structure, use_text_mode):
    """Runs in a daemon thread. Writes result to a temp file when complete."""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)

        if not use_text_mode:
            # Document mode: send raw PDF — no chunking possible
            print('[pdf-import] job ' + job_id + ' document mode (single call)')
            prompt = PROMPT_TEMPLATE.replace('__TEMPLATE_STRUCTURE__', template_structure)
            messages = [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': pdf_b64}},
                        {'type': 'text', 'text': prompt},
                    ],
                }
            ]
            parsed = _call_claude(client, messages, MAX_TOKENS_SINGLE)

        elif len(extracted_text) <= CHUNK_THRESHOLD:
            # Small PDF — single call
            print('[pdf-import] job ' + job_id + ' text mode, single call (' + str(len(extracted_text)) + ' chars)')
            prompt = PROMPT_TEMPLATE.replace('__TEMPLATE_STRUCTURE__', template_structure)
            messages = [{'role': 'user', 'content': prompt + '\n\n---\nPDF TEXT CONTENT:\n' + extracted_text}]
            parsed = _call_claude(client, messages, MAX_TOKENS_SINGLE)

        else:
            # Large PDF — split into chunks and merge
            chunks = _split_into_chunks(extracted_text)
            print('[pdf-import] job ' + job_id + ' text mode, chunked: ' + str(len(chunks)) + ' chunks from ' + str(len(extracted_text)) + ' chars')

            results = []
            for i, chunk in enumerate(chunks):
                print('[pdf-import] job ' + job_id + ' chunk ' + str(i + 1) + '/' + str(len(chunks)) + ' (' + str(len(chunk)) + ' chars)')
                chunk_prompt = (
                    CHUNK_PROMPT_TEMPLATE
                    .replace('__TEMPLATE_STRUCTURE__', template_structure)
                    .replace('__CHUNK_TEXT__', chunk)
                )
                messages = [{'role': 'user', 'content': chunk_prompt}]
                try:
                    chunk_result = _call_claude(client, messages, MAX_TOKENS_CHUNK)
                    results.append(chunk_result)
                except json.JSONDecodeError as e:
                    print('[pdf-import] job ' + job_id + ' chunk ' + str(i + 1) + ' JSON error (skipping): ' + str(e))
                    # Skip bad chunks rather than failing the whole job
                    continue

            if not results:
                raise ValueError('All chunks failed to parse — no usable data extracted')

            parsed = _merge_results(results)

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

    if not use_text_mode and pdf_b64 is None:
        pdf_b64 = base64.b64encode(raw_bytes).decode('utf-8')

    # Start background job and return immediately
    job_id = str(uuid.uuid4())
    _write_job(job_id, {'status': 'processing'})

    thread = threading.Thread(
        target=_run_import_job,
        args=(job_id, api_key, extracted_text, pdf_b64, template_structure, use_text_mode),
        daemon=True,
    )
    thread.start()

    print('[pdf-import] started job ' + job_id + ' (text_len=' + str(len(extracted_text)) + ', chunked=' + str(len(extracted_text) > CHUNK_THRESHOLD) + ')')
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
