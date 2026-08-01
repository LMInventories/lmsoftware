"""
migrate_learning_tables.py
────────────────────────────
Creates the tables backing the prompt-learning pipeline
(backend/learning/*): transcription_fill_diffs, transcription_mined_inspections,
transcription_golden_fixtures, transcription_prompt_proposals.

Run once on deploy (safe to re-run — uses CREATE TABLE IF NOT EXISTS):
    python migrate_learning_tables.py
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

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS transcription_fill_diffs (
        id                  SERIAL PRIMARY KEY,
        inspection_id       INTEGER REFERENCES inspections(id) ON DELETE SET NULL,
        log_entry_index     INTEGER NOT NULL,
        log_entry_hash      VARCHAR(64) NOT NULL,
        log_entry_ts        TIMESTAMP,
        mode                VARCHAR(10) NOT NULL,
        fill_fn_name        VARCHAR(50),
        section_type        VARCHAR(30),
        room                VARCHAR(255),
        item_id             VARCHAR(50),
        item_name           VARCHAR(255),
        field               VARCHAR(30) NOT NULL,
        transcript_excerpt  TEXT,
        ai_value            TEXT,
        final_value         TEXT,
        edit_type           VARCHAR(20) NOT NULL,
        match_confidence    VARCHAR(10) DEFAULT 'exact',
        mined_at            TIMESTAMP,
        CONSTRAINT uq_diff_entry UNIQUE (inspection_id, log_entry_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_transcription_fill_diffs_inspection_id ON transcription_fill_diffs (inspection_id)",
    "CREATE INDEX IF NOT EXISTS ix_transcription_fill_diffs_log_entry_hash ON transcription_fill_diffs (log_entry_hash)",

    """
    CREATE TABLE IF NOT EXISTS transcription_mined_inspections (
        id                          SERIAL PRIMARY KEY,
        inspection_id               INTEGER NOT NULL UNIQUE REFERENCES inspections(id) ON DELETE CASCADE,
        last_log_entry_count        INTEGER DEFAULT 0,
        last_inspection_updated_at  TIMESTAMP,
        last_mined_at               TIMESTAMP
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS transcription_golden_fixtures (
        id                     SERIAL PRIMARY KEY,
        source_inspection_id   INTEGER REFERENCES inspections(id) ON DELETE SET NULL,
        log_entry_index        INTEGER NOT NULL,
        fill_fn_name           VARCHAR(50) NOT NULL,
        section_type           VARCHAR(30),
        room_name              VARCHAR(255),
        transcript              TEXT NOT NULL,
        items_snapshot_json     TEXT NOT NULL,
        expected_filled_json    TEXT NOT NULL,
        source_diff_ids_json    TEXT,
        is_active               BOOLEAN DEFAULT TRUE,
        created_at              TIMESTAMP
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS transcription_prompt_proposals (
        id                     SERIAL PRIMARY KEY,
        run_date               DATE NOT NULL,
        status                 VARCHAR(20) NOT NULL,
        target_function        VARCHAR(50),
        pattern_summary        TEXT,
        old_snippet            TEXT,
        new_snippet            TEXT,
        example_diff_ids_json  TEXT,
        eval_before_json       TEXT,
        eval_after_json        TEXT,
        pr_url                 VARCHAR(500),
        branch_name            VARCHAR(200),
        error_message          TEXT,
        created_at             TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_transcription_prompt_proposals_run_date ON transcription_prompt_proposals (run_date)",
]

with engine.connect() as conn:
    for stmt in STATEMENTS:
        conn.execute(text(stmt))
    conn.commit()

print('✓ prompt-learning tables ensured: transcription_fill_diffs, transcription_mined_inspections, '
      'transcription_golden_fixtures, transcription_prompt_proposals')
