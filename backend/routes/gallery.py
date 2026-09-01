"""
gallery.py — Public photo viewer for PDF clickable-photo links.

Clicking a photo in a generated PDF opens the specific photo full-size, with
every OTHER photo in the whole report browsable via left/right arrows and a
filmstrip carousel underneath — not just the photos for that one item.

Routes:
  GET /api/gallery/<inspection_id>/<sid>/<rid>
      → HTML viewer, opened straight to the clicked item's first photo.
        Built once as a flat, ordered list of every photo in the report
        (fixed sections, then rooms in report order, overview photos first
        within each room); only that flat list's metadata is embedded in the
        page — actual image bytes are lazy-loaded per photo, so the page
        stays tiny even for a report with hundreds of photos.
        When the clicked item itself has no photos, shows diagnostic info
        about what keys DO exist (unchanged from before — still useful for
        tracking down a report_data photo-URL bug).

  GET /api/gallery/<inspection_id>/photo/<n>
      → Binary JPEG for the nth photo in the WHOLE-REPORT flat list
        (Pillow-compressed to ≤1600 px / quality 82, or ≤320 px / quality 70
        with ?thumb=1 for the filmstrip). Cached for 1 hour per (n, thumb).
        Uses the report-wide token, not the per-item one.

  GET /api/gallery/<inspection_id>/<sid>/<rid>/debug
      → JSON diagnostic: shows what keys exist and how many photos were found
        for that specific item (unchanged).

Tokens (no login required — HMAC provides security without a session):
  Per-item (still used for the initial click-through URL, unchanged):
    HMAC-SHA256(JWT_SECRET_KEY, "{inspection_id}:{sid}:{rid}")[:16]
  Report-wide (grants browsing of every photo in this ONE inspection only):
    HMAC-SHA256(JWT_SECRET_KEY, "{inspection_id}:report")[:16]
"""

import io
import os
import re
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
_RD_CACHE_MAX = 100      # hard cap — see _PHOTO_CACHE_MAX for why this must
                          # be enforced unconditionally, not just on staleness

# Compressed JPEG cache — avoids re-running Pillow on every photo request.
# Key: (inspection_id, sid, rid, n)  Value: (expires_at, jpeg_bytes)
_PHOTO_CACHE: dict = {}
_PHOTO_TTL      = 3600   # 1 hour
_PHOTO_CACHE_MAX = 2000  # hard cap — entries can each be a few hundred KB of
                          # JPEG bytes, and this cache is per gunicorn worker
                          # (independent dict per fork), so leaving it
                          # unbounded showed up as steadily climbing Railway
                          # memory billing under sustained gallery traffic.

gallery_bp = Blueprint('gallery', __name__)


@gallery_bp.route('/gallery/ping')
def gallery_ping():
    return 'gallery ok', 200


def make_gallery_token(inspection_id, sid, rid):
    secret = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    msg    = f'{inspection_id}:{sid}:{rid}'
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def make_report_token(inspection_id):
    """Grants browsing of every photo in ONE inspection — minted server-side
    and embedded in the per-item viewer page, never given out separately."""
    secret = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    msg    = f'{inspection_id}:report'
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

    # Populate cache, then enforce the hard cap (stale entries first, then
    # oldest — see _PHOTO_CACHE_MAX for why staleness alone isn't enough)
    if use_cache:
        _RD_CACHE[inspection_id] = (time.time() + _RD_TTL, rd, label)
        if len(_RD_CACHE) > _RD_CACHE_MAX:
            now = time.time()
            stale = [k for k, v in _RD_CACHE.items() if v[0] < now]
            for k in stale:
                del _RD_CACHE[k]
            overflow = len(_RD_CACHE) - _RD_CACHE_MAX
            if overflow > 0:
                oldest = sorted(_RD_CACHE.items(), key=lambda kv: kv[1][0])[:overflow]
                for k, _ in oldest:
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


_FS_PREFIX_RE = re.compile(r'^fs_(\d+)_')

_NON_ROOM_KEYS = {
    '_roomOrder', '_roomNames', '_hiddenRooms', '_customRooms',
    '_transcriptionLog', '_signatures',
}


def _photo_src(p):
    """Normalises one raw _photos entry (string or {url|src: ...} dict) to a src string, or None."""
    if isinstance(p, str) and p:
        return p
    if isinstance(p, dict):
        return p.get('url') or p.get('src') or None
    return None


def _collect_all_photos(rd):
    """
    Walks the ENTIRE report_data and returns a flat, ordered list of every
    photo in the report: [{ 'src', 'sid', 'rid', 'label' }, ...].

    Order approximates the PDF's own layout — fixed sections first (sorted by
    their "fs_<N>_..." numeric prefix), then rooms (respecting _roomOrder when
    present), and within each room: Room Overview photos first, then items in
    _itemOrder (falling back to insertion order). This module doesn't load
    the Template, so exact template-defined item order isn't guaranteed —
    good enough for a photo browser, unlike the PDF itself.
    """
    if not isinstance(rd, dict):
        return []

    photos = []

    def add_row(sid, rid, row_data, label):
        if not isinstance(row_data, dict):
            return
        for p in (row_data.get('_photos') or []):
            src = _photo_src(p)
            if src:
                photos.append({'src': src, 'sid': str(sid), 'rid': str(rid), 'label': label})

    def ordered_row_ids(section):
        order = section.get('_itemOrder') or []
        all_ids = [k for k in section.keys() if not k.startswith('_')]
        seen = set(order)
        return [r for r in order if r in all_ids] + [r for r in all_ids if r not in seen]

    # Fixed sections, ordered by their fs_<N>_ prefix
    fixed_keys = [k for k in rd.keys() if isinstance(k, str) and k.startswith('fs_')]
    fixed_keys.sort(key=lambda k: int(m.group(1)) if (m := _FS_PREFIX_RE.match(k)) else 999)
    for sid in fixed_keys:
        section = rd.get(sid)
        if not isinstance(section, dict):
            continue
        label = sid.split('_', 2)[-1].replace('_', ' ').title() if '_' in sid else sid
        for rid in ordered_row_ids(section):
            add_row(sid, rid, section.get(rid), label)

    # Rooms, respecting _roomOrder
    room_names   = rd.get('_roomNames') or {}
    hidden_rooms = set(str(r) for r in (rd.get('_hiddenRooms') or []))
    room_order   = [str(r) for r in (rd.get('_roomOrder') or [])]
    room_keys = [
        k for k in rd.keys()
        if isinstance(k, str) and k not in fixed_keys and k not in _NON_ROOM_KEYS
        and not k.startswith('_') and isinstance(rd.get(k), dict)
    ]
    seen_rooms = set(room_order)
    ordered_rooms = [r for r in room_order if r in room_keys] + [r for r in room_keys if r not in seen_rooms]

    for sid in ordered_rooms:
        if sid in hidden_rooms:
            continue
        section = rd.get(sid) or {}
        label   = room_names.get(sid, sid)

        overview = section.get('_overview')
        if isinstance(overview, dict):
            add_row(sid, '_overview', overview, f'{label} — Overview')

        for rid in ordered_row_ids(section):
            add_row(sid, rid, section.get(rid), label)

    return photos


def _compress_photo(src: str, max_px: int = 1600, quality: int = 82) -> bytes:
    """
    Decode a photo src (data URI or URL) and compress it with Pillow.
    Returns JPEG bytes.  Falls back to raw decoded bytes on any Pillow error.
    max_px/quality are tuned down for filmstrip thumbnails (see ?thumb=1).
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
        if w > max_px or h > max_px:
            pil.thumbnail((max_px, max_px), _PILImg.LANCZOS)
        out = io.BytesIO()
        pil.save(out, format='JPEG', quality=quality, optimize=True)
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

    # ── Build the whole-report flat photo list and find where this item's
    # first photo sits within it, so the viewer opens straight to it. ───────
    all_photos = _collect_all_photos(rd)
    if not all_photos:
        all_photos = [{'src': p, 'sid': str(sid), 'rid': str(rid), 'label': label} for p in photos]
    start_index = next(
        (i for i, p in enumerate(all_photos) if p['sid'] == str(sid) and p['rid'] == str(rid)),
        0,
    )
    count        = len(all_photos)
    report_token = make_report_token(inspection_id)

    thumbs_html = ''.join(
        f'<img class="thumb{" active" if i == start_index else ""}" data-idx="{i}" '
        f'src="/api/gallery/{inspection_id}/photo/{i}?token={report_token}&thumb=1" '
        f'alt="Photo {i + 1}" loading="lazy" onclick="goTo({i})">\n'
        for i in range(count)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html.escape(label)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{background:#0f172a;font-family:system-ui,-apple-system,sans-serif;
      display:flex;flex-direction:column;overflow:hidden}}
.hdr{{background:#1e293b;padding:12px 20px;border-bottom:1px solid #334155;
      display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-shrink:0}}
.hdr h1{{color:#f1f5f9;font-size:15px;font-weight:600;
         white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.hdr p{{color:#94a3b8;font-size:12px;white-space:nowrap}}
.main{{flex:1;display:flex;align-items:center;justify-content:center;
       position:relative;padding:16px;min-height:0}}
.main img{{max-width:100%;max-height:100%;object-fit:contain;border-radius:4px;background:#1e293b}}
.nav-btn{{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:44px;
          border-radius:50%;border:none;background:rgba(15,23,42,.65);color:#fff;
          font-size:24px;line-height:1;cursor:pointer;display:flex;align-items:center;
          justify-content:center;user-select:none}}
.nav-btn:hover{{background:rgba(15,23,42,.92)}}
.nav-btn:disabled{{opacity:.25;cursor:default}}
.nav-prev{{left:14px}}
.nav-next{{right:14px}}
.filmstrip{{background:#1e293b;border-top:1px solid #334155;padding:8px;
            display:flex;gap:6px;overflow-x:auto;scroll-behavior:smooth;flex-shrink:0}}
.thumb{{width:64px;height:64px;object-fit:cover;border-radius:4px;cursor:pointer;
        opacity:.55;flex-shrink:0;border:2px solid transparent;
        transition:opacity .15s,border-color .15s}}
.thumb:hover{{opacity:.85}}
.thumb.active{{opacity:1;border-color:#6366f1}}
</style>
</head>
<body>
<div class="hdr">
  <h1>{_html.escape(label)}</h1>
  <p id="counter">Photo {start_index + 1} of {count}</p>
</div>
<div class="main">
  <button class="nav-btn nav-prev" id="prevBtn" onclick="goTo(current-1)">&#8249;</button>
  <img id="mainImg" alt="">
  <button class="nav-btn nav-next" id="nextBtn" onclick="goTo(current+1)">&#8250;</button>
</div>
<div class="filmstrip" id="filmstrip">
{thumbs_html}</div>
<script>
const total = {count};
const token = "{report_token}";
const inspectionId = {inspection_id};
let current = {start_index};

function urlFor(i, thumb) {{
  return `/api/gallery/${{inspectionId}}/photo/${{i}}?token=${{token}}` + (thumb ? '&thumb=1' : '');
}}

function goTo(i) {{
  if (i < 0 || i >= total) return;
  current = i;
  document.getElementById('mainImg').src = urlFor(i, false);
  document.getElementById('counter').textContent = `Photo ${{i + 1}} of ${{total}}`;
  document.getElementById('prevBtn').disabled = i === 0;
  document.getElementById('nextBtn').disabled = i === total - 1;
  document.querySelectorAll('.thumb').forEach(t => t.classList.toggle('active', Number(t.dataset.idx) === i));
  const activeThumb = document.querySelector('.thumb.active');
  if (activeThumb) activeThumb.scrollIntoView({{behavior:'smooth', inline:'center', block:'nearest'}});
}}

document.addEventListener('keydown', e => {{
  if (e.key === 'ArrowLeft') goTo(current - 1);
  if (e.key === 'ArrowRight') goTo(current + 1);
}});

let touchStartX = null;
const mainEl = document.querySelector('.main');
mainEl.addEventListener('touchstart', e => {{ touchStartX = e.touches[0].clientX; }});
mainEl.addEventListener('touchend', e => {{
  if (touchStartX === null) return;
  const dx = e.changedTouches[0].clientX - touchStartX;
  if (dx > 50) goTo(current - 1);
  else if (dx < -50) goTo(current + 1);
  touchStartX = null;
}});

goTo(current);
</script>
</body>
</html>"""

    return make_response(html, 200, {'Content-Type': 'text/html; charset=utf-8'})


# ── Per-photo binary endpoint (whole-report flat index) ───────────────────────

@gallery_bp.route('/gallery/<int:inspection_id>/photo/<int:n>')
def gallery_photo_flat(inspection_id, n):
    """
    Serve the nth photo of the WHOLE REPORT's flat photo list as a compressed
    JPEG — ?thumb=1 for a small filmstrip-sized version. Uses the report-wide
    token (not the per-item one), since this browses across every item.
    """
    token    = request.args.get('token', '')
    expected = make_report_token(inspection_id)
    if not hmac.compare_digest(token, expected):
        abort(403)

    thumb = request.args.get('thumb') == '1'
    cache_key = (inspection_id, n, thumb)
    now = time.time()
    cached = _PHOTO_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return make_response(cached[1], 200, {
            'Content-Type':  'image/jpeg',
            'Cache-Control': 'private, max-age=3600',
            'X-Cache':       'HIT',
        })

    rd, _, _ = _load_report_data(inspection_id)
    all_photos = _collect_all_photos(rd)

    if n < 0 or n >= len(all_photos):
        abort(404)

    try:
        data = (
            _compress_photo(all_photos[n]['src'], max_px=320, quality=70) if thumb
            else _compress_photo(all_photos[n]['src'])
        )
    except Exception as e:
        import traceback
        print(f'[gallery] flat photo {n} error: {e}')
        print(traceback.format_exc())
        abort(500)

    # Store in cache, then enforce the hard cap: first drop anything already
    # TTL-stale, and if sustained traffic within the TTL window means that
    # still isn't enough, drop the oldest entries too — the cache must never
    # grow past _PHOTO_CACHE_MAX regardless of traffic pattern.
    _PHOTO_CACHE[cache_key] = (now + _PHOTO_TTL, data)
    if len(_PHOTO_CACHE) > _PHOTO_CACHE_MAX:
        stale = [k for k, v in _PHOTO_CACHE.items() if v[0] < now]
        for k in stale:
            del _PHOTO_CACHE[k]
        overflow = len(_PHOTO_CACHE) - _PHOTO_CACHE_MAX
        if overflow > 0:
            oldest = sorted(_PHOTO_CACHE.items(), key=lambda kv: kv[1][0])[:overflow]
            for k, _ in oldest:
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
