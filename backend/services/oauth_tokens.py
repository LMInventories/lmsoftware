"""
services/oauth_tokens.py
─────────────────────────
Shared SystemSetting-backed CRUD for per-platform OAuth token storage.

Every OAuth integration (Google, Microsoft, Dropbox, Slack, ...) stores its
tokens as a handful of SystemSetting rows named "{prefix}_{field}" (e.g.
"microsoft_access_token"). This module only generalises that boring CRUD —
the actual OAuth flow (auth URL, token exchange, refresh semantics) differs
enough per platform that it stays written out in each routes/<platform>.py
file rather than being forced into one abstraction.

Also provides short-lived `state` storage for CSRF protection on the
`/auth` -> `/callback` round trip.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable


def save_tokens(prefix: str, data: dict) -> None:
    """Upsert a dict of {field: value} as SystemSetting rows named '{prefix}_{field}'."""
    from models import db, SystemSetting

    for field, value in data.items():
        key = f'{prefix}_{field}'
        row = SystemSetting.query.filter_by(key=key).first()
        if row is None:
            db.session.add(SystemSetting(key=key, value=value))
        else:
            row.value = value
    db.session.commit()


def load_tokens(prefix: str, fields: Iterable[str]) -> dict:
    """Load SystemSetting rows named '{prefix}_{field}' for each field.
    Returns {field: value} (only for rows that exist)."""
    from models import SystemSetting

    keys = [f'{prefix}_{f}' for f in fields]
    rows = SystemSetting.query.filter(SystemSetting.key.in_(keys)).all()
    by_key = {r.key: r.value for r in rows}
    return {f: by_key[f'{prefix}_{f}'] for f in fields if f'{prefix}_{f}' in by_key}


def clear_tokens(prefix: str, fields: Iterable[str]) -> None:
    """Delete SystemSetting rows named '{prefix}_{field}' for each field."""
    from models import db, SystemSetting

    keys = [f'{prefix}_{f}' for f in fields]
    SystemSetting.query.filter(SystemSetting.key.in_(keys)).delete(synchronize_session=False)
    db.session.commit()


# ── CSRF state helpers ──────────────────────────────────────────────────────
# Stored as a single SystemSetting row per platform, valued "{state}:{expiry_iso}".
# A DB row (not a server-side session) is used because the OAuth round trip
# crosses a redirect to a third party and back — there's no reliable session
# to carry it in, and this app is single-instance-per-deploy already relying
# on SystemSetting for similar small bits of transient state.

def new_state(prefix: str, ttl_seconds: int = 600) -> str:
    """Generate, store, and return a random state token for this platform's /auth step."""
    from models import db, SystemSetting

    state = secrets.token_urlsafe(24)
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    key = f'{prefix}_oauth_state'
    value = f'{state}:{expiry}'
    row = SystemSetting.query.filter_by(key=key).first()
    if row is None:
        db.session.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    db.session.commit()
    return state


def verify_state(prefix: str, state: str) -> bool:
    """Check a returned state against the stored one, then consume it (one-time use)."""
    from models import db, SystemSetting

    key = f'{prefix}_oauth_state'
    row = SystemSetting.query.filter_by(key=key).first()
    if row is None or not row.value or not state:
        return False

    try:
        stored_state, expiry_str = row.value.split(':', 1)
        expiry = datetime.fromisoformat(expiry_str)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except Exception:
        return False

    db.session.delete(row)
    db.session.commit()

    if datetime.now(timezone.utc) > expiry:
        return False
    return secrets.compare_digest(stored_state, state)
