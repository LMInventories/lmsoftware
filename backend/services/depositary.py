"""
services/depositary.py
──────────────────────
The Depositary integration service.

The Depositary is a UK end-of-tenancy platform that automates deposit
reconciliation. This module handles pushing completed Check Out inspection
data (report PDF, dilapidations, meter readings, tenant details) to their API.

┌──────────────────────────────────────────────────────────────────┐
│  PLACEHOLDER — fill in once you receive API credentials          │
│                                                                  │
│  1. Contact The Depositary: thedepositary.com/integrations       │
│  2. They will supply:                                            │
│       • API base URL   (add to system_settings: depositary_api_url) │
│       • API key        (add to system_settings: depositary_api_key) │
│  3. Confirm the exact request/response shapes and update         │
│     _build_payload() and push_checkout() accordingly.           │
└──────────────────────────────────────────────────────────────────┘

Usage (called automatically from routes/inspections.py on check_out complete):
    from services.depositary import push_checkout
    ok, err = push_checkout(inspection, pdf_bytes)
"""
import json
import urllib.request
import urllib.error
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Configuration helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_settings() -> dict:
    """Load depositary settings from SystemSetting table."""
    try:
        from models import SystemSetting
        rows = SystemSetting.query.filter(
            SystemSetting.key.in_(['depositary_api_url', 'depositary_api_key'])
        ).all()
        return {r.key: r.value for r in rows if r.value}
    except Exception:
        return {}


def is_configured() -> bool:
    """Returns True only when both API URL and key are set."""
    s = _get_settings()
    return bool(s.get('depositary_api_url') and s.get('depositary_api_key'))


# ─────────────────────────────────────────────────────────────────────────────
# Payload builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_payload(inspection) -> dict:
    """
    Build the JSON payload to send to The Depositary.

    ⚠️  PLACEHOLDER — field names and structure must be confirmed with
    The Depositary once you receive their API documentation.

    The structure below is based on publicly documented integrations with
    similar inventory platforms (InventoryBase, ACT Property) and should
    map closely to what they expect, but verify every key name.
    """
    prop   = inspection.property
    client = prop.client if prop else None

    # ── Property & tenancy ────────────────────────────────────────────────────
    payload = {
        # TODO: confirm exact field names with The Depositary
        'property': {
            'address': prop.address if prop else '',
        },
        'tenancy': {
            'tenant_name':  getattr(inspection, 'tenant_name',  None) or '',
            'tenant_email': getattr(inspection, 'tenant_email', None) or '',
            # Deposit details — set on the inspection via InspectionDetailView
            'deposit_amount': getattr(inspection, 'deposit_amount', None),
            'deposit_scheme': getattr(inspection, 'deposit_scheme', None) or '',  # 'TDS' | 'mydeposits' | 'DPS'
            'deposit_ref':    getattr(inspection, 'deposit_ref',    None) or '',  # Certificate/registration number
            # The inspection date
            'checkout_date':  inspection.conduct_date.isoformat() if inspection.conduct_date else None,
        },
        'clerk': {
            'name':  inspection.inspector.name  if inspection.inspector else '',
            'email': inspection.inspector.email if inspection.inspector else '',
        },
        'agent': {
            'name':  client.name    if client else '',
            'email': client.email   if client else '',
            'company': client.company if client else '',
        },
    }

    # ── Dilapidations — from check-out action items ───────────────────────────
    # These come from the _actions array in report_data, set when clerk marks
    # items as damaged during check-out.
    dilapidations = []
    try:
        rd = {}
        if inspection.report_data:
            rd = json.loads(inspection.report_data) if isinstance(inspection.report_data, str) else inspection.report_data
        for action in (rd.get('_actions') or []):
            dilapidations.append({
                'room':        action.get('room', ''),
                'item':        action.get('item', ''),
                'description': action.get('description', ''),
                'condition':   action.get('condition', ''),
                # TODO: confirm whether The Depositary expects cost estimates
                # 'estimated_cost': action.get('estimated_cost', None),
            })
    except Exception as e:
        print(f'[depositary] warning: could not extract dilapidations: {e}')

    payload['dilapidations'] = dilapidations

    # ── Meter readings — from fixed sections in report_data ───────────────────
    # InspectPro stores meter readings in the fixed _overview section.
    # TODO: confirm whether The Depositary accepts meter readings and in what format.
    meter_readings = {}
    try:
        rd = rd if 'rd' in dir() else {}
        overview_items = (rd.get('_overview') or {}).get('items') or {}
        for meter in ('electricity', 'gas', 'water', 'heat'):
            key = f'meter_{meter}'
            val = overview_items.get(key, {}).get('value', '')
            if val:
                meter_readings[meter] = val
    except Exception:
        pass
    payload['meter_readings'] = meter_readings

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Main push function
# ─────────────────────────────────────────────────────────────────────────────

def push_checkout(inspection, pdf_bytes: bytes | None = None) -> tuple[bool, str]:
    """
    Push a completed Check Out inspection to The Depositary.

    Returns:
        (True, depositary_tenancy_id)   on success
        (False, error_message)          on failure

    The depositary_tenancy_id is stored back on the inspection model so it
    can be displayed in the UI and used for follow-up API calls.

    ⚠️  PLACEHOLDER — the exact endpoint paths and request format must be
    confirmed with The Depositary. Adjust the urllib calls below once you
    have their API documentation.
    """
    if not is_configured():
        return False, 'Depositary not configured — set depositary_api_url and depositary_api_key in Settings → Integrations'

    settings   = _get_settings()
    base_url   = settings['depositary_api_url'].rstrip('/')
    api_key    = settings['depositary_api_key']

    payload    = _build_payload(inspection)
    body_bytes = json.dumps(payload).encode('utf-8')

    # ── TODO: confirm the correct endpoint path ───────────────────────────────
    # Based on similar integrations, The Depositary likely exposes something like:
    #   POST /api/v1/tenancies          — create tenancy + checkout record
    #   POST /api/v1/tenancies/{id}/report  — attach PDF report
    # Adjust below once confirmed.
    tenancy_endpoint = f'{base_url}/api/v1/tenancies'  # TODO: confirm path

    headers = {
        'Content-Type':  'application/json',
        'Accept':        'application/json',
        # TODO: confirm auth header name — may be 'X-Api-Key', 'Authorization: Bearer ...', etc.
        'X-Api-Key':     api_key,
        'User-Agent':    'InspectPro/1.0',
    }

    try:
        # Step 1 — Create / update the tenancy record
        req  = urllib.request.Request(tenancy_endpoint, data=body_bytes, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data  = json.loads(resp.read().decode('utf-8'))
            # TODO: confirm the response key that contains the tenancy ID
            tenancy_id = resp_data.get('id') or resp_data.get('tenancy_id') or resp_data.get('uuid')

        print(f'[depositary] tenancy created OK — id={tenancy_id}')

        # Step 2 — Attach PDF report (if available and if API supports it)
        # TODO: confirm whether The Depositary accepts multipart PDF uploads
        # and what the endpoint path is.
        if pdf_bytes and tenancy_id:
            _attach_pdf(base_url, api_key, tenancy_id, pdf_bytes, inspection)

        # Step 3 — Store the Depositary tenancy ID back on the inspection
        if tenancy_id:
            try:
                from models import db
                inspection.depositary_tenancy_id = str(tenancy_id)
                inspection.depositary_pushed_at  = datetime.utcnow()
                db.session.commit()
            except Exception as e:
                print(f'[depositary] warning: could not save tenancy_id back to inspection: {e}')

        return True, str(tenancy_id or 'ok')

    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8')
        except Exception:
            pass
        msg = f'HTTP {e.code}: {body[:300]}'
        print(f'[depositary] push_checkout HTTP error: {msg}')
        return False, msg

    except Exception as e:
        print(f'[depositary] push_checkout error: {e}')
        return False, str(e)


def _attach_pdf(base_url: str, api_key: str, tenancy_id: str, pdf_bytes: bytes, inspection) -> None:
    """
    Attach the checkout PDF to an existing Depositary tenancy record.

    ⚠️  PLACEHOLDER — endpoint path and multipart format must be confirmed.
    """
    import io
    # TODO: confirm The Depositary's PDF upload endpoint and content type.
    # Typical pattern for similar APIs:
    #   POST /api/v1/tenancies/{id}/documents
    #   Content-Type: multipart/form-data  (or application/octet-stream)
    report_endpoint = f'{base_url}/api/v1/tenancies/{tenancy_id}/documents'  # TODO: confirm

    prop    = inspection.property
    address = prop.address.replace(',', '').replace(' ', '_')[:40] if prop else 'report'
    fname   = f'checkout_{address}_{inspection.id}.pdf'

    # Simple multipart boundary
    boundary  = b'----InspectProBoundary'
    body_parts = [
        b'--' + boundary,
        f'Content-Disposition: form-data; name="document"; filename="{fname}"'.encode(),
        b'Content-Type: application/pdf',
        b'',
        pdf_bytes,
        b'--' + boundary + b'--',
    ]
    body = b'\r\n'.join(body_parts)

    headers = {
        'Content-Type':   f'multipart/form-data; boundary={boundary.decode()}',
        'X-Api-Key':      api_key,           # TODO: confirm auth header name
        'User-Agent':     'InspectPro/1.0',
    }

    try:
        req = urllib.request.Request(report_endpoint, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f'[depositary] PDF attached OK — tenancy_id={tenancy_id}, status={resp.status}')
    except Exception as e:
        # Non-fatal — tenancy was already created; just log the failure
        print(f'[depositary] warning: PDF attach failed (non-fatal): {e}')
