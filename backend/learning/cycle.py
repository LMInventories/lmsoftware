"""
backend/learning/cycle.py
───────────────────────────
One full run of the learning agent, called by the scheduler (every 3 days by
default — LEARNING_PIPELINE_CADENCE_DAYS) or by hand:

    1. mine new clerk edits + (maybe) open a prompt-fix PR   (pr_pipeline)
    2. glossary agent: queue new vocabulary suggestions as pending
    3. structural report on deletions / sub-items (+ Sonnet advice if there are findings)
    4. reminder email with the signed review link, if anything awaits a human

Each step is isolated: one failing never stops the next, and the reminder always
goes out when something is pending, even if mining or the LLM calls broke.

    python -m learning.cycle [--live]
"""

import argparse


def run_learning_cycle(force_live: bool = False) -> dict:
    result = {}

    try:
        from learning.pr_pipeline import run_daily_pipeline
        r = run_daily_pipeline(force_live=force_live)
        result['pr_pipeline'] = r.get('status')
    except Exception as e:
        result['pr_pipeline'] = f'FAILED: {e!r}'

    try:
        from learning.glossary_mining import run_glossary_agent
        g = run_glossary_agent()
        result['glossary'] = {k: g[k] for k in ('rows', 'candidates', 'queued')}
    except Exception as e:
        result['glossary'] = f'FAILED: {e!r}'

    structure, suggestions = None, []
    try:
        from learning.structure_report import build_report, has_findings, suggest_rules
        structure = build_report(90)
        if has_findings(structure):
            suggestions = suggest_rules(structure)
        result['structure'] = {'findings': has_findings(structure), 'suggestions': len(suggestions)}
    except Exception as e:
        result['structure'] = f'FAILED: {e!r}'

    try:
        from learning.notify import send_review_reminder
        result['reminder'] = send_review_reminder(suggestions, structure, force_live=force_live).get('status')
    except Exception as e:
        result['reminder'] = f'FAILED: {e!r}'

    return result


def main():
    parser = argparse.ArgumentParser(description='Run one full learning-agent cycle')
    parser.add_argument('--live', action='store_true', help='Override LEARNING_PIPELINE_DRY_RUN (opens PR / sends email)')
    args = parser.parse_args()
    print(run_learning_cycle(force_live=args.live))


if __name__ == '__main__':
    main()
