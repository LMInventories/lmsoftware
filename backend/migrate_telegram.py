"""
migrate_telegram.py
─────────────────────
Creates the telegram_links, telegram_link_codes, and telegram_sessions
tables (see models.py::TelegramLink/TelegramLinkCode/TelegramSession) — the
Telegram bot integration for booking inspections / creating properties
via free-text chat.

Run once (or automatically via start.sh on deploy):
    python migrate_telegram.py
"""

import os
from sqlalchemy import create_engine, text

database_url = os.environ.get('DATABASE_URL', '')
if not database_url:
    print('ERROR: DATABASE_URL env var not set')
    exit(1)

database_url = database_url.replace('postgres://', 'postgresql+psycopg://')
database_url = database_url.replace('postgresql://', 'postgresql+psycopg://')

engine = create_engine(database_url)

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS telegram_links (
            id                   SERIAL PRIMARY KEY,
            user_id              INTEGER NOT NULL REFERENCES users(id),
            chat_id              BIGINT NOT NULL,
            telegram_username    VARCHAR(100),
            telegram_first_name  VARCHAR(100),
            linked_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_telegram_links_user_id ON telegram_links (user_id)"
    ))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_telegram_links_chat_id ON telegram_links (chat_id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS telegram_link_codes (
            id         SERIAL PRIMARY KEY,
            code       VARCHAR(16) NOT NULL,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at    TIMESTAMPTZ
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_telegram_link_codes_code ON telegram_link_codes (code)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS telegram_sessions (
            id                   SERIAL PRIMARY KEY,
            chat_id              BIGINT NOT NULL,
            state                VARCHAR(30) NOT NULL DEFAULT 'idle',
            pending_tool         VARCHAR(30),
            pending_action_json  TEXT,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_telegram_sessions_chat_id ON telegram_sessions (chat_id)"
    ))

    conn.commit()

print('OK telegram tables ensured')
