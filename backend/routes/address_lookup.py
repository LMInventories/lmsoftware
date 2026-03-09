import os
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

address_lookup_bp = Blueprint('address_lookup', __name__)

GETADDRESS_API_KEY = os.environ.get('GETADDRESS_API_KEY', '')
GETADDRESS_BASE    = 'https://api.getaddress.io'


def _params(**extra):
    """Always include api-key as a query parameter (getAddress.io requirement)."""
    p = {'api-key': GETADDRESS_API_KEY}
    p.update(extra)
    return p


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
            params=_params(expand='true', sort='true'),
            timeout=8
        )
        if res.status_code == 404:
            return jsonify({'postcode': postcode, 'addresses': []}), 200
        if res.status_code != 200:
            return jsonify({'error': f'Lookup failed ({res.status_code})', 'detail': res.text}), res.status_code

        data = res.json()
        addresses = []
        for a in data.get('addresses', []):
            if isinstance(a, dict):
                # expand=true gives structured objects
                addresses.append({
                    'line1':  a.get('line_1', '').strip(),
                    'line2':  a.get('line_2', '').strip(),
                    'line3':  a.get('line_3', '').strip(),
                    'city':   a.get('town_or_city', '').strip(),
                    'county': a.get('county', '').strip(),
                })
            else:
                # Fallback: comma-separated string "line1,line2,line3,line4,locality,town,county"
                parts = [p.strip() for p in str(a).split(',')]
                addresses.append({
                    'line1':  parts[0] if len(parts) > 0 else '',
                    'line2':  parts[1] if len(parts) > 1 else '',
                    'line3':  parts[2] if len(parts) > 2 else '',
                    'city':   parts[5] if len(parts) > 5 else (parts[3] if len(parts) > 3 else ''),
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
    """
    if not GETADDRESS_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    q = request.args.get('q', '').strip()
    if not q or len(q) < 3:
        return jsonify({'suggestions': []}), 200

    try:
        res = requests.get(
            f'{GETADDRESS_BASE}/autocomplete/{requests.utils.quote(q)}',
            params=_params(all='true'),
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


@address_lookup_bp.route('/get', methods=['GET'])
@jwt_required()
def get_address_by_id():
    """
    Resolve a full address from an autocomplete suggestion URL/ID.
    GET /api/address/get?url=/get/12345
    Response: { line1, line2, line3, city, county, postcode }

    The 'url' field comes from the autocomplete suggestions and looks like '/get/{id}'.
    We strip the leading '/get/' and call https://api.getaddress.io/get/{id}
    """
    if not GETADDRESS_API_KEY:
        return jsonify({'error': 'Address lookup not configured'}), 503

    url_path = request.args.get('url', '').strip()
    if not url_path:
        return jsonify({'error': 'url parameter required'}), 400

    # Extract the ID — url_path is like '/get/12345' or just '12345'
    addr_id = url_path.lstrip('/get/').lstrip('/')
    if not addr_id:
        return jsonify({'error': 'Invalid address URL'}), 400

    try:
        res = requests.get(
            f'{GETADDRESS_BASE}/get/{addr_id}',
            params=_params(),
            timeout=8
        )
        if res.status_code != 200:
            return jsonify({'error': f'Address fetch failed ({res.status_code})'}), res.status_code

        a = res.json()
        return jsonify({
            'line1':  a.get('line_1', '').strip(),
            'line2':  a.get('line_2', '').strip(),
            'line3':  a.get('line_3', '').strip(),
            'city':   a.get('town_or_city', '').strip(),
            'county': a.get('county', '').strip(),
            'postcode': a.get('postcode', '').strip(),
        })

    except requests.Timeout:
        return jsonify({'error': 'Address fetch timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500
