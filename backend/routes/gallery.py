"""
gallery.py — Public photo gallery endpoint for PDF clickable-photo links.

Routes:
  GET /api/gallery/<inspection_id>/<sid>/<rid>
      → HTML gallery shell (lightweight, no embedded photos)

  GET /api/gallery/<inspection_id>/<sid>/<rid>/photo/<index>
      → binary image response for photo[index]

Token:  HMAC-SHA256(JWT_SECRET_KEY, "{inspection_id}:{sid}:{rid}")[:16]
No login required — the HMAC token provides security without a session.
"""

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
        except Exception:
            pass

    raw = (rd.get(str(sid)) or {}).get(str(rid), {}).get('_photos', []) or []

    # Normalise: items may be strings (URL / data-URI) or dicts with a 'url' key
    photos = []
    for p in raw:
        if isinstance(p, str):
            photos.append(p)
        elif isinstance(p, dict):
            url = p.get('url') or p.get('src') or ''
            if url:
                photos.append(url)

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


# ── Gallery HTML shell ────────────────────────────────────────────────────────

@gallery_bp.route('/gallery/<int:inspection_id>/<sid>/<rid>')
def photo_gallery(inspection_id, sid, rid):
    token    = request.args.get('token', '')
    expected = make_gallery_token(inspection_id, sid, rid)
    if not hmac.compare_digest(token, expected):
        abort(403)

    photos, label = _load_photos(inspection_id, sid, rid)

    if not photos:
        return make_response(
            '<p style="font-family:system-ui;padding:24px;color:#64748b">'
            'No photos found for this item.</p>',
            200, {'Content-Type': 'text/html; charset=utf-8'}
        )

    count  = len(photos)
    plural = 's' if count != 1 else ''

    # Build photo src list: use /photo/<n> endpoint for data URIs (avoids
    # embedding megabytes of base64 in the HTML), pass through http URLs directly.
    photo_srcs = []
    for i, p in enumerate(photos):
        if p.startswith('data:'):
            photo_srcs.append(
                f'/api/gallery/{inspection_id}/{sid}/{rid}/photo/{i}?token={token}'
            )
        else:
            photo_srcs.append(p)

    srcs_js = json.dumps(photo_srcs)

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
<div class="grid" id="grid"></div>
<div class="lb" id="lb" onclick="closeLb()">
  <span class="lb-x">&#215;</span>
  <img id="lb-img" src="" alt="">
</div>
<script>
var SRCS = {srcs_js};
var grid = document.getElementById('grid');
SRCS.forEach(function(src, i) {{
  var img     = document.createElement('img');
  img.alt     = 'Photo ' + (i + 1);
  img.src     = src;
  img.onclick = (function(s) {{ return function() {{ openLb(s); }}; }})(src);
  grid.appendChild(img);
}});
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


# ── Individual photo binary endpoint ─────────────────────────────────────────

@gallery_bp.route('/gallery/<int:inspection_id>/<sid>/<rid>/photo/<int:index>')
def gallery_photo(inspection_id, sid, rid, index):
    token    = request.args.get('token', '')
    expected = make_gallery_token(inspection_id, sid, rid)
    if not hmac.compare_digest(token, expected):
        abort(403)

    photos, _ = _load_photos(inspection_id, sid, rid)

    if index < 0 or index >= len(photos):
        abort(404)

    photo = photos[index]

    if photo.startswith('data:'):
        # Parse  data:<mime>;base64,<data>
        try:
            header, b64data = photo.split(',', 1)
            mime = header.split(':')[1].split(';')[0]  # e.g. 'image/jpeg'
            image_bytes = base64.b64decode(b64data)
            return make_response(image_bytes, 200, {
                'Content-Type':  mime,
                'Cache-Control': 'private, max-age=3600',
            })
        except Exception:
            abort(500)
    else:
        # HTTP URL — redirect the browser to fetch it directly
        from flask import redirect
        return redirect(photo)
