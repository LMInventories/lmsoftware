"""
Gunicorn configuration for InspectPro backend.

Key decisions:
- 4 sync workers: handles 4 concurrent requests without asyncio complexity.
  Railway Hobby runs on a shared vCPU; more than 4 workers fights for the same
  core and hurts rather than helps. Increase to 8 on a dedicated-CPU plan.
- sync worker class: our endpoints are DB-bound (fast SQLAlchemy calls), not
  I/O-bound with long waits, so sync workers are the right fit.
- timeout=120: covers large sync payloads and AI transcription calls.
- graceful_timeout=30: when Railway sends SIGTERM during a deploy, workers
  get 30s to finish any in-flight request before being force-killed.
  This prevents mid-flight PDF exports or mobile syncs being dropped.
  Keep this below Railway's drain window (default 60s).
- preload_app=True: loads the Flask app once in the master process before
  forking workers, so all 4 workers share the same code memory, DB migrations
  have already run, and the APScheduler only starts once (not once per worker).
"""
import os

bind             = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers          = int(os.environ.get('GUNICORN_WORKERS', '4'))
worker_class     = 'sync'
timeout          = 120
graceful_timeout = 30   # finish in-flight requests after SIGTERM before hard kill
keepalive        = 5    # keep TCP connection alive for 5s between requests
preload_app      = True # load app once, share across workers; scheduler runs once

# Logging
accesslog    = '-'      # stdout
errorlog     = '-'
loglevel     = os.environ.get('LOG_LEVEL', 'info')
