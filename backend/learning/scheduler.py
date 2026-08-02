"""
backend/learning/scheduler.py
────────────────────────────────
Registers the prompt-learning pipeline run (learning/pr_pipeline.py) with
APScheduler, following the exact idiom already used for the Google
connection expiry check (routes/google.py:schedule_expiry_check).

Cadence is configurable via LEARNING_PIPELINE_CADENCE_DAYS (default 1 —
daily). Set it to e.g. 14 in Railway for fortnightly, no code change or
redeploy-time edit needed beyond the variable itself. Uses IntervalTrigger
(not CronTrigger) anchored to a fixed start_date, so the schedule doesn't
drift or reset to "run again tomorrow" every time the service restarts —
a fortnightly cadence stays on the same 14-day boundary regardless of how
many times Railway redeploys in between.

Safe to register unconditionally — pr_pipeline.run_daily_pipeline() defaults
to LEARNING_PIPELINE_DRY_RUN=true, so a run mines real data and may draft a
proposal, but never opens a PR, never touches git/GitHub, and never sends
an email unless that env var is explicitly set to 'false' in Railway. It
also exits immediately (no Anthropic API calls at all) on any run where
mining found zero newly-completed reports since the last run — see
pr_pipeline.run_daily_pipeline's early-exit check.

Call once after create_app():
    from learning.scheduler import schedule_learning_pipeline
    schedule_learning_pipeline(app)
"""

import os
from datetime import datetime

# Fixed anchor — do not change this once live. It only sets which day-of-cycle
# the schedule lands on; changing it after the fact shifts every future fire
# time. 20:00 Europe/London, the day this pipeline first went live.
_ANCHOR = datetime(2026, 8, 1, 20, 0, 0)


def schedule_learning_pipeline(app):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        cadence_days = int(os.environ.get('LEARNING_PIPELINE_CADENCE_DAYS', '1'))

        scheduler = BackgroundScheduler(timezone='Europe/London')

        def job():
            with app.app_context():
                from learning.pr_pipeline import run_daily_pipeline
                try:
                    result = run_daily_pipeline()
                    print(f"[learning] pipeline run: {result.get('status')}")
                except Exception as e:
                    print(f'[learning] pipeline run FAILED: {e!r}')

        trigger = IntervalTrigger(days=cadence_days, start_date=_ANCHOR, timezone='Europe/London')
        scheduler.add_job(job, trigger)
        scheduler.start()
        print(f'[learning] prompt-learning pipeline scheduler started — runs every {cadence_days} '
              f'day(s) at 20:00 Europe/London')
        return scheduler
    except ImportError:
        print('[learning] APScheduler not installed — prompt-learning pipeline disabled')
        return None
