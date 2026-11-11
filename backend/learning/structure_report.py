"""
backend/learning/structure_report.py
──────────────────────────────────────
Report on the STRUCTURAL corrections clerks make that the glossary can't
express: items the AI filled that the clerk then deleted, sub-items the AI
invented that were removed, and sub-items the clerk had to add that the AI
missed. Read-only — nothing here is applied automatically. The findings feed the
review page / reminder email, and a Sonnet pass turns them into suggested
prompt rules for a human to consider.

Needs the sub-item matching introduced alongside this module in
learning/mining.py; run `python -m learning.mining --reset-ledger` once after
deploy to backfill the existing history with it.

Usage (run from backend/):
    python -m learning.structure_report
    python -m learning.structure_report --window-days 180 --suggest
"""

import argparse
import json
import os

from sqlalchemy import text

from learning._db import get_engine

MIN_COUNT = 3


def build_report(window_days: int = 90, engine=None) -> dict:
    engine = engine or get_engine()
    params = {'days': window_days, 'min': MIN_COUNT}
    with engine.connect() as conn:
        deleted_items = conn.execute(text('''
            SELECT item_name, section_type, count(DISTINCT (inspection_id, item_id)) AS n,
                   count(DISTINCT inspection_id) AS inspections
            FROM transcription_fill_diffs
            WHERE edit_type = 'deleted' AND field NOT LIKE '\\_subs.%' AND item_id IS NOT NULL
              AND mined_at >= now() - make_interval(days => :days)
            GROUP BY item_name, section_type HAVING count(DISTINCT (inspection_id, item_id)) >= :min
            ORDER BY n DESC LIMIT 15
        '''), params).fetchall()

        removed_subs = conn.execute(text('''
            SELECT lower(ai_value) AS sub_name, item_name, count(*) AS n, count(DISTINCT inspection_id) AS inspections
            FROM transcription_fill_diffs
            WHERE edit_type = 'deleted' AND field LIKE '\\_subs.%.name'
              AND mined_at >= now() - make_interval(days => :days)
            GROUP BY lower(ai_value), item_name HAVING count(*) >= :min
            ORDER BY n DESC LIMIT 15
        '''), params).fetchall()

        added_subs = conn.execute(text('''
            SELECT lower(final_value) AS sub_name, item_name, count(*) AS n, count(DISTINCT inspection_id) AS inspections,
                   avg(CASE WHEN transcript_excerpt ILIKE '%sub item%' OR transcript_excerpt ILIKE '%sub-item%'
                            THEN 1.0 ELSE 0.0 END) AS said_sub_item
            FROM transcription_fill_diffs
            WHERE edit_type = 'added' AND field LIKE '\\_subs.new%.name'
              AND mined_at >= now() - make_interval(days => :days)
            GROUP BY lower(final_value), item_name HAVING count(*) >= :min
            ORDER BY n DESC LIMIT 15
        '''), params).fetchall()

        totals = conn.execute(text('''
            SELECT
              count(*) FILTER (WHERE edit_type = 'deleted' AND field NOT LIKE '\\_subs.%') AS item_fields_deleted,
              count(*) FILTER (WHERE edit_type = 'deleted' AND field LIKE '\\_subs.%')     AS sub_fields_deleted,
              count(*) FILTER (WHERE edit_type = 'added')                                   AS sub_fields_added,
              count(*) FILTER (WHERE edit_type = 'unresolved')                              AS unresolved
            FROM transcription_fill_diffs WHERE mined_at >= now() - make_interval(days => :days)
        '''), params).fetchone()

    return {
        'window_days': window_days,
        'totals': dict(totals._mapping),
        'deleted_items': [dict(r._mapping) for r in deleted_items],
        'ai_subs_clerk_removed': [dict(r._mapping) for r in removed_subs],
        'clerk_added_subs': [
            {**dict(r._mapping), 'said_sub_item': round(float(r.said_sub_item or 0), 2)} for r in added_subs
        ],
    }


def has_findings(report: dict) -> bool:
    return any(report[k] for k in ('deleted_items', 'ai_subs_clerk_removed', 'clerk_added_subs'))


def suggest_rules(report: dict) -> list:
    """Sonnet reads the aggregate and proposes up to 5 candidate prompt rules.
    Advice only — returned as plain strings for a human to weigh."""
    if not has_findings(report):
        return []
    import anthropic

    prompt = f"""You are reviewing how clerks correct an AI that transcribes UK property-inventory
dictation into structured items and sub-items. Below is an aggregate of the last
{report['window_days']} days of structural corrections:

- deleted_items: items the AI filled but the clerk deleted (AI filled something it shouldn't have)
- ai_subs_clerk_removed: sub-items the AI created that the clerk removed (over-splitting / invention)
- clerk_added_subs: sub-items the clerk had to add that the AI didn't create. said_sub_item is the
  share of those where the dictation contained the words "sub item" (high = the AI ignored an
  explicit trigger; low = the clerk added structure the dictation never asked for)

{json.dumps(report, indent=1, default=str)[:6000]}

Suggest at most 5 concrete, testable prompt rules or checks that would reduce these corrections.
Each: one sentence rule + one sentence of evidence from the data. If the data is too thin or
looks like taste rather than a pattern, say so instead of inventing rules.
Respond with strict JSON only: ["...", "..."]"""

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    message = client.messages.create(model='claude-sonnet-4-6', max_tokens=1200,
                                     messages=[{'role': 'user', 'content': prompt}])
    raw = message.content[0].text.strip().replace('```json', '').replace('```', '').strip()
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(x)[:600] for x in out][:5] if isinstance(out, list) else []


def main():
    parser = argparse.ArgumentParser(description='Report on deletions / sub-item corrections by clerks')
    parser.add_argument('--window-days', type=int, default=90)
    parser.add_argument('--suggest', action='store_true', help='Also ask Sonnet for candidate rules')
    args = parser.parse_args()

    report = build_report(args.window_days)
    print(json.dumps(report, indent=2, default=str))
    if args.suggest:
        print('\nSuggested rules (advice only):')
        for s in suggest_rules(report):
            print(f'  - {s}')


if __name__ == '__main__':
    main()
