"""
gallery.py — Public photo gallery endpoint for PDF clickable-photo links.

Routes:
  GET /api/gallery/<inspection_id>/<sid>/<rid>
      → Full HTML gallery with photos embedded as compressed data URIs.
        No secondary requests needed — everything is in one response.

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
import base64
import html as _html
from flask import Blueprint, request, abort, make_response

gallery_bp = Blueprint('gallery', __name__)


def make_gallery_token(inspection_id, sid, rid):
    secret = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    msg    = f'{inspection_id}:{sid}:{rid}'
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def _load_photos(inspection_id, sid, rid):
    """Return (photos_list, label) for the given inspection / section / row."""
    from models import Inspection
    insp = Inspection.query.get_or_404(inspection_id)

    rd = {}
    if insp.report_data:
        try:
            rd = json.loads(insp.report_data) if isinstance(insp.report_data, str) else insp.report_data
        except Exception as e:
            print(f'[gallery] ERROR parsing report_data for inspection {inspection_id}: {e}')

    sid_key = str(sid)
    rid_key = str(rid)
    section_data = rd.get(sid_key) or {}
    row_data     = section_data.get(rid_key) or {}
    raw          = row_data.get('_photos', []) or []

    print(f'[gallery] inspection={inspection_id} sid={sid_key!r} rid={rid_key!r} '
          f'section_keys={list(section_data.keys())[:10]} raw_count={len(raw)}')

    # Normalise: items may be strings (URL / data-URI) or dicts with a 'url' key
    photos = []
    for p in raw:
        if isinstance(p, str):
            photos.append(p)
        elif isinstance(p, dict):
            url = p.get('url') or p.get('src') or ''
            if url:
                photos.append(url)

    print(f'[gallery] normalised photo count: {len(photos)}')

    label = ''
    try:
        prop = insp.property
        if prop:
            label = prop.address or ''
    except Exception:
        pass
    if not label:
        label = f'Inspection #{inspection_id}'

    return photos, label


def _compress_to_data_uri(raw_url: str, max_px: int = 1400, quality: int = 75) -> str:
    """
    Decode a photo (data URI or HTTP URL) and return a compressed JPEG data URI.
    Falls back to the original string if anything fails.
    """
    try:
        if raw_url.startswith('data:'):
            _, b64data = raw_url.split(',', 1)
            data = base64.b64decode(b64data)
        else:
            import urllib.request
            req  = urllib.request.Request(raw_url, headers={'User-Agent': 'InspectPro/1.0'})
            data = urllib.request.urlopen(req, timeout=10).read()

        from PIL import Image as _PILImage, ImageOps
        pil = _PILImage.open(io.BytesIO(data)).convert('RGB')
        try:
            pil = ImageOps.exif_transpose(pil)
        except Exception:
            pass
        w, h = pil.size
        if w > max_px or h > max_px:
            pil.thumbnail((max_px, max_px), _PILImage.LANCZOS)
        out = io.BytesIO()
        pil.save(out, format='JPEG', quality=quality, optimize=True)
        compressed = base64.b64encode(out.getvalue()).decode('ascii')
        return f'data:image/jpeg;base64,{compressed}'
    except Exception as e:
        print(f'[gallery] compress error: {e}')
        # If we can't compress, return the original if it's already a data URI;
        # otherwise return empty string to skip the broken image.
        return raw_url if raw_url.startswith('data:') else ''


# ── Gallery HTML (photos embedded inline) ─────────────────────────────────────

@gallery_bp.route('/gallery/<int:inspection_id>/<sid>/<rid>')
def photo_gallery(inspection_id, sid, rid):
    token    = request.args.get('token', '')
    expected = make_gallery_token(inspection_id, sid, rid)
    if not hmac.compare_digest(token, expected):
        abort(403)

    photos, label = _load_photos(inspection_id, sid, rid)

    if not photos:
        body = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_html.escape(label)}</title>'
            '<style>body{background:#0f172a;font-family:system-ui,sans-serif;'
            'display:flex;align-items:center;justify-content:center;min-height:100vh}'
            'p{color:#64748b;font-size:15px;text-align:center;padding:24px}</style>'
            '</head><body>'
            f'<p>No photos found for this item.<br>'
            f'<small style="color:#475569">({_html.escape(label)} — {sid}/{rid})</small></p>'
            '</body></html>'
        )
        return make_response(body, 200, {'Content-Type': 'text/html; charset=utf-8'})

    count  = len(photos)
    plural = 's' if count != 1 else ''

    # Compress every photo and embed directly as data URIs.
    # This avoids all secondary /photo/<n> requests and works in any browser context.
    photo_srcs = []
    for p in photos:
        uri = _compress_to_data_uri(p)
        if uri:
            photo_srcs.append(uri)

    if not photo_srcs:
        # All photos failed to compress — shouldn't happen but handle gracefully
        body = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<style>body{background:#0f172a;display:flex;align-items:center;'
            'justify-content:center;min-height:100vh}'
            'p{color:#ef4444;font-size:15px;font-family:system-ui}</style>'
            '</head><body><p>Photos could not be loaded. Please try again.</p></body></html>'
        )
        return make_response(body, 200, {'Content-Type': 'text/html; charset=utf-8'})

    # Embed srcs directly into the HTML — no JS fetch needed.
    imgs_html = ''
    for i, src in enumerate(photo_srcs):
        imgs_html += (
            f'<img src="{src}" alt="Photo {i+1}" loading="lazy" '
            f'onclick="openLb(this.src)">'
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

    # Summarise photo types without dumping full base64 payloads
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
