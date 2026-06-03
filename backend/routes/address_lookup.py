"""
routes/address_lookup.py
────────────────────────
UK address lookup.  Two backends — highest-quality one used when its key is set:

  1. GetAddress.io  (recommended)
     Set GETADDRESS_API_KEY in environment.
     Free tier: 20 lookups/day (~600/month) — ample for 50-100/month usage.
     Sign up free at https://getaddress.io  (no credit card needed).
     Backed by Royal Mail PAF — full residential address coverage.

  2. Nominatim / postcodes.io  (no-key fallback)
     Used automatically when GETADDRESS_API_KEY is not set.
     Coverage is incomplete for individual UK residential addresses
     (OpenStreetMap data), but works without any registration.

Endpoints (API contract unchanged — both backends serve the same shape):
  GET /api/address/find/<postcode>
      → { postcode, addresses: [{line1, line2, line3, city, county, postcode}] }

  GET /api/address/autocomplete?q=<query>
      → { suggestions: [{address, url}] }
      'url' is an opaque reference passed back to /get to resolve full details.

  GET /api/address/get?url=<ref>
      → { line1, line2, line3, city, county, postcode }
"""

import os
import re
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

address_lookup_bp = Blueprint('address_lookup', __name__)

# ── Backend bases ─────────────────────────────────────────────────────────────

_GETADDRESS_BASE   = 'https://api.getaddress.io'
_NOMINATIM_BASE    = 'https://nominatim.openstreetmap.org'
_POSTCODES_IO_BASE = 'https://api.postcodes.io'

# Nominatim usage policy requires a meaningful User-Agent.
_UA = 'InspectPro/1.0 (property inspection management; contact=support@lminventories.co.uk)'

_PC_RE = re.compile(r'^[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}$', re.I)

_UK_SUFFIXES = (
    ', England, United Kingdom', ', Scotland, United Kingdom',
    ', Wales, United Kingdom',   ', Northern Ireland, United Kingdom',
    ', United Kingdom',
)


# ── Config helpers ────────────────────────────────────────────────────────────

def _ga_key():
    return os.environ.get('GETADDRESS_API_KEY', '').strip()

def _use_getaddress():
    return bool(_ga_key())


# ── Shared normalisers ────────────────────────────────────────────────────────

def _norm_pc(postcode: str) -> str:
    pc = postcode.replace(' ', '').upper()
    return f'{pc[:-3]} {pc[-3:]}' if len(pc) >= 5 else pc


# ── GetAddress.io helpers ─────────────────────────────────────────────────────

def _parse_getaddress(item: dict, fallback_pc: str = '') -> dict:
    """
    Map a GetAddress.io expanded address object to our internal shape.
    Fields: line_1..line_4, town_or_city, county, postcode.
    """
    line1 = (item.get('line_1') or '').strip()
    line2 = ', '.join(filter(None, [
        (item.get('line_2') or '').strip(),
        (item.get('line_3') or '').strip(),
        (item.get('line_4') or '').strip(),
    ]))
    city    = (item.get('town_or_city') or '').strip()
    county  = (item.get('county')       or '').strip()
    pc      = (item.get('postcode')     or fallback_pc).strip()
    return {'line1': line1, 'line2': line2, 'line3': '', 'city': city, 'county': county, 'postcode': pc}


def _ga_find(pc: str):
    """Postcode lookup via GetAddress.io.  Returns list of address dicts."""
    r = requests.get(
        f'{_GETADDRESS_BASE}/find/{pc.replace(" ", "")}',
        params={'api-key': _ga_key(), 'expand': 'true'},
        timeout=8,
    )
    if r.status_code == 401:
        print('[address] GetAddress.io: invalid API key')
        return None
    if r.status_code == 404:
        return []                       # valid postcode, no addresses
    if r.status_code != 200:
        print(f'[address] GetAddress.io find error {r.status_code}: {r.text[:200]}')
        return None                     # signal to fall back to Nominatim

    data      = r.json()
    addresses = []
    seen      = set()
    for item in (data.get('addresses') or []):
        addr = _parse_getaddress(item, fallback_pc=pc)
        key  = addr['line1'].lower()
        if addr['line1'] and key not in seen:
            seen.add(key)
            addresses.append(addr)

    # Sort by line1 so the list is alphabetical / numerical
    addresses.sort(key=lambda a: a['line1'])
    return addresses


def _ga_autocomplete(q: str):
    """Typeahead via GetAddress.io.  Returns suggestions list or None on error."""
    r = requests.get(
        f'{_GETADDRESS_BASE}/autocomplete/{requests.utils.quote(q)}',
        params={'api-key': _ga_key(), 'all': 'true', 'top': '10'},
        timeout=8,
    )
    if r.status_code == 401:
        print('[address] GetAddress.io: invalid API key')
        return None
    if r.status_code != 200:
        print(f'[address] GetAddress.io autocomplete error {r.status_code}')
        return None

    raw  = r.json()
    suggestions = []
    seen = set()
    for s in (raw.get('suggestions') or []):
        addr_str = s.get('address', '').strip()
        url_val  = s.get('url', '').strip()
        if addr_str and url_val and addr_str not in seen:
            seen.add(addr_str)
            # Store the raw GetAddress.io URL (e.g. "/get/xxxxxxxx") prefixed
            # so /get can distinguish it from a Nominatim reference.
            suggestions.append({'address': addr_str, 'url': 'ga:' + url_val})

    return suggestions


def _ga_get(ga_url: str) -> dict | None:
    """Resolve a full address from a GetAddress.io get URL (e.g. /get/xxxxxxxx)."""
    # Strip our 'ga:' prefix, keep the rest (e.g. '/get/xxxxxxxx')
    path = ga_url.removeprefix('ga:').lstrip('/')
    r = requests.get(
        f'{_GETADDRESS_BASE}/{path}',
        params={'api-key': _ga_key()},
        timeout=8,
    )
    if r.status_code != 200:
        print(f'[address] GetAddress.io get error {r.status_code}')
        return None
    return _parse_getaddress(r.json())


# ── Nominatim helpers (fallback) ──────────────────────────────────────────────

def _parse_nominatim(addr: dict) -> dict:
    house_number = addr.get('house_number', '')
    house_name   = addr.get('house_name', '')
    road = (addr.get('road') or addr.get('pedestrian')
            or addr.get('footway') or addr.get('path') or '')

    if house_name:
        line1 = f'{house_name}, {road}' if road else house_name
    elif house_number and road:
        line1 = f'{house_number} {road}'
    else:
        line1 = road or house_name or ''

    line2  = (addr.get('suburb') or addr.get('neighbourhood')
              or addr.get('quarter') or addr.get('hamlet') or '')
    city   = (addr.get('city') or addr.get('town')
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
    for suffix in _UK_SUFFIXES:
        if display_name.endswith(suffix):
            return display_name[:-len(suffix)]
    return display_name


# ── Routes ────────────────────────────────────────────────────────────────────

@address_lookup_bp.route('/find/<postcode>', methods=['GET'])
@jwt_required()
def find_by_postcode(postcode):
    pc = _norm_pc(postcode)

    # ── GetAddress.io path ────────────────────────────────────────────────────
    if _use_getaddress():
        try:
            addresses = _ga_find(pc)
            if addresses is not None:
                if not addresses:
                    # Valid postcode but no results — synthesise a skeleton so
                    # the user can at least pre-fill postcode and type the rest.
                    addresses = [{'line1': '', 'line2': '', 'line3': '',
                                  'city': '', 'county': '', 'postcode': pc}]
                return jsonify({'postcode': pc, 'addresses': addresses})
            # None means API error — fall through to Nominatim
        except Exception as e:
            print(f'[address] GetAddress.io exception: {e}')

    # ── Nominatim fallback ────────────────────────────────────────────────────
    fallback_city = fallback_county = ''
    try:
        r = requests.get(f'{_POSTCODES_IO_BASE}/postcodes/{pc.replace(" ", "")}', timeout=6)
        if r.status_code == 200:
            result = r.json().get('result') or {}
            fallback_city   = result.get('admin_district') or result.get('parish') or ''
            fallback_county = result.get('admin_county')   or result.get('admin_district') or ''
        elif r.status_code == 404:
            return jsonify({'postcode': pc, 'addresses': []}), 200
    except Exception as e:
        print(f'[address] postcodes.io error: {e}')

    addresses = []
    try:
        r = requests.get(
            f'{_NOMINATIM_BASE}/search',
            params={'postalcode': pc, 'countrycodes': 'gb',
                    'addressdetails': 1, 'format': 'json', 'limit': 40},
            headers={'User-Agent': _UA}, timeout=8,
        )
        if r.status_code == 200:
            seen = set()
            for item in r.json():
                addr = _parse_nominatim(item.get('address', {}))
                if not addr['line1']:
                    continue
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

    if not addresses:
        addresses.append({'line1': '', 'line2': '', 'line3': '',
                          'city': fallback_city, 'county': fallback_county, 'postcode': pc})

    return jsonify({'postcode': pc, 'addresses': addresses})


@address_lookup_bp.route('/autocomplete', methods=['GET'])
@jwt_required()
def autocomplete():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 3:
        return jsonify({'suggestions': []}), 200

    # ── GetAddress.io path ────────────────────────────────────────────────────
    if _use_getaddress():
        try:
            suggestions = _ga_autocomplete(q)
            if suggestions is not None:
                return jsonify({'suggestions': suggestions})
        except Exception as e:
            print(f'[address] GetAddress.io autocomplete exception: {e}')

    # ── Nominatim fallback ────────────────────────────────────────────────────
    try:
        r = requests.get(
            f'{_NOMINATIM_BASE}/search',
            params={'q': q, 'countrycodes': 'gb', 'addressdetails': 1,
                    'format': 'json', 'limit': 10},
            headers={'User-Agent': _UA}, timeout=8,
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
            osm_type = (item.get('osm_type') or '')[:1].upper()
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
    ref = request.args.get('url', '').strip()
    if not ref:
        return jsonify({'error': 'url parameter required'}), 400

    # ── GetAddress.io path (url starts with 'ga:') ────────────────────────────
    if ref.startswith('ga:') and _use_getaddress():
        try:
            addr = _ga_get(ref)
            if addr:
                return jsonify(addr)
            return jsonify({'error': 'Address not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── Nominatim fallback (OSM reference like N123456 / W123456 / R123456) ───
    try:
        r = requests.get(
            f'{_NOMINATIM_BASE}/lookup',
            params={'osm_ids': ref, 'addressdetails': 1, 'format': 'json'},
            headers={'User-Agent': _UA}, timeout=8,
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
