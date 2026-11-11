"""
backend/learning/notify.py
────────────────────────────
The reminder half of the learning agent. After each scheduled run, if anything is
waiting on a human — pending glossary suggestions, or open prompt-fix pull
requests — email the admin one digest with a signed link to the review page
(learning/review.py). Items that were already pending on an earlier run are
flagged "still awaiting", which is the nudge to authorise previous suggestions.

Respects LEARNING_PIPELINE_DRY_RUN like the PR step: in dry-run it only prints
what it would send.
"""

import os
import sys
from datetime import datetime, timezone

import requests
from sqlalchemy import text

from learning._db import get_engine

GH_API = 'https://api.github.com/repos/LMInventories/lmsoftware'


def _dry_run() -> bool:
    return os.environ.get('LEARNING_PIPELINE_DRY_RUN', 'true').strip().lower() != 'false'


def open_learning_prs() -> list:
    """Open pull requests opened by the prompt-learning pipeline. [] when
    GH_TOKEN is missing or GitHub is unreachable."""
    token = os.environ.get('GH_TOKEN')
    if not token:
        return []
    try:
        resp = requests.get(f'{GH_API}/pulls', params={'state': 'open', 'per_page': 50}, timeout=20,
                            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'})
        if resp.status_code != 200:
            return []
        out = []
        for pr in resp.json():
            if not str(pr.get('head', {}).get('ref', '')).startswith('prompt-learning/'):
                continue
            created = datetime.fromisoformat(pr['created_at'].replace('Z', '+00:00'))
            out.append({'title': pr['title'], 'url': pr['html_url'],
                        'age_days': (datetime.now(timezone.utc) - created).days})
        return out
    except Exception:
        return []


def _pending_glossary() -> list:
    with get_engine().connect() as conn:
        return conn.execute(text('''
            SELECT id, heard, correct, kind, occurrences, inspections,
                   GREATEST(0, EXTRACT(DAY FROM now() - created_at))::int AS age_days
            FROM transcription_glossary WHERE status = 'pending' ORDER BY occurrences DESC, id
        ''')).fetchall()


def _esc(s) -> str:
    import html
    return html.escape(str(s))


def build_digest(pending, prs, suggestions, structure) -> tuple:
    """-> (subject, html_body, plain_summary)"""
    stale = [p for p in pending if p.age_days >= 3]
    new = [p for p in pending if p.age_days < 3]

    parts = []
    if stale:
        parts.append(
            f'<p><b>Reminder:</b> {len(stale)} suggestion{"s" if len(stale) != 1 else ""} from earlier runs '
            f'{"are" if len(stale) != 1 else "is"} still waiting for you to authorise or reject.</p>'
        )

    def glossary_list(items, heading):
        if not items:
            return ''
        lis = ''.join(
            f'<li><b>{_esc(p.heard)}</b> &rarr; <b>{_esc(p.correct)}</b> '
            f'<span style="color:#64748b">({_esc(p.kind)}, {p.occurrences} edits in {p.inspections} inspections'
            f'{f", suggested {p.age_days} days ago" if p.age_days >= 1 else ""})</span></li>'
            for p in items
        )
        return f'<p style="margin-bottom:4px"><b>{heading}</b></p><ul style="margin-top:0">{lis}</ul>'

    parts.append(glossary_list(stale, 'Still awaiting a decision'))
    parts.append(glossary_list(new, 'New glossary suggestions'))

    if prs:
        lis = ''.join(f'<li><a href="{_esc(p["url"])}">{_esc(p["title"])}</a> (open {p["age_days"]} days)</li>' for p in prs)
        parts.append(f'<p style="margin-bottom:4px"><b>Prompt-fix pull requests awaiting review</b></p><ul style="margin-top:0">{lis}</ul>')

    if suggestions:
        lis = ''.join(f'<li>{_esc(s)}</li>' for s in suggestions)
        parts.append(f'<p style="margin-bottom:4px"><b>Structural patterns the agent noticed</b> (advice only, nothing applied)</p>'
                     f'<ul style="margin-top:0">{lis}</ul>')
    elif structure and structure.get('totals'):
        t = structure['totals']
        parts.append(f'<p style="color:#64748b">Structural corrections in the last {structure["window_days"]} days: '
                     f'{t.get("item_fields_deleted", 0)} deleted item fields, {t.get("sub_fields_deleted", 0)} removed sub-item fields, '
                     f'{t.get("sub_fields_added", 0)} clerk-added sub-item fields.</p>')

    from learning.review import make_review_link
    link = make_review_link()
    parts.append(f'<p><a href="{_esc(link)}" style="background:#1d4ed8;color:#fff;padding:10px 18px;'
                 f'border-radius:6px;text-decoration:none;display:inline-block">Review &amp; authorise</a></p>'
                 f'<p style="color:#64748b;font-size:12px">The link works for 14 days. Approved glossary entries go live within a couple of minutes.</p>')

    n_items = len(pending) + len(prs)
    subject = f'Transcription learning: {n_items} item{"s" if n_items != 1 else ""} awaiting your authorisation'
    plain = f'{len(pending)} pending glossary suggestions ({len(stale)} stale), {len(prs)} open PRs'
    return subject, ''.join(parts), plain


def send_review_reminder(suggestions=None, structure=None, force_live: bool = False) -> dict:
    pending = _pending_glossary()
    prs = open_learning_prs()
    if not pending and not prs:
        return {'status': 'nothing_pending'}

    subject, body, plain = build_digest(pending, prs, suggestions or [], structure)
    if _dry_run() and not force_live:
        print(f'[learning] DRY RUN — would email reminder: {subject} ({plain})')
        return {'status': 'dry_run', 'summary': plain}

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from routes.email_service import ADMIN_NOTIFY_EMAIL, SMTP_FROM, _send, _wrap
    ok, err = _send(SMTP_FROM, ADMIN_NOTIFY_EMAIL, subject, _wrap(body, subject))
    return {'status': 'sent' if ok else 'send_failed', 'error': err, 'summary': plain}
