"""
backend/learning/glossary_mining.py
─────────────────────────────────────
The glossary agent. Reads the clerk-edit diffs written by learning/mining.py,
finds word/phrase SUBSTITUTIONS that clerks keep making (AI wrote "chub", the
finished report says "chubb"), asks Sonnet to judge which are genuine
vocabulary corrections (brands, spellings, trade terms) as opposed to
property-specific content edits or formatting rules, and queues the good ones in
transcription_glossary as status='pending'.

Nothing here changes live behaviour. A pending entry only starts being injected
into the transcription prompts after a human approves it on the review page
(learning/review.py) — the reminder email links there.

Thresholds are deliberately lower than the prompt-PR pipeline's (3 rows across
2 inspections, no minimum inspector count): a glossary entry is a one-line,
instantly reversible vocabulary hint, and a human approves each one.

Usage (run from backend/):
    python -m learning.glossary_mining                # mine, judge, queue pending entries
    python -m learning.glossary_mining --no-judge     # just print the candidate clusters
    python -m learning.glossary_mining --window-days 180
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from learning._db import get_engine
from learning.proposal import _extract_ops, _normalize

MIN_ROWS = 3
MIN_INSPECTIONS = 2
MAX_PHRASE_WORDS = 3
MAX_JUDGED_PER_RUN = 25
_MODEL = 'claude-sonnet-4-6'


def _load_rows(engine, window_days: int):
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    query = text('''
        SELECT d.id, d.inspection_id, d.field, d.transcript_excerpt, d.ai_value, d.final_value,
               d.item_name, i.inspector_id
        FROM transcription_fill_diffs d
        JOIN inspections i ON i.id = d.inspection_id
        WHERE d.edit_type = 'edited' AND d.match_confidence IN ('exact', 'similar')
          AND d.mined_at >= :since
    ''')
    with engine.connect() as conn:
        return conn.execute(query, {'since': since}).fetchall()


def _known_pairs(engine) -> set:
    """Every (heard, correct) already in the glossary in ANY state — a rejected
    pair must never be re-suggested."""
    with engine.connect() as conn:
        rows = conn.execute(text('SELECT heard, correct FROM transcription_glossary')).fetchall()
    return {(_normalize(r.heard), _normalize(r.correct)) for r in rows}


def known_pairs() -> set:
    return _known_pairs(get_engine())


def build_candidates(rows, known: set) -> list:
    """Substitution clusters only (removed AND added both non-empty, short)."""
    clusters = defaultdict(lambda: {'rows': [], 'inspections': set(), 'inspectors': set()})
    for r in rows:
        for removed, added in _extract_ops(r.ai_value, r.final_value):
            if not removed or not added:
                continue            # pure insertion/deletion = content or formatting, not vocabulary
            if len(removed.split()) > MAX_PHRASE_WORDS or len(added.split()) > MAX_PHRASE_WORDS:
                continue
            if (removed, added) in known:
                continue
            c = clusters[(removed, added)]
            c['rows'].append(r)
            c['inspections'].add(r.inspection_id)
            if r.inspector_id is not None:
                c['inspectors'].add(r.inspector_id)
    out = [
        (key, c) for key, c in clusters.items()
        if len(c['rows']) >= MIN_ROWS and len(c['inspections']) >= MIN_INSPECTIONS
    ]
    out.sort(key=lambda kc: len(kc[1]['rows']), reverse=True)
    return out


def _judge(candidates: list) -> list:
    """One Sonnet call over all candidates. Returns accepted dicts
    {heard, correct, kind, auto_replace, rationale, idx}."""
    import anthropic

    blocks = []
    for n, ((removed, added), c) in enumerate(candidates):
        examples = '\n'.join(
            f'    - field={r.field} item={r.item_name!r} AI={str(r.ai_value)[:120]!r} FINAL={str(r.final_value)[:120]!r}'
            for r in c['rows'][:3]
        )
        blocks.append(
            f'[{n}] "{removed}" -> "{added}"  ({len(c["rows"])} edits, {len(c["inspections"])} inspections, '
            f'{len(c["inspectors"])} clerks)\n{examples}'
        )

    prompt = f"""You maintain a vocabulary glossary for an AI that transcribes UK property-inventory
dictation. Each candidate below is a phrase the AI wrote that human clerks repeatedly changed
when proof-reading ("AI wrote X" -> "clerk made it Y").

Classify each candidate:
- "glossary": a consistent vocabulary fix that would be right in ANY inventory — a brand name,
  a UK spelling, a trade/building term, a standard abbreviation. Safe to give the AI as a hint.
- "rule": a formatting/structure convention (capitalisation style, punctuation, prefixes,
  wording style) — NOT vocabulary. Skip it.
- "noise": specific to one property or a matter of taste/rewording, a number/colour/size/date
  change, or a change in the opposite direction that makes no general sense. Skip it.

For "glossary" give the properly cased correct form in "correct" and the lowercase form the AI
produced in "heard". Set "auto_replace" true ONLY if "heard" is clearly a non-word or
mis-transcription that could never be legitimate in an inventory (e.g. "chub" for the brand
Chubb is NOT safe, because "chub" could be a real word; "cereal number" for "serial number" is).
When unsure, false.

Candidates:

{chr(10).join(blocks)}

Respond with strict JSON only, no markdown — an array with one object per candidate:
[{{"idx": 0, "verdict": "glossary"|"rule"|"noise", "heard": "...", "correct": "...",
   "kind": "brand"|"spelling"|"term", "auto_replace": false, "rationale": "<one sentence>"}}]"""

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    message = client.messages.create(model=_MODEL, max_tokens=3000,
                                     messages=[{'role': 'user', 'content': prompt}])
    raw = message.content[0].text.strip().replace('```json', '').replace('```', '').strip()
    try:
        verdicts = json.loads(raw)
    except json.JSONDecodeError:
        print(f'[glossary] judge response was not valid JSON: {raw[:300]!r}')
        return []

    accepted = []
    for v in verdicts if isinstance(verdicts, list) else []:
        if not isinstance(v, dict) or v.get('verdict') != 'glossary':
            continue
        idx = v.get('idx')
        heard, correct = str(v.get('heard') or '').strip(), str(v.get('correct') or '').strip()
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)) or not heard or not correct:
            continue
        if _normalize(heard) == _normalize(correct):
            continue
        accepted.append({
            'idx': idx, 'heard': heard[:200].lower(), 'correct': correct[:200],
            'kind': v.get('kind') if v.get('kind') in ('brand', 'spelling', 'term') else 'term',
            'auto_replace': bool(v.get('auto_replace')),
            'rationale': str(v.get('rationale') or '')[:500],
        })
    return accepted


def run_glossary_agent(window_days: int = 90, judge: bool = True) -> dict:
    engine = get_engine()
    rows = _load_rows(engine, window_days)
    candidates = build_candidates(rows, _known_pairs(engine))
    stats = {'rows': len(rows), 'candidates': len(candidates), 'queued': 0}
    if not candidates or not judge:
        stats['candidate_preview'] = [
            (k, len(c['rows']), len(c['inspections'])) for k, c in candidates[:15]
        ]
        return stats

    batch = candidates[:MAX_JUDGED_PER_RUN]
    accepted = _judge(batch)
    with engine.connect() as conn:
        for a in accepted:
            _key, c = batch[a['idx']]
            examples = [
                {'ai': str(r.ai_value)[:160], 'final': str(r.final_value)[:160], 'field': r.field}
                for r in c['rows'][:3]
            ]
            res = conn.execute(text('''
                INSERT INTO transcription_glossary
                    (heard, correct, kind, auto_replace, status, source, occurrences, inspections,
                     inspectors, rationale, example_json, created_at)
                VALUES (:heard, :correct, :kind, :auto, 'pending', 'agent', :occ, :insp, :clerks,
                        :why, :examples, now())
                ON CONFLICT (heard, correct) DO NOTHING
            '''), {
                'heard': a['heard'], 'correct': a['correct'], 'kind': a['kind'], 'auto': a['auto_replace'],
                'occ': len(c['rows']), 'insp': len(c['inspections']), 'clerks': len(c['inspectors']),
                'why': a['rationale'], 'examples': json.dumps(examples),
            })
            stats['queued'] += res.rowcount or 0
        conn.commit()
    return stats


def main():
    parser = argparse.ArgumentParser(description='Mine clerk edits for glossary suggestions (queued as pending)')
    parser.add_argument('--window-days', type=int, default=90)
    parser.add_argument('--no-judge', action='store_true', help='Print candidate clusters only; no Sonnet call, no writes')
    args = parser.parse_args()

    stats = run_glossary_agent(window_days=args.window_days, judge=not args.no_judge)
    print(f"{stats['rows']} edited rows -> {stats['candidates']} candidate clusters -> {stats['queued']} queued as pending")
    for key, n, insp in stats.get('candidate_preview', []):
        print(f'  [{n} rows, {insp} inspections] {key[0]!r} -> {key[1]!r}')


if __name__ == '__main__':
    main()
