import os
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

address_lookup_bp = Blueprint('address_lookup', __name__)

IDEALPOSTCODES_API_KEY = os.environ.get('IDEALPOSTCODES_API_KEY', '')
IDEALPOSTCODES_BASE    = 'https://api.ideal-postcodes.co.uk/v1'


def _params(**extra):
    """Always include api_key as a query parameter."""
    p = {'api_key': IDEALPOSTCODES_API_KEY}
    p.update(extra)
    return p


@address_lookup_bp.route('/find/<postcode>', methods=['GET'])
@jwt_required()
def find_by_postcode(postcode):
    """
    Return all addresses for a UK postcode.
    GET /api/address/find/SW1A1AA
    Response: { postcode, addresses: [{ line1, line2, line3, city, county, udprn }] }
    """
    if not IDEALPOSTCODES_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    pc = postcode.replace(' ', '').upper()
    try:
        res = requests.get(
            f'{IDEALPOSTCODES_BASE}/postcodes/{pc}',
            params=_params(),
            timeout=8
        )
        if res.status_code == 404:
            return jsonify({'postcode': postcode, 'addresses': []}), 200
        if res.status_code != 200:
            return jsonify({'error': f'Lookup failed ({res.status_code})', 'detail': res.text}), res.status_code

        data = res.json()
        addresses = []
        for a in data.get('result', []):
            addresses.append({
                'line1':  a.get('line_1', '').strip(),
                'line2':  a.get('line_2', '').strip(),
                'line3':  a.get('line_3', '').strip(),
                'city':   a.get('post_town', '').strip(),
                'county': a.get('county', '').strip(),
                'udprn':  a.get('udprn', ''),
            })

        return jsonify({
            'postcode':  pc,
            'addresses': addresses
        })

    except requests.Timeout:
        return jsonify({'error': 'Address lookup timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@address_lookup_bp.route('/autocomplete', methods=['GET'])
@jwt_required()
def autocomplete():
    """
    Autocomplete a partial address (street name, area, etc.).
    GET /api/address/autocomplete?q=10+Downing+Street
    Response: { suggestions: [{ address, url }] }

    Note: 'url' carries the udprn as a string so the frontend interface is unchanged.
    """
    if not IDEALPOSTCODES_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    q = request.args.get('q', '').strip()
    if not q or len(q) < 3:
        return jsonify({'suggestions': []}), 200

    try:
        res = requests.get(
            f'{IDEALPOSTCODES_BASE}/autocomplete/addresses',
            params=_params(q=q),
            timeout=8
        )
        if res.status_code != 200:
            return jsonify({'suggestions': []}), 200

        data = res.json()
        suggestions = []
        for s in data.get('result', {}).get('hits', []):
            suggestions.append({
                'address': s.get('suggestion', ''),
                # Pass udprn as the 'url' field so selectAutocomplete() can call /get
                'url': str(s.get('udprn', '')),
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
    Resolve a full address from a udprn (passed as the 'url' param for frontend compat).
    GET /api/address/get?url=25962203
    Response: { line1, line2, line3, city, county, postcode }
    """
    if not IDEALPOSTCODES_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    udprn = request.args.get('url', '').strip()
    if not udprn:
        return jsonify({'error': 'url parameter required'}), 400

    # Strip any non-numeric characters just in case
    udprn = ''.join(filter(str.isdigit, udprn))
    if not udprn:
        return jsonify({'error': 'Invalid address ID'}), 400

    try:
        res = requests.get(
            f'{IDEALPOSTCODES_BASE}/udprn/{udprn}',
            params=_params(),
            timeout=8
        )
        if res.status_code != 200:
            return jsonify({'error': f'Address fetch failed ({res.status_code})'}), res.status_code

        a = res.json().get('result', {})
        return jsonify({
            'line1':    a.get('line_1', '').strip(),
            'line2':    a.get('line_2', '').strip(),
            'line3':    a.get('line_3', '').strip(),
            'city':     a.get('post_town', '').strip(),
            'county':   a.get('county', '').strip(),
            'postcode': a.get('postcode', '').strip(),
        })

    except requests.Timeout:
        return jsonify({'error': 'Address fetch timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500
