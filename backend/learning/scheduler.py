"""
backend/learning/scheduler.py
────────────────────────────────
Registers the daily prompt-learning pipeline run (learning/pr_pipeline.py)
with APScheduler, following the exact idiom already used for the Google
connection expiry check (routes/google.py:schedule_expiry_check).

Safe to register unconditionally — pr_pipeline.run_daily_pipeline() defaults
to LEARNING_PIPELINE_DRY_RUN=true, so a daily run mines real data and may
draft a proposal, but never opens a PR, never touches git/GitHub, and never
sends an email unless that env var is explicitly set to 'false' in Railway.

Call once after create_app():
    from learning.scheduler import schedule_learning_pipeline
    schedule_learning_pipeline(app)
"""


def schedule_learning_pipeline(app):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone='Europe/London')

        def job():
            with app.app_context():
                from learning.pr_pipeline import run_daily_pipeline
                try:
                    result = run_daily_pipeline()
                    print(f"[learning] daily pipeline run: {result.get('status')}")
                except Exception as e:
                    print(f'[learning] daily pipeline run FAILED: {e!r}')

        scheduler.add_job(job, CronTrigger(hour=20, minute=0, timezone='Europe/London'))
        scheduler.start()
        print('[learning] prompt-learning pipeline scheduler started — runs daily at 20:00 Europe/London')
        return scheduler
    except ImportError:
        print('[learning] APScheduler not installed — prompt-learning pipeline disabled')
        return None
