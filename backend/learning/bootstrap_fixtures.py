"""
backend/learning/bootstrap_fixtures.py
─────────────────────────────────────────
Phase-0 manual bootstrap for the prompt-learning regression harness
(learning/eval_harness.py). NOT scheduled — run by hand once to seed the
transcription_golden_fixtures table before the automatic mining job
(learning/mining.py, Phase 1) exists, so the prerequisite prompt-rule
consolidation refactor in routes/transcribe.py has a safety net to run
eval_harness against.

Scans recent COMPLETE inspections' `_transcriptionLog` (written by the
mobile app on every AI fill) for room-mode entries where every field the AI
produced was left byte-for-byte unchanged in the finished report_data — that
agreement is the signal a fixture is worth freezing as a regression check.

Only handles room-mode entries for _claude_fill_room / _claude_fill_room_checkout /
_claude_fill_room_damage — the three highest-value, most-duplicated fill
functions and the ones the Phase-0 refactor actually touches. Instant-mode
entries and fixed-section entries are left to the full mining job (Phase 1),
which has the harder room-name/item-name resolution logic this script
doesn't attempt.

Usage (run from backend/):
    python -m learning.bootstrap_fixtures                    # dry run — prints candidates
    python -m learning.bootstrap_fixtures --commit            # inserts them
    python -m learning.bootstrap_fixtures --commit --max-fixtures 20
"""

import argparse
import json

from sqlalchemy import text

from learning._db import get_engine

_ROOM_FILL_FN_BY_TYPE = {
    'check_out':     '_claude_fill_room_checkout',
    'damage_report': '_claude_fill_room_damage',
}
_DEFAULT_FILL_FN = '_claude_fill_room'

_META_KEYS = {'name', '_subs', '_delete', '_descAction', '_condAction'}


def _normalize(value) -> str:
    if value is None:
        return ''
    return ' '.join(str(value).casefold().split())


def _fields_match(ai_fields: dict, current_row: dict) -> bool:
    """True if every non-meta field the AI produced is still present, unchanged,
    in the item's current row in report_data."""
    if not current_row:
        return False
    for key, ai_value in ai_fields.items():
        if key in _META_KEYS:
            continue
        if _normalize(ai_value) != _normalize(current_row.get(key)):
            return False
    return True


def _candidate_inspections(engine, pool_size: int):
    query = text(
        "SELECT id, report_data, template_id, inspection_type "
        "FROM inspections WHERE status = 'complete' "
        "ORDER BY updated_at DESC LIMIT :pool_size"
    )
    with engine.connect() as conn:
        return conn.execute(query, {'pool_size': pool_size}).fetchall()


def _sections_for_template(engine, template_id: int):
    """{name.lower(): (section_id_str, section_type)} for one template."""
    query = text('SELECT id, name, section_type FROM sections WHERE template_id = :tid')
    with engine.connect() as conn:
        rows = conn.execute(query, {'tid': template_id}).fetchall()
    return {r.name.strip().lower(): (str(r.id), r.section_type) for r in rows}


def _items_for_section(engine, section_id: int):
    """Full item list for a section, in the shape fill functions expect."""
    query = text(
        'SELECT id, name FROM items WHERE section_id = :sid ORDER BY order_index'
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {'sid': section_id}).fetchall()
    return [{'id': str(r.id), 'name': r.name} for r in rows]


def find_candidates(pool_size: int = 100):
    engine = get_engine()
    candidates = []
    section_cache = {}   # template_id -> {name.lower(): (id, type)}
    items_cache = {}     # section_id -> items list

    for insp in _candidate_inspections(engine, pool_size):
        if not insp.report_data:
            continue
        try:
            report_data = json.loads(insp.report_data)
        except (json.JSONDecodeError, TypeError):
            continue

        log = report_data.get('_transcriptionLog') or []
        if not log:
            continue

        if insp.template_id not in section_cache:
            section_cache[insp.template_id] = _sections_for_template(engine, insp.template_id)
        section_map = section_cache[insp.template_id]

        fill_fn_name = _ROOM_FILL_FN_BY_TYPE.get(insp.inspection_type, _DEFAULT_FILL_FN)

        for idx, entry in enumerate(log):
            if entry.get('mode') != 'room':
                continue   # instant-mode / fixed-section: left to the full mining job
            room = (entry.get('room') or '').strip().lower()
            if room not in section_map:
                continue
            section_id, section_type = section_map[room]
            if section_type != 'room':
                continue

            filled = entry.get('filled') or {}
            if not filled:
                continue

            section_data = report_data.get(section_id) or {}
            all_unchanged = all(
                _fields_match(item_fields, section_data.get(item_id) or {})
                for item_id, item_fields in filled.items()
                if isinstance(item_fields, dict)
            )
            if not all_unchanged:
                continue

            if section_id not in items_cache:
                items_cache[section_id] = _items_for_section(engine, int(section_id))

            candidates.append({
                'inspection_id':  insp.id,
                'log_entry_index': idx,
                'fill_fn_name':    fill_fn_name,
                'section_type':    section_type,
                'room_name':       entry.get('room'),
                'transcript':      entry.get('transcript') or '',
                'items_snapshot':  items_cache[section_id],
                'expected_filled': filled,
            })

    return candidates


def insert_fixtures(candidates: list, max_fixtures: int):
    engine = get_engine()
    inserted = 0
    with engine.connect() as conn:
        for c in candidates[:max_fixtures]:
            conn.execute(
                text(
                    'INSERT INTO transcription_golden_fixtures '
                    '(source_inspection_id, log_entry_index, fill_fn_name, section_type, room_name, '
                    ' transcript, items_snapshot_json, expected_filled_json, is_active, created_at) '
                    'VALUES (:source_inspection_id, :log_entry_index, :fill_fn_name, :section_type, :room_name, '
                    ' :transcript, :items_snapshot_json, :expected_filled_json, true, now())'
                ),
                {
                    'source_inspection_id': c['inspection_id'],
                    'log_entry_index':      c['log_entry_index'],
                    'fill_fn_name':          c['fill_fn_name'],
                    'section_type':          c['section_type'],
                    'room_name':             c['room_name'],
                    'transcript':            c['transcript'],
                    'items_snapshot_json':   json.dumps(c['items_snapshot']),
                    'expected_filled_json':  json.dumps(c['expected_filled']),
                },
            )
            inserted += 1
        conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description='Bootstrap golden fixtures from real completed inspections')
    parser.add_argument('--pool-size', type=int, default=100, help='How many recent complete inspections to scan')
    parser.add_argument('--max-fixtures', type=int, default=30, help='Cap on fixtures to insert')
    parser.add_argument('--commit', action='store_true', help='Actually insert into the DB (default: dry run, print only)')
    args = parser.parse_args()

    candidates = find_candidates(pool_size=args.pool_size)
    print(f'Found {len(candidates)} unchanged room-mode log entries across the scanned inspections.')

    for c in candidates[:args.max_fixtures]:
        print(f"  inspection={c['inspection_id']} entry={c['log_entry_index']} "
              f"fn={c['fill_fn_name']} room={c['room_name']!r} "
              f"transcript={c['transcript'][:80]!r}")

    if not args.commit:
        print(f'\nDry run — would insert {min(len(candidates), args.max_fixtures)} fixtures. '
              f'Re-run with --commit to insert them.')
        return

    inserted = insert_fixtures(candidates, args.max_fixtures)
    print(f'\nInserted {inserted} golden fixtures.')


if __name__ == '__main__':
    main()
