#!/usr/bin/env python3
"""
migrate_photos_to_s3.py
=======================
One-time script to move all base64-encoded photos out of PostgreSQL and into S3.

What it migrates
----------------
  1. clients.logo            — agency logo (base64 PNG/JPEG)
  2. properties.overview_photo — property overview photo (base64 JPEG)
  3. inspections.report_data — JSON blob containing:
       • _overview.items.photo.uri  — overview photo (may be base64 or file://)
       • <section>.<item>._photos[] — inspection room photos

How to run
----------
  Set the same env vars your Flask app uses, then:

      python migrate_photos_to_s3.py [--dry-run] [--limit N] [--table TABLE]

  Options:
    --dry-run    Print what would be migrated without writing anything
    --limit N    Only process the first N rows per table (for testing)
    --table      One of: clients, properties, inspections, all  (default: all)
    --skip-errors  Continue on per-row errors instead of aborting

  Required env vars:
    DATABASE_URL        PostgreSQL connection string (same as Flask)
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME
    (plus S3_ENDPOINT_URL and S3_PUBLIC_BASE_URL for Cloudflare R2)

Progress
--------
  The script prints one line per migrated asset and a summary at the end.
  It is safe to re-run: assets already uploaded (value starts with https://)
  are skipped automatically.
"""

import argparse
import json
import os
import sys

# ── Bootstrap Flask app so we can reuse db + models ──────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from app import create_app
from models import db, Client, Property, Inspection
from utils.s3 import is_configured, upload_base64, is_s3_url, is_base64_uri


def _parse_args():
    p = argparse.ArgumentParser(description='Migrate base64 photos → S3')
    p.add_argument('--dry-run',     action='store_true', help='No writes')
    p.add_argument('--limit',       type=int, default=None, help='Max rows per table')
    p.add_argument('--table',       default='all',
                   choices=['all', 'clients', 'properties', 'inspections'])
    p.add_argument('--skip-errors', action='store_true', help='Continue on errors')
    return p.parse_args()


# ── Counters ─────────────────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.skipped  = 0   # already S3 URL
        self.uploaded = 0
        self.errors   = 0
        self.dry_run  = 0

    def summary(self):
        print(f'\n{"─" * 50}')
        print(f'  Uploaded : {self.uploaded}')
        print(f'  Skipped  : {self.skipped}  (already S3 URLs)')
        print(f'  Dry-run  : {self.dry_run}')
        print(f'  Errors   : {self.errors}')
        print(f'{"─" * 50}\n')


stats = Stats()


def _upload(data_uri: str, key: str, label: str, dry_run: bool) -> str | None:
    """Upload one base64 data URI to S3.  Returns the public URL, or None on error."""
    if not data_uri:
        return None

    if is_s3_url(data_uri):
        stats.skipped += 1
        return data_uri   # already migrated

    if not is_base64_uri(data_uri):
        # Not a base64 data URI — might be a file:// left over; skip
        print(f'  [SKIP] {label}: not base64 ({data_uri[:60]}...)')
        stats.skipped += 1
        return None

    if dry_run:
        print(f'  [DRY-RUN] would upload {label} → s3://{key}')
        stats.dry_run += 1
        return None

    try:
        url = upload_base64(data_uri, key)
        print(f'  [OK] {label} → {url}')
        stats.uploaded += 1
        return url
    except Exception as e:
        print(f'  [ERROR] {label}: {e}', file=sys.stderr)
        stats.errors += 1
        return None


# ── Table migrations ──────────────────────────────────────────────────────────

def migrate_clients(dry_run: bool, limit: int | None, skip_errors: bool):
    print('\n── Clients (logo) ───────────────────────────────────────────')
    q = Client.query.filter(Client.logo.isnot(None))
    if limit:
        q = q.limit(limit)
    rows = q.all()
    print(f'  {len(rows)} clients with a logo')

    for client in rows:
        key = f'clients/{client.id}/logo.jpg'
        try:
            new_url = _upload(client.logo, key, f'client:{client.id} ({client.name})', dry_run)
            if new_url and new_url != client.logo:
                client.logo = new_url
                if not dry_run:
                    db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'  [ERROR] client {client.id}: {e}', file=sys.stderr)
            stats.errors += 1
            if not skip_errors:
                raise


def migrate_properties(dry_run: bool, limit: int | None, skip_errors: bool):
    print('\n── Properties (overview_photo) ──────────────────────────────')
    q = Property.query.filter(Property.overview_photo.isnot(None))
    if limit:
        q = q.limit(limit)
    rows = q.all()
    print(f'  {len(rows)} properties with an overview photo')

    for prop in rows:
        key = f'properties/{prop.id}/overview.jpg'
        try:
            new_url = _upload(prop.overview_photo, key,
                              f'property:{prop.id} ({prop.address[:40]})', dry_run)
            if new_url and new_url != prop.overview_photo:
                prop.overview_photo = new_url
                if not dry_run:
                    db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'  [ERROR] property {prop.id}: {e}', file=sys.stderr)
            stats.errors += 1
            if not skip_errors:
                raise


def migrate_inspections(dry_run: bool, limit: int | None, skip_errors: bool):
    print('\n── Inspections (report_data photos) ─────────────────────────')
    # Only inspections that actually have photos (contain "data:image")
    q = Inspection.query.filter(
        Inspection.report_data.isnot(None),
        Inspection.report_data.like('%data:image%')
    )
    if limit:
        q = q.limit(limit)
    rows = q.all()
    print(f'  {len(rows)} inspections containing base64 images')

    for inspection in rows:
        try:
            rd = json.loads(inspection.report_data)
        except (json.JSONDecodeError, TypeError):
            print(f'  [SKIP] inspection {inspection.id}: invalid JSON')
            continue

        changed  = False
        prefix   = f'inspections/{inspection.id}/photos'

        # ── Overview photo ───────────────────────────────────────────────────
        try:
            ov_item = rd.get('_overview', {}).get('items', {}).get('photo', {})
            ov_uri  = ov_item.get('uri', '')
            if is_base64_uri(ov_uri):
                key     = f'{prefix}/overview.jpg'
                new_url = _upload(ov_uri, key,
                                  f'insp:{inspection.id} overview', dry_run)
                if new_url:
                    rd['_overview']['items']['photo']['uri'] = new_url
                    changed = True
        except (KeyError, TypeError):
            pass

        # ── Room / section photos ────────────────────────────────────────────
        photo_index = 0
        for section_key, section in rd.items():
            if not isinstance(section, dict):
                continue
            for item_key, item in section.items():
                if not isinstance(item, dict):
                    continue
                photos = item.get('_photos', [])
                if not isinstance(photos, list):
                    continue
                new_photos = []
                for uri in photos:
                    if is_base64_uri(uri):
                        key     = f'{prefix}/photo_{photo_index:04d}.jpg'
                        new_url = _upload(
                            uri, key,
                            f'insp:{inspection.id} {section_key}/{item_key}[{photo_index}]',
                            dry_run
                        )
                        new_photos.append(new_url if new_url else uri)
                        if new_url:
                            changed = True
                        photo_index += 1
                    else:
                        new_photos.append(uri)
                item['_photos'] = new_photos

        if changed and not dry_run:
            try:
                inspection.report_data = json.dumps(rd)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f'  [ERROR] saving inspection {inspection.id}: {e}', file=sys.stderr)
                stats.errors += 1
                if not skip_errors:
                    raise


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = _parse_args()

    if not is_configured():
        print('ERROR: S3 is not configured. Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, '
              'and S3_BUCKET_NAME (and S3_ENDPOINT_URL / S3_PUBLIC_BASE_URL for R2).',
              file=sys.stderr)
        sys.exit(1)

    app = create_app()

    print(f'Photo migration to S3')
    print(f'  dry-run     : {args.dry_run}')
    print(f'  table       : {args.table}')
    print(f'  limit       : {args.limit or "all rows"}')
    print(f'  skip-errors : {args.skip_errors}')

    with app.app_context():
        if args.table in ('all', 'clients'):
            migrate_clients(args.dry_run, args.limit, args.skip_errors)

        if args.table in ('all', 'properties'):
            migrate_properties(args.dry_run, args.limit, args.skip_errors)

        if args.table in ('all', 'inspections'):
            migrate_inspections(args.dry_run, args.limit, args.skip_errors)

    stats.summary()

    if stats.errors > 0:
        print(f'Completed with {stats.errors} error(s). Check output above.', file=sys.stderr)
        sys.exit(1)
    else:
        print('Migration complete.')


if __name__ == '__main__':
    main()
