"""
services/google_sheets.py
─────────────────────────
Google Sheets API helper for InspectPro.

Upserts a row to the master job-records spreadsheet whenever an inspection
is created or its scheduling fields change.

Column order written (must match your sheet's header row):
  A: Client | B: Clerk | C: Date | D: Reference | E: Address | F: Job | G: Size

Columns H, I (formulas) and J (invoice paid) are left untouched when a row is written.
Column K is used internally to store the InspectPro inspection ID so the
correct row is always found even when the same address is used across
multiple tenancies (e.g. Check In → Check Out → new Check In).

Row lookup strategy (in priority order):
  1. Inspection ID in column K — exact, handles same-address lifecycle reuse
  2. Address (E) + job type (F) + date (C) — fallback for rows written before
     the K column was introduced

Year tabs
─────────
With "YEAR TABS | ON" on the sheet's Settings tab, rows live in one tab per
calendar year, named "2025", "2026", …:
  • a job is written to the tab for the year of its date (or the latest earlier
    year tab if that one doesn't exist yet);
  • lookups search every year tab, and a job whose date moves to another year has
    its whole row (A:Z, so fees, paid and automation flags too) moved with it;
  • invoice paid is written as a tick box value (TRUE / FALSE).
With the setting off or missing, everything targets the first tab and invoice
paid is written as "YES" / blank.

Requires:
  • Google OAuth connected with the spreadsheets scope
    (Settings → Integrations → Connect Google)
  • google_master_sheet_id saved in system settings
    (Settings → Integrations → Master Sheet ID)
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import urllib.error
from datetime import date
from typing import Optional

_SHEETS_BASE = 'https://sheets.googleapis.com/v4/spreadsheets'
_YEAR_TAB = re.compile(r'^20\d\d$')
_ROW_WIDTH = 26  # A:Z travels with a row when it moves between year tabs

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

def sync_inspection_row(inspection, layout: Optional[list] = None) -> tuple[bool, Optional[str]]:
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
    if getattr(inspection, 'pdf_import', False):
        return True, None
    try:
        return _sync(inspection, layout)
    except Exception as exc:
        return False, str(exc)


# Keep the old name so any other callers don't break
append_inspection_row = sync_inspection_row


def delete_inspection_row(inspection) -> tuple[bool, Optional[str]]:
    """
    Delete this inspection's row from the master sheet (found via the column K
    stamp / legacy address+type+date fallback, same lookup used by sync).

    Returns (True, detail) if a row was deleted or none was found (nothing to
    do isn't a failure). Returns (False, error_message) only on an actual API
    error. Safe to call fire-and-forget — never raises.
    """
    try:
        return _delete_row(inspection)
    except Exception as exc:
        return False, str(exc)


def write_invoice_paid(inspection, paid: bool) -> tuple[bool, Optional[str]]:
    """
    Write YES/blank to column J for this inspection's row.
    Returns (True, detail) on success, (False, error_message) on failure.
    Safe to call fire-and-forget — never raises.
    """
    if getattr(inspection, 'inspection_type', None) == 'heads_up':
        return True, 'skipped: heads_up inspection type'
    try:
        return _write_invoice_paid(inspection, paid)
    except Exception as exc:
        return False, str(exc)


def get_sheet_layout() -> tuple[Optional[list], Optional[str]]:
    """
    The year tabs ([] when the sheet isn't split by year), for callers that sync many
    rows in one go: pass the result to sync_inspection_row so it is read only once.
    Returns (layout, None) on success, (None, error_message) on failure.
    """
    sheet_id = _get_sheet_id()
    if not sheet_id:
        return None, 'Master Sheet ID is not configured'
    from routes.google import get_valid_access_token
    token = get_valid_access_token()
    if not token:
        return None, 'could not obtain Google access token — check OAuth connection'
    try:
        return _year_tabs(sheet_id, token), None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return None, f'Sheets GET {e.code}: {body[:400]}'
    except Exception as exc:
        return None, str(exc)


def get_existing_reference_numbers() -> tuple[Optional[set], Optional[str]]:
    """
    Return the set of reference numbers (lower-cased) already present in
    column D of the master sheet, via a single bulk read.

    Returns (set, None) on success, (None, error_message) if the sheet
    couldn't be read (not configured / not connected / API error).
    """
    from routes.google import get_valid_access_token

    sheet_id = _get_sheet_id()
    if not sheet_id:
        return None, 'google_master_sheet_id not configured'

    token = get_valid_access_token()
    if not token:
        return None, 'Google not connected (no valid access token)'

    try:
        tabs = _year_tabs(sheet_id, token)
        ranges = [_a1(tab, 'D:D') for tab in tabs] if tabs else ['D:D']
        columns = _read(sheet_id, token, ranges)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return None, f'Sheets GET {e.code}: {body[:400]}'
    except Exception as exc:
        return None, str(exc)

    refs = {str(row[0]).strip().lower() for rows in columns for row in rows[1:] if row and row[0]}
    return refs, None


def _row_with_reference(rows: list, reference: str, column: int = 0) -> Optional[int]:
    """Return the 1-based row number whose `column` matches the given reference number."""
    ref = reference.strip().lower()
    for row_idx, row in enumerate(rows[1:], start=2):  # skip header
        if len(row) > column and str(row[column]).strip().lower() == ref:
            return row_idx
    return None


def _write_invoice_paid(inspection, paid: bool) -> tuple[bool, Optional[str]]:
    from routes.google import get_valid_access_token

    sheet_id = _get_sheet_id()
    if not sheet_id:
        return False, 'google_master_sheet_id not configured'

    token = get_valid_access_token()
    if not token:
        return False, 'Google not connected (no valid access token)'

    reference = (inspection.reference_number or '').strip()
    if not reference:
        return False, f'inspection {inspection.id} has no reference number'

    try:
        tabs = _year_tabs(sheet_id, token)
        tab, target_row = None, None
        if tabs:
            tables = _read(sheet_id, token, [_a1(t, 'A:K') for t in tabs])
            # The inspection ID is exact; fall back to the reference for rows without one.
            for column, wanted in ((10, str(inspection.id)), (3, reference)):
                for candidate, rows in zip(tabs, tables):
                    target_row = _row_with_reference(rows, wanted, column)
                    if target_row:
                        tab = candidate
                        break
                if target_row:
                    break
        else:
            target_row = _row_with_reference(_read(sheet_id, token, ['D:D'])[0], reference)
    except Exception as exc:
        return False, f'row lookup failed: {exc}'

    if target_row is None:
        return False, f'no row found in column D for reference "{reference}"'

    cell = _a1(tab, f'J{target_row}')
    value = bool(paid) if tab else ('YES' if paid else '')
    try:
        _put(sheet_id, token, cell, [[value]], 'RAW')
        msg = f'wrote {"YES" if paid else "blank"} to {cell} (ref {reference})'
        print(f'[sheets] invoice_paid: {msg}')
        return True, msg
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


def _call(token: str, method: str, url: str, payload: Optional[dict] = None, timeout: int = 15) -> dict:
    headers = {'Authorization': f'Bearer {token}'}
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body) if body else {}


def _a1(tab: Optional[dict], cells: str) -> str:
    """A range on `tab`, or on the first tab when tab is None."""
    return f"'{tab['title']}'!{cells}" if tab else cells


def _path(a1: str) -> str:
    return urllib.parse.quote(a1, safe=':')


def _read(sheet_id: str, token: str, ranges: list) -> list:
    """The values of each range, in order (a list of rows per range)."""
    if len(ranges) == 1:
        data = _call(token, 'GET', f'{_SHEETS_BASE}/{sheet_id}/values/{_path(ranges[0])}')
        return [data.get('values', [])]
    query = urllib.parse.urlencode([('ranges', r) for r in ranges])
    data = _call(token, 'GET', f'{_SHEETS_BASE}/{sheet_id}/values:batchGet?{query}')
    return [item.get('values', []) for item in data.get('valueRanges', [])]


def _put(sheet_id: str, token: str, a1: str, values: list, how: str) -> dict:
    return _call(token, 'PUT', f'{_SHEETS_BASE}/{sheet_id}/values/{_path(a1)}?valueInputOption={how}',
                 {'range': a1, 'values': values})


def _tab_properties(sheet_id: str, token: str) -> list:
    data = _call(token, 'GET', f'{_SHEETS_BASE}/{sheet_id}?fields=sheets.properties')
    return [sheet['properties'] for sheet in data.get('sheets', [])]


def _year_tabs(sheet_id: str, token: str) -> list:
    """The year tabs, oldest first, when the sheet's "YEAR TABS" setting is ON; otherwise [].

    Any failure to read the setting raises: guessing could write a job to the wrong tab."""
    tabs = _tab_properties(sheet_id, token)
    on = False
    if any(t['title'] == 'Settings' for t in tabs):
        rows = _read(sheet_id, token, ['Settings!A:B'])[0]
        on = any(len(r) > 1 and str(r[0]).strip().upper() == 'YEAR TABS' and str(r[1]).strip().upper() == 'ON'
                 for r in rows)
    if not on:
        if tabs and tabs[0]['title'] == 'Dashboard':
            raise RuntimeError('the sheet has been arranged by year but "YEAR TABS" is not ON in its Settings tab')
        return []
    years = sorted((t for t in tabs if _YEAR_TAB.match(t['title'])), key=lambda t: t['title'])
    if not years:
        raise RuntimeError('"YEAR TABS" is ON but there are no year tabs')
    return years


def _tab_for_year(tabs: list, year: int) -> dict:
    """The tab for `year`, else the latest earlier one, else the oldest."""
    earlier = [t for t in tabs if int(t['title']) <= year]
    return earlier[-1] if earlier else tabs[0]


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

    job = _job_for(inspection.inspection_type, inspection)

    bedrooms = prop.bedrooms if prop else None
    size = str(bedrooms) if bedrooms is not None else ''

    return [client_name, clerk_name, date_str, ref, address, job, size]


def _update_ci_enabled(inspection) -> bool:
    """
    True when this is a Check In worked from a previous Check Out report and
    the client has "Update CI" enabled (report_photo_settings.sheet_update_ci).
    """
    if getattr(inspection, 'inspection_type', None) not in ('check_in', 'inventory'):
        return False
    source_id = getattr(inspection, 'source_inspection_id', None)
    if not source_id:
        return False

    prop   = inspection.property
    client = prop.client if prop else None
    try:
        ps = json.loads(client.report_photo_settings or '{}') if client else {}
    except (TypeError, ValueError):
        return False
    if not isinstance(ps, dict) or ps.get('sheet_update_ci') is not True:
        return False

    from models import Inspection, db
    source = db.session.get(Inspection, source_id)
    return bool(source and source.inspection_type == 'check_out')


def _job_for(inspection_type: str, inspection=None) -> str:
    type_map = {
        'check_in':      'Inventory & Check In',
        'inventory':     'Inventory & Check In',
        'check_out':     'Check Out',
        'midterm':       'Midterm',
        'damage_report': 'Damage Report',
    }
    if inspection is not None and _update_ci_enabled(inspection):
        return 'Update CI'
    return type_map.get(inspection_type or '', inspection_type or '')


def _find_in_rows(rows: list, inspection) -> tuple[Optional[int], bool]:
    """
    (1-based row number, matched by ID) for this inspection within one tab's A:K values.

    Pass 1 — scan column K for the inspection ID.  This correctly handles
    property lifecycle reuse (same address, same type, different tenancy)
    because each inspection has a unique ID regardless of address or type.

    Pass 2 — fallback for rows written before the K column was introduced.
    Matches on address (E) + job type (F) + date (C).  Only used when no
    ID match is found; date is included here specifically to avoid the
    lifecycle problem (different dates = different tenancy = different row).
    """
    insp_id_str = str(inspection.id)

    prop     = inspection.property
    address  = (prop.address if prop else '').strip().lower()
    job      = _job_for(inspection.inspection_type or '', inspection).lower()
    date_obj = inspection.conduct_date or inspection.scheduled_date
    date_str = date_obj.strftime('%d/%m/%Y') if date_obj else ''

    fallback_row: Optional[int] = None

    # Skip header row (index 0 = sheet row 1)
    for row_idx, row in enumerate(rows[1:], start=2):
        padded = row + [''] * max(0, 11 - len(row))

        # Pass 1: inspection ID in column K (index 10)
        if str(padded[10]).strip() == insp_id_str:
            return row_idx, True

        # Pass 2: address + type + date (legacy rows without an ID stamp)
        if fallback_row is None and date_str:
            row_date    = str(padded[2]).strip()        # col C
            row_address = str(padded[4]).strip().lower() # col E
            row_job     = str(padded[5]).strip().lower() # col F
            if row_date == date_str and row_address == address and row_job == job:
                fallback_row = row_idx

    return fallback_row, False


def _find_existing_row(sheet_id: str, token: str, inspection, tabs: list) -> tuple[Optional[dict], Optional[int]]:
    """(tab, row number) of this inspection's row: an ID match on any tab beats a legacy match.
    tab is None for the first-tab (not split by year) layout."""
    if not tabs:
        return None, _find_in_rows(_read(sheet_id, token, ['A:K'])[0], inspection)[0]
    fallback = (None, None)
    for tab, rows in zip(tabs, _read(sheet_id, token, [_a1(t, 'A:K') for t in tabs])):
        row, by_id = _find_in_rows(rows, inspection)
        if by_id:
            return tab, row
        if row and fallback[1] is None:
            fallback = (tab, row)
    return fallback


def _get_next_row(sheet_id: str, token: str, tab: Optional[dict] = None) -> int:
    """
    Return the row after the last row holding real data (A:G or the K ID
    stamp; H:J formulas are ignored).  Starts at row 2 (row 1 is the header).

    Uses the last populated row index rather than a count of non-blank
    cells in column A — a blank client name or a gap would otherwise keep
    the count static and every new inspection would overwrite the same row.
    """
    values = _read(sheet_id, token, [_a1(tab, 'A:K')])[0]
    last = 1
    for idx, r in enumerate(values, start=1):
        cells = list(r[:7]) + ([r[10]] if len(r) > 10 else [])
        if any(str(c).strip() for c in cells):
            last = idx
    return last + 1


def _write_row(sheet_id: str, token: str, row_number: int,
               row_data: list, tab: Optional[dict] = None) -> tuple[bool, Optional[str]]:
    """PUT row_data into columns A:G of the given 1-based row."""
    target_range = _a1(tab, f'A{row_number}:G{row_number}')
    try:
        result = _put(sheet_id, token, target_range, [row_data], 'USER_ENTERED')
        return True, result.get('updatedRange', target_range)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return False, f'Sheets PUT {e.code}: {body[:400]}'
    except Exception as exc:
        return False, str(exc)


def _stamp_inspection_id(sheet_id: str, token: str, row_number: int,
                         inspection_id: int, tab: Optional[dict] = None) -> None:
    """
    Write the inspection ID to column K of the given row.
    Issued as a separate PUT so that H:J (formulas + tick box) are untouched.
    Failures are non-fatal — the visible data in A:G was already written.
    """
    _put(sheet_id, token, _a1(tab, f'K{row_number}'), [[str(inspection_id)]], 'RAW')


def _grow_requests(tab: dict, row_number: int) -> list:
    """Requests that add rows to `tab` if `row_number` is below its last row."""
    grid = tab.setdefault('gridProperties', {})
    missing = row_number - grid.get('rowCount', row_number)
    if missing <= 0:
        return []
    grid['rowCount'] = row_number
    return [{'appendDimension': {'sheetId': tab['sheetId'], 'dimension': 'ROWS', 'length': missing}}]


def _delete_request(tab_id: int, row_number: int) -> dict:
    return {'deleteDimension': {'range': {
        'sheetId': tab_id, 'dimension': 'ROWS',
        'startIndex': row_number - 1, 'endIndex': row_number,
    }}}


def _move_row(sheet_id: str, token: str, source: dict, row_number: int, target: dict) -> int:
    """Move a whole row to the next free row of another tab, in one atomic request, so fees,
    paid and the automation's "sent" flags go with it. Returns the new row number."""
    new_row = _get_next_row(sheet_id, token, target)
    requests = _grow_requests(target, new_row)

    def whole_row(tab, number):
        return {'sheetId': tab['sheetId'], 'startRowIndex': number - 1, 'endRowIndex': number,
                'startColumnIndex': 0, 'endColumnIndex': _ROW_WIDTH}

    requests.append({'copyPaste': {'source': whole_row(source, row_number),
                                   'destination': whole_row(target, new_row), 'pasteType': 'PASTE_NORMAL'}})
    requests.append(_delete_request(source['sheetId'], row_number))
    _call(token, 'POST', f'{_SHEETS_BASE}/{sheet_id}:batchUpdate', {'requests': requests})
    return new_row


def _get_first_sheet_tab_id(sheet_id: str, token: str) -> int:
    """Return the numeric sheetId (gid) of the first tab — the tab unprefixed
    ranges implicitly target."""
    return _tab_properties(sheet_id, token)[0]['sheetId']


def _delete_row(inspection) -> tuple[bool, Optional[str]]:
    from routes.google import get_valid_access_token

    sheet_id = _get_sheet_id()
    if not sheet_id:
        return False, 'google_master_sheet_id not configured'

    token = get_valid_access_token()
    if not token:
        return False, 'Google not connected (no valid access token)'

    try:
        tab, target_row = _find_existing_row(sheet_id, token, inspection, _year_tabs(sheet_id, token))
    except Exception as exc:
        return False, f'row lookup failed: {exc}'

    if target_row is None:
        return True, f'no matching row for inspection {inspection.id}'

    try:
        tab_id = tab['sheetId'] if tab else _get_first_sheet_tab_id(sheet_id, token)
    except Exception as exc:
        return False, f'could not resolve sheet tab id: {exc}'

    try:
        _call(token, 'POST', f'{_SHEETS_BASE}/{sheet_id}:batchUpdate',
              {'requests': [_delete_request(tab_id, target_row)]})
        msg = f'deleted row {target_row} (inspection {inspection.id})'
        print(f'[sheets] {msg}')
        return True, msg
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return False, f'Sheets batchUpdate {e.code}: {body[:400]}'
    except Exception as exc:
        return False, str(exc)


def _sync(inspection, layout: Optional[list] = None) -> tuple[bool, Optional[str]]:
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
        tabs = _year_tabs(sheet_id, token) if layout is None else layout
        tab, target_row = _find_existing_row(sheet_id, token, inspection, tabs)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        msg  = f'Sheets GET {e.code}: {body[:400]}'
        print(f'[sheets] ERROR searching for existing row: {msg}')
        return False, msg
    except Exception as exc:
        print(f'[sheets] ERROR searching for existing row: {exc}')
        return False, str(exc)

    action = 'updated' if target_row is not None else 'appended'
    date_obj = inspection.conduct_date or inspection.scheduled_date

    # ── Year tabs: choose the tab, moving the row if the job changed year ────
    if tabs:
        if date_obj:
            wanted = _tab_for_year(tabs, date_obj.year)
        else:  # undated: leave it where it is, or file it under the current year
            wanted = tab or _tab_for_year(tabs, date.today().year)
        if target_row is not None and wanted['sheetId'] != tab['sheetId']:
            try:
                target_row = _move_row(sheet_id, token, tab, target_row, wanted)
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', errors='replace')
                msg  = f'Sheets move {e.code}: {body[:400]}'
                print(f'[sheets] ERROR moving row to {wanted["title"]}: {msg}')
                return False, msg
            except Exception as exc:
                print(f'[sheets] ERROR moving row to {wanted["title"]}: {exc}')
                return False, str(exc)
            action = f'moved to {wanted["title"]} and updated'
        tab = wanted

    # ── Find next empty row if this is a new entry ───────────────────────────
    if target_row is None:
        try:
            target_row = _get_next_row(sheet_id, token, tab)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            msg  = f'Sheets GET {e.code}: {body[:400]}'
            print(f'[sheets] ERROR reading next row: {msg}')
            return False, msg
        except Exception as exc:
            print(f'[sheets] ERROR reading next row: {exc}')
            return False, str(exc)

    if tab:
        try:
            requests = _grow_requests(tab, target_row)
            if requests:
                _call(token, 'POST', f'{_SHEETS_BASE}/{sheet_id}:batchUpdate', {'requests': requests})
        except Exception as exc:
            print(f'[sheets] ERROR adding rows to {tab["title"]}: {exc}')
            return False, str(exc)

    # ── Write A:G ────────────────────────────────────────────────────────────
    ok, detail = _write_row(sheet_id, token, target_row, row_data, tab)
    if not ok:
        print(f'[sheets] ERROR writing row {target_row}: {detail}')
        return False, detail

    # ── Stamp inspection ID into column K (separate call — leaves H:J alone) ─
    try:
        _stamp_inspection_id(sheet_id, token, target_row, inspection.id, tab)
    except Exception as exc:
        print(f'[sheets] WARNING: could not stamp inspection ID to K{target_row}: {exc}')

    print(f'[sheets] {action} row {target_row} in sheet {sheet_id} '
          f'for inspection {inspection.id}')
    return True, None
