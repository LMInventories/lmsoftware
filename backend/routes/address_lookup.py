"""
routes/address_lookup.py
────────────────────────
Free UK address lookup — no API keys required.

Backends:
  postcodes.io  — postcode validation and admin-area metadata (free, no auth)
  Nominatim     — address search and structured geocoding (free, no auth)
                  Usage policy requires a descriptive User-Agent header.

Endpoints:
  GET /api/address/find/<postcode>  → { postcode, addresses: [{line1, line2, line3, city, county, postcode}] }
  GET /api/address/autocomplete?q=  → { suggestions: [{address, url}] }
  GET /api/address/get?url=         → { line1, line2, line3, city, county, postcode }

The 'url' field in autocomplete suggestions carries a Nominatim OSM reference
("<OsmType><osm_id>", e.g. "N123456789") so /get can resolve the full address.
"""

import re
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

address_lookup_bp = Blueprint('address_lookup', __name__)

_NOMINATIM_BASE    = 'https://nominatim.openstreetmap.org'
_POSTCODES_IO_BASE = 'https://api.postcodes.io'

# Nominatim usage policy requires a meaningful User-Agent identifying the application.
_UA = 'InspectPro/1.0 (property inspection management; contact=support@lminventories.co.uk)'

_PC_RE = re.compile(r'^[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}$', re.I)

# Trailing suffixes that Nominatim appends to UK display_names — strip these for cleaner dropdown labels.
_UK_SUFFIXES = (
    ', England, United Kingdom',
    ', Scotland, United Kingdom',
    ', Wales, United Kingdom',
    ', Northern Ireland, United Kingdom',
    ', United Kingdom',
)


def _norm_pc(postcode: str) -> str:
    """Uppercase and insert the canonical space before the inward code."""
    pc = postcode.replace(' ', '').upper()
    return f'{pc[:-3]} {pc[-3:]}' if len(pc) >= 5 else pc


def _parse_nominatim(addr: dict) -> dict:
    """Map a Nominatim address object to our internal {line1, line2, line3, city, county, postcode}."""
    house_number = addr.get('house_number', '')
    house_name   = addr.get('house_name', '')
    road         = (addr.get('road') or addr.get('pedestrian')
                    or addr.get('footway') or addr.get('path') or '')

    if house_name:
        line1 = f'{house_name}, {road}' if road else house_name
    elif house_number and road:
        line1 = f'{house_number} {road}'
    else:
        line1 = road or house_name or ''

    line2 = (addr.get('suburb') or addr.get('neighbourhood')
             or addr.get('quarter') or addr.get('hamlet') or '')

    city  = (addr.get('city') or addr.get('town')
             or addr.get('village') or addr.get('municipality') or '')

    county = addr.get('county') or addr.get('state_district') or ''

    return {
        'line1':    line1.strip(),
        'line2':    line2.strip(),
        'line3':    '',
        'city':     city.strip(),
        'county':   county.strip(),
        'postcode': addr.get('postcode', '').strip(),
    }


def _trim_display(display_name: str) -> str:
    """Remove trailing UK region/country noise from a Nominatim display_name."""
    for suffix in _UK_SUFFIXES:
        if display_name.endswith(suffix):
            return display_name[:-len(suffix)]
    return display_name


# ── Routes ────────────────────────────────────────────────────────────────────

@address_lookup_bp.route('/find/<postcode>', methods=['GET'])
@jwt_required()
def find_by_postcode(postcode):
    """
    Look up UK addresses for a given postcode.
    GET /api/address/find/SW1A2AA
    Response: { postcode, addresses: [{line1, line2, line3, city, county, postcode}] }
    """
    pc = _norm_pc(postcode)

    # 1. Validate postcode and collect admin-area fallbacks from postcodes.io
    fallback_city   = ''
    fallback_county = ''
    try:
        r = requests.get(
            f'{_POSTCODES_IO_BASE}/postcodes/{pc.replace(" ", "")}',
            timeout=6,
        )
        if r.status_code == 200:
            result = r.json().get('result') or {}
            fallback_city   = result.get('admin_district') or result.get('parish') or ''
            fallback_county = result.get('admin_county') or result.get('admin_district') or ''
        elif r.status_code == 404:
            return jsonify({'postcode': pc, 'addresses': []}), 200
    except Exception as e:
        print(f'[address] postcodes.io error: {e}')

    # 2. Search Nominatim for addresses that carry this postcode
    addresses = []
    try:
        r = requests.get(
            f'{_NOMINATIM_BASE}/search',
            params={
                'postalcode':     pc,
                'countrycodes':   'gb',
                'addressdetails': 1,
                'format':         'json',
                'limit':          40,
            },
            headers={'User-Agent': _UA},
            timeout=8,
        )
        if r.status_code == 200:
            seen = set()
            for item in r.json():
                addr = _parse_nominatim(item.get('address', {}))
                # Skip results with no usable street line
                if not addr['line1']:
                    continue
                # Fill blanks from postcodes.io metadata
                if not addr['postcode']:
                    addr['postcode'] = pc
                if not addr['city']:
                    addr['city'] = fallback_city
                if not addr['county']:
                    addr['county'] = fallback_county
                key = (addr['line1'].lower(), addr['city'].lower())
                if key not in seen:
                    seen.add(key)
                    addresses.append(addr)
    except Exception as e:
        print(f'[address] Nominatim postcode search error: {e}')

    # 3. Fallback: if Nominatim returned nothing, synthesise one entry from postcodes.io data
    #    so the user can at least pre-fill city/county/postcode and type the street manually.
    if not addresses:
        addresses.append({
            'line1':    '',
            'line2':    '',
            'line3':    '',
            'city':     fallback_city,
            'county':   fallback_county,
            'postcode': pc,
        })

    return jsonify({'postcode': pc, 'addresses': addresses})


@address_lookup_bp.route('/autocomplete', methods=['GET'])
@jwt_required()
def autocomplete():
    """
    Autocomplete a UK address using Nominatim free-text search.
    GET /api/address/autocomplete?q=10+Downing+Street
    Response: { suggestions: [{address, url}] }

    'url' is a Nominatim OSM reference (e.g. "N123456789").
    Pass it to /get?url=… to resolve the full structured address.
    """
    q = request.args.get('q', '').strip()
    if not q or len(q) < 3:
        return jsonify({'suggestions': []}), 200

    try:
        r = requests.get(
            f'{_NOMINATIM_BASE}/search',
            params={
                'q':              q,
                'countrycodes':   'gb',
                'addressdetails': 1,
                'format':         'json',
                'limit':          10,
            },
            headers={'User-Agent': _UA},
            timeout=8,
        )
        if r.status_code != 200:
            return jsonify({'suggestions': []}), 200

        suggestions = []
        seen = set()
        for item in r.json():
            display = _trim_display(item.get('display_name', ''))
            if not display or display in seen:
                continue
            seen.add(display)

            # Build OSM reference: first letter of type (N/W/R) + numeric ID
            osm_type = (item.get('osm_type') or '')[:1].upper()  # node→N, way→W, relation→R
            osm_id   = str(item.get('osm_id', ''))
            osm_ref  = f'{osm_type}{osm_id}' if osm_type and osm_id else ''

            suggestions.append({'address': display, 'url': osm_ref})

        return jsonify({'suggestions': suggestions})

    except requests.Timeout:
        return jsonify({'error': 'Autocomplete timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@address_lookup_bp.route('/get', methods=['GET'])
@jwt_required()
def get_address_by_id():
    """
    Resolve a full structured address from a Nominatim OSM reference.
    GET /api/address/get?url=N123456789
    Response: { line1, line2, line3, city, county, postcode }
    """
    osm_ref = request.args.get('url', '').strip()
    if not osm_ref:
        return jsonify({'error': 'url parameter required'}), 400

    try:
        r = requests.get(
            f'{_NOMINATIM_BASE}/lookup',
            params={
                'osm_ids':        osm_ref,
                'addressdetails': 1,
                'format':         'json',
            },
            headers={'User-Agent': _UA},
            timeout=8,
        )
        if r.status_code != 200:
            return jsonify({'error': f'Nominatim lookup failed ({r.status_code})'}), r.status_code

        results = r.json()
        if not results:
            return jsonify({'error': 'Address not found'}), 404

        return jsonify(_parse_nominatim(results[0].get('address', {})))

    except requests.Timeout:
        return jsonify({'error': 'Address fetch timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500
