"""
set_telegram_webhook.py
─────────────────────────
One-off script that registers the deployed backend URL with Telegram as the
bot's webhook target. NOT run automatically by start.sh — run manually after
first deploy with TELEGRAM_BOT_TOKEN/TELEGRAM_WEBHOOK_SECRET/BACKEND_URL set,
and again any time BACKEND_URL or the secret is rotated.

Usage:
    python set_telegram_webhook.py
"""

import os
import requests

token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
backend_url = os.environ.get('BACKEND_URL', '').rstrip('/')

if not token:
    print('ERROR: TELEGRAM_BOT_TOKEN env var not set')
    exit(1)
if not secret:
    print('ERROR: TELEGRAM_WEBHOOK_SECRET env var not set')
    exit(1)
if not backend_url:
    print('ERROR: BACKEND_URL env var not set')
    exit(1)

webhook_url = f'{backend_url}/api/telegram/webhook/{secret}'

resp = requests.post(
    f'https://api.telegram.org/bot{token}/setWebhook',
    json={
        'url': webhook_url,
        'secret_token': secret,
        'allowed_updates': ['message', 'callback_query'],
    },
    timeout=15,
)

print(resp.status_code, resp.json())
