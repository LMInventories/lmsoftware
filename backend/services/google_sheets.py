"""
services/google_sheets.py
─────────────────────────
Google Sheets API helper for InspectPro.

Upserts a row to the master job-records spreadsheet whenever an inspection
is created or its scheduling fields change.

Column order written (must match your sheet's header row):
  A: Client | B: Clerk | C: Date | D: Reference | E: Address | F: Job | G: Size

Columns H, I (formulas) and J (tick boxes) are left untouched.
Column K is used internally to store the InspectPro inspection ID so the
correct row is always found even when the same address is used across
multiple tenancies (e.g. Check In → Check Out → new Check In).

Row lookup strategy (in priority order):
  1. Inspection ID in column K — exact, handles same-address lifecycle reuse
  2. Address (E) + job type (F) + date (C) — fallback for rows written before
     the K column was introduced

Requires:
  • Google OAuth connected with the spreadsheets scope
    (Settings → Integrations → Connect Google)
  • google_master_sheet_id saved in system settings
    (Settings → Integrations → Master Sheet ID)
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Optional

_SHEETS_BASE = 'https://sheets.googleapis.com/v4/spreadsheets'

# ── Client display-name mapping ───────────────────────────────────────────────
# Maps the stored client company/name (lower-cased) → the label to write in the
# Master Sheet.  Add new clients here as the business grows.
# For any client not listed the full stored name is used as a safe fallback.
_CLIENT_NAME_MAP: dict[str, str] = {
    'yellands estates':   'Yellands',
    'spencer james':      'Spencer James',
    'hunters camberwell': 'Hunters Camberwell',
    'hunters camden':     'Hunters Camden',
}


# ── Public entry point ────────────────────────────────────────────────────────

def sync_inspection_row(inspection) -> tuple[bool, Optional[str]]:
    """
    Upsert one row for *inspection* in the configured master Google Sheet.

    Finds the row by inspection ID (col K), falls back to address + type + date
    for legacy rows, then overwrites A:G with the latest values and stamps K
    with the inspection ID.  Appends a new row when no match is found.

    Returns (True, None) on success, (False, error_message) on any failure.
    Safe to call fire-and-forget — never raises.
    """
    if getattr(inspection, 'inspection_type', None) == 'heads_up':
        return True, None
    try:
        return _sync(inspection)
    except Exception as exc:
        return False, str(exc)


# Keep the old name so any other callers don't break
append_inspection_row = sync_inspection_row


def write_invoice_paid(inspection, paid: bool) -> tuple[bool, Optional[str]]:
    """
    Write TRUE/FALSE to column J (Invoice Paid tick box) for this inspection's row.

    Finds the row by inspection ID in column K, same as sync_inspection_row.
    Returns (True, None) on success, (False, error_message) on failure.
    Safe to call fire-and-forget — never raises.
    """
    if getattr(inspection, 'inspection_type', None) == 'heads_up':
        return True, None
    try:
        return _write_invoice_paid(inspection, paid)
    except Exception as exc:
        return False, str(exc)


def _write_invoice_paid(inspection, paid: bool) -> tuple[bool, Optional[str]]:
    from routes.google import get_valid_access_token

    sheet_id = _get_sheet_id()
    if not sheet_id:
        return False, 'google_master_sheet_id not configured'

    token = get_valid_access_token()
    if not token:
        return False, 'Google not connected (no valid access token)'

    try:
        target_row = _find_existing_row(sheet_id, token, inspection)
    except Exception as exc:
        return False, f'row lookup failed: {exc}'

    if target_row is None:
        return False, f'no sheet row found for inspection {inspection.id}'

    target_range = f'J{target_row}'
    url = f'{_SHEETS_BASE}/{sheet_id}/values/{target_range}?valueInputOption=USER_ENTERED'
    payload = json.dumps({
        'range':  target_range,
        'values': [['TRUE' if paid else 'FALSE']],
    }).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        method='PUT',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        print(f'[sheets] invoice_paid={paid} written to J{target_row} for inspection {inspection.id}')
        return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return False, f'Sheets PUT {e.code}: {body[:400]}'
    except Exception as exc:
        return False, str(exc)


# ── Internal ──────────────────────────────────────────────────────────────────

def _get_sheet_id() -> Optional[str]:
    from models import SystemSetting
    row = SystemSetting.query.filter_by(key='google_master_sheet_id').first()
    return (row.value or '').strip() if row else None


def _build_row(inspection) -> list:
    """
    Return cell values in the agreed column order:
    A: Client | B: Clerk | C: Date | D: Reference | E: Address | F: Job | G: Size
    """
    prop   = inspection.property
    client = prop.client if prop else None
    client_name = ''
    if client:
        full = (client.company or client.name or '').strip()
        client_name = _CLIENT_NAME_MAP.get(full.lower(), full) if full else ''

    clerk_full = inspection.inspector.name if inspection.inspector else ''
    clerk_name = clerk_full.split()[0] if clerk_full else ''

    date_obj = inspection.conduct_date or inspection.scheduled_date
    date_str = date_obj.strftime('%d/%m/%Y') if date_obj else ''

    ref = (inspection.reference_number or '').strip() or f'INS-{inspection.id}'

    address = prop.address if prop else ''

    type_map = {
        'check_in':      'Inventory & Check In',
        'check_out':     'Check Out',
        'midterm':       'Midterm',
        'damage_report': 'Damage Report',
    }
    job = type_map.get(inspection.inspection_type or '', inspection.inspection_type or '')

    bedrooms = prop.bedrooms if prop else None
    size = str(bedrooms) if bedrooms is not None else ''

    return [client_name, clerk_name, date_str, ref, address, job, size]


def _job_for(inspection_type: str) -> str:
    type_map = {
        'check_in':      'Inventory & Check In',
        'check_out':     'Check Out',
        'midterm':       'Midterm',
        'damage_report': 'Damage Report',
    }
    return type_map.get(inspection_type or '', inspection_type or '')


def _find_existing_row(sheet_id: str, token: str, inspection) -> Optional[int]:
    """
    Return the 1-based sheet row number that belongs to this inspection.

    Pass 1 — scan column K for the inspection ID.  This correctly handles
    property lifecycle reuse (same address, same type, different tenancy)
    because each inspection has a unique ID regardless of address or type.

    Pass 2 — fallback for rows written before the K column was introduced.
    Matches on address (E) + job type (F) + date (C).  Only used when no
    ID match is found; date is included here specifically to avoid the
    lifecycle problem (different dates = different tenancy = different row).
    """
    url = f'{_SHEETS_BASE}/{sheet_id}/values/A:K'
    req = urllib.request.Request(
        url,
        headers={'Authorization': f'Bearer {token}'},
        method='GET',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    rows = data.get('values', [])

    insp_id_str = str(inspection.id)

    prop     = inspection.property
    address  = (prop.address if prop else '').strip().lower()
    job      = _job_for(inspection.inspection_type or '').lower()
    date_obj = inspection.conduct_date or inspection.scheduled_date
    date_str = date_obj.strftime('%d/%m/%Y') if date_obj else ''

    fallback_row: Optional[int] = None

    # Skip header row (index 0 = sheet row 1)
    for row_idx, row in enumerate(rows[1:], start=2):
        padded = row + [''] * max(0, 11 - len(row))

        # Pass 1: inspection ID in column K (index 10)
        if str(padded[10]).strip() == insp_id_str:
            return row_idx

        # Pass 2: address + type + date (legacy rows without an ID stamp)
        if fallback_row is None and date_str:
            row_date    = str(padded[2]).strip()        # col C
            row_address = str(padded[4]).strip().lower() # col E
            row_job     = str(padded[5]).strip().lower() # col F
            if row_date == date_str and row_address == address and row_job == job:
                fallback_row = row_idx

    return fallback_row


def _get_next_row(sheet_id: str, token: str) -> int:
    """
    Read column A to find the last populated cell, then return the next row
    number.  Starts at row 2 (row 1 is the header).
    """
    url = f'{_SHEETS_BASE}/{sheet_id}/values/A:A'
    req = urllib.request.Request(
        url,
        headers={'Authorization': f'Bearer {token}'},
        method='GET',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    values    = data.get('values', [])
    populated = sum(1 for r in values if r and str(r[0]).strip())
    return max(2, populated + 1)


def _write_row(sheet_id: str, token: str, row_number: int,
               row_data: list) -> tuple[bool, Optional[str]]:
    """PUT row_data into columns A:G of the given 1-based row."""
    target_range = f'A{row_number}:G{row_number}'
    url = (
        f'{_SHEETS_BASE}/{sheet_id}/values/{target_range}'
        f'?valueInputOption=USER_ENTERED'
    )
    payload = json.dumps({'range': target_range, 'values': [row_data]}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        method='PUT',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return True, result.get('updatedRange', target_range)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return False, f'Sheets PUT {e.code}: {body[:400]}'
    except Exception as exc:
        return False, str(exc)


def _stamp_inspection_id(sheet_id: str, token: str,
                         row_number: int, inspection_id: int) -> None:
    """
    Write the inspection ID to column K of the given row.
    Issued as a separate PUT so that H:J (formulas + tick box) are untouched.
    Failures are non-fatal — the visible data in A:G was already written.
    """
    target_range = f'K{row_number}'
    url = f'{_SHEETS_BASE}/{sheet_id}/values/{target_range}?valueInputOption=RAW'
    payload = json.dumps({'range': target_range,
                          'values': [[str(inspection_id)]]}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        method='PUT',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _sync(inspection) -> tuple[bool, Optional[str]]:
    from routes.google import get_valid_access_token

    sheet_id = _get_sheet_id()
    if not sheet_id:
        return False, 'google_master_sheet_id not configured'

    token = get_valid_access_token()
    if not token:
        return False, 'Google not connected (no valid access token)'

    row_data = _build_row(inspection)

    # ── Find existing row (by ID, then by address+type+date fallback) ────────
    try:
        target_row = _find_existing_row(sheet_id, token, inspection)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        msg  = f'Sheets GET {e.code}: {body[:400]}'
        print(f'[sheets] ERROR searching for existing row: {msg}')
        return False, msg
    except Exception as exc:
        print(f'[sheets] ERROR searching for existing row: {exc}')
        return False, str(exc)

    action = 'updated' if target_row is not None else 'appended'

    # ── Find next empty row if this is a new entry ───────────────────────────
    if target_row is None:
        try:
            target_row = _get_next_row(sheet_id, token)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            msg  = f'Sheets GET {e.code}: {body[:400]}'
            print(f'[sheets] ERROR reading next row: {msg}')
            return False, msg
        except Exception as exc:
            print(f'[sheets] ERROR reading next row: {exc}')
            return False, str(exc)

    # ── Write A:G ────────────────────────────────────────────────────────────
    ok, detail = _write_row(sheet_id, token, target_row, row_data)
    if not ok:
        print(f'[sheets] ERROR writing row {target_row}: {detail}')
        return False, detail

    # ── Stamp inspection ID into column K (separate call — leaves H:J alone) ─
    try:
        _stamp_inspection_id(sheet_id, token, target_row, inspection.id)
    except Exception as exc:
        print(f'[sheets] WARNING: could not stamp inspection ID to K{target_row}: {exc}')

    print(f'[sheets] {action} row {target_row} in sheet {sheet_id} '
          f'for inspection {inspection.id}')
    return True, None
