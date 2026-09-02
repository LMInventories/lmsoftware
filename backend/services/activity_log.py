"""
services/activity_log.py — records InspectionActivity rows for the per-inspection
Activity Log card. See models.InspectionActivity for the event_type values and
routes/inspections.py for where each one gets triggered.

Event types:
  created       — inspection record created (office/admin)
  details_added — inspection metadata edited from the web app (not a mobile sync)
  fetched       — clerk downloaded the inspection to their phone for offline work
  started       — clerk moved the inspection to 'active' (on-site work begun)
  synced        — clerk's phone pushed report data back to the server
  completed     — inspection moved to 'complete'
  email_sent    — the report PDF was successfully emailed (auto-completion or Share PDF)
  email_failed  — a report PDF send attempt failed; see routes/email_notifications.py's
                  daily failure-alert job, which queries this event type
"""
from datetime import datetime, timezone, timedelta
from models import db, InspectionActivity

# Some event types (details_added in particular) can fire on every autosave from
# the web app — throttle those so rapid edits collapse into one timeline entry
# instead of flooding the log. Deliberate user actions (created/fetched/started/
# synced/completed) are never throttled — each is already a discrete action.
_THROTTLED_EVENTS = {'details_added'}
_THROTTLE_WINDOW = timedelta(minutes=5)


def log_activity(inspection_id, event_type, user_id=None, detail=None):
    """
    Record one InspectionActivity row. Never raises — activity logging is a
    nice-to-have timeline, not something that should ever break the request
    it's attached to.
    """
    try:
        if event_type in _THROTTLED_EVENTS:
            recent = (InspectionActivity.query
                      .filter_by(inspection_id=inspection_id, event_type=event_type)
                      .order_by(InspectionActivity.created_at.desc())
                      .first())
            if recent and recent.created_at:
                recent_at = recent.created_at
                if recent_at.tzinfo is None:
                    recent_at = recent_at.replace(tzinfo=timezone.utc)
                if recent_at > datetime.now(timezone.utc) - _THROTTLE_WINDOW:
                    return
        db.session.add(InspectionActivity(
            inspection_id=inspection_id,
            event_type=event_type,
            user_id=user_id,
            detail=detail,
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'[activity_log] failed to log {event_type!r} for inspection {inspection_id}: {e}')
