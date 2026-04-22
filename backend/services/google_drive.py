"""
services/google_drive.py
─────────────────────────
Upload completed inspection PDF reports to Google Drive.

Folder structure created automatically:
  InspectPro Reports/
    {Client Name}/
      {Property Address}/
        {inspection_type}_{date}_{inspection_id}.pdf

Called automatically from routes/inspections.py after a report is marked
complete and the PDF is generated — only if Google Drive is connected.

Usage:
    from services.google_drive import upload_report, is_drive_connected
    if is_drive_connected():
        ok, result = upload_report(inspection, pdf_bytes)
"""

from __future__ import annotations

import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional


_DRIVE_UPLOAD_URL = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart'
_DRIVE_FILES_URL  = 'https://www.googleapis.com/drive/v3/files'


# ── Connection check ──────────────────────────────────────────────────────────

def is_drive_connected() -> bool:
    """True if Google is connected and the drive scope was granted."""
    try:
        from routes.google import is_connected, _load_tokens
        if not is_connected():
            return False
        tokens = _load_tokens()
        return 'drive' in tokens.get('google_scopes', '')
    except Exception:
        return False


# ── Internal Drive API helpers ────────────────────────────────────────────────

def _api_request(method: str, url: str, access_token: str,
                 body: bytes | None = None,
                 content_type: str = 'application/json') -> dict:
    """Make an authenticated Drive API request. Returns parsed JSON."""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept':        'application/json',
    }
    if body is not None:
        headers['Content-Type'] = content_type

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _find_or_create_folder(name: str, parent_id: Optional[str],
                            access_token: str) -> str:
    """
    Find a Drive folder by name (under parent_id if given), or create it.
    Returns the folder's Drive file ID.
    """
    # Build search query
    q_parts = [
        "mimeType='application/vnd.google-apps.folder'",
        f"name='{name.replace(chr(39), chr(39)*2)}'",  # escape single quotes
        'trashed=false',
    ]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")
    q = ' and '.join(q_parts)

    search_url = (
        f'{_DRIVE_FILES_URL}?'
        + urllib.parse.urlencode({
            'q':      q,
            'fields': 'files(id,name)',
            'spaces': 'drive',
        })
    )

    try:
        result = _api_request('GET', search_url, access_token)
        files = result.get('files', [])
        if files:
            return files[0]['id']
    except Exception as e:
        print(f'[google_drive] folder search error: {e}')

    # Not found — create it
    metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        metadata['parents'] = [parent_id]

    body = json.dumps(metadata).encode()
    result = _api_request('POST', _DRIVE_FILES_URL, access_token, body=body)
    return result['id']


def _multipart_upload(filename: str, pdf_bytes: bytes,
                      folder_id: str, access_token: str) -> dict:
    """
    Upload a PDF to Drive using multipart upload (metadata + file in one request).
    Returns the created file resource.
    """
    metadata = {
        'name':    filename,
        'parents': [folder_id],
    }
    meta_json = json.dumps(metadata).encode()

    boundary = b'--inspectpro_boundary_abc123'
    body = (
        boundary + b'\r\n'
        + b'Content-Type: application/json; charset=UTF-8\r\n\r\n'
        + meta_json + b'\r\n'
        + boundary + b'\r\n'
        + b'Content-Type: application/pdf\r\n\r\n'
        + pdf_bytes + b'\r\n'
        + boundary + b'--'
    )

    content_type = f'multipart/related; boundary={boundary[2:].decode()}'
    return _api_request(
        'POST', _DRIVE_UPLOAD_URL, access_token,
        body=body, content_type=content_type,
    )


# ── Public upload function ────────────────────────────────────────────────────

def upload_report(inspection, pdf_bytes: bytes) -> tuple[bool, str]:
    """
    Upload a completed inspection PDF to the connected Google Drive account.

    Folder structure:
      InspectPro Reports / {Client Name} / {Property Address} / {filename}.pdf

    Returns:
      (True, drive_file_url)   on success
      (False, error_message)   on failure
    """
    from routes.google import get_valid_access_token

    access_token = get_valid_access_token()
    if not access_token:
        return False, 'Google not connected or token refresh failed'

    try:
        prop   = inspection.property
        client = prop.client if prop else None

        client_name  = (client.name  if client else 'Unknown Client').strip()
        address      = (prop.address if prop   else 'Unknown Property').strip()
        # Truncate address to keep folder names reasonable
        address_short = address[:60] if len(address) > 60 else address

        # Build filename: e.g. check_in_2026-04-22_inspection_42.pdf
        date_str = (
            inspection.conduct_date.strftime('%Y-%m-%d')
            if inspection.conduct_date else 'undated'
        )
        insp_type = (inspection.inspection_type or 'inspection').replace(' ', '_')
        filename  = f'{insp_type}_{date_str}_id{inspection.id}.pdf'

        # ── Ensure folder hierarchy exists ────────────────────────────────────
        root_id     = _find_or_create_folder('InspectPro Reports', None, access_token)
        client_id_  = _find_or_create_folder(client_name,   root_id,  access_token)
        prop_id     = _find_or_create_folder(address_short, client_id_, access_token)

        # ── Upload the PDF ────────────────────────────────────────────────────
        result = _multipart_upload(filename, pdf_bytes, prop_id, access_token)
        file_id = result.get('id', '')

        drive_url = f'https://drive.google.com/file/d/{file_id}/view' if file_id else ''
        print(f'[google_drive] uploaded OK — {filename} → {drive_url}')
        return True, drive_url

    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8')[:300]
        except Exception:
            pass
        msg = f'Drive API HTTP {e.code}: {body}'
        print(f'[google_drive] upload error: {msg}')
        return False, msg

    except Exception as e:
        print(f'[google_drive] upload error: {e}')
        return False, str(e)
