"""
AI action tags for check-out reports.

At the end of a check-out room the clerk taps "Suggest actions". Every new check-out condition
line that has no action yet gets a suggested (action, responsibility) pair, which the clerk
accepts, edits or declines line by line - same interaction as AI Proofread. Nothing is saved
to the report until a clerk accepts it.

Suggestions come from three layers, cheapest and most trustworthy first:
  1. rule     - a tiny table of patterns the clerks' own history showed are near-unanimous
  2. learned  - the same line text (normalised) was confirmed the same way >= 2 times, and
                clerks have not mostly declined it (ActionTagDecision memory)
  3. ai       - Claude, shown the closest previous clerk decisions as examples; told to answer
                "Investigate" when unsure rather than guess a liability

Endpoints (registered at /api/action-tags):
  POST /suggest    {inspectionId, roomName, items:[{id, name, lines:[...], checkIn}]}
  POST /decisions  {inspectionId, decisions:[{...}]}   - feeds the learned layer
"""
import json
import os
import re

import anthropic
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import ActionTagDecision, TranscriptionUsage, db

action_tags_bp = Blueprint('action_tags', __name__)

_MODEL = 'claude-sonnet-4-6'
_MAX_LINES_PER_CALL = 120
_MEMORY_MIN_DECISIONS = 2        # confirmed the same way at least this often...
_MEMORY_MIN_SHARE = 0.8          # ...with at least this share agreeing
_EXAMPLE_POOL = 1500             # most recent confirmed decisions searched for few-shot examples
_EXAMPLES_PER_LINE = 3
_EXAMPLES_MAX = 15

# (pattern, action name, responsibility, reason). Names are resolved against the live catalogue,
# which managers can edit; a rule whose action/responsibility no longer exists is silently skipped.
# Only patterns the history mine (34 check-outs, Nov 2026) showed clerks tag almost uniformly.
_RULES = [
    (re.compile(r'^\s*not seen\b', re.I), 'Missing Item', 'Tenant', 'Not seen at check-out'),
    (re.compile(r'\bunable to test\b|\bno power\b', re.I), 'Maintenance Required', 'Investigate',
     'Could not be tested'),
]


def normalise(line: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', (line or '').lower())).strip()[:300]


def _tokens(norm: str) -> set:
    return {t for t in norm.split() if len(t) > 2}


def _catalogue():
    from routes.actions import _load_config
    cfg = _load_config()
    actions = [a for a in cfg.get('actions', []) if a.get('id') and a.get('name')]
    return actions, [r for r in cfg.get('responsibilities', []) if isinstance(r, str) and r]


def _find_name(options, wanted, key=None):
    wanted = wanted.strip().lower()
    for o in options:
        label = o[key] if key else o
        if label.strip().lower() == wanted:
            return o
    return None


def _rule_match(line, actions, resps):
    for pattern, action_name, resp_name, reason in _RULES:
        if pattern.search(line):
            act = _find_name(actions, action_name, 'name')
            resp = _find_name(resps, resp_name)
            if act and resp:
                return {'actionId': act['id'], 'responsibility': resp, 'confidence': 'high',
                        'source': 'rule', 'reason': reason}
    return None


def _additional_item_match(actions, resps):
    """Additional Items (added to the property during tenancy) are ALWAYS Additional Item / Tenant."""
    act = _find_name(actions, 'Additional Item', 'name')
    resp = _find_name(resps, 'Tenant')
    if act and resp:
        return {'actionId': act['id'], 'responsibility': resp, 'confidence': 'high',
                'source': 'rule', 'reason': 'Additional items are always Tenant'}
    return None


def _learned_match(norm, rows, actions, resps):
    """rows: ActionTagDecision rows with this exact normalised line."""
    confirmed = [r for r in rows if r.decision in ('accepted', 'edited') and r.final_action_id]
    declined = [r for r in rows if r.decision == 'declined']
    if len(confirmed) < _MEMORY_MIN_DECISIONS or len(declined) * 2 > len(confirmed):
        return None
    tally = {}
    for r in confirmed:
        tally[(r.final_action_id, r.final_resp)] = tally.get((r.final_action_id, r.final_resp), 0) + 1
    (action_id, resp), n = max(tally.items(), key=lambda kv: kv[1])
    if n / len(confirmed) < _MEMORY_MIN_SHARE:
        return None
    if not any(a['id'] == action_id for a in actions) or resp not in resps:
        return None   # catalogue changed since - don't resurrect a deleted tag
    return {'actionId': action_id, 'responsibility': resp, 'confidence': 'high', 'source': 'learned',
            'reason': f'Tagged this way {n} time{"s" if n != 1 else ""} before'}


def _examples_for(lines_norm, actions):
    """Closest previous confirmed decisions (token overlap) to show the model."""
    pool = (ActionTagDecision.query
            .filter(ActionTagDecision.final_action_id.isnot(None),
                    ActionTagDecision.decision.in_(('accepted', 'edited')))
            .order_by(ActionTagDecision.id.desc()).limit(_EXAMPLE_POOL).all())
    names = {a['id']: a['name'] for a in actions}
    seen, out = set(), []
    pool_tokens = [(r, _tokens(r.line_norm)) for r in pool if r.final_action_id in names]
    for norm in lines_norm:
        toks = _tokens(norm)
        if not toks:
            continue
        scored = []
        for r, rt in pool_tokens:
            if not rt:
                continue
            score = len(toks & rt) / len(toks | rt)
            if score >= 0.3:
                scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        for _, r in scored[:_EXAMPLES_PER_LINE]:
            key = (r.line_norm, r.final_action_id, r.final_resp)
            if key in seen:
                continue
            seen.add(key)
            out.append(f'- {json.dumps(r.line)} -> {names[r.final_action_id]} / {r.final_resp}')
            if len(out) >= _EXAMPLES_MAX:
                return out
    return out


def _build_prompt(room_name, items, actions, resps, examples):
    lines = []
    for it in items:
        lines.append(f'ITEM id={json.dumps(it["id"])} name={json.dumps(it["name"])}')
        if it.get('checkIn'):
            lines.append(f'  check-in text (context only, may already mention the same thing): {json.dumps(it["checkIn"])}')
        for ln in it['lines']:
            lines.append(f'  LINE {json.dumps(ln)}')
    ex = ('\nPREVIOUS DECISIONS BY THIS COMPANY\'S CLERKS (follow these when a line is similar):\n'
          + '\n'.join(examples) + '\n') if examples else ''
    return f"""You are helping a clerk finish a UK property CHECK-OUT report. Each LINE below is a new
condition finding recorded at check-out. For each line choose the ACTION and who is RESPONSIBLE, from
these fixed lists only.

ACTIONS: {json.dumps([a['name'] for a in actions])}
RESPONSIBLE: {json.dumps(resps)}

ROOM: {json.dumps(room_name)}

{chr(10).join(lines)}
{ex}
GUIDANCE:
- "Review" is the default action. Use a more specific action only when the line clearly calls for it.
- Be honest about uncertainty. A wrong liability can cost someone money. If a line could be damage,
  wear and tear or pre-existing, or you cannot tell who is responsible, answer "Investigate" with
  confidence "low". Never guess a liability to be helpful.
- A clerk will accept, edit or decline every suggestion, so give your best honest call, not a safe average.
- "reason" is a few words a clerk can read at a glance.
- Return one entry per LINE, copying the line text EXACTLY.

Return ONLY JSON, no markdown:
{{"tags": [{{"itemId": "...", "line": "...", "action": "Review", "responsibility": "Tenant", "confidence": "high", "reason": "Marks beyond wear"}}]}}"""


def _validate_ai_tags(raw_tags, items, actions, resps):
    """Keep only tags for real lines, with action/responsibility that exist in the catalogue."""
    lines_by_item = {it['id']: set(it['lines']) for it in items}
    out, seen = {}, set()
    if not isinstance(raw_tags, list):
        return out
    for t in raw_tags:
        if not isinstance(t, dict):
            continue
        item_id, line = str(t.get('itemId') or ''), t.get('line')
        if not isinstance(line, str) or line not in lines_by_item.get(item_id, ()):
            continue
        if (item_id, line) in seen:
            continue
        act = _find_name(actions, str(t.get('action') or ''), 'name')
        resp = _find_name(resps, str(t.get('responsibility') or ''))
        if not act or not resp:
            continue
        seen.add((item_id, line))
        conf = 'low' if str(t.get('confidence')).lower() == 'low' else 'high'
        out[(item_id, line)] = {'actionId': act['id'], 'responsibility': resp, 'confidence': conf,
                                'source': 'ai', 'reason': str(t.get('reason') or '')[:120]}
    return out


def _clean_items(raw_items):
    items, total = [], 0
    for it in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(it, dict) or not it.get('id'):
            continue
        lines = []
        for ln in it.get('lines') or []:
            if isinstance(ln, str) and ln.strip() and ln not in lines and total < _MAX_LINES_PER_CALL:
                lines.append(ln[:500])
                total += 1
        if lines:
            items.append({'id': str(it['id']), 'name': str(it.get('name') or '')[:200], 'lines': lines,
                          'checkIn': str(it.get('checkIn') or '')[:600],
                          'additional': it.get('kind') == 'additional'})
    return items


@action_tags_bp.route('/suggest', methods=['POST'])
@jwt_required()
def suggest():
    data = request.get_json() or {}
    items = _clean_items(data.get('items'))
    room_name = str(data.get('roomName') or '')[:100]
    inspection_id = int(data['inspectionId']) if data.get('inspectionId') else None
    if not items:
        return jsonify({'suggestions': []})

    actions, resps = _catalogue()
    if not actions or not resps:
        return jsonify({'suggestions': [], 'error': 'No actions configured'}), 200

    all_norms = {normalise(ln) for it in items for ln in it['lines']}
    memory = {}
    for r in ActionTagDecision.query.filter(ActionTagDecision.line_norm.in_(all_norms)).all():
        memory.setdefault(r.line_norm, []).append(r)

    resolved, pending = {}, []
    for it in items:
        for ln in it['lines']:
            hit = (_additional_item_match(actions, resps) if it['additional'] else None) \
                or _rule_match(ln, actions, resps) or _learned_match(normalise(ln), memory.get(normalise(ln), []), actions, resps)
            if hit:
                resolved[(it['id'], ln)] = hit
            else:
                pending.append((it, ln))

    if pending:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            if not resolved:
                return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503
        else:
            sub_items = {}
            for it, ln in pending:
                sub_items.setdefault(it['id'], dict(it, lines=[]))['lines'].append(ln)
            ai_items = list(sub_items.values())
            prompt = _build_prompt(room_name, ai_items, actions, resps,
                                   _examples_for([normalise(ln) for _, ln in pending], actions))
            try:
                client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
                message = client.messages.create(
                    model=_MODEL, max_tokens=4000,
                    messages=[{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': '{'}],
                )
            except Exception as e:
                print(f'[action-tags] Claude call failed: {e!r}')
                if not resolved:
                    return jsonify({'error': 'AI suggestions are unavailable right now — please try again'}), 502
                message = None
            if message is not None:
                from routes.transcribe import _sanitise_json
                raw = ('{' + message.content[0].text).strip().replace('```json', '').replace('```', '').strip()
                try:
                    parsed = json.loads(_sanitise_json(raw))
                    resolved.update(_validate_ai_tags(parsed.get('tags') if isinstance(parsed, dict) else None,
                                                      ai_items, actions, resps))
                except json.JSONDecodeError:
                    print(f'[action-tags] JSON parse error: {raw[:300]}')
                    if not resolved:
                        return jsonify({'error': 'AI returned an invalid response — please try again'}), 500
                try:
                    db.session.add(TranscriptionUsage(
                        call_type='item', inspection_id=inspection_id, user_id=int(get_jwt_identity()),
                        audio_seconds=0,
                        input_tokens=message.usage.input_tokens if message.usage else 0,
                        output_tokens=message.usage.output_tokens if message.usage else 0,
                        section_type='action_tags',
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    out = []
    for it in items:
        for i, ln in enumerate(it['lines']):
            tag = resolved.get((it['id'], ln))
            if tag:
                out.append({'id': f'{it["id"]}:{i}', 'itemId': it['id'], 'itemName': it['name'], 'line': ln, **tag})
    return jsonify({'suggestions': out})


@action_tags_bp.route('/decisions', methods=['POST'])
@jwt_required()
def decisions():
    """Record accepted / edited / declined suggestions. 'accepted' with different final tags is stored as 'edited'."""
    data = request.get_json() or {}
    inspection_id = int(data['inspectionId']) if data.get('inspectionId') else None
    user_id = int(get_jwt_identity())
    actions, resps = _catalogue()
    action_ids = {a['id'] for a in actions}
    saved = 0
    for d in (data.get('decisions') or [])[:300]:
        if not isinstance(d, dict) or d.get('decision') not in ('accepted', 'edited', 'declined'):
            continue
        line = d.get('line')
        if not isinstance(line, str) or not line.strip():
            continue
        sug_action, sug_resp = d.get('suggestedActionId'), d.get('suggestedResp')
        fin_action, fin_resp = d.get('finalActionId'), d.get('finalResp')
        decision = d['decision']
        if decision == 'declined':
            fin_action = fin_resp = None
        else:
            if fin_action not in action_ids or fin_resp not in resps:
                continue
            if (fin_action, fin_resp) != (sug_action, sug_resp):
                decision = 'edited'
        db.session.add(ActionTagDecision(
            inspection_id=inspection_id, user_id=user_id,
            room=str(d.get('room') or '')[:255] or None,
            item_name=str(d.get('itemName') or '')[:255] or None,
            line=line[:1000], line_norm=normalise(line),
            suggested_action_id=str(sug_action)[:64] if sug_action else None,
            suggested_resp=str(sug_resp)[:100] if sug_resp else None,
            final_action_id=str(fin_action)[:64] if fin_action else None,
            final_resp=str(fin_resp)[:100] if fin_resp else None,
            decision=decision,
            source=d.get('source') if d.get('source') in ('rule', 'learned', 'ai', 'history') else 'ai',
        ))
        saved += 1
    db.session.commit()
    return jsonify({'saved': saved})
