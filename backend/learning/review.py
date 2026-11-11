"""
backend/learning/review.py
────────────────────────────
The "authorise" step for the learning agent. The reminder email contains a
signed, expiring link to a small server-rendered page where each pending
glossary suggestion can be approved, approved-with-auto-replace, or rejected,
and live entries can be switched off. No login or frontend build needed — the
signed token is the credential, and every change is a POST.

    GET  /api/learning/review?t=<token>   -> the page
    POST /api/learning/review             -> apply decisions, redirect back

Approved entries are live in the transcription prompts within ~2 minutes
(routes.transcribe caches the glossary for _GLOSSARY_TTL seconds; this module
also clears the cache of the worker that handled the click).
"""

import html
import json
import os
from datetime import datetime

from flask import Blueprint, abort, redirect, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import text

from models import db

learning_review_bp = Blueprint('learning_review', __name__)

_TOKEN_SALT = 'learning-review-v1'
TOKEN_MAX_AGE = 14 * 24 * 3600


def _serializer():
    return URLSafeTimedSerializer(os.environ.get('JWT_SECRET_KEY', 'change-me-in-production'), salt=_TOKEN_SALT)


def make_review_link() -> str:
    backend = os.environ.get('BACKEND_URL', 'https://app.lminventories.co.uk').strip().rstrip('/')
    return f'{backend}/api/learning/review?t={_serializer().dumps({"scope": "review"})}'


def _check_token(token: str):
    try:
        data = _serializer().loads(token or '', max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        abort(410, 'This review link has expired — a fresh one is in the next reminder email.')
    except BadSignature:
        abort(403)
    if data.get('scope') != 'review':
        abort(403)


def _e(value) -> str:
    return html.escape(str(value if value is not None else ''))


def _age_days(ts) -> int:
    if not ts:
        return 0
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return 0
    return max((datetime.now(ts.tzinfo) - ts).days, 0)


def _page(token: str, message: str = '') -> str:
    pending = db.session.execute(text(
        "SELECT * FROM transcription_glossary WHERE status = 'pending' ORDER BY occurrences DESC, id"
    )).fetchall()
    active = db.session.execute(text(
        "SELECT * FROM transcription_glossary WHERE status = 'active' ORDER BY occurrences DESC, id"
    )).fetchall()

    rows = []
    for r in pending:
        try:
            examples = json.loads(r.example_json or '[]')
        except ValueError:
            examples = []
        ex = ''.join(
            f'<div class="ex">AI: {_e(x.get("ai"))}<br>Clerk: {_e(x.get("final"))}</div>' for x in examples[:2]
        )
        age = _age_days(r.created_at)
        rows.append(f'''
        <tr>
          <td><b>{_e(r.heard)}</b> &rarr; <b>{_e(r.correct)}</b><br>
              <span class="meta">{_e(r.kind)} &middot; {r.occurrences} edits, {r.inspections} inspections, {r.inspectors} clerks
              &middot; suggested {age} day{"s" if age != 1 else ""} ago{" &middot; <b>still awaiting a decision</b>" if age >= 3 else ""}</span>
              <div class="why">{_e(r.rationale)}</div>{ex}</td>
          <td class="choices">
            <label><input type="radio" name="d_{r.id}" value="approve"> Approve (hint)</label>
            <label><input type="radio" name="d_{r.id}" value="approve_replace"> Approve + auto-replace{" (agent recommends)" if r.auto_replace else ""}</label>
            <label><input type="radio" name="d_{r.id}" value="reject"> Reject</label>
            <label><input type="radio" name="d_{r.id}" value="skip" checked> Decide later</label>
          </td>
        </tr>''')
    pending_html = (
        f'<table>{"".join(rows)}</table>' if rows else '<p class="muted">Nothing waiting for approval.</p>'
    )

    active_html = ''.join(
        f'<li><label><input type="checkbox" name="rm_{r.id}" value="1"> '
        f'<b>{_e(r.heard)}</b> &rarr; <b>{_e(r.correct)}</b>'
        f'{" <span class=meta>(auto-replace)</span>" if r.auto_replace else ""}</label></li>'
        for r in active
    ) or '<li class="muted">No live entries yet.</li>'

    prs_html = ''
    try:
        from learning.notify import open_learning_prs
        prs = open_learning_prs()
        if prs:
            prs_html = '<h2>Open prompt-fix pull requests</h2><ul>' + ''.join(
                f'<li><a href="{_e(p["url"])}">{_e(p["title"])}</a> <span class="meta">open {p["age_days"]} days</span></li>'
                for p in prs
            ) + '</ul>'
    except Exception:
        pass

    struct_html = ''
    try:
        from learning.structure_report import build_report, has_findings
        rep = build_report(90)
        if has_findings(rep):
            def tbl(title, items, cols):
                if not items:
                    return ''
                head = ''.join(f'<th>{c[1]}</th>' for c in cols)
                body = ''.join('<tr>' + ''.join(f'<td>{_e(i.get(c[0]))}</td>' for c in cols) + '</tr>' for i in items)
                return f'<h3>{title}</h3><table class="grid"><tr>{head}</tr>{body}</table>'
            struct_html = (
                '<h2>Structural corrections (information only)</h2>'
                + tbl('Items the AI filled that clerks deleted', rep['deleted_items'],
                      [('item_name', 'Item'), ('section_type', 'Section'), ('n', 'Times'), ('inspections', 'Inspections')])
                + tbl('Sub-items the AI invented that clerks removed', rep['ai_subs_clerk_removed'],
                      [('sub_name', 'Sub-item'), ('item_name', 'On item'), ('n', 'Times'), ('inspections', 'Inspections')])
                + tbl('Sub-items clerks added that the AI missed', rep['clerk_added_subs'],
                      [('sub_name', 'Sub-item'), ('item_name', 'On item'), ('n', 'Times'), ('said_sub_item', 'Dictation said "sub item"')])
            )
    except Exception:
        pass

    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Learning review</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#1e293b}}
 table{{width:100%;border-collapse:collapse}} td,th{{padding:10px 8px;border-bottom:1px solid #e2e8f0;vertical-align:top;text-align:left}}
 .choices label{{display:block;font-size:14px;margin:2px 0}} .meta,.muted{{color:#64748b;font-size:13px}}
 .why{{margin-top:6px;font-size:14px}} .ex{{font-size:12px;color:#475569;background:#f8fafc;padding:4px 6px;margin-top:4px}}
 button{{background:#1d4ed8;color:#fff;border:0;padding:10px 18px;border-radius:6px;font-size:15px;cursor:pointer}}
 .msg{{background:#dcfce7;padding:10px;border-radius:6px}} .grid td,.grid th{{font-size:13px}}
</style></head><body>
<h1>Transcription learning &mdash; review</h1>
{f'<p class="msg">{_e(message)}</p>' if message else ''}
<p class="muted">Approved glossary entries are added to every AI transcription prompt within about two minutes. &ldquo;Auto-replace&rdquo;
also rewrites the heard word in the raw transcript before the AI sees it &mdash; use it only for mis-hearings that are never a real word.</p>
<form method="post" action="/api/learning/review">
<input type="hidden" name="t" value="{_e(token)}">
<h2>Waiting for approval ({len(pending)})</h2>{pending_html}
<h2>Live glossary ({len(active)})</h2><p class="muted">Tick to switch an entry off.</p><ul>{active_html}</ul>
<p><button type="submit">Save decisions</button></p>
</form>
{prs_html}{struct_html}
</body></html>'''


@learning_review_bp.route('/review', methods=['GET'])
def review_page():
    token = request.args.get('t', '')
    _check_token(token)
    return _page(token, request.args.get('done', ''))


@learning_review_bp.route('/review', methods=['POST'])
def review_apply():
    token = request.form.get('t', '')
    _check_token(token)

    approved = rejected = removed = 0
    for key, value in request.form.items():
        if key.startswith('d_') and key[2:].isdigit():
            gid = int(key[2:])
            if value in ('approve', 'approve_replace'):
                db.session.execute(text(
                    "UPDATE transcription_glossary SET status='active', auto_replace=:ar, decided_at=now() "
                    "WHERE id=:id AND status='pending'"), {'ar': value == 'approve_replace', 'id': gid})
                approved += 1
            elif value == 'reject':
                db.session.execute(text(
                    "UPDATE transcription_glossary SET status='rejected', decided_at=now() "
                    "WHERE id=:id AND status='pending'"), {'id': gid})
                rejected += 1
        elif key.startswith('rm_') and key[3:].isdigit() and value == '1':
            db.session.execute(text(
                "UPDATE transcription_glossary SET status='rejected', decided_at=now() "
                "WHERE id=:id AND status='active'"), {'id': int(key[3:])})
            removed += 1
    db.session.commit()

    try:
        from routes.transcribe import invalidate_glossary_cache
        invalidate_glossary_cache()
    except Exception:
        pass

    msg = f'Saved: {approved} approved, {rejected} rejected, {removed} switched off.'
    from urllib.parse import quote
    return redirect(f'/api/learning/review?t={quote(token)}&done={quote(msg)}', code=303)
