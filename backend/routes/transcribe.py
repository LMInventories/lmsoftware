import os
import json
import tempfile
import base64
import anthropic
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

transcribe_bp = Blueprint('transcribe', __name__)


# ── Helpers ────────────────────────────────────────────────────────────────

def _whisper_transcribe(audio_bytes: bytes, mime_type: str) -> str:
    """Send audio bytes to OpenAI Whisper, return transcript string."""
    import openai

    client = openai.OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

    ext_map = {
        'audio/webm':  'webm',
        'audio/ogg':   'ogg',
        'audio/mp4':   'mp4',
        'audio/mpeg':  'mp3',
        'audio/wav':   'wav',
        'audio/x-wav': 'wav',
        'audio/flac':  'flac',
        'audio/m4a':   'm4a',
    }
    ext = ext_map.get(mime_type, 'webm')

    with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, 'rb') as f:
            response = client.audio.transcriptions.create(
                model='whisper-1',
                file=f,
                language='en',
                response_format='text',
                prompt=(
                    'This is a UK property inventory inspection dictation. '
                    'The speaker is describing the condition and appearance of items in a room. '
                    'Items may include furniture, fixtures, fittings, walls, floors, ceilings. '
                    'Preserve all detail accurately.'
                )
            )
        return str(response).strip()
    finally:
        os.unlink(tmp_path)


def _claude_fill_item(transcript: str, item_label: str, room_name: str) -> dict:
    """
    Given a short transcript for a single item, return { description, condition }.
    Uses claude-haiku-4-5 — fast and cheap for this structured task.
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    prompt = f"""You are processing a UK property inspection dictation for a single item.

Room: {room_name}
Item: {item_label}

The clerk has dictated the following about this item:
"{transcript}"

Extract and structure this into:
- description: the physical description of the item (what it is, material, colour, size if mentioned)
- condition: the current condition (wear, marks, damage, cleanliness, or "Good condition" if no issues mentioned)

Rules:
- Be concise and professional — inventory report style
- If the transcript only mentions condition (no physical description), leave description blank
- If the transcript mentions both, split them appropriately
- Do not invent information not present in the transcript
- Use British English spelling

Return ONLY valid JSON, no markdown:
{{"description": "...", "condition": "..."}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=300,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(raw)


def _claude_fill_full_report(transcript: str, template_structure: dict) -> dict:
    """
    Given a long continuous transcript covering a whole inspection,
    fill all items in the template structure.

    Returns a dict matching reportData shape:
    { sectionId: { rowId: { description: "...", condition: "..." } } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    structure_json = json.dumps(template_structure, indent=2)

    prompt = f"""You are processing a UK property inventory inspection audio transcript.
The clerk has walked through the property and dictated descriptions and conditions for items room by room.

Template structure (the items that need filling):
{structure_json}

Full transcript:
"{transcript}"

Instructions:
- Map the clerk's dictation to the correct items in the template
- For each item, extract description and condition
- Be concise and professional — inventory report style
- Use British English spelling
- Only fill items that are mentioned in the transcript
- If an item is not mentioned, omit it from the output entirely

Return ONLY valid JSON in this exact shape (no markdown):
{{
  "<sectionId>": {{
    "<rowId>": {{
      "description": "...",
      "condition": "..."
    }}
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=4000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(raw)


# ── Endpoints ─────────────────────────────────────────────────────────────

@transcribe_bp.route('/status', methods=['GET'])
@jwt_required()
def transcribe_status():
    """Returns which AI services are configured — used by TranscriptionSettings."""
    return jsonify({
        'openai':    'ok' if os.environ.get('OPENAI_API_KEY')    else 'missing',
        'anthropic': 'ok' if os.environ.get('ANTHROPIC_API_KEY') else 'missing',
    })


@transcribe_bp.route('/item', methods=['POST'])
@jwt_required()
def transcribe_item():
    """
    Per-item clip — called immediately when a short item recording stops.

    Request JSON:
    {
      "audio":      "<base64-encoded audio>",
      "mimeType":   "audio/webm",
      "itemLabel":  "Door & Frame",
      "roomName":   "Kitchen",
      "sectionId":  "abc123",
      "rowId":      "456"
    }

    Response JSON:
    {
      "transcript":  "White painted panel door...",
      "description": "White painted panel door with chrome handle",
      "condition":   "Good condition",
      "sectionId":   "abc123",
      "rowId":       "456"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    audio_b64  = data.get('audio')
    mime_type  = data.get('mimeType', 'audio/webm')
    item_label = data.get('itemLabel', 'Item')
    room_name  = data.get('roomName', '')
    section_id = data.get('sectionId')
    row_id     = data.get('rowId')

    if not audio_b64:
        return jsonify({'error': 'No audio data'}), 400

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return jsonify({'error': 'Invalid base64 audio data'}), 400

    try:
        transcript = _whisper_transcribe(audio_bytes, mime_type)

        if not transcript:
            return jsonify({'error': 'No speech detected in recording'}), 422

        filled = _claude_fill_item(transcript, item_label, room_name)

        return jsonify({
            'transcript':  transcript,
            'description': filled.get('description', ''),
            'condition':   filled.get('condition', ''),
            'sectionId':   section_id,
            'rowId':       row_id,
        })

    except Exception as e:
        print(f'[transcribe/item] Error: {e}')
        return jsonify({'error': str(e)}), 500


@transcribe_bp.route('/full', methods=['POST'])
@jwt_required()
def transcribe_full():
    """
    Full inspection continuous recording — called at Processing stage for AI typist.

    Request JSON:
    {
      "audio":    "<base64-encoded audio>",
      "mimeType": "audio/webm",
      "template": { ...simplified template structure... }
    }

    Response JSON:
    {
      "transcript": "...",
      "filled": {
        "<sectionId>": {
          "<rowId>": { "description": "...", "condition": "..." }
        }
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    audio_b64 = data.get('audio')
    mime_type = data.get('mimeType', 'audio/webm')
    template  = data.get('template', {})

    if not audio_b64:
        return jsonify({'error': 'No audio data'}), 400

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return jsonify({'error': 'Invalid base64 audio data'}), 400

    try:
        transcript = _whisper_transcribe(audio_bytes, mime_type)

        if not transcript:
            return jsonify({'error': 'No speech detected in recording'}), 422

        filled = _claude_fill_full_report(transcript, template)

        return jsonify({
            'transcript': transcript,
            'filled':     filled,
        })

    except Exception as e:
        print(f'[transcribe/full] Error: {e}')
        return jsonify({'error': str(e)}), 500
