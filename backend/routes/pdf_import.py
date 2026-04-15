import os
import json
import base64
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

pdf_import_bp = Blueprint('pdf_import', __name__)

ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'


@pdf_import_bp.route('/pdf-import', methods=['POST'])
@jwt_required()
def pdf_import():
    """
    Parse a PDF inspection report using Claude's document understanding.

    Request JSON:
    {
      "pdf":               "<base64-encoded PDF>",
      "templateStructure": "<JSON string of template structure or null>"
    }

    Response JSON:
    {
      "rooms": [
        {
          "name": "Lounge",
          "items": [
            { "label": "Door & Frame", "description": "...", "condition": "..." }
          ]
        }
      ],
      "fixedSections": {
        "condition_summary":  [...],
        "keys":               [...],
        "meter_readings":     [...],
        "cleaning_summary":   [...]
      }
    }
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    pdf_b64          = data.get('pdf')
    template_structure = data.get('templateStructure') or 'No template — infer structure from PDF'

    if not pdf_b64:
        return jsonify({'error': 'No PDF data provided'}), 400

    # Validate base64
    try:
        base64.b64decode(pdf_b64)
    except Exception:
        return jsonify({'error': 'Invalid base64 PDF data'}), 400

    prompt = f"""You are parsing a UK property inspection report PDF (inventory or check-in) to extract structured data for a Check Out system.

Template structure available to match against:
{template_structure}

Extract ALL rooms and items. For each item:
- label: the item name
- description: physical description of the item
- condition: condition at time of check-in

PDF format is typically: [Room/Item Name] [Description] [Condition at Check In]
Some PDFs use columns: Item | Description | Condition at Check In | Condition at Check Out

IMPORTANT RULES:
- Extract condition at CHECK IN only (not check out, even if present)
- Preserve exact wording — this is a legal document
- If an item has no description or condition, still include it with empty strings
- Match room names to the template structure where possible

Return ONLY valid JSON — no markdown, no explanation:
{{
  "rooms": [
    {{
      "name": "Lounge",
      "items": [
        {{ "label": "Door, Frame, Threshold & Furniture", "description": "White painted panel door with chrome handle", "condition": "Appears in good condition" }}
      ]
    }}
  ],
  "fixedSections": {{
    "condition_summary": [{{ "name": "General Condition", "condition": "Good overall" }}],
    "keys": [{{ "name": "Front Door Key", "description": "2 x Yale, 1 x Deadlock" }}],
    "meter_readings": [{{ "name": "Gas Meter", "locationSerial": "Under stairs\\nSerial Number: 123456", "reading": "12345.6" }}],
    "cleaning_summary": [{{ "name": "General Cleanliness", "cleanliness": "Professionally Cleaned", "cleanlinessNotes": "" }}]
  }}
}}"""

    payload = {
        'model':      'claude-sonnet-4-6',
        'max_tokens': 16000,
        'messages': [
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'document',
                        'source': {
                            'type':       'base64',
                            'media_type': 'application/pdf',
                            'data':       pdf_b64,
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

    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                'x-api-key':          api_key,
                'anthropic-version':  '2023-06-01',
                'anthropic-beta':     'pdfs-2024-09-25',
                'content-type':       'application/json',
            },
            json=payload,
            timeout=180,
        )

        if resp.status_code != 200:
            print(f'[pdf-import] Anthropic error {resp.status_code}: {resp.text[:400]}')
            return jsonify({'error': f'Claude API error: {resp.status_code}', 'detail': resp.text[:400]}), 502

        result = resp.json()
        raw = result.get('content', [{}])[0].get('text', '').strip()

        # Strip any accidental markdown fences
        raw = raw.replace('```json', '').replace('```', '').strip()

        parsed = json.loads(raw)

        room_count = len(parsed.get('rooms', []))
        item_count = sum(len(r.get('items', [])) for r in parsed.get('rooms', []))
        print(f'[pdf-import] extracted {room_count} rooms, {item_count} items')

        return jsonify(parsed)

    except requests.exceptions.Timeout:
        return jsonify({'error': 'PDF analysis timed out — try a smaller PDF'}), 504

    except json.JSONDecodeError as e:
        print(f'[pdf-import] JSON parse error: {e}')
        print(f'[pdf-import] Raw response: {raw[:500]}')
        return jsonify({'error': f'Claude returned invalid JSON: {str(e)}', 'raw': raw[:500]}), 500

    except Exception as e:
        import traceback
        print(f'[pdf-import] Error: {e}')
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
