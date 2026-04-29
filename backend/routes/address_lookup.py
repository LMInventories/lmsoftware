import os
import json
import base64
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

address_lookup_bp = Blueprint('address_lookup', __name__)

OS_API_KEY    = os.environ.get('OS_API_KEY', '')
OS_NAMES_BASE = 'https://api.os.uk/search/names/v1'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _entry_to_addr(entry):
    """Map a GAZETTEER_ENTRY dict to our internal address format."""
    name1    = entry.get('NAME1', '').strip()
    name2    = entry.get('NAME2', '').strip()
    place    = entry.get('POPULATED_PLACE', '').strip()
    district = entry.get('DISTRICT_BOROUGH', '').strip()
    county   = entry.get('COUNTY_UNITARY', '').strip()
    postcode = entry.get('POSTCODE_DISTRICT', '').strip()

    # city: prefer populated place, fall back to district borough
    city = place if place else district

    return {
        'line1':    name1,
        'line2':    name2,
        'line3':    '',
        'city':     city,
        'county':   county,
        'postcode': postcode,
    }


def _entry_to_label(entry):
    """Build a single-line display string from a GAZETTEER_ENTRY."""
    parts = []
    for key in ('NAME1', 'POPULATED_PLACE', 'DISTRICT_BOROUGH', 'COUNTY_UNITARY', 'POSTCODE_DISTRICT'):
        val = entry.get(key, '').strip()
        if val and val not in parts:
            parts.append(val)
    return ', '.join(parts)


def _encode(addr: dict) -> str:
    """Base64-encode an address dict so it can ride in a URL query param."""
    return base64.urlsafe_b64encode(json.dumps(addr).encode()).decode()


def _decode(token: str) -> dict:
    """Decode a base64 address token back to a dict."""
    return json.loads(base64.urlsafe_b64decode(token.encode()).decode())


def _os_find(query: str, maxresults: int = 10):
    """Call the OS Names /find endpoint and return raw results list."""
    res = requests.get(
        f'{OS_NAMES_BASE}/find',
        params={'query': query, 'key': OS_API_KEY, 'maxresults': maxresults},
        timeout=8,
    )
    if res.status_code not in (200, 404, 400):
        res.raise_for_status()
    if res.status_code != 200:
        return []
    return res.json().get('results', [])


# ── Routes ────────────────────────────────────────────────────────────────────

@address_lookup_bp.route('/find/<postcode>', methods=['GET'])
@jwt_required()
def find_by_postcode(postcode):
    """
    Search OS Names for a postcode and return any matching entries.
    GET /api/address/find/SW1A1AA
    Response: { postcode, addresses: [{ line1, line2, line3, city, county, postcode }] }

    Note: OS Names is a gazetteer, not a full AddressBase.  It won't return
    individual door numbers — it will return the street/locality the postcode
    belongs to.  For most property-creation flows the autocomplete endpoint
    is more useful; this endpoint is retained for API compatibility.
    """
    if not OS_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    pc = postcode.replace(' ', '').upper()
    try:
        results = _os_find(pc, maxresults=20)
        addresses = [_entry_to_addr(r['GAZETTEER_ENTRY']) for r in results if 'GAZETTEER_ENTRY' in r]
        return jsonify({'postcode': pc, 'addresses': addresses})
    except requests.Timeout:
        return jsonify({'error': 'Address lookup timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@address_lookup_bp.route('/autocomplete', methods=['GET'])
@jwt_required()
def autocomplete():
    """
    Autocomplete a street name, place, or postcode using OS Names API.
    GET /api/address/autocomplete?q=10+Downing+Street
    Response: { suggestions: [{ address, url }] }

    'url' carries a base64-encoded address dict so the /get endpoint can
    resolve it without a second round-trip to OS Names.
    """
    if not OS_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    q = request.args.get('q', '').strip()
    if not q or len(q) < 3:
        return jsonify({'suggestions': []}), 200

    try:
        results = _os_find(q, maxresults=10)
        suggestions = []
        for r in results:
            entry = r.get('GAZETTEER_ENTRY', {})
            label = _entry_to_label(entry)
            if not label:
                continue
            addr  = _entry_to_addr(entry)
            suggestions.append({
                'address': label,
                'url':     _encode(addr),
            })
        return jsonify({'suggestions': suggestions[:10]})
    except requests.Timeout:
        return jsonify({'error': 'Autocomplete timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@address_lookup_bp.route('/get', methods=['GET'])
@jwt_required()
def get_address_by_id():
    """
    Decode a base64 address token back into address fields.
    GET /api/address/get?url=<token>
    Response: { line1, line2, line3, city, county, postcode }

    Unlike the old Ideal Postcodes implementation (which made a second HTTP
    request to resolve a UDPRN), the OS Names implementation encodes the full
    address into the token at autocomplete time, so this endpoint is purely
    local — no network call needed.
    """
    token = request.args.get('url', '').strip()
    if not token:
        return jsonify({'error': 'url parameter required'}), 400

    try:
        addr = _decode(token)
        return jsonify({
            'line1':    addr.get('line1', ''),
            'line2':    addr.get('line2', ''),
            'line3':    addr.get('line3', ''),
            'city':     addr.get('city', ''),
            'county':   addr.get('county', ''),
            'postcode': addr.get('postcode', ''),
        })
    except Exception as e:
        return jsonify({'error': f'Invalid address token: {e}'}), 400
