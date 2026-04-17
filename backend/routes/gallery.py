"""
gallery.py — Public photo gallery endpoint for PDF clickable-photo links.

Routes:
  GET /api/gallery/<inspection_id>/<sid>/<rid>
      → HTML gallery shell.  Photos are loaded via separate /photo/<n> requests
        so the initial page is tiny even when there are many large photos.
        When photos aren't found, shows diagnostic info about what keys DO exist.

  GET /api/gallery/<inspection_id>/<sid>/<rid>/photo/<n>
      → Binary JPEG for the nth photo (Pillow-compressed to ≤1600 px, quality 82).
        Cached for 1 hour.  Same token as the gallery URL.

  GET /api/gallery/<inspection_id>/<sid>/<rid>/debug
      → JSON diagnostic: shows what keys exist and how many photos were found.

Token:  HMAC-SHA256(JWT_SECRET_KEY, "{inspection_id}:{sid}:{rid}")[:16]
No login required — the HMAC token provides security without a session.
"""

import io
import os
import json
import hmac
import hashlib
import base64 as _b64
import html as _html
import time
from flask import Blueprint, request, abort, make_response

# ── Gallery base URL ───────────────────────────────────────────────────────────
# Photo <img> tags use absolute URLs so the browser fetches them directly from
# the backend, bypassing the frontend Express proxy entirely.  This eliminates
# the ETIMEDOUT errors caused by many parallel photo requests going through the
# proxy to the Railway private network.
#
# Railway injects RAILWAY_PUBLIC_DOMAIN automatically (e.g. "xyz.up.railway.app").
# Set GALLERY_BASE_URL explicitly to override (e.g. for a custom domain on the
# backend, or for local dev where neither var is set).
# Falls back to '' which means relative URLs (safe for local dev).
_RAILWAY_DOMAIN  = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
GALLERY_BASE_URL = os.environ.get(
    'GALLERY_BASE_URL',
    f'https://{_RAILWAY_DOMAIN}' if _RAILWAY_DOMAIN else ''
)

# ── In-memory cache for report_data ───────────────────────────────────────────
# Each gallery page fires N concurrent photo requests for the same inspection.
# Caching for 2 minutes means only the first request hits the DB; the rest
# are served from memory.  Workers have independent caches (gunicorn fork
# model) but each worker still benefits from repeated requests to the same page.
_RD_CACHE: dict = {}     # {inspection_id: (expires_at, rd, label)}
_RD_TTL   = 120          # seconds

# Compressed JPEG cache — avoids re-running Pillow on every photo request.
# Key: (inspection_id, sid, rid, n)  Value: (expires_at, jpeg_bytes)
_PHOTO_CACHE: dict = {}
_PHOTO_TTL  = 3600       # 1 hour

gallery_bp = Blueprint('gallery', __name__)


@gallery_bp.route('/gallery/ping')
def gallery_ping():
    return 'gallery ok', 200


def make_gallery_token(inspection_id, sid, rid):
    secret = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    msg    = f'{inspection_id}:{sid}:{rid}'
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def _load_report_data(inspection_id, use_cache=True):
    """Return (rd dict, label string, parse_error string|None) for the inspection."""
    if use_cache:
        now = time.time()
        entry = _RD_CACHE.get(inspection_id)
        if entry and now < entry[0]:
            return entry[1], entry[2], None

    from models import Inspection
    insp = Inspection.query.get_or_404(inspection_id)

    rd = {}
    parse_error = None
    if insp.report_data:
        try:
            rd = json.loads(insp.report_data) if isinstance(insp.report_data, str) else insp.report_data
        except Exception as e:
            parse_error = str(e)
            print(f'[gallery] ERROR parsing report_data for inspection {inspection_id}: {e}')

    label = ''
    try:
        prop = insp.property
        if prop:
            label = prop.address or ''
    except Exception:
        pass
    if not label:
        label = f'Inspection #{inspection_id}'

    # Populate cache; evict stale entries if the cache grows large
    if use_cache:
        _RD_CACHE[inspection_id] = (time.time() + _RD_TTL, rd, label)
        if len(_RD_CACHE) > 100:
            now = time.time()
            stale = [k for k, v in _RD_CACHE.items() if v[0] < now]
            for k in stale:
                del _RD_CACHE[k]

    return rd, label, parse_error


def _extract_photos(rd, sid, rid):
    """
    Return list of photo src strings from rd[sid][rid]['_photos'].
    Also returns diagnostic dict with what was found / not found.
    """
    sid_key      = str(sid)
    rid_key      = str(rid)
    top_keys     = list(rd.keys())
    section_data = rd.get(sid_key) or {}
    sec_keys     = list(section_data.keys())
    row_data     = section_data.get(rid_key) or {}
    raw          = row_data.get('_photos', []) or []

    print(f'[gallery] sid={sid_key!r} rid={rid_key!r} '
          f'top_keys={top_keys[:15]} sec_keys={sec_keys[:15]} raw={len(raw)}')

    photos = []
    for p in raw:
        if isinstance(p, str) and p:
            photos.append(p)
        elif isinstance(p, dict):
            url = p.get('url') or p.get('src') or ''
            if url:
                photos.append(url)

    diag = {
        'sid_key':       sid_key,
        'rid_key':       rid_key,
        'top_keys':      top_keys[:20],
        'section_found': bool(section_data),
        'sec_keys':      sec_keys[:20],
        'row_found':     bool(row_data),
        'row_keys':      list(row_data.keys()),
        'raw_count':     len(raw),
        'photo_count':   len(photos),
    }
    return photos, diag


def _compress_photo(src: str) -> bytes:
    """
    Decode a photo src (data URI or URL) and compress it with Pillow.
    Returns JPEG bytes.  Falls back to raw decoded bytes on any Pillow error.
    """
    if src.startswith('data:'):
        # Split on the first comma to get the base64 payload
        _, b64 = src.split(',', 1)
        # Normalise: strip whitespace, convert URL-safe chars, fix padding
        b64 = b64.strip().replace('-', '+').replace('_', '/')
        b64 += '=' * (4 - len(b64) % 4) if len(b64) % 4 else ''
        data = _b64.b64decode(b64)
    else:
        import urllib.request
        req  = urllib.request.Request(src, headers={'User-Agent': 'InspectPro/1.0'})
        data = urllib.request.urlopen(req, timeout=10).read()

    try:
        from PIL import Image as _PILImg, ImageOps
        pil = _PILImg.open(io.BytesIO(data)).convert('RGB')
        try:
            pil = ImageOps.exif_transpose(pil)
        except Exception:
            pass
        w, h = pil.size
        if w > 1600 or h > 1600:
            pil.thumbnail((1600, 1600), _PILImg.LANCZOS)
        out = io.BytesIO()
        pil.save(out, format='JPEG', quality=82, optimize=True)
        return out.getvalue()
    except Exception:
        return data


# ── Gallery HTML ──────────────────────────────────────────────────────────────

@gallery_bp.route('/gallery/<int:inspection_id>/<sid>/<rid>')
def photo_gallery(inspection_id, sid, rid):
    token    = request.args.get('token', '')
    expected = make_gallery_token(inspection_id, sid, rid)
    if not hmac.compare_digest(token, expected):
        abort(403)

    rd, label, parse_error = _load_report_data(inspection_id)
    photos, diag           = _extract_photos(rd, sid, rid)

    # ── No photos: show diagnostic page ──────────────────────────────────────
    if not photos:
        esc_label = _html.escape(label)
        diag_rows = ''
        for k, v in diag.items():
            diag_rows += (
                f'<tr><td style="color:#94a3b8;padding:4px 12px 4px 0;'
                f'white-space:nowrap;vertical-align:top">{_html.escape(k)}</td>'
                f'<td style="color:#e2e8f0;word-break:break-all">{_html.escape(str(v))}</td></tr>'
            )
        if parse_error:
            diag_rows += (
                f'<tr><td colspan="2" style="color:#f87171;padding-top:8px">'
                f'Parse error: {_html.escape(parse_error)}</td></tr>'
            )
        body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc_label}</title>
<style>
body{{background:#0f172a;font-family:system-ui,sans-serif;
     padding:32px 20px;color:#f1f5f9;max-width:680px;margin:0 auto}}
h2{{font-size:16px;margin:0 0 6px}}
p{{color:#64748b;font-size:13px;margin:0 0 20px}}
table{{font-size:12px;border-collapse:collapse;width:100%}}
</style></head>
<body>
<h2>No photos found — {esc_label}</h2>
<p>Looking for: inspection {inspection_id} → section <code>{_html.escape(str(sid))}</code>
   → row <code>{_html.escape(str(rid))}</code></p>
<table>{diag_rows}</table>
</body></html>"""
        return make_response(body, 200, {'Content-Type': 'text/html; charset=utf-8'})

    count  = len(photos)
    plural = 's' if count != 1 else ''

    # ── Inline every photo as a base64 data URI ───────────────────────────────
    # This makes the gallery a single self-contained HTML response.  The
    # browser needs no further requests, so the frontend proxy is only hit
    # once — eliminating the ETIMEDOUT errors caused by parallel sub-requests
    # going through Railway's private network.
    #
    # Each photo is compressed to ≤1600 px / quality 82 by _compress_photo
    # (same as the /photo/<n> endpoint), so payload size is the same total
    # data, just delivered in one response instead of N+1 round trips.
    imgs_html = ''
    for i, src in enumerate(photos):
        try:
            jpeg_bytes = _compress_photo(src)
            b64        = _b64.b64encode(jpeg_bytes).decode('ascii')
            data_uri   = f'data:image/jpeg;base64,{b64}'
        except Exception as e:
            print(f'[gallery] inline photo {i} failed: {e}')
            data_uri = ''   # skip broken photos

        if data_uri:
            imgs_html += (
                f'<img src="{data_uri}" alt="Photo {i + 1}" loading="lazy" '
                f'onclick="openLb(this.src)">\n'
            )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html.escape(label)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f172a;font-family:system-ui,-apple-system,sans-serif;min-height:100vh}}
.hdr{{background:#1e293b;padding:16px 20px;border-bottom:1px solid #334155}}
.hdr h1{{color:#f1f5f9;font-size:15px;font-weight:600;margin-bottom:3px;
         white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.hdr p{{color:#94a3b8;font-size:12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:3px;padding:3px}}
.grid img{{width:100%;height:220px;object-fit:cover;cursor:zoom-in;
           transition:opacity .15s;display:block;background:#1e293b}}
.grid img:hover{{opacity:.82}}
.lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);
     z-index:9999;align-items:center;justify-content:center;padding:16px}}
.lb.on{{display:flex}}
.lb img{{max-width:100%;max-height:100%;object-fit:contain;border-radius:3px}}
.lb-x{{position:fixed;top:14px;right:18px;color:#fff;font-size:34px;
        cursor:pointer;line-height:1;opacity:.75;user-select:none}}
.lb-x:hover{{opacity:1}}
</style>
</head>
<body>
<div class="hdr">
  <h1>{_html.escape(label)}</h1>
  <p>{count} photo{plural}</p>
</div>
<div class="grid">
{imgs_html}
</div>
<div class="lb" id="lb" onclick="closeLb()">
  <span class="lb-x">&#215;</span>
  <img id="lb-img" src="" alt="">
</div>
<script>
function openLb(src) {{
  document.getElementById('lb-img').src = src;
  document.getElementById('lb').classList.add('on');
}}
function closeLb() {{
  document.getElementById('lb').classList.remove('on');
}}
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeLb();
}});
</script>
</body>
</html>"""

    return make_response(html, 200, {'Content-Type': 'text/html; charset=utf-8'})


# ── Per-photo binary endpoint ─────────────────────────────────────────────────

@gallery_bp.route('/gallery/<int:inspection_id>/<sid>/<rid>/photo/<int:n>')
def gallery_photo(inspection_id, sid, rid, n):
    """
    Serve the nth photo for an inspection item as a compressed JPEG.
    Uses the same HMAC token as the gallery page — no extra auth needed.
    """
    token    = request.args.get('token', '')
    expected = make_gallery_token(inspection_id, sid, rid)
    if not hmac.compare_digest(token, expected):
        abort(403)

    # ── Check compressed-photo cache first ───────────────────────────────────
    cache_key = (inspection_id, sid, rid, n)
    now = time.time()
    cached = _PHOTO_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return make_response(cached[1], 200, {
            'Content-Type':  'image/jpeg',
            'Cache-Control': 'private, max-age=3600',
            'X-Cache':       'HIT',
        })

    rd, _, _ = _load_report_data(inspection_id)
    photos, _ = _extract_photos(rd, sid, rid)

    if n < 0 or n >= len(photos):
        abort(404)

    try:
        data = _compress_photo(photos[n])
    except Exception as e:
        import traceback
        print(f'[gallery] photo {n} error: {e}')
        print(traceback.format_exc())
        abort(500)

    # Store in cache; evict stale entries if it grows large
    _PHOTO_CACHE[cache_key] = (now + _PHOTO_TTL, data)
    if len(_PHOTO_CACHE) > 500:
        stale = [k for k, v in _PHOTO_CACHE.items() if v[0] < now]
        for k in stale:
            del _PHOTO_CACHE[k]

    return make_response(data, 200, {
        'Content-Type':  'image/jpeg',
        'Cache-Control': 'private, max-age=3600',
        'X-Cache':       'MISS',
    })


# ── Debug endpoint ─────────────────────────────────────────────────────────────

@gallery_bp.route('/gallery/<int:inspection_id>/<sid>/<rid>/debug')
def gallery_debug(inspection_id, sid, rid):
    """
    JSON diagnostic — call with the same token as the gallery URL.
    Returns what keys were found and how many photos exist.
    """
    token    = request.args.get('token', '')
    expected = make_gallery_token(inspection_id, sid, rid)
    if not hmac.compare_digest(token, expected):
        abort(403)

    from models import Inspection
    insp = Inspection.query.get_or_404(inspection_id)

    rd = {}
    parse_error = None
    if insp.report_data:
        try:
            rd = json.loads(insp.report_data) if isinstance(insp.report_data, str) else insp.report_data
        except Exception as e:
            parse_error = str(e)

    sid_key      = str(sid)
    rid_key      = str(rid)
    section_data = rd.get(sid_key) or {}
    row_data     = section_data.get(rid_key) or {}
    raw_photos   = row_data.get('_photos', []) or []

    photo_types = []
    for p in raw_photos:
        if isinstance(p, str):
            if p.startswith('data:'):
                photo_types.append(f'data-uri ({len(p)} chars)')
            else:
                photo_types.append(f'url: {p[:80]}')
        elif isinstance(p, dict):
            photo_types.append(f'dict keys={list(p.keys())}')
        else:
            photo_types.append(f'unknown type: {type(p).__name__}')

    info = {
        'inspection_id':    inspection_id,
        'sid_requested':    sid_key,
        'rid_requested':    rid_key,
        'parse_error':      parse_error,
        'top_level_keys':   list(rd.keys())[:20],
        'section_found':    bool(section_data),
        'section_keys':     list(section_data.keys())[:20],
        'row_found':        bool(row_data),
        'row_keys':         list(row_data.keys()),
        'photos_count':     len(raw_photos),
        'photos_summary':   photo_types,
    }

    resp = make_response(json.dumps(info, indent=2), 200, {
        'Content-Type': 'application/json',
    })
    return resp
