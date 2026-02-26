import os
import json
import tempfile
import base64
import anthropic
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, TranscriptionUsage

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


def _claude_fill_item(transcript: str, item_label: str, room_name: str, section_type: str = 'room') -> dict:
    """
    Given a short transcript for a single item, return the appropriate fields
    based on section type. Uses claude-haiku-4-5.

    Section types and their fields:
    - room (default):        { description, condition }
    - condition_summary:     { condition }
    - cleaning_summary:      { notes }
    - fire_door_safety:      { notes }
    - health_safety:         { notes }
    - keys:                  { description }
    - meter_readings:        { locationSerial, reading }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    # Shared formatting rules applied to all section types
    formatting_rules = """
FORMATTING RULES — apply to all output fields:
- Convert spoken numbers to numerals: "two" → "2", "three" → "3", "one" → "1" etc.
- Format quantities as "N x item": "two green curtains" → "2 x green curtains"
- When multiple distinct items are listed, put each on its own line
- For meter readings location: use line breaks for clarity, e.g.:
    "Located to entrance hallway cupboard\nSerial Number: 123456"
- Capitalise the first word of each line
- Do NOT use bullet points or dashes — just line breaks between items
- Keep each line concise"""

    if section_type == 'meter_readings':
        field_instructions = """Extract into these two fields:
- locationSerial: where the meter is located and its serial number, formatted across lines:
    "Located to [location]\nSerial Number: [number]"
  If only location mentioned, just the location. If only serial, just the serial.
- reading: the meter reading value only (e.g. "12345")
Return ONLY valid JSON, no markdown:
{"locationSerial": "...", "reading": ""}"""

    elif section_type == 'cleaning_summary':
        field_instructions = """Put the complete transcript (cleaned of filler words only) into cleanlinessNotes.
If multiple points are made, put each on its own line using \n.
Return ONLY valid JSON, no markdown:
{"cleanlinessNotes": "..."}"""

    elif section_type in ('fire_door_safety', 'health_safety', 'smoke_alarms'):
        field_instructions = """Put the complete transcript (cleaned of filler words only) into notes.
If multiple points are made, put each on its own line using \n.
Return ONLY valid JSON, no markdown:
{"notes": "..."}"""

    elif section_type == 'condition_summary':
        field_instructions = """Put the complete transcript (cleaned of filler words only) into condition.
If multiple points are made, put each on its own line.
Return ONLY valid JSON, no markdown:
{"condition": "..."}"""

    elif section_type == 'keys':
        field_instructions = """Put the complete transcript into the description field.
Format rules:
- Collection/return info goes on the first line (e.g. "Keys collected from and returned to agent")
- Each key type goes on its own line using \n, formatted as "N x [key type]"
  Example: "1 x Yale key\n1 x mailbox key\n2 x garage fob"
- Convert spoken numbers to numerals: "one" → "1", "two" → "2"
- Use "x" not "×" for quantities
Return ONLY valid JSON, no markdown:
{"description": "..."}"""

    else:
        field_instructions = """Extract and structure this into:
- description: the physical appearance (material, colour, size, style, finish)
- condition: the state or working order

SPLITTING rules:
- Condition phrases that signal the start of the condition field:
  "in good order", "in fair order", "in poor order", "good order", "fair order",
  "poor order", "as new", "as inventory", "in good condition"
- Anything said AFTER a condition phrase is ALSO condition, not description.
  Example: "two white metal radiators, in good order, appear complete"
    description: "Two white metal radiators"
    condition: "In good order, appear complete"
- Functional observations like "appear complete", "tested for power", "appears working"
  are ALWAYS condition, never description
- If transcript only mentions condition, leave description blank

MULTI-COMPONENT FORMATTING — this is critical:
- If the description contains multiple distinct physical components, put EACH on its own line using \n
- A "component" is a distinct element — different material, surface type, or fitting
- ALWAYS use \n line breaks, NEVER commas to separate components
  Example: "part white ceramic tile, part grey fitted carpet with silver metal threshold"
    CORRECT:   "Part white ceramic tile\nPart grey fitted carpet\nSilver metal threshold"
    INCORRECT: "Part white ceramic tile, part grey fitted carpet with silver metal threshold"
  Example: "dark wood curtain rail, two green fabric floor length curtains"
    CORRECT:   "Dark wood curtain rail\n2 x green fabric floor length curtains"
    INCORRECT: "Dark wood curtain rail, two green fabric floor length curtains"
- The same rule applies to condition if multiple condition points are made:
  Example: "in good order, light indentations to tiles, light wear to carpet"
    CORRECT:   "In good order\nLight indentations to tiles\nLight wear to carpet"
    INCORRECT: "In good order, light indentations to tiles, light wear to carpet"
- When in doubt: if you would use a comma to separate two ideas, use \n instead

Return ONLY valid JSON, no markdown:
{"description": "...", "condition": ""}"""

    prompt = f"""You are processing a UK property inspection dictation.

Section type: {section_type}
Item: {item_label}
Room/Section: {room_name}

The clerk has dictated:
"{transcript}"

CRITICAL LANGUAGE RULES:
- Use the EXACT words and phrases the clerk spoke. Do not substitute synonyms.
- "good order" stays "good order" — never change to "good condition"
- "fair wear and tear" stays exactly that
- This is a legal document — preserve all professional terminology exactly
- Only clean up filler words (um, uh, er) and obvious repetition
- Use British English spelling
{formatting_rules}

{field_instructions}"""

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
- CRITICAL: Use the EXACT words and phrases the clerk spoke. Do not substitute synonyms or rephrase.
  Example: if the clerk says "good order", write "Good order" — NOT "Good condition"
  Example: if the clerk says "fair wear and tear", write exactly that
  Example: if the clerk says "as new" or "as inventory", preserve those exact phrases
- The clerk's terminology is professional and intentional — this is a legal document
- Only clean up filler words (um, uh, er) and obvious repetition
- Use British English spelling for any connecting words you add
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

    audio_b64    = data.get('audio')
    mime_type    = data.get('mimeType', 'audio/webm')
    item_label   = data.get('itemLabel', 'Item')
    room_name    = data.get('roomName', '')
    section_id   = data.get('sectionId')
    row_id       = data.get('rowId')
    section_type = data.get('sectionType', 'room')  # room|condition_summary|cleaning_summary|keys|meter_readings|fire_door_safety|health_safety

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

        filled, filled_msg = _claude_fill_item(transcript, item_label, room_name, section_type)

        # Log usage
        try:
            usage = TranscriptionUsage(
                call_type     = 'item',
                inspection_id = int(data.get('inspectionId')) if data.get('inspectionId') else None,
                user_id       = int(get_jwt_identity()),
                audio_seconds = len(audio_bytes) / 16000,  # rough estimate
                input_tokens  = filled_msg.usage.input_tokens  if filled_msg and filled_msg.usage else 0,
                output_tokens = filled_msg.usage.output_tokens if filled_msg and filled_msg.usage else 0,
                section_type  = section_type,
            )
            db.session.add(usage)
            db.session.commit()
        except Exception:
            pass  # never let logging break the response

        return jsonify({
            'transcript':       transcript,
            'description':      filled.get('description', ''),
            'condition':        filled.get('condition', ''),
            'notes':            filled.get('notes', ''),
            'cleanlinessNotes': filled.get('cleanlinessNotes', ''),
            'locationSerial':   filled.get('locationSerial', ''),
            'reading':          filled.get('reading', ''),
            'sectionId':        section_id,
            'rowId':            row_id,
            'sectionType':      section_type,
        })

    except Exception as e:
        import traceback
        print(f'[transcribe/item] Error: {e}')
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@transcribe_bp.route('/usage', methods=['GET'])
@jwt_required()
def transcribe_usage():
    """Returns usage stats and cost estimates in GBP."""
    from datetime import datetime, timedelta
    from sqlalchemy import func

    # Period filter
    period = request.args.get('period', '30')  # days
    since  = datetime.utcnow() - timedelta(days=int(period))

    rows = TranscriptionUsage.query.filter(TranscriptionUsage.created_at >= since).all()

    USD_TO_GBP           = 0.79
    WHISPER_PER_MIN_USD  = 0.006
    HAIKU_IN_PER_1M_USD  = 0.80
    HAIKU_OUT_PER_1M_USD = 4.00

    total_seconds = sum(r.audio_seconds for r in rows)
    total_in      = sum(r.input_tokens  for r in rows)
    total_out     = sum(r.output_tokens for r in rows)
    item_count    = sum(1 for r in rows if r.call_type == 'item')
    full_count    = sum(1 for r in rows if r.call_type == 'full')

    whisper_usd = (total_seconds / 60) * WHISPER_PER_MIN_USD
    claude_usd  = (total_in  / 1_000_000) * HAIKU_IN_PER_1M_USD +                   (total_out / 1_000_000) * HAIKU_OUT_PER_1M_USD
    total_gbp   = (whisper_usd + claude_usd) * USD_TO_GBP

    return jsonify({
        'period_days':     int(period),
        'item_calls':      item_count,
        'full_calls':      full_count,
        'total_calls':     len(rows),
        'audio_minutes':   round(total_seconds / 60, 1),
        'whisper_cost_gbp': round(whisper_usd * USD_TO_GBP, 4),
        'claude_cost_gbp':  round(claude_usd  * USD_TO_GBP, 4),
        'total_cost_gbp':   round(total_gbp, 4),
        'recent':          [r.to_dict() for r in sorted(rows, key=lambda x: x.created_at, reverse=True)[:20]],
    })


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
