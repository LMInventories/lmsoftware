"""
backend/learning/eval_harness.py
──────────────────────────────────
Standalone regression harness for the transcription fill prompts in
routes/transcribe.py.

Replays TranscriptionGoldenFixture rows — historical (transcript, expected
output) pairs where a human left the AI's fill completely unchanged in the
finished report — against either the live fill functions or a candidate
edited copy of transcribe.py, and reports which fixtures pass/fail.

This is the regression gate for both hand-written and pipeline-proposed
prompt edits: run it before and after a change and require zero fixtures
that used to pass to start failing (see compare()).

Usage (run from backend/):
    python -m learning.eval_harness --report
    python -m learning.eval_harness --report --fill-fn _claude_fill_room
    python -m learning.eval_harness --candidate /path/to/candidate_transcribe.py
"""

import argparse
import importlib.util
import json
import os
from dataclasses import dataclass, field

from sqlalchemy import text

from learning._db import get_engine

_TRANSCRIBE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'routes', 'transcribe.py'
)

# Fill functions that return (dict, message) — everything except
# _claude_fill_full_report, which returns the dict directly.
_RETURNS_TUPLE = {
    '_claude_fill_item',
    '_claude_fill_room',
    '_claude_fill_room_checkout',
    '_claude_fill_room_damage',
    '_claude_fill_fixed_section',
}


@dataclass
class Fixture:
    id: int
    fill_fn_name: str
    section_type: str | None
    room_name: str | None
    transcript: str
    items_snapshot_json: str
    expected_filled_json: str


@dataclass
class FixtureResult:
    fixture_id: int
    passed: bool
    diffs: list = field(default_factory=list)   # human-readable field-level mismatches


def load_fixtures(limit: int = 300, fill_fn_name: str | None = None) -> list[Fixture]:
    """Most-recent-first, is_active=True, capped so a full run is seconds not minutes."""
    engine = get_engine()
    query = (
        'SELECT id, fill_fn_name, section_type, room_name, transcript, '
        'items_snapshot_json, expected_filled_json '
        'FROM transcription_golden_fixtures WHERE is_active = true'
    )
    params = {}
    if fill_fn_name:
        query += ' AND fill_fn_name = :fill_fn_name'
        params['fill_fn_name'] = fill_fn_name
    query += ' ORDER BY id DESC LIMIT :limit'
    params['limit'] = limit

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    return [
        Fixture(
            id=r.id, fill_fn_name=r.fill_fn_name, section_type=r.section_type,
            room_name=r.room_name, transcript=r.transcript,
            items_snapshot_json=r.items_snapshot_json, expected_filled_json=r.expected_filled_json,
        )
        for r in rows
    ]


def load_fill_module(path: str | None = None):
    """
    Load either the live transcribe module (default) or a candidate file at
    `path`, as a fresh module object — so a proposed edit can be exercised
    without touching the live file or restarting the process.
    """
    target = path or _TRANSCRIBE_PATH
    spec = importlib.util.spec_from_file_location('transcribe_eval_target', target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _call_fill_fn(fill_module, fx: Fixture):
    fn = getattr(fill_module, fx.fill_fn_name, None)
    if fn is None:
        raise AttributeError(f'{fx.fill_fn_name} not found on fill module')

    snapshot = json.loads(fx.items_snapshot_json)

    if fx.fill_fn_name in ('_claude_fill_room', '_claude_fill_room_damage'):
        result = fn(fx.transcript, fx.room_name, snapshot)
    elif fx.fill_fn_name == '_claude_fill_room_checkout':
        result = fn(fx.transcript, fx.room_name, snapshot)
    elif fx.fill_fn_name == '_claude_fill_fixed_section':
        result = fn(fx.transcript, fx.room_name, fx.section_type, snapshot)
    elif fx.fill_fn_name == '_claude_fill_item':
        # snapshot here is the single-item call context, not an items list —
        # see bootstrap_fixtures.py's item-mode fixture shape.
        result = fn(
            fx.transcript,
            snapshot['item_label'],
            fx.room_name,
            snapshot.get('section_type', 'room'),
            snapshot.get('edit_mode', 'normal'),
            snapshot.get('is_check_out', False),
            snapshot.get('is_damage_report', False),
        )
    elif fx.fill_fn_name == '_claude_fill_full_report':
        return fn(fx.transcript, snapshot)   # returns dict directly, not a tuple
    else:
        raise ValueError(f'unknown fill_fn_name: {fx.fill_fn_name}')

    filled, _message = result
    return filled


def _normalize(value) -> str:
    """casefold + collapse whitespace — a 'pass' means the model reproduced
    what the human actually kept, not a byte-exact match."""
    if value is None:
        return ''
    return ' '.join(str(value).casefold().split())


def _flatten(obj, prefix: str = '') -> dict:
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f'{prefix}{k}.'))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f'{prefix}{i}.'))
    else:
        out[prefix.rstrip('.') or '(root)'] = obj
    return out


def _compare_filled(actual: dict, expected: dict) -> list[str]:
    flat_actual = _flatten(actual)
    flat_expected = _flatten(expected)
    diffs = []
    for key in sorted(set(flat_actual) | set(flat_expected)):
        a, e = flat_actual.get(key), flat_expected.get(key)
        if _normalize(a) != _normalize(e):
            diffs.append(f'{key}: expected {e!r}, got {a!r}')
    return diffs


def run_eval(fill_module, fixtures: list[Fixture]) -> dict[int, FixtureResult]:
    results = {}
    for fx in fixtures:
        try:
            actual = _call_fill_fn(fill_module, fx)
            expected = json.loads(fx.expected_filled_json)
            diffs = _compare_filled(actual, expected)
            results[fx.id] = FixtureResult(fixture_id=fx.id, passed=not diffs, diffs=diffs)
        except Exception as e:
            results[fx.id] = FixtureResult(fixture_id=fx.id, passed=False, diffs=[f'error: {e!r}'])
    return results


def compare(before: dict[int, FixtureResult], after: dict[int, FixtureResult]) -> dict:
    """
    regressions = fixtures that passed in `before` and fail in `after` — the hard gate,
    a prompt change must produce zero of these.
    improvements = failed in `before`, pass in `after` — informational only.
    """
    regressions, improvements = [], []
    for fid, r in before.items():
        a = after.get(fid)
        if a is None:
            continue
        if r.passed and not a.passed:
            regressions.append(fid)
        elif not r.passed and a.passed:
            improvements.append(fid)

    total = len(before)
    passed_before = sum(1 for r in before.values() if r.passed)
    passed_after = sum(1 for r in after.values() if r.passed)

    return {
        'total': total,
        'passed_before': passed_before,
        'passed_after': passed_after,
        'pass_rate_before': (passed_before / total) if total else 0.0,
        'pass_rate_after': (passed_after / total) if total else 0.0,
        'regressions': regressions,
        'improvements': improvements,
    }


def main():
    parser = argparse.ArgumentParser(description='Run the transcription prompt regression harness')
    parser.add_argument('--report', action='store_true', help='Print per-fixture pass/fail detail')
    parser.add_argument('--fill-fn', default=None, help='Only test fixtures for this fill_fn_name')
    parser.add_argument('--limit', type=int, default=300)
    parser.add_argument('--candidate', default=None, help='Path to a candidate transcribe.py to test instead of the live one')
    args = parser.parse_args()

    fixtures = load_fixtures(limit=args.limit, fill_fn_name=args.fill_fn)
    if not fixtures:
        print('No golden fixtures found — run bootstrap_fixtures.py first.')
        return

    module = load_fill_module(args.candidate)
    results = run_eval(module, fixtures)

    passed = sum(1 for r in results.values() if r.passed)
    pct = passed / len(results) if results else 0
    print(f'{passed}/{len(results)} fixtures passed ({pct:.0%})'
          + (f'  [candidate: {args.candidate}]' if args.candidate else '  [live transcribe.py]'))

    if args.report:
        for fx in fixtures:
            r = results[fx.id]
            status = 'PASS' if r.passed else 'FAIL'
            print(f'[{status}] fixture #{fx.id}  {fx.fill_fn_name}  room={fx.room_name!r}')
            if not r.passed:
                for d in r.diffs:
                    print(f'    {d}')


if __name__ == '__main__':
    main()
