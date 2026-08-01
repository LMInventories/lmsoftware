"""
backend/learning/mining.py
─────────────────────────────
Daily mining job (wired up to the scheduler in Phase 4) that diffs every new
_transcriptionLog entry (written by the mobile app on each AI fill) against
the current, finished report_data for that inspection, and records the
result in transcription_fill_diffs.

For each inspection whose report_data changed since it was last mined:
  - resolve each new log entry's room (and, for instant mode, item label)
    to a real template item
  - diff every field the AI produced against what's now actually stored
  - upsert one transcription_fill_diffs row per (log entry, item, field)
  - if every field in a room-mode entry came back "unchanged", promote it
    to transcription_golden_fixtures (once only — checked by (inspection_id,
    log_entry_index), never re-promoted)
  - record the new high-water mark in transcription_mined_inspections

Like the other learning/ scripts, this uses a raw SQLAlchemy engine rather
than the Flask-SQLAlchemy `db` object / app context, so it stays runnable
standalone (matches the migrate_*.py convention) — the scheduler wrapper
(Phase 4) can call run_daily_mining() directly, no app context needed.

Safe to run repeatedly: diff upserts are keyed on (inspection_id,
log_entry_hash), and fixture promotion checks for an existing row first.

Usage (run from backend/):
    python -m learning.mining
    python -m learning.mining --pool-size 500
    python -m learning.mining --inspection-id 145      # force re-mine one inspection
"""

import argparse
import hashlib
import json
from datetime import datetime

from sqlalchemy import bindparam, text

from learning._db import get_engine

_META_KEYS = {'name', '_delete', '_descAction', '_condAction'}
_ROOM_FILL_FN_BY_TYPE = {
    'check_out':     '_claude_fill_room_checkout',
    'damage_report': '_claude_fill_room_damage',
}
_DEFAULT_ROOM_FILL_FN = '_claude_fill_room'


def _normalize(value) -> str:
    if value is None:
        return ''
    return ' '.join(str(value).casefold().split())


def _to_text(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _entry_hash(inspection_id, log_entry_index, item_id, field) -> str:
    raw = f'{inspection_id}|{log_entry_index}|{item_id}|{field}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(str(ts_str).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def _deleted_ids(section_data: dict) -> set:
    raw = section_data.get('_deleted')
    if isinstance(raw, list):
        return {str(x) for x in raw}
    if isinstance(raw, dict):
        return {str(k) for k in raw.keys()}
    return set()


def _strip_media(report_data: dict) -> None:
    """In-place removal of embedded photo/audio blobs so a multi-MB
    report_data is never held in memory longer than necessary."""
    for section in report_data.values():
        if not isinstance(section, dict):
            continue
        for item in section.values():
            if isinstance(item, dict):
                item.pop('_photos', None)
                item.pop('audioB64', None)
    log = report_data.get('_transcriptionLog')
    if isinstance(log, list):
        for entry in log:
            if isinstance(entry, dict):
                entry.pop('audioB64', None)


def _candidate_inspections(engine, limit: int):
    """id/updated_at-only query — never touches report_data for inspections
    that haven't changed since they were last mined (or were never mined)."""
    query = text('''
        SELECT i.id
        FROM inspections i
        LEFT JOIN transcription_mined_inspections m ON m.inspection_id = i.id
        WHERE i.status = 'complete'
          AND (m.id IS NULL OR i.updated_at > m.last_inspection_updated_at)
        ORDER BY i.updated_at DESC
        LIMIT :limit
    ''')
    with engine.connect() as conn:
        return [r.id for r in conn.execute(query, {'limit': limit}).fetchall()]


def _load_inspections(engine, ids: list):
    if not ids:
        return []
    query = text(
        'SELECT id, updated_at, template_id, inspection_type, report_data '
        'FROM inspections WHERE id IN :ids'
    ).bindparams(bindparam('ids', expanding=True))
    with engine.connect() as conn:
        return conn.execute(query, {'ids': ids}).fetchall()


def _ledger_start_indices(engine, ids: list) -> dict:
    """{inspection_id: last_log_entry_count} for all given ids in one round trip."""
    if not ids:
        return {}
    query = text(
        'SELECT inspection_id, last_log_entry_count FROM transcription_mined_inspections '
        'WHERE inspection_id IN :ids'
    ).bindparams(bindparam('ids', expanding=True))
    with engine.connect() as conn:
        rows = conn.execute(query, {'ids': ids}).fetchall()
    return {r.inspection_id: r.last_log_entry_count for r in rows}


def _upsert_ledger(conn, inspection_id: int, log_entry_count: int, updated_at):
    conn.execute(text('''
        INSERT INTO transcription_mined_inspections
            (inspection_id, last_log_entry_count, last_inspection_updated_at, last_mined_at)
        VALUES (:iid, :count, :updated_at, now())
        ON CONFLICT (inspection_id) DO UPDATE SET
            last_log_entry_count = EXCLUDED.last_log_entry_count,
            last_inspection_updated_at = EXCLUDED.last_inspection_updated_at,
            last_mined_at = now()
    '''), {'iid': inspection_id, 'count': log_entry_count, 'updated_at': updated_at})


def _sections_for_template(engine, template_id: int):
    """{name.lower(): (section_id_str, section_type)} for one template."""
    query = text('SELECT id, name, section_type FROM sections WHERE template_id = :tid')
    with engine.connect() as conn:
        rows = conn.execute(query, {'tid': template_id}).fetchall()
    return {r.name.strip().lower(): (str(r.id), r.section_type) for r in rows}


def _items_for_section(engine, section_id: int):
    query = text('SELECT id, name FROM items WHERE section_id = :sid ORDER BY order_index')
    with engine.connect() as conn:
        rows = conn.execute(query, {'sid': section_id}).fetchall()
    return [{'id': str(r.id), 'name': r.name} for r in rows]


def _infer_fill_fn_name(entry: dict, inspection_type: str, section_type: str) -> str:
    if entry.get('mode') == 'instant':
        return '_claude_fill_item'
    if section_type != 'room':
        return '_claude_fill_fixed_section'
    return _ROOM_FILL_FN_BY_TYPE.get(inspection_type, _DEFAULT_ROOM_FILL_FN)


def _classify(ai_value, final_value) -> str:
    if _normalize(ai_value) == _normalize(final_value):
        return 'unchanged'
    if not _normalize(final_value):
        return 'deleted'
    return 'edited'


def _diff_subs(ai_subs, current_subs, fill_fn_name: str) -> list[dict]:
    """
    Checkout mode: the AI's _subs entries carry a real, stable _sid (they
    target an existing sub-item), so match by that id — match_confidence='exact'.
    Room/damage mode: a NEW sub-item's _sid is only assigned client-side after
    the AI call, so the AI's output has no id to match on — fall back to
    positional matching, flagged match_confidence='fuzzy'.
    """
    diffs = []
    current_subs = current_subs or []
    ai_subs = ai_subs or []

    if fill_fn_name == '_claude_fill_room_checkout':
        current_by_sid = {s.get('_sid'): s for s in current_subs if isinstance(s, dict)}
        for i, ai_sub in enumerate(ai_subs):
            current = current_by_sid.get(ai_sub.get('_sid'))
            for key, ai_value in ai_sub.items():
                if key == '_sid':
                    continue
                final_value = current.get(key) if current else None
                edit_type = 'deleted' if current is None else _classify(ai_value, final_value)
                diffs.append({
                    'field': f'_subs.{i}.{key}', 'ai_value': ai_value, 'final_value': final_value,
                    'edit_type': edit_type, 'match_confidence': 'exact',
                })
    else:
        for i, ai_sub in enumerate(ai_subs):
            current = current_subs[i] if i < len(current_subs) and isinstance(current_subs[i], dict) else None
            for key, ai_value in ai_sub.items():
                if key == '_sid':
                    continue
                final_value = current.get(key) if current else None
                edit_type = 'unresolved' if current is None else _classify(ai_value, final_value)
                diffs.append({
                    'field': f'_subs.{i}.{key}', 'ai_value': ai_value, 'final_value': final_value,
                    'edit_type': edit_type, 'match_confidence': 'fuzzy',
                })
    return diffs


def _diff_item_fields(ai_fields: dict, current_row, deleted_ids: set, item_id: str, fill_fn_name: str) -> list[dict]:
    diffs = []

    if item_id in deleted_ids:
        for key, ai_value in ai_fields.items():
            if key in _META_KEYS or key == '_subs':
                continue
            diffs.append({'field': key, 'ai_value': ai_value, 'final_value': None,
                          'edit_type': 'deleted', 'match_confidence': 'exact'})
        return diffs

    if not isinstance(current_row, dict):
        for key, ai_value in ai_fields.items():
            if key in _META_KEYS or key == '_subs':
                continue
            diffs.append({'field': key, 'ai_value': ai_value, 'final_value': None,
                          'edit_type': 'unresolved', 'match_confidence': 'fuzzy'})
        return diffs

    for key, ai_value in ai_fields.items():
        if key in _META_KEYS:
            continue
        if key == '_subs':
            diffs.extend(_diff_subs(ai_value, current_row.get('_subs'), fill_fn_name))
            continue
        final_value = current_row.get(key)
        diffs.append({'field': key, 'ai_value': ai_value, 'final_value': final_value,
                      'edit_type': _classify(ai_value, final_value), 'match_confidence': 'exact'})
    return diffs


def _diff_room_mode_entry(entry: dict, report_data: dict, section_map: dict, inspection_type: str):
    room = (entry.get('room') or '').strip().lower()
    if room not in section_map:
        return None   # room renamed/removed since the entry was logged — nothing to diff against
    section_id, section_type = section_map[room]
    section_data = report_data.get(section_id) or {}
    deleted_ids = _deleted_ids(section_data)
    fill_fn_name = _infer_fill_fn_name(entry, inspection_type, section_type)

    filled = entry.get('filled') or {}
    all_diffs = []
    for item_id, item_fields in filled.items():
        if not isinstance(item_fields, dict):
            continue
        item_diffs = _diff_item_fields(item_fields, section_data.get(item_id), deleted_ids, item_id, fill_fn_name)
        for d in item_diffs:
            d['item_id'] = item_id
            d['item_name'] = item_fields.get('name')
        all_diffs.extend(item_diffs)

    return {'section_id': section_id, 'section_type': section_type, 'fill_fn_name': fill_fn_name, 'diffs': all_diffs}


def _diff_instant_mode_entry(entry: dict, report_data: dict, section_map: dict, engine, items_cache: dict):
    """
    No item_id in instant-mode logs — only a room/item label string. Resolve
    via case-insensitive (then singular/plural-normalised) match against the
    section's current Item.name. 0 or >1 match -> edit_type='unresolved',
    stored for audit but excluded from golden-fixture promotion and, by
    default, pattern mining.
    """
    room = (entry.get('room') or '').strip().lower()
    item_label = (entry.get('item') or '').strip().lower()
    filled = entry.get('filled') or {}
    if room not in section_map or not item_label:
        return None
    section_id, section_type = section_map[room]

    if section_id not in items_cache:
        items_cache[section_id] = _items_for_section(engine, int(section_id))
    items = items_cache[section_id]

    matches = [i for i in items if i['name'].strip().lower() == item_label]
    if len(matches) != 1:
        matches = [i for i in items if i['name'].strip().lower().rstrip('s') == item_label.rstrip('s')]

    if len(matches) != 1:
        diffs = [
            {'field': k, 'ai_value': v, 'final_value': None, 'edit_type': 'unresolved',
             'match_confidence': 'fuzzy', 'item_id': None, 'item_name': entry.get('item')}
            for k, v in filled.items() if k not in _META_KEYS and k != '_subs'
        ]
        return {'section_id': section_id, 'section_type': section_type, 'fill_fn_name': '_claude_fill_item', 'diffs': diffs}

    item_id = matches[0]['id']
    section_data = report_data.get(section_id) or {}
    deleted_ids = _deleted_ids(section_data)
    diffs = _diff_item_fields(filled, section_data.get(item_id), deleted_ids, item_id, '_claude_fill_item')
    for d in diffs:
        d['item_id'] = item_id
        d['item_name'] = matches[0]['name']
        d['match_confidence'] = 'fuzzy'   # the label->item resolution itself is fuzzy, even if values matched exactly
    return {'section_id': section_id, 'section_type': section_type, 'fill_fn_name': '_claude_fill_item', 'diffs': diffs}


_DIFF_ROW_COLUMNS = [
    'inspection_id', 'log_entry_index', 'log_entry_hash', 'log_entry_ts', 'mode', 'fill_fn_name',
    'section_type', 'room', 'item_id', 'item_name', 'field', 'transcript_excerpt',
    'ai_value', 'final_value', 'edit_type', 'match_confidence',
]


def _build_diff_row_params(inspection_id, log_entry_index, log_entry_ts, mode, fill_fn_name, section_type, room, transcript, diffs) -> list[dict]:
    """Build the flat param dicts for a log entry's diffs — collected across
    (potentially) many entries/inspections and flushed via one batched
    multi-VALUES INSERT (_flush_diff_rows) instead of one round trip per row,
    which is what made the very first mining run against ~600 inspections
    take upwards of 20 minutes (one INSERT per diffed field)."""
    excerpt = (transcript or '')[:500]
    rows = []
    for d in diffs:
        rows.append({
            'inspection_id': inspection_id, 'log_entry_index': log_entry_index,
            'log_entry_hash': _entry_hash(inspection_id, log_entry_index, d.get('item_id'), d['field']),
            'log_entry_ts': log_entry_ts, 'mode': mode, 'fill_fn_name': fill_fn_name,
            'section_type': section_type, 'room': room, 'item_id': d.get('item_id'), 'item_name': d.get('item_name'),
            'field': d['field'], 'transcript_excerpt': excerpt,
            'ai_value': _to_text(d.get('ai_value')), 'final_value': _to_text(d.get('final_value')),
            'edit_type': d['edit_type'], 'match_confidence': d['match_confidence'],
        })
    return rows


def _flush_diff_rows(conn, rows: list[dict], batch_size: int = 200) -> None:
    """One multi-VALUES INSERT per batch instead of one INSERT per row."""
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        value_groups, params = [], {}
        for i, row in enumerate(chunk):
            value_groups.append('(' + ', '.join(f':{col}_{i}' for col in _DIFF_ROW_COLUMNS) + ', now())')
            for col in _DIFF_ROW_COLUMNS:
                params[f'{col}_{i}'] = row[col]
        sql = (
            'INSERT INTO transcription_fill_diffs (' + ', '.join(_DIFF_ROW_COLUMNS) + ', mined_at) VALUES '
            + ', '.join(value_groups) +
            ' ON CONFLICT (inspection_id, log_entry_hash) DO UPDATE SET '
            'final_value = EXCLUDED.final_value, edit_type = EXCLUDED.edit_type, '
            'match_confidence = EXCLUDED.match_confidence, mined_at = now()'
        )
        conn.execute(text(sql), params)


def _promote_if_fully_unchanged(conn, inspection_id, log_entry_index, entry, fill_fn_name, section_type, room, items_snapshot) -> bool:
    existing = conn.execute(text('''
        SELECT id FROM transcription_golden_fixtures
        WHERE source_inspection_id = :iid AND log_entry_index = :idx
    '''), {'iid': inspection_id, 'idx': log_entry_index}).fetchone()
    if existing:
        return False

    filled = entry.get('filled') or {}
    expected = {
        item_id: {k: v for k, v in item_fields.items() if k not in _META_KEYS}
        for item_id, item_fields in filled.items() if isinstance(item_fields, dict)
    }

    conn.execute(text('''
        INSERT INTO transcription_golden_fixtures
            (source_inspection_id, log_entry_index, fill_fn_name, section_type, room_name,
             transcript, items_snapshot_json, expected_filled_json, is_active, created_at)
        VALUES (:iid, :idx, :fn, :st, :room, :transcript, :items, :expected, true, now())
    '''), {
        'iid': inspection_id, 'idx': log_entry_index, 'fn': fill_fn_name, 'st': section_type,
        'room': room, 'transcript': entry.get('transcript') or '',
        'items': json.dumps(items_snapshot), 'expected': json.dumps(expected),
    })
    return True


def run_daily_mining(pool_size: int = 200, force_inspection_id: int | None = None) -> dict:
    engine = get_engine()
    stats = {'inspections_scanned': 0, 'entries_mined': 0, 'diffs_written': 0,
              'fixtures_promoted': 0, 'unresolved_fields': 0}

    ids = [force_inspection_id] if force_inspection_id else _candidate_inspections(engine, pool_size)
    inspections = _load_inspections(engine, ids)
    if not inspections:
        return stats

    ledger_starts = {} if force_inspection_id else _ledger_start_indices(engine, [i.id for i in inspections])

    section_cache = {}   # template_id -> {name.lower(): (id, type)}
    items_cache = {}     # section_id -> items list

    with engine.connect() as conn:
        for insp in inspections:
            stats['inspections_scanned'] += 1
            if not insp.report_data:
                continue
            try:
                report_data = json.loads(insp.report_data)
            except (json.JSONDecodeError, TypeError):
                continue
            _strip_media(report_data)

            log = report_data.get('_transcriptionLog') or []
            if not log:
                continue

            start_idx = ledger_starts.get(insp.id, 0)
            new_entries = list(enumerate(log))[start_idx:]
            if not new_entries:
                continue

            if insp.template_id not in section_cache:
                section_cache[insp.template_id] = _sections_for_template(engine, insp.template_id)
            section_map = section_cache[insp.template_id]

            pending_rows = []
            for idx, entry in new_entries:
                mode = entry.get('mode')
                if mode == 'room':
                    result = _diff_room_mode_entry(entry, report_data, section_map, insp.inspection_type)
                elif mode == 'instant':
                    result = _diff_instant_mode_entry(entry, report_data, section_map, engine, items_cache)
                else:
                    continue
                if result is None or not result['diffs']:
                    continue

                stats['entries_mined'] += 1
                stats['unresolved_fields'] += sum(1 for d in result['diffs'] if d['edit_type'] == 'unresolved')

                pending_rows.extend(_build_diff_row_params(
                    insp.id, idx, _parse_ts(entry.get('timestamp')), mode,
                    result['fill_fn_name'], result['section_type'], entry.get('room'),
                    entry.get('transcript'), result['diffs'],
                ))
                stats['diffs_written'] += len(result['diffs'])

                all_unchanged = all(d['edit_type'] == 'unchanged' for d in result['diffs'])
                if all_unchanged and mode == 'room':
                    section_id = result['section_id']
                    if section_id not in items_cache:
                        items_cache[section_id] = _items_for_section(engine, int(section_id))
                    if _promote_if_fully_unchanged(
                        conn, insp.id, idx, entry, result['fill_fn_name'],
                        result['section_type'], entry.get('room'), items_cache[section_id],
                    ):
                        stats['fixtures_promoted'] += 1

            if pending_rows:
                _flush_diff_rows(conn, pending_rows)
            _upsert_ledger(conn, insp.id, len(log), insp.updated_at)
            conn.commit()

    return stats


def main():
    parser = argparse.ArgumentParser(description='Mine _transcriptionLog vs report_data into transcription_fill_diffs')
    parser.add_argument('--pool-size', type=int, default=200, help='Max inspections to scan per run')
    parser.add_argument('--inspection-id', type=int, default=None, help='Force re-mine a single inspection, ignoring its ledger high-water mark')
    args = parser.parse_args()

    stats = run_daily_mining(pool_size=args.pool_size, force_inspection_id=args.inspection_id)
    print(
        f"Scanned {stats['inspections_scanned']} inspections, mined {stats['entries_mined']} log entries, "
        f"wrote {stats['diffs_written']} diff rows ({stats['unresolved_fields']} unresolved fields), "
        f"promoted {stats['fixtures_promoted']} new golden fixtures."
    )


if __name__ == '__main__':
    main()
