"""
backend/learning/proposal.py
──────────────────────────────
Phase 3 of the prompt-learning pipeline: mine transcription_fill_diffs
(written by learning/mining.py) for a recurring AI-vs-human correction
pattern (Tier A, cheap/deterministic clustering) and draft a targeted
prompt-text fix for the strongest one via a single Sonnet call (Tier B).

Print-only in this phase — no file edits, no git, no GitHub. Run by hand to
see what the pipeline WOULD propose, and to tune the cluster thresholds
against real accumulated data, before wiring up learning/pr_pipeline.py
(Phase 4, which adds the eval-gate + PR-creation + email flow around this).

A cluster only becomes a candidate once it shows up:
  >= MIN_ROWS times, across >= MIN_INSPECTIONS distinct inspections,
  from >= MIN_INSPECTORS distinct inspectors — the inspector-diversity
  threshold specifically guards against "learning" one clerk's personal
  wording preference instead of a genuine, fixable prompt gap.

Usage (run from backend/):
    python -m learning.proposal
    python -m learning.proposal --window-days 90
    python -m learning.proposal --no-draft          # just show clusters, skip the Sonnet call
"""

import argparse
import difflib
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from learning._db import get_engine

MIN_ROWS = 8
MIN_INSPECTIONS = 3
MIN_INSPECTORS = 2

# Shared prompt-rule constants a proposal is allowed to target (see
# routes/transcribe.py) — preferred over a single fill function's inline
# prose, since a fix here propagates to every fill function that uses it.
_TARGETABLE_SYMBOLS = [
    '_UK_SPELLING_RULE', '_APPLIANCE_FORMATTING_RULE',
    '_CONDITION_WORDS', '_DESCRIPTION_VOCABULARY',
]

_TRANSCRIBE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'routes', 'transcribe.py'
)


@dataclass
class ProposalDraft:
    has_pattern: bool
    target_symbol: str | None = None
    old_snippet: str | None = None
    new_snippet: str | None = None
    justification: str | None = None
    confidence: str | None = None


def _normalize(value) -> str:
    if value is None:
        return ''
    return ' '.join(str(value).casefold().split())


def _load_edited_rows(engine, window_days: int):
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    query = text('''
        SELECT d.id, d.inspection_id, d.field, d.section_type, d.transcript_excerpt,
               d.ai_value, d.final_value, i.inspector_id
        FROM transcription_fill_diffs d
        JOIN inspections i ON i.id = d.inspection_id
        WHERE d.edit_type = 'edited' AND d.match_confidence = 'exact'
          AND d.mined_at >= :since
    ''')
    with engine.connect() as conn:
        return conn.execute(query, {'since': since}).fetchall()


def _extract_ops(ai_value: str, final_value: str) -> list[tuple[str, str]]:
    """Word-level diff ops between ai_value and final_value -> list of
    (removed_phrase, added_phrase) pairs, one per non-equal opcode block."""
    a_words = _normalize(ai_value).split()
    b_words = _normalize(final_value).split()
    sm = difflib.SequenceMatcher(None, a_words, b_words)
    ops = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        removed = ' '.join(a_words[i1:i2])
        added = ' '.join(b_words[j1:j2])
        if removed or added:
            ops.append((removed, added))
    return ops


def build_clusters(rows) -> dict:
    """key: (field, section_type, removed, added) -> {rows, inspections, inspectors}"""
    clusters = defaultdict(lambda: {'rows': [], 'inspections': set(), 'inspectors': set()})
    for r in rows:
        for removed, added in _extract_ops(r.ai_value, r.final_value):
            c = clusters[(r.field, r.section_type, removed, added)]
            c['rows'].append(r)
            c['inspections'].add(r.inspection_id)
            if r.inspector_id is not None:
                c['inspectors'].add(r.inspector_id)
    return clusters


def rank_candidates(clusters: dict, min_rows: int = MIN_ROWS) -> list:
    candidates = [
        (key, c) for key, c in clusters.items()
        if len(c['rows']) >= min_rows
        and len(c['inspections']) >= MIN_INSPECTIONS
        and len(c['inspectors']) >= MIN_INSPECTORS
    ]
    candidates.sort(key=lambda kc: len(kc[1]['rows']), reverse=True)
    return candidates


def _read_transcribe_source() -> str:
    with open(_TRANSCRIBE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def _symbol_snippets(source: str) -> dict:
    """Generous (not precisely parsed) slice of each targetable constant's
    current definition — enough for the model to see the real text without
    needing a real Python parser here."""
    snippets = {}
    for symbol in _TARGETABLE_SYMBOLS:
        idx = source.find(f'{symbol} = ')
        if idx == -1:
            continue
        snippets[symbol] = source[idx:idx + 4000]
    return snippets


def draft_proposal(cluster_key: tuple, cluster: dict) -> ProposalDraft | None:
    import anthropic

    field, section_type, removed, added = cluster_key
    rows = cluster['rows'][:15]
    source = _read_transcribe_source()
    symbol_texts = _symbol_snippets(source)

    examples = '\n\n'.join(
        f'Transcript: "{(r.transcript_excerpt or "")[:300]}"\n'
        f'AI produced: {r.ai_value!r}\nHuman kept: {r.final_value!r}'
        for r in rows
    )

    prompt = f"""You are analysing a recurring correction pattern in an AI property-inspection
transcription pipeline. In the "{field}" field (section_type={section_type}), the AI
consistently produces "{removed}" where the human clerk consistently ends up with
"{added}" instead — across {len(cluster['inspections'])} different inspections and
{len(cluster['inspectors'])} different inspectors, so this is unlikely to be one
person's wording preference.

Up to 15 real examples of this pattern:

{examples}

Below are the current shared prompt rule constants in routes/transcribe.py that you
may propose editing. You may ONLY propose a change to ONE of these — do not propose
editing anything else, and do not invent a symbol name not listed here.

{json.dumps(symbol_texts, indent=2)[:8000]}

Decide: is this a genuine, fixable pattern (a consistent mishearing, a missing rule, a
formatting gap, a missing vocabulary term) that a small, targeted edit to ONE of the
above constants would plausibly fix — as opposed to noise, a one-off, or something no
prompt edit could realistically fix?

If yes, respond with strict JSON (no markdown):
{{"has_pattern": true, "target_symbol": "<one of the constant names above, exactly>",
  "old_snippet": "<EXACT substring to find in that constant's CURRENT text above, copied verbatim>",
  "new_snippet": "<replacement text>", "justification": "<one paragraph>",
  "confidence": "high" or "medium"}}

If no, respond with exactly:
{{"has_pattern": false}}

old_snippet MUST be an exact, unique substring of the constant's current text shown
above — it will be used for a literal string replacement, not a smart merge."""

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    message = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=1000,
        messages=[{'role': 'user', 'content': prompt}],
    )
    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f'[proposal] Sonnet response was not valid JSON: {raw[:300]!r}')
        return None

    if not data.get('has_pattern'):
        return ProposalDraft(has_pattern=False)

    return ProposalDraft(
        has_pattern=True,
        target_symbol=data.get('target_symbol'),
        old_snippet=data.get('old_snippet'),
        new_snippet=data.get('new_snippet'),
        justification=data.get('justification'),
        confidence=data.get('confidence'),
    )


def validate_draft(draft: ProposalDraft) -> str | None:
    """Returns an error string if the draft can't be safely applied, else None."""
    if draft.target_symbol not in _TARGETABLE_SYMBOLS:
        return f'target_symbol {draft.target_symbol!r} is not an allowed target'
    if not draft.old_snippet:
        return 'old_snippet is empty'
    source = _read_transcribe_source()
    count = source.count(draft.old_snippet)
    if count == 0:
        return 'old_snippet not found in transcribe.py'
    if count > 1:
        return f'old_snippet is ambiguous ({count} occurrences)'
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Mine transcription_fill_diffs for a recurring correction pattern and draft a '
                    'prompt fix (print-only — no file edits, no git, no GitHub)'
    )
    parser.add_argument('--window-days', type=int, default=30)
    parser.add_argument('--min-rows', type=int, default=MIN_ROWS)
    parser.add_argument('--no-draft', action='store_true', help='Only show clusters, skip the Sonnet call')
    args = parser.parse_args()

    engine = get_engine()
    rows = _load_edited_rows(engine, args.window_days)
    print(f"Loaded {len(rows)} edited/exact-match diff rows from the last {args.window_days} days.")

    clusters = build_clusters(rows)
    candidates = rank_candidates(clusters, min_rows=args.min_rows)
    print(
        f"{len(candidates)} clusters meet the threshold "
        f"(>= {args.min_rows} rows, >= {MIN_INSPECTIONS} inspections, >= {MIN_INSPECTORS} inspectors)."
    )

    if not candidates:
        near = sorted(clusters.items(), key=lambda kc: len(kc[1]['rows']), reverse=True)[:8]
        if near:
            print('\nTop clusters that did NOT meet the threshold (for tuning):')
            for key, c in near:
                field, section_type, removed, added = key
                print(
                    f"  [{len(c['rows'])} rows, {len(c['inspections'])} inspections, "
                    f"{len(c['inspectors'])} inspectors] {field}/{section_type}: "
                    f"{removed!r} -> {added!r}"
                )
        return

    top_key, top_cluster = candidates[0]
    field, section_type, removed, added = top_key
    print(
        f"\nTop candidate: {field}/{section_type}  {removed!r} -> {added!r}  "
        f"({len(top_cluster['rows'])} rows, {len(top_cluster['inspections'])} inspections, "
        f"{len(top_cluster['inspectors'])} inspectors)"
    )

    if args.no_draft:
        return

    draft = draft_proposal(top_key, top_cluster)
    if draft is None or not draft.has_pattern:
        print('\nSonnet judged this not to be a genuine, fixable prompt pattern (or the call failed).')
        return

    print('\nDraft proposal:')
    print(f'  target_symbol: {draft.target_symbol}')
    print(f'  confidence:    {draft.confidence}')
    print(f'  old_snippet:   {draft.old_snippet!r}')
    print(f'  new_snippet:   {draft.new_snippet!r}')
    print(f'  justification: {draft.justification}')

    error = validate_draft(draft)
    if error:
        print(f'\nVALIDATION FAILED (would be rejected before ever reaching a PR): {error}')
    else:
        print('\nValidation passed — old_snippet found exactly once in transcribe.py.')


if __name__ == '__main__':
    main()
