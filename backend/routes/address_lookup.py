import os
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

address_lookup_bp = Blueprint('address_lookup', __name__)

GETADDRESS_API_KEY = os.environ.get('GETADDRESS_API_KEY', '')
GETADDRESS_BASE    = 'https://api.getaddress.io'


def _headers():
    return {'api-key': GETADDRESS_API_KEY}


@address_lookup_bp.route('/find/<postcode>', methods=['GET'])
@jwt_required()
def find_by_postcode(postcode):
    """
    Return all addresses for a UK postcode.
    GET /api/address/find/SW1A1AA
    Response: { postcode, addresses: [{ line1, line2, line3, city, county }] }
    """
    if not GETADDRESS_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    pc = postcode.replace(' ', '').upper()
    try:
        res = requests.get(
            f'{GETADDRESS_BASE}/find/{pc}',
            headers=_headers(),
            params={'expand': 'true', 'sort': 'true'},
            timeout=8
        )
        if res.status_code == 404:
            return jsonify({'postcode': postcode, 'addresses': []}), 200
        if res.status_code != 200:
            return jsonify({'error': f'Lookup failed ({res.status_code})'}), res.status_code

        data = res.json()
        addresses = []
        for a in data.get('addresses', []):
            # Expanded format gives a dict; non-expanded gives comma string
            if isinstance(a, dict):
                addresses.append({
                    'line1':  a.get('line_1', '').strip(),
                    'line2':  a.get('line_2', '').strip(),
                    'line3':  a.get('line_3', '').strip(),
                    'city':   a.get('town_or_city', '').strip(),
                    'county': a.get('county', '').strip(),
                })
            else:
                # Fallback: comma-separated string
                parts = [p.strip() for p in str(a).split(',')]
                addresses.append({
                    'line1':  parts[0] if len(parts) > 0 else '',
                    'line2':  parts[1] if len(parts) > 1 else '',
                    'line3':  parts[2] if len(parts) > 2 else '',
                    'city':   parts[5] if len(parts) > 5 else '',
                    'county': parts[6] if len(parts) > 6 else '',
                })

        return jsonify({
            'postcode':  data.get('postcode', pc),
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
    The frontend can then call /find with the returned postcode.
    """
    if not GETADDRESS_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    q = request.args.get('q', '').strip()
    if not q or len(q) < 3:
        return jsonify({'suggestions': []}), 200

    try:
        res = requests.get(
            f'{GETADDRESS_BASE}/autocomplete/{requests.utils.quote(q)}',
            headers=_headers(),
            params={'all': 'true'},
            timeout=8
        )
        if res.status_code != 200:
            return jsonify({'suggestions': []}), 200

        data = res.json()
        suggestions = [
            {'address': s.get('address', ''), 'url': s.get('url', '')}
            for s in data.get('suggestions', [])
        ]
        return jsonify({'suggestions': suggestions[:10]})

    except requests.Timeout:
        return jsonify({'error': 'Autocomplete timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500
