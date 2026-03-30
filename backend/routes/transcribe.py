import os
import json
import tempfile
import base64
import anthropic
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, TranscriptionUsage

transcribe_bp = Blueprint('transcribe', __name__)


# ── Edit-mode detection ────────────────────────────────────────────────────
# Clerks can prefix a recording with trigger phrases to amend existing fields
# rather than filling only-if-empty.
#
#   "Amend description ..." → overwrite description field
#   "Amend condition ..."   → overwrite condition field
#   "Add to description ..."→ append to description field
#   "Add to condition ..."  → append to condition field

_EDIT_TRIGGERS = [
    ('amend description',     'overwrite', 'description'),
    ('amend the description',  'overwrite', 'description'),
    ('amend condition',        'overwrite', 'condition'),
    ('amend the condition',    'overwrite', 'condition'),
    ('add to description',     'append',    'description'),
    ('add to the description', 'append',    'description'),
    ('add to condition',       'append',    'condition'),
    ('add to the condition',   'append',    'condition'),
    ('add to conditions',      'append',    'condition'),
    ('add to the conditions',  'append',    'condition'),
]

def _detect_edit_mode(transcript: str):
    """
    Check if transcript starts with an edit-mode trigger phrase.
    Returns (mode, field, cleaned_transcript).
      mode:    'overwrite' | 'append' | 'normal'
      field:   'description' | 'condition' | None
      cleaned: transcript with trigger phrase stripped
    """
    lower = transcript.lower().strip()
    for phrase, mode, field in _EDIT_TRIGGERS:
        if lower.startswith(phrase):
            cleaned = transcript[len(phrase):].lstrip(' ,.:-').strip()
            return mode, field, cleaned
    return 'normal', None, transcript


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
        'audio/mp3':   'mp3',
        'audio/wav':   'wav',
        'audio/x-wav': 'wav',
        'audio/flac':  'flac',
        'audio/m4a':   'm4a',
        'audio/aac':   'm4a',
        'video/webm':  'webm',  # some browsers report video/webm for audio
    }
    # Strip codec suffix e.g. "audio/webm;codecs=opus" → "audio/webm"
    mime_base = mime_type.split(';')[0].strip().lower() if mime_type else 'audio/webm'
    ext = ext_map.get(mime_base, 'webm')
    print(f'[transcribe/item] mime_base: {repr(mime_base)} → ext: {ext}')

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
- If the clerk mentions NO condition at all, default condition to "In good order"

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
{"description": "...", "condition": "In good order"}"""

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
    return json.loads(raw), message

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

@transcribe_bp.route('/classify-photo', methods=['OPTIONS'])
def classify_photo_options():
    return '', 204


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

    # Debug: log what we received
    print(f'[transcribe/item] mimeType received: {repr(mime_type)}')
    print(f'[transcribe/item] audio_b64 length: {len(audio_b64)}')

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return jsonify({'error': 'Invalid base64 audio data'}), 400

    try:
        raw_transcript = _whisper_transcribe(audio_bytes, mime_type)

        if not raw_transcript:
            return jsonify({'error': 'No speech detected in recording'}), 422

        # Detect edit-mode trigger phrases before passing to Claude
        edit_mode, edit_field, transcript = _detect_edit_mode(raw_transcript)
        print(f'[transcribe/item] edit_mode={edit_mode!r} field={edit_field!r} transcript={transcript[:60]!r}')

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
            'transcript':       raw_transcript,   # return original for reference
            'description':      filled.get('description', ''),
            'condition':        filled.get('condition', ''),
            'notes':            filled.get('notes', ''),
            'cleanlinessNotes': filled.get('cleanlinessNotes', ''),
            'locationSerial':   filled.get('locationSerial', ''),
            'reading':          filled.get('reading', ''),
            'sectionId':        section_id,
            'rowId':            row_id,
            'sectionType':      section_type,
            'editMode':         edit_mode,    # 'normal' | 'overwrite' | 'append'
            'editField':        edit_field,   # 'description' | 'condition' | None
        })

    except Exception as e:
        import traceback
        print(f'[transcribe/item] Error: {e}')
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@transcribe_bp.route('/classify-photo', methods=['POST'])
@jwt_required()
def classify_photo():
    """
    Accepts a base64 image and room/item context string.
    Uses Claude vision to identify which room and item the photo belongs to.

    Request JSON:
    {
      "imageBase64": "<base64 jpeg>",
      "mimeType":    "image/jpeg",
      "roomContext": "<formatted room+item list string>"
    }

    Response JSON:
    {
      "sectionKey":  "42",
      "sectionName": "Bedroom 1",
      "itemKey":     "87",
      "itemName":    "Door & Frame",
      "confidence":  0.92
    }
    """
    data = request.get_json(force=True)
    image_base64 = data.get('imageBase64', '')
    mime_type    = data.get('mimeType', 'image/jpeg')
    room_context = data.get('roomContext', '')

    if not image_base64 or not room_context:
        return jsonify({'error': 'imageBase64 and roomContext are required'}), 400

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    prompt = f"""You are a property inspection assistant. Look at this photo carefully and identify which item in the room it belongs to.

{room_context}

Each item above may include a "described as" note (what the inspector has already written about it) and/or a "condition" note. Use these text descriptions alongside your visual analysis — if an item's description matches what you see in the photo, that is a strong signal.

Common property inspection items and what they look like:
- Door Fittings / Door & Frame: door handles, hinges, door frames, locks, letterboxes, door furniture
- Lighting / Light Fitting: ceiling lights, pendant lights, light shades, lampshades, wall lights, spotlights, bulbs, light fittings
- Walls: painted surfaces, wallpaper, plasterwork, wall damage, marks, dado rails
- Ceiling: ceiling surfaces, coving, cornices, ceiling roses
- Floor / Flooring: carpet, hardwood, laminate, tiles, vinyl, skirting boards
- Windows / Window & Frame: glass panes, window frames, window sills, blinds, curtains, curtain rails
- Radiator / Heating: radiators, heating units, thermostats, towel rails
- Sockets & Switches: electrical outlets, light switches, fuse boxes, consumer units
- Smoke Alarm / Carbon Monoxide Alarm: round alarm units mounted on ceiling or wall
- Kitchen appliances: oven, hob, microwave, dishwasher, fridge, extractor fan
- Bathroom: bath, shower, sink, toilet, taps, shower screen, tiles

Respond ONLY with a raw JSON object — no markdown, no backticks, no explanation, just the JSON:
{{"sectionKey":"<key>","sectionName":"<room name>","itemKey":"<key>","itemName":"<item name>","confidence":0.92}}

Rules:
- confidence is a number from 0.0 to 1.0
- Give confidence above 0.8 only when you are certain of both the room AND the item
- If an item's existing description closely matches what you see visually, increase your confidence accordingly
- If you can identify the item type but are unsure which one in the list, give 0.5-0.7
- sectionKey and itemKey must be copied exactly from the provided context list
- Match to the single closest item in the list"""

    try:
        message = client.messages.create(
            model='claude-opus-4-5',
            max_tokens=150,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type':       'base64',
                            'media_type': mime_type,
                            'data':       image_base64,
                        },
                    },
                    {
                        'type': 'text',
                        'text': prompt,
                    },
                ],
            }],
        )

        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        result = json.loads(raw)

        # Ensure all required fields are present
        for field in ('sectionKey', 'sectionName', 'itemKey', 'itemName'):
            if field not in result:
                result[field] = ''
        result['confidence'] = float(result.get('confidence', 0))

        return jsonify(result)

    except json.JSONDecodeError as e:
        # Claude returned something that wasn't valid JSON — return gracefully
        print(f'[classify-photo] JSON parse error: {e}, raw: {raw!r}')
        return jsonify({
            'sectionKey': '', 'sectionName': '',
            'itemKey': '',    'itemName': '',
            'confidence': 0,
        })

    except Exception as e:
        import traceback
        print(f'[classify-photo] Error: {e}')
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


def _claude_fill_room(transcript: str, section_name: str, items: list) -> dict:
    """
    Fill a single room's items from a continuous dictation transcript.
    Item names are used as 'chapter headings' — the clerk says the item name
    then describes it, so the AI maps each passage to the correct item.

    items: [{ 'id': str, 'name': str, 'hasCondition': bool, 'hasDescription': bool }]

    Returns: { itemId: { 'description': '...', 'condition': '...' } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  - ID: "{item["id"]}", Name: "{item["name"]}"'
        for item in items
    )

    prompt = f"""You are processing a UK property inventory inspection dictation for a single room.

The clerk walked through the room and spoke each item name aloud followed by its description and condition.
Item names act as CHAPTER HEADINGS — when the clerk says an item name (or something close to it), everything that follows until the next item name is the description and/or condition for that item.

Room: {section_name}

Items to fill (use the ID as the JSON key, match by Name):
{items_list}

Transcript:
"{transcript}"

RULES:
1. Match each passage to the closest item name. The clerk may abbreviate (e.g. "Door" for "Door & Frame") — use fuzzy matching.
2. Extract description and condition separately. If the clerk says a single phrase, put it in description.
3. CRITICAL: Use the EXACT words the clerk spoke. Do not rephrase or substitute synonyms.
   - "good order" → "Good order" (NOT "Good condition")
   - "fair wear and tear" → "Fair wear and tear"
   - "as new" or "as inventory" → preserve exactly
4. Clean up only: filler words (um, uh, er), obvious repetition, false starts.
5. Only fill items that are mentioned. Omit unmentioned items entirely from the output.
6. Use British English spelling for any connecting words.
7. If only one piece of information is given for an item, put it in description.

MULTI-COMPONENT FORMATTING — critical for description and condition fields:
- If the description contains multiple distinct physical components, put EACH on its own line using \n
- A "component" is a distinct element — different material, surface type, or fitting
- ALWAYS use \n line breaks between components, NEVER commas
  Example: "white painted door, white painted frame" → "White painted door\nWhite painted frame"
  Example: "part white ceramic tile, part grey fitted carpet" → "Part white ceramic tile\nPart grey fitted carpet"
  Example: "dark wood curtain rail, two green fabric floor length curtains" → "Dark wood curtain rail\n2 x green fabric floor length curtains"
- The same rule applies to condition if multiple condition points are made:
  Example: "in good order, light indentations to tiles" → "In good order\nLight indentations to tiles"
- Convert spoken numbers to numerals: "two" → "2", "three" → "3"
- Format quantities as "N x item": "two green curtains" → "2 x green curtains"
- Capitalise the first word of each line
- Do NOT use bullet points or dashes — just \n line breaks

SPLITTING description vs condition:
- Condition signal phrases: "in good order", "in fair order", "in poor order", "good order",
  "fair order", "poor order", "as new", "as inventory", "in good condition"
- Everything said AFTER a condition phrase is also condition
- Functional observations ("appear complete", "tested", "appears working") are always condition
- If no condition is mentioned, default condition to "In good order"

Return ONLY valid JSON — no markdown, no extra text:
{{
  "<itemId>": {{
    "description": "...",
    "condition": "..."
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f'[_claude_fill_room] JSON parse error: {raw[:200]}')
        return {}


def _claude_fill_fixed_section(transcript: str, section_name: str, section_type: str, items: list) -> dict:
    """
    Fill a fixed section's items from a continuous dictation transcript.
    Like _claude_fill_room but returns section-type-specific field names.

    items: [{ 'id': str, 'name': str }]

    Return shapes per section type:
      condition_summary        → { "condition": "..." }
      cleaning_summary         → { "cleanlinessNotes": "..." }
      fire_door_safety /
        health_safety /
        smoke_alarms           → { "notes": "...", "answer": "Yes"|"No"|"" }
      keys                     → { "description": "..." }
      meter_readings            → { "locationSerial": "...", "reading": "..." }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  - ID: "{item["id"]}", Name: "{item["name"]}"'
        for item in items
    )

    if section_type == 'condition_summary':
        field_schema = '{"condition": "one or more lines of condition text"}'
        field_instructions = (
            'Extract the condition observations into "condition". '
            'If multiple points are made, put each on its own line using \\n. '
            'Use the EXACT words the clerk spoke.'
        )
    elif section_type == 'cleaning_summary':
        field_schema = '{"cleanlinessNotes": "one or more lines of notes"}'
        field_instructions = (
            'Extract the cleanliness observations into "cleanlinessNotes". '
            'If multiple points are made, put each on its own line using \\n. '
            'Use the EXACT words the clerk spoke.'
        )
    elif section_type in ('fire_door_safety', 'health_safety', 'smoke_alarms'):
        field_schema = '{"notes": "one or more lines of notes", "answer": "Yes or No or empty string"}'
        field_instructions = (
            'Extract observations into "notes". '
            'If the clerk gives a yes/no answer (e.g. "yes", "no", "working", "not working"), '
            'put "Yes" or "No" in "answer"; otherwise leave it as an empty string. '
            'If multiple note points, put each on its own line using \\n. '
            'Use the EXACT words the clerk spoke.'
        )
    elif section_type == 'keys':
        field_schema = '{"description": "one or more lines listing keys"}'
        field_instructions = (
            'Extract key descriptions into "description". '
            'Format each key type as "N x [key type]" on its own line using \\n. '
            'Convert spoken numbers to numerals ("two" → "2"). '
            'Use the EXACT words the clerk spoke.'
        )
    elif section_type == 'meter_readings':
        field_schema = '{"locationSerial": "Located to [location]\\nSerial Number: [number]", "reading": "meter reading value"}'
        field_instructions = (
            'Extract meter location and serial number into "locationSerial" '
            '(format: "Located to [location]\\nSerial Number: [number]"). '
            'Extract the reading value only into "reading". '
            'Use the EXACT words the clerk spoke.'
        )
    else:
        field_schema = '{"notes": "..."}'
        field_instructions = 'Extract all observations into "notes". Use the EXACT words the clerk spoke.'

    prompt = f"""You are processing a UK property inventory inspection dictation for a fixed section.

The clerk spoke each item name aloud followed by their observations.
Item names act as CHAPTER HEADINGS — everything said after an item name belongs to that item, until the next item name is spoken.

Section: {section_name}
Section type: {section_type}

Items to fill (use the ID as the JSON key, match by Name):
{items_list}

Transcript:
"{transcript}"

RULES:
1. Match each passage to the closest item name. The clerk may abbreviate — use fuzzy matching.
2. {field_instructions}
3. CRITICAL: Use the EXACT words the clerk spoke. Do not rephrase or substitute synonyms.
   - "good order" → "Good order" (NOT "Good condition")
   - "fair wear and tear" → "Fair wear and tear"
4. Clean up only: filler words (um, uh, er), obvious repetition, false starts.
5. Only fill items that are mentioned. Omit unmentioned items entirely from the output.
6. Use British English spelling for any connecting words.
7. Capitalise the first word of each line.

Return ONLY valid JSON — no markdown, no extra text:
{{
  "<itemId>": {field_schema}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f'[_claude_fill_fixed_section] JSON parse error: {raw[:200]}')
        return {}


@transcribe_bp.route('/room', methods=['POST'])
@jwt_required()
def transcribe_room():
    """
    Per-room dictation — the clerk records the whole room in one go (with pause/resume),
    then presses 'AI Transcribe' in the app to fill all item fields at once.

    This replaces the old 'ai_processing' server-side flow. All processing now happens
    on demand from the app before syncing.

    Request JSON:
    {
      "clips":       [{"audio": "<base64>", "mimeType": "audio/m4a"}, ...],
      "sectionName": "Living Room",
      "sectionKey":  "123",
      "items": [
        {"id": "456", "name": "Ceiling", "hasCondition": true, "hasDescription": true},
        ...
      ]
    }

    Response JSON:
    {
      "transcript": "Ceiling. Good condition, white painted...",
      "filled": {
        "456": {"description": "White painted", "condition": "Good condition"}
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    clips        = data.get('clips', [])
    section_name = data.get('sectionName', 'Room')
    section_type = data.get('sectionType', 'room')   # 'room' | fixed-section types
    items        = data.get('items', [])

    if not clips:
        return jsonify({'error': 'No audio clips provided'}), 400
    if not items:
        return jsonify({'error': 'No items provided'}), 400

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # Transcribe each clip with Whisper, then join
    transcripts = []
    for i, clip in enumerate(clips):
        audio_b64 = clip.get('audio')
        mime_type = clip.get('mimeType', 'audio/m4a')
        if not audio_b64:
            continue
        try:
            audio_bytes = base64.b64decode(audio_b64)
            text = _whisper_transcribe(audio_bytes, mime_type)
            if text:
                transcripts.append(text.strip())
        except Exception as e:
            print(f'[transcribe/room] clip {i} whisper error: {e}')

    full_transcript = ' '.join(transcripts)
    if not full_transcript:
        return jsonify({'error': 'No speech detected in recording'}), 422

    try:
        if section_type == 'room':
            filled = _claude_fill_room(full_transcript, section_name, items)
        else:
            filled = _claude_fill_fixed_section(full_transcript, section_name, section_type, items)
    except Exception as e:
        print(f'[transcribe/room] claude error: {e}')
        return jsonify({'error': f'AI fill error: {str(e)}'}), 500

    return jsonify({
        'transcript': full_transcript,
        'filled':     filled,
    })


@transcribe_bp.route('/full', methods=['POST'])
@jwt_required()
def transcribe_full():
    """
    Full inspection continuous recording — legacy endpoint, kept for backward compatibility.

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

    # Debug: log what we received
    print(f'[transcribe/item] mimeType received: {repr(mime_type)}')
    print(f'[transcribe/item] audio_b64 length: {len(audio_b64)}')

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
