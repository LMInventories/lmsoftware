"""
pdf_import.py — Parse a PDF inspection report with Claude.

Accepts multipart/form-data:
  file              — the PDF binary (required)
  templateStructure — optional JSON string of the template structure

Strategy:
  1. Extract text from the PDF using pdfplumber (fast, works for text-based PDFs).
  2. Send the extracted text to Claude as a plain text message (much faster than
     sending the binary document — a 5MB PDF becomes ~100KB of text).
  3. If text extraction yields too little content (scanned/image PDF), fall back
     to the Anthropic document API with the raw binary.

Response JSON:
  { "rooms": [...], "fixedSections": { ... } }
"""

import os
import io
import json
import base64
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

pdf_import_bp = Blueprint('pdf_import', __name__)

ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'

# Minimum characters of extracted text before we trust it (vs treating as scanned)
MIN_TEXT_CHARS = 500

PROMPT_TEMPLATE = """You are parsing a UK property inspection report (inventory or check-in) to extract structured data for a Check Out system.

Template structure available to match against:
__TEMPLATE_STRUCTURE__

Extract ALL rooms and items. For each item:
- label: the item name
- description: physical description of the item
- condition: condition at time of check-in

The report format is typically: [Room/Item Name] [Description] [Condition at Check In]
Some reports use columns: Item | Description | Condition at Check In | Condition at Check Out

IMPORTANT RULES:
- Extract condition at CHECK IN only (not check out, even if present)
- Preserve exact wording - this is a legal document
- If an item has no description or condition, still include it with empty strings
- Match room names to the template structure where possible

Return ONLY valid JSON - no markdown, no explanation:
{
  "rooms": [
    {
      "name": "Lounge",
      "items": [
        { "label": "Door, Frame, Threshold & Furniture", "description": "White painted panel door with chrome handle", "condition": "Appears in good condition" }
      ]
    }
  ],
  "fixedSections": {
    "condition_summary": [{ "name": "General Condition", "condition": "Good overall" }],
    "keys": [{ "name": "Front Door Key", "description": "2 x Yale, 1 x Deadlock" }],
    "meter_readings": [{ "name": "Gas Meter", "locationSerial": "Under stairs\\nSerial Number: 123456", "reading": "12345.6" }],
    "cleaning_summary": [{ "name": "General Cleanliness", "cleanliness": "Professionally Cleaned", "cleanlinessNotes": "" }]
  }
}"""


def _extract_pdf_text(raw_bytes):
    """Extract all text from a PDF using pdfplumber. Returns '' on failure."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if page_text:
                    text_parts.append(page_text)
        return '\n'.join(text_parts)
    except Exception as e:
        print('[pdf-import] pdfplumber extraction failed: ' + str(e))
        return ''


def _build_prompt(template_structure):
    return PROMPT_TEMPLATE.replace('__TEMPLATE_STRUCTURE__', template_structure)


@pdf_import_bp.route('/pdf-import', methods=['POST'])
@jwt_required()
def pdf_import():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # Accept multipart/form-data (preferred) OR legacy JSON {pdf: base64}
    raw_bytes = None
    pdf_b64 = None

    if request.content_type and 'multipart/form-data' in request.content_type:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided in form data'}), 400
        file_obj = request.files['file']
        raw_bytes = file_obj.read()
        if not raw_bytes:
            return jsonify({'error': 'Uploaded file is empty'}), 400
        template_structure = request.form.get('templateStructure') or 'No template - infer structure from PDF'
        print('[pdf-import] received file via multipart: ' + repr(file_obj.filename) + ', ' + str(len(raw_bytes)) + ' bytes')
    else:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': 'No data provided - send multipart/form-data with a "file" field'}), 400
        pdf_b64 = data.get('pdf')
        template_structure = data.get('templateStructure') or 'No template - infer structure from PDF'
        if not pdf_b64:
            return jsonify({'error': 'No PDF data provided'}), 400
        raw_bytes = base64.b64decode(pdf_b64)
        print('[pdf-import] received file via JSON base64: ' + str(len(pdf_b64)) + ' chars')

    # Try text extraction first (fast path)
    extracted_text = _extract_pdf_text(raw_bytes)
    use_text_mode = len(extracted_text) >= MIN_TEXT_CHARS

    prompt = _build_prompt(template_structure)

    if use_text_mode:
        print('[pdf-import] text extraction OK: ' + str(len(extracted_text)) + ' chars - using text mode')
        payload = {
            'model': 'claude-sonnet-4-6',
            'max_tokens': 16000,
            'messages': [
                {
                    'role': 'user',
                    'content': prompt + '\n\n---\nPDF TEXT CONTENT:\n' + extracted_text,
                }
            ],
        }
    else:
        # Fallback: send raw PDF as a document (works for scanned/image PDFs)
        print('[pdf-import] text extraction insufficient (' + str(len(extracted_text)) + ' chars) - using document mode')
        if pdf_b64 is None:
            pdf_b64 = base64.b64encode(raw_bytes).decode('utf-8')
        payload = {
            'model': 'claude-sonnet-4-6',
            'max_tokens': 16000,
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'document',
                            'source': {
                                'type': 'base64',
                                'media_type': 'application/pdf',
                                'data': pdf_b64,
                            },
                        },
                        {
                            'type': 'text',
                            'text': prompt,
                        },
                    ],
                }
            ],
        }

    raw = ''
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json=payload,
            timeout=270,
        )

        if resp.status_code != 200:
            print('[pdf-import] Anthropic error ' + str(resp.status_code) + ': ' + resp.text[:400])
            return jsonify({'error': 'Claude API error: ' + str(resp.status_code), 'detail': resp.text[:400]}), 502

        result = resp.json()
        raw = result.get('content', [{}])[0].get('text', '').strip()

        # Strip any accidental markdown fences
        raw = raw.replace('```json', '').replace('```', '').strip()

        parsed = json.loads(raw)

        room_count = len(parsed.get('rooms', []))
        item_count = sum(len(r.get('items', [])) for r in parsed.get('rooms', []))
        mode = 'text' if use_text_mode else 'document'
        print('[pdf-import] extracted ' + str(room_count) + ' rooms, ' + str(item_count) + ' items (mode=' + mode + ')')

        return jsonify(parsed)

    except requests.exceptions.Timeout:
        return jsonify({'error': 'PDF analysis timed out - try a smaller PDF'}), 504

    except json.JSONDecodeError as e:
        print('[pdf-import] JSON parse error: ' + str(e))
        print('[pdf-import] Raw response: ' + raw[:500])
        return jsonify({'error': 'Claude returned invalid JSON: ' + str(e), 'raw': raw[:500]}), 500

    except Exception as e:
        import traceback
        print('[pdf-import] Error: ' + str(e))
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
