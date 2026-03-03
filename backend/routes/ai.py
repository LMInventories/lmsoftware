"""
backend/routes/ai.py

Secure server-side proxy for:
  POST /api/ai/claude   — forward a messages payload to Anthropic Claude
  POST /api/ai/transcribe — transcribe audio via OpenAI Whisper

Why this exists:
  Calling the Anthropic API directly from the browser now fails due to
  CORS restrictions and the requirement to keep the API key server-side.
  All Claude calls (PDF import, dictation transcription) must go through
  this proxy instead.

Required environment variables on Render:
  ANTHROPIC_API_KEY   — your sk-ant-... key
  OPENAI_API_KEY      — your OpenAI key (for Whisper transcription)
"""

import os
import requests
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required

ai_bp = Blueprint('ai', __name__)

ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'
OPENAI_TRANSCRIBE_URL = 'https://api.openai.com/v1/audio/transcriptions'


# ──────────────────────────────────────────────────────────────────────────────
#  Claude proxy
#  Accepts the same JSON body that you would send to Anthropic directly.
#  The frontend just hits /api/ai/claude instead of api.anthropic.com.
# ──────────────────────────────────────────────────────────────────────────────
@ai_bp.route('/claude', methods=['POST'])
@jwt_required()
def claude_proxy():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 500

    payload = request.get_json(force=True)
    if not payload:
        return jsonify({'error': 'No JSON payload received'}), 400

    # Force the model to our approved Sonnet version if not specified
    if 'model' not in payload:
        payload['model'] = 'claude-sonnet-4-6'
    if 'max_tokens' not in payload:
        payload['max_tokens'] = 8000

    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json=payload,
            timeout=120,  # PDF analysis can take a while
        )
        # Stream the response back with the same status code
        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get('content-type', 'application/json'),
        )
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Claude API timed out'}), 504
    except Exception as e:
        return jsonify({'error': f'Claude proxy error: {str(e)}'}), 500


# ──────────────────────────────────────────────────────────────────────────────
#  Whisper transcription proxy
#  Accepts multipart/form-data with:
#    file   — audio blob (webm/mp4/m4a/wav)
#    prompt — optional context string
# ──────────────────────────────────────────────────────────────────────────────
@ai_bp.route('/transcribe', methods=['POST'])
@jwt_required()
def transcribe_audio():
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 500

    if 'file' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['file']
    prompt = request.form.get('prompt', 'UK property inspection report. Condition notes for items such as walls, floors, ceilings, doors, windows.')

    try:
        resp = requests.post(
            OPENAI_TRANSCRIBE_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (audio_file.filename or 'audio.webm', audio_file.stream, audio_file.content_type or 'audio/webm')},
            data={
                'model': 'whisper-1',
                'language': 'en',
                'prompt': prompt,
            },
            timeout=60,
        )
        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get('content-type', 'application/json'),
        )
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Transcription timed out'}), 504
    except Exception as e:
        return jsonify({'error': f'Transcription proxy error: {str(e)}'}), 500


# ──────────────────────────────────────────────────────────────────────────────
#  Health check — lets you verify the keys are present without calling them
# ──────────────────────────────────────────────────────────────────────────────
@ai_bp.route('/status', methods=['GET'])
@jwt_required()
def ai_status():
    return jsonify({
        'anthropic_key_set': bool(os.environ.get('ANTHROPIC_API_KEY')),
        'openai_key_set':    bool(os.environ.get('OPENAI_API_KEY')),
    })
