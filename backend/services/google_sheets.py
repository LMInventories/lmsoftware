"""
services/google_sheets.py
─────────────────────────
Google Sheets API helper for InspectPro.

Appends a new row to the master job-records spreadsheet whenever an
inspection is created.

Column order written (must match your sheet's header row):
  A: Client | B: Clerk | C: Date | D: Reference | E: Address | F: Job | G: Size

Columns H, I (formulas) and J (tick boxes) are left untouched — the row is
written by looking up the last non-empty cell in column A and targeting the
very next row explicitly, so Sheets formulas in H:J never interfere.

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


# ── Public entry point ────────────────────────────────────────────────────────

def append_inspection_row(inspection) -> tuple[bool, Optional[str]]:
    """
    Append one row for *inspection* to the configured master Google Sheet.

    Returns (True, None) on success, (False, error_message) on any failure.
    Safe to call fire-and-forget — never raises.
    """
    try:
        return _append(inspection)
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
    # Client — prefer company name, fall back to contact name
    prop = inspection.property
    client = prop.client if prop else None
    client_name = ''
    if client:
        client_name = (client.company or client.name or '').strip()

    # Clerk
    clerk_name = inspection.inspector.name if inspection.inspector else ''

    # Date — prefer conduct_date, fall back to scheduled_date
    date_obj = inspection.conduct_date or inspection.scheduled_date
    date_str = date_obj.strftime('%d/%m/%Y') if date_obj else ''

    # Reference
    ref = (inspection.reference_number or '').strip() or f'INS-{inspection.id}'

    # Address
    address = prop.address if prop else ''

    # Job type — exact labels expected by master sheet formulas
    type_map = {
        'check_in':      'Inventory & Check In',
        'check_out':     'Check Out',
        'midterm':       'Midterm',
        'damage_report': 'Damage Report',
    }
    job = type_map.get(inspection.inspection_type or '', inspection.inspection_type or '')

    # Size (bedrooms)
    bedrooms = prop.bedrooms if prop else None
    size = str(bedrooms) if bedrooms is not None else ''

    return [client_name, clerk_name, date_str, ref, address, job, size]


def _get_next_row(sheet_id: str, token: str) -> int:
    """
    Read column A to find the last populated cell, then return the next row
    number. Starts at row 2 (row 1 is assumed to be the header).

    This avoids the Sheets :append endpoint treating formula-filled cells in
    columns H/I/J as "table data" and inserting the row in the wrong place.
    """
    url = f'{_SHEETS_BASE}/{sheet_id}/values/A:A'
    req = urllib.request.Request(
        url,
        headers={'Authorization': f'Bearer {token}'},
        method='GET',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    values = data.get('values', [])
    # values is a list of rows; each row is a list with one element (or empty).
    # Count how many rows have any content in column A.
    populated = sum(1 for r in values if r and str(r[0]).strip())
    # Next row is one past the last populated row, minimum row 2.
    return max(2, populated + 1)


def _append(inspection) -> tuple[bool, Optional[str]]:
    from routes.google import get_valid_access_token

    # Prerequisites
    sheet_id = _get_sheet_id()
    if not sheet_id:
        return False, 'google_master_sheet_id not configured'

    token = get_valid_access_token()
    if not token:
        return False, 'Google not connected (no valid access token)'

    row_data = _build_row(inspection)

    # Find the target row by inspecting column A -- safe even when H:J have
    # formulas or tick boxes that would confuse the :append heuristic.
    try:
        next_row = _get_next_row(sheet_id, token)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        msg = f'Sheets GET {e.code}: {body[:400]}'
        print(f'[sheets] ERROR reading next row: {msg}')
        return False, msg
    except Exception as exc:
        print(f'[sheets] ERROR reading next row: {exc}')
        return False, str(exc)

    target_range = f'A{next_row}:G{next_row}'

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
        updated = result.get('updatedRows', 0)
        print(f'[sheets] wrote {updated} row(s) at {target_range} in sheet {sheet_id} for inspection {inspection.id}')
        return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        msg = f'Sheets PUT {e.code}: {body[:400]}'
        print(f'[sheets] ERROR writing row: {msg}')
        return False, msg
    except Exception as exc:
        print(f'[sheets] ERROR writing row: {exc}')
        return False, str(exc)
