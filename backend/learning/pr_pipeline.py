"""
backend/learning/pr_pipeline.py
──────────────────────────────────
Phase 4 of the prompt-learning pipeline: takes the top pattern cluster
(learning/proposal.py), drafts a fix via Sonnet, re-verifies it against the
eval harness, and — only if it introduces zero CONFIRMED regressions —
opens a GitHub PR for human review. Never merges anything itself.

Ships behind LEARNING_PIPELINE_DRY_RUN (defaults to true / dry-run): logs
everything it WOULD do (the diff, the PR title/body, the eval numbers) but
makes no git branch, no GitHub API call, and sends no email. Flip the env
var to 'false' only after a soak period reviewing the dry-run logs — this
is the one component with write access to the repo.

Uses the GitHub REST API directly (Contents + Pulls) via `requests`, not a
git/gh CLI subprocess — the production container has no usable .git
checkout (Railway's build context is scoped to backend/), so a
clone-and-push approach would need extra packages and a scratch clone for
no real benefit; three JSON API calls do the same job.

Every run's outcome is recorded in transcription_prompt_proposals —
opened_pr, rejected_regression, error, or skipped_no_pattern — so nothing
the pipeline decides is silently dropped.

Usage (run from backend/):
    python -m learning.pr_pipeline                  # mine -> cluster -> draft -> gate -> (dry-run) PR
    python -m learning.pr_pipeline --live            # override LEARNING_PIPELINE_DRY_RUN for this run
    python -m learning.pr_pipeline --skip-mining     # use existing transcription_fill_diffs, don't re-mine
"""

import argparse
import base64
import json
import os
import sys
import tempfile
from datetime import date

import requests
from sqlalchemy import text

from learning import eval_harness, mining, proposal
from learning._db import get_engine

GH_OWNER = 'LMInventories'
GH_REPO = 'lmsoftware'
GH_API = f'https://api.github.com/repos/{GH_OWNER}/{GH_REPO}'
GH_BASE_BRANCH = 'main'
GH_TARGET_FILE = 'backend/routes/transcribe.py'

# API temperature is unset (non-zero) on the fill calls, so a single flipped
# fixture between two runs of the SAME unmodified code can be pure sampling
# noise rather than a real behaviour change (observed directly: fixing the
# check-out "As Inventory+" gap flipped two _claude_fill_room fixtures — a
# function that edit never touched — purely from re-running the live prompt
# twice). Re-check each apparent regression this many extra times and only
# trust it if EVERY recheck reproduces the flip.
_REGRESSION_RECHECK_ATTEMPTS = 2


def _dry_run() -> bool:
    return os.environ.get('LEARNING_PIPELINE_DRY_RUN', 'true').strip().lower() != 'false'


def _gh_headers():
    token = os.environ.get('GH_TOKEN')
    if not token:
        raise RuntimeError('GH_TOKEN env var not set — required to open a PR (not needed in dry-run mode)')
    return {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'}


def _open_pr_exists_for_symbol(target_symbol: str) -> bool:
    """
    True if a previous run already opened a PR targeting this same symbol
    and it's still open (not merged/closed). Prevents piling up duplicate
    proposals for the same pattern every day while a human hasn't reviewed
    the existing one yet — transcription_fill_diffs is a permanent
    historical log, so a dominant pattern keeps re-clustering as the top
    candidate until either it's fixed AND enough new data dilutes the old
    diffs, or this check skips it.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text('''
            SELECT pr_url FROM transcription_prompt_proposals
            WHERE status = 'opened_pr' AND target_function = :symbol AND pr_url LIKE 'https://%'
            ORDER BY id DESC LIMIT 1
        '''), {'symbol': target_symbol}).fetchone()
    if not row:
        return False

    pr_number = row.pr_url.rstrip('/').split('/')[-1]
    try:
        headers = _gh_headers()
    except RuntimeError:
        return False   # no GH_TOKEN configured (e.g. local/dry-run testing) — can't check, assume clear

    resp = requests.get(f'{GH_API}/pulls/{pr_number}', headers=headers, timeout=30)
    if resp.status_code != 200:
        return False
    return resp.json().get('state') == 'open'


def _record_proposal(status, target_function=None, pattern_summary=None, old_snippet=None,
                      new_snippet=None, example_diff_ids=None, eval_before=None, eval_after=None,
                      pr_url=None, branch_name=None, error_message=None):
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text('''
            INSERT INTO transcription_prompt_proposals
                (run_date, status, target_function, pattern_summary, old_snippet, new_snippet,
                 example_diff_ids_json, eval_before_json, eval_after_json, pr_url, branch_name,
                 error_message, created_at)
            VALUES (:run_date, :status, :target_function, :pattern_summary, :old_snippet, :new_snippet,
                    :example_diff_ids, :eval_before, :eval_after, :pr_url, :branch_name,
                    :error_message, now())
        '''), {
            'run_date': date.today(), 'status': status, 'target_function': target_function,
            'pattern_summary': pattern_summary, 'old_snippet': old_snippet, 'new_snippet': new_snippet,
            'example_diff_ids': json.dumps(example_diff_ids) if example_diff_ids else None,
            'eval_before': json.dumps(eval_before) if eval_before else None,
            'eval_after': json.dumps(eval_after) if eval_after else None,
            'pr_url': pr_url, 'branch_name': branch_name, 'error_message': error_message,
        })
        conn.commit()


def _apply_snippet(source: str, old_snippet: str, new_snippet: str) -> str:
    count = source.count(old_snippet)
    if count != 1:
        raise ValueError(f'old_snippet must appear exactly once in transcribe.py (found {count})')
    return source.replace(old_snippet, new_snippet, 1)


def _write_candidate(source: str) -> str:
    fd, path = tempfile.mkstemp(suffix='_transcribe_candidate.py')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(source)
    return path


def _confirmed_regressions(regressed_ids, fixtures_by_id, before_module, after_module) -> list:
    """Re-replay just the fixtures that flipped pass->fail, _REGRESSION_RECHECK_ATTEMPTS
    more times each, and only keep it as a real regression if every recheck reproduces
    the flip — see the module docstring for why this matters."""
    confirmed = []
    for fid in regressed_ids:
        fx = fixtures_by_id[fid]
        still_regressed = True
        for _ in range(_REGRESSION_RECHECK_ATTEMPTS):
            before_result = eval_harness.run_eval(before_module, [fx])[fid]
            after_result = eval_harness.run_eval(after_module, [fx])[fid]
            if not (before_result.passed and not after_result.passed):
                still_regressed = False
                break
        if still_regressed:
            confirmed.append(fid)
    return confirmed


def gate_and_evaluate(draft: proposal.ProposalDraft) -> dict:
    """
    Runs the eval harness before/after the proposed change. Returns a dict
    with pass counts plus a 'regressions' list of CONFIRMED regressions
    (already re-checked for sampling noise) and 'candidate_source' (the
    full proposed file content, for _open_pr to commit).
    """
    fixtures = eval_harness.load_fixtures(limit=300)
    fixtures_by_id = {fx.id: fx for fx in fixtures}

    before_module = eval_harness.load_fill_module(None)   # live transcribe.py
    with open(eval_harness._TRANSCRIBE_PATH, 'r', encoding='utf-8') as f:
        source = f.read()
    candidate_source = _apply_snippet(source, draft.old_snippet, draft.new_snippet)
    candidate_path = _write_candidate(candidate_source)
    try:
        after_module = eval_harness.load_fill_module(candidate_path)

        before = eval_harness.run_eval(before_module, fixtures)
        after = eval_harness.run_eval(after_module, fixtures)
        cmp = eval_harness.compare(before, after)

        cmp['regressions'] = _confirmed_regressions(cmp['regressions'], fixtures_by_id, before_module, after_module)
        cmp['candidate_source'] = candidate_source
        return cmp
    finally:
        os.unlink(candidate_path)


def _open_pr(draft: proposal.ProposalDraft, cmp: dict) -> tuple:
    headers = _gh_headers()

    base_ref = requests.get(f'{GH_API}/git/ref/heads/{GH_BASE_BRANCH}', headers=headers, timeout=30)
    base_ref.raise_for_status()
    base_sha = base_ref.json()['object']['sha']

    slug = draft.target_symbol.strip('_').lower().replace('_', '-')
    branch_name = f'prompt-learning/{date.today().isoformat()}-{slug}'
    ref_resp = requests.post(
        f'{GH_API}/git/refs', headers=headers,
        json={'ref': f'refs/heads/{branch_name}', 'sha': base_sha}, timeout=30,
    )
    ref_resp.raise_for_status()

    file_resp = requests.get(
        f'{GH_API}/contents/{GH_TARGET_FILE}', headers=headers,
        params={'ref': GH_BASE_BRANCH}, timeout=30,
    )
    file_resp.raise_for_status()
    file_sha = file_resp.json()['sha']

    # candidate_source came from a plain text-mode read (universal newlines —
    # \r\n silently normalised to \n), but transcribe.py is tracked with CRLF
    # line endings on disk. Pushing LF-only content against a CRLF-tracked
    # file makes git (and GitHub's diff view) treat every line as changed,
    # producing a ~7000-line diff for what should be a ~15-line change.
    # Detect the real on-disk convention and re-apply it before pushing.
    with open(eval_harness._TRANSCRIBE_PATH, 'rb') as f:
        uses_crlf = b'\r\n' in f.read()
    content_to_push = cmp['candidate_source']
    if uses_crlf:
        content_to_push = content_to_push.replace('\r\n', '\n').replace('\n', '\r\n')

    new_content_b64 = base64.b64encode(content_to_push.encode('utf-8')).decode('ascii')
    commit_message = f'prompt-learning: {draft.target_symbol}'
    put_resp = requests.put(f'{GH_API}/contents/{GH_TARGET_FILE}', headers=headers, json={
        'message': commit_message, 'content': new_content_b64, 'sha': file_sha, 'branch': branch_name,
    }, timeout=30)
    put_resp.raise_for_status()

    body = (
        '**Auto-generated by the prompt-learning pipeline — do not merge without human review '
        'of the underlying examples.**\n\n'
        f'### Pattern\n{draft.justification}\n\n'
        f'### Target\n`{draft.target_symbol}` in `{GH_TARGET_FILE}`\n\n'
        f'### Eval harness (before -> after, {cmp["total"]} golden fixtures)\n'
        f'- Passed: {cmp["passed_before"]} -> {cmp["passed_after"]}\n'
        f'- Confirmed regressions: {len(cmp["regressions"])}\n'
        f'- Improvements: {len(cmp["improvements"])}\n\n'
        f'### Confidence\n{draft.confidence}\n'
    )
    pr_resp = requests.post(f'{GH_API}/pulls', headers=headers, json={
        'title': f'[prompt-learning] {draft.target_symbol}: automated fix proposal',
        'head': branch_name, 'base': GH_BASE_BRANCH, 'body': body,
    }, timeout=30)
    pr_resp.raise_for_status()
    return pr_resp.json()['html_url'], branch_name


def _send_email(draft: proposal.ProposalDraft, pr_url: str, eval_summary: dict):
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from routes.email_service import ADMIN_NOTIFY_EMAIL, SMTP_FROM, _send, _wrap

    subject = f'Prompt-learning proposal ready for review: {draft.target_symbol}'
    body = (
        f'<p>A new automated prompt-fix proposal is ready for review.</p>'
        f'<p><b>Target:</b> {draft.target_symbol}</p>'
        f'<p><b>Justification:</b> {draft.justification}</p>'
        f'<p><b>Eval:</b> {eval_summary["passed_before"]}/{eval_summary["total"]} &rarr; '
        f'{eval_summary["passed_after"]}/{eval_summary["total"]} golden fixtures passing</p>'
        f'<p><a href="{pr_url}">{pr_url}</a></p>'
    )
    _send(SMTP_FROM, ADMIN_NOTIFY_EMAIL, subject, _wrap(body, subject))


def run_daily_pipeline(skip_mining: bool = False, force_live: bool = False) -> dict:
    if not skip_mining:
        mining.run_daily_mining()

    engine = get_engine()
    rows = proposal._load_edited_rows(engine, window_days=30)
    clusters = proposal.build_clusters(rows)
    candidates = proposal.rank_candidates(clusters)

    if not candidates:
        _record_proposal(status='skipped_no_pattern')
        return {'status': 'skipped_no_pattern'}

    top_key, top_cluster = candidates[0]
    field, section_type, removed, added = top_key
    pattern_summary = f"{field}/{section_type}: {removed!r} -> {added!r} ({len(top_cluster['rows'])} rows)"
    example_diff_ids = [r.id for r in top_cluster['rows'][:15]]

    try:
        draft = proposal.draft_proposal(top_key, top_cluster)
    except Exception as e:
        _record_proposal(status='error', pattern_summary=pattern_summary, error_message=repr(e))
        return {'status': 'error', 'error': repr(e)}

    if draft is None or not draft.has_pattern:
        _record_proposal(status='skipped_no_pattern', pattern_summary=pattern_summary)
        return {'status': 'skipped_no_pattern'}

    if _open_pr_exists_for_symbol(draft.target_symbol):
        _record_proposal(
            status='skipped_no_pattern', target_function=draft.target_symbol,
            pattern_summary=pattern_summary + ' [skipped: an open PR already targets this symbol]',
        )
        return {'status': 'skipped_open_pr_exists', 'target_function': draft.target_symbol}

    validation_error = proposal.validate_draft(draft)
    if validation_error:
        _record_proposal(
            status='error', target_function=draft.target_symbol, pattern_summary=pattern_summary,
            old_snippet=draft.old_snippet, new_snippet=draft.new_snippet,
            example_diff_ids=example_diff_ids, error_message=validation_error,
        )
        return {'status': 'error', 'error': validation_error}

    try:
        cmp = gate_and_evaluate(draft)
    except Exception as e:
        _record_proposal(
            status='error', target_function=draft.target_symbol, pattern_summary=pattern_summary,
            old_snippet=draft.old_snippet, new_snippet=draft.new_snippet,
            example_diff_ids=example_diff_ids, error_message=repr(e),
        )
        return {'status': 'error', 'error': repr(e)}

    eval_summary = {k: v for k, v in cmp.items() if k != 'candidate_source'}

    if cmp['regressions']:
        _record_proposal(
            status='rejected_regression', target_function=draft.target_symbol, pattern_summary=pattern_summary,
            old_snippet=draft.old_snippet, new_snippet=draft.new_snippet, example_diff_ids=example_diff_ids,
            eval_before=eval_summary, eval_after=eval_summary,
        )
        print(f"[pr_pipeline] REJECTED — confirmed regressions: {cmp['regressions']}")
        return {'status': 'rejected_regression', 'regressions': cmp['regressions']}

    if _dry_run() and not force_live:
        print('[pr_pipeline] DRY RUN — would open a PR:')
        print(f'  target_symbol: {draft.target_symbol}')
        print(f'  old_snippet:   {draft.old_snippet!r}')
        print(f'  new_snippet:   {draft.new_snippet!r}')
        print(f'  justification: {draft.justification}')
        print(f"  eval: {cmp['passed_before']}/{cmp['total']} -> {cmp['passed_after']}/{cmp['total']}")
        _record_proposal(
            status='opened_pr', target_function=draft.target_symbol, pattern_summary=pattern_summary,
            old_snippet=draft.old_snippet, new_snippet=draft.new_snippet, example_diff_ids=example_diff_ids,
            eval_before=eval_summary, eval_after=eval_summary, pr_url='(dry-run — no PR opened)',
        )
        return {'status': 'dry_run_would_open_pr', 'draft': draft, 'eval': eval_summary}

    pr_url, branch_name = _open_pr(draft, cmp)
    _record_proposal(
        status='opened_pr', target_function=draft.target_symbol, pattern_summary=pattern_summary,
        old_snippet=draft.old_snippet, new_snippet=draft.new_snippet, example_diff_ids=example_diff_ids,
        eval_before=eval_summary, eval_after=eval_summary, pr_url=pr_url, branch_name=branch_name,
    )
    _send_email(draft, pr_url, eval_summary)
    return {'status': 'opened_pr', 'pr_url': pr_url}


def main():
    parser = argparse.ArgumentParser(
        description='Run the daily prompt-learning pipeline: mine -> cluster -> draft -> gate -> (dry-run) PR'
    )
    parser.add_argument('--live', action='store_true',
                        help='Override LEARNING_PIPELINE_DRY_RUN for this run and actually open a PR + send email')
    parser.add_argument('--skip-mining', action='store_true',
                        help='Skip the mining step, use the existing transcription_fill_diffs')
    args = parser.parse_args()

    result = run_daily_pipeline(skip_mining=args.skip_mining, force_live=args.live)
    print(f"\nResult: {result['status']}")


if __name__ == '__main__':
    main()
