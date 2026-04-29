import os
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

address_lookup_bp = Blueprint('address_lookup', __name__)

GOOGLE_API_KEY   = os.environ.get('GOOGLE_PLACES_API_KEY', '')
PLACES_BASE      = 'https://maps.googleapis.com/maps/api/place'
GEOCODE_BASE     = 'https://maps.googleapis.com/maps/api/geocode/json'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _component(components, *types):
    """Return the long_name of the first address component matching any of the given types."""
    for c in components:
        if any(t in c.get('types', []) for t in types):
            return c.get('long_name', '').strip()
    return ''


def _parse_place_details(components):
    """
    Map Google address_components to our internal format.

    Google types used:
      street_number   → house / flat number
      subpremise      → flat / unit within a building
      route           → street name
      postal_town     → city (UK-specific; falls back to locality)
      locality        → town/city fallback
      administrative_area_level_2 → county
      postal_code     → postcode
    """
    subpremise     = _component(components, 'subpremise')
    street_number  = _component(components, 'street_number')
    route          = _component(components, 'route')
    postal_town    = _component(components, 'postal_town')
    locality       = _component(components, 'locality')
    county         = _component(components, 'administrative_area_level_2')
    postcode       = _component(components, 'postal_code')

    # Build line1: "Flat 3, 10 High Street"  or just "10 High Street"
    number_part = ' '.join(filter(None, [street_number, route]))
    line1 = ', '.join(filter(None, [subpremise, number_part])) if subpremise else number_part
    city  = postal_town or locality

    return {
        'line1':    line1,
        'line2':    '',
        'line3':    '',
        'city':     city,
        'county':   county,
        'postcode': postcode,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@address_lookup_bp.route('/find/<postcode>', methods=['GET'])
@jwt_required()
def find_by_postcode(postcode):
    """
    Geocode a UK postcode via Google Geocoding API and return the result.
    GET /api/address/find/SW1A1AA
    Response: { postcode, addresses: [{ line1, line2, line3, city, county, postcode }] }

    Note: Google doesn't provide a list of individual properties per postcode
    (that requires AddressBase / Royal Mail PAF).  We return the best geocoded
    match for the postcode so the form can at least pre-fill city/county.
    The autocomplete endpoint is the primary address-entry path.
    """
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    pc = postcode.replace(' ', '').upper()
    try:
        res = requests.get(
            GEOCODE_BASE,
            params={
                'address':    pc,
                'components': 'country:GB',
                'key':        GOOGLE_API_KEY,
            },
            timeout=8,
        )
        if res.status_code != 200:
            return jsonify({'postcode': pc, 'addresses': []}), 200

        data = res.json()
        addresses = []
        for result in data.get('results', []):
            addr = _parse_place_details(result.get('address_components', []))
            addresses.append(addr)

        return jsonify({'postcode': pc, 'addresses': addresses})

    except requests.Timeout:
        return jsonify({'error': 'Address lookup timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@address_lookup_bp.route('/autocomplete', methods=['GET'])
@jwt_required()
def autocomplete():
    """
    Autocomplete a UK address using Google Places Autocomplete.
    GET /api/address/autocomplete?q=10+Downing+Street
    Response: { suggestions: [{ address, url }] }

    'url' carries the Google place_id so /get can resolve the full address.
    """
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    q = request.args.get('q', '').strip()
    if not q or len(q) < 3:
        return jsonify({'suggestions': []}), 200

    try:
        res = requests.get(
            f'{PLACES_BASE}/autocomplete/json',
            params={
                'input':      q,
                'key':        GOOGLE_API_KEY,
                'components': 'country:gb',
                'types':      'address',
                'language':   'en-GB',
            },
            timeout=8,
        )
        if res.status_code != 200:
            return jsonify({'suggestions': []}), 200

        data = res.json()
        if data.get('status') not in ('OK', 'ZERO_RESULTS'):
            # Surface API-level errors (e.g. REQUEST_DENIED) for easier debugging
            return jsonify({'suggestions': [], 'api_status': data.get('status')}), 200

        suggestions = []
        for p in data.get('predictions', []):
            suggestions.append({
                'address': p.get('description', ''),
                'url':     p.get('place_id', ''),
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
    Resolve a full structured address from a Google place_id.
    GET /api/address/get?url=<place_id>
    Response: { line1, line2, line3, city, county, postcode }
    """
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    place_id = request.args.get('url', '').strip()
    if not place_id:
        return jsonify({'error': 'url parameter required'}), 400

    try:
        res = requests.get(
            f'{PLACES_BASE}/details/json',
            params={
                'place_id': place_id,
                'key':      GOOGLE_API_KEY,
                'fields':   'address_components',
                'language': 'en-GB',
            },
            timeout=8,
        )
        if res.status_code != 200:
            return jsonify({'error': f'Place details failed ({res.status_code})'}), res.status_code

        data = res.json()
        if data.get('status') != 'OK':
            return jsonify({'error': f'Place not found: {data.get("status")}'}), 404

        components = data['result'].get('address_components', [])
        return jsonify(_parse_place_details(components))

    except requests.Timeout:
        return jsonify({'error': 'Address fetch timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500
