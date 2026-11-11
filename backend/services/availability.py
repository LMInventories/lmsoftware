"""Availability checks shared by the clerk pickers and the Telegram booking flow."""
import re
from datetime import date

from models import UserUnavailability

# Working-day windows (minutes from midnight) used to decide whether a slot is blocked.
# A clerk counts as unavailable only if their blocks cover the *whole* window, so
# someone off 08:00-11:00 can still take a PM job.
_WINDOWS = {'am': (8 * 60, 12 * 60), 'pm': (12 * 60, 18 * 60), 'anytime': (8 * 60, 18 * 60)}
_SPECIFIC_LENGTH = 60


def slot_window(time_pref):
    """Map a conduct_time_preference ('am', 'pm', 'anytime', 'specific:HH_MM') to (start, end) minutes."""
    pref = (time_pref or 'anytime').lower()
    m = re.fullmatch(r'specific:(\d{1,2})_(\d{2})', pref)
    if m:
        start = int(m.group(1)) * 60 + int(m.group(2))
        return start, min(start + _SPECIFIC_LENGTH, 24 * 60)
    return _WINDOWS.get(pref, _WINDOWS['anytime'])


def _blocks_for_day(rows, d):
    out = []
    for r in rows:
        if r.kind == 'repeating':
            applies = r.weekday == d.weekday()
        else:
            applies = r.start_date is not None and r.start_date <= d <= (r.end_date or r.start_date)
        if applies:
            out.append((0, 1440) if r.start_min is None or r.end_min is None else (r.start_min, r.end_min))
    return out


def _covers(blocks, start, end):
    pos = start
    for s, e in sorted(blocks):
        if s > pos:
            break
        pos = max(pos, e)
        if pos >= end:
            return True
    return pos >= end


def unavailable_user_ids(d, time_pref=None, user_ids=None):
    """IDs of users whose unavailability fully covers the given date + time slot."""
    if not isinstance(d, date):
        return set()
    q = UserUnavailability.query
    if user_ids is not None:
        if not user_ids:
            return set()
        q = q.filter(UserUnavailability.user_id.in_(list(user_ids)))
    by_user = {}
    for r in q.all():
        by_user.setdefault(r.user_id, []).append(r)
    start, end = slot_window(time_pref)
    return {uid for uid, rows in by_user.items() if _covers(_blocks_for_day(rows, d), start, end)}


def _as_date(value):
    if value is None:
        return None
    return value.date() if hasattr(value, 'date') and callable(value.date) else value


def clerk_conflict(inspector_id, conduct_date, time_pref=None):
    """The User if `inspector_id` has availability blocks covering this date + slot, else None."""
    d = _as_date(conduct_date)
    if not inspector_id or d is None:
        return None
    if inspector_id not in unavailable_user_ids(d, time_pref, [inspector_id]):
        return None
    from models import db, User
    return db.session.get(User, inspector_id)


def availability_block_response(clerk, can_override):
    """The 422 body returned when a booking/reassignment would land on an unavailable clerk."""
    name = clerk.name if clerk else 'That clerk'
    msg = f'{name} is marked unavailable at that date/time.'
    if can_override:
        msg += ' Choose another clerk, or override their availability.'
    return {
        'error': msg,
        'code': 'clerk_unavailable',
        'inspector_id': clerk.id if clerk else None,
        'inspector_name': name,
        'can_override': bool(can_override),
    }
