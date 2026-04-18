"""
pdf_generator.py — Server-side PDF generation for InspectPro.

Uses ReportLab (pure Python, no system libraries, works on Render free tier
with any Python version including 3.14).

Renders the same sections as PdfExportModal.vue:
  Cover → Contents → Disclaimer → Fixed Sections → Rooms →
  Action Summary (check-out) → Declaration

Usage:
    from routes.pdf_generator import generate_inspection_pdf
    pdf_bytes = generate_inspection_pdf(inspection_id)
"""

import io
import json
import os
import hmac as _hmac
import hashlib
import urllib.request
from datetime import datetime

APP_BASE_URL = os.environ.get('APP_BASE_URL', 'https://app.lminventories.co.uk')

from models import db, Inspection

# ── ReportLab imports ─────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether, Image as RLImage,
)
from reportlab.platypus.flowables import HRFlowable, Flowable
from reportlab.pdfbase import pdfmetrics


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_inspection_pdf(inspection_id: int) -> bytes:
    """
    Generate a PDF for the given inspection and return raw bytes.
    Raises ValueError if the inspection doesn't exist.
    """
    inspection = Inspection.query.get(inspection_id)
    if not inspection:
        raise ValueError(f'Inspection {inspection_id} not found')

    builder = _PDFBuilder(inspection)
    return builder.build()


# ─────────────────────────────────────────────────────────────────────────────
# Colour helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hex(h: str):
    """Convert '#RRGGBB' to a ReportLab Color."""
    h = (h or '#1E3A8A').strip().lstrip('#')
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return colors.Color(r/255, g/255, b/255)
    except Exception:
        return colors.HexColor('#1E3A8A')

def _lighten(color, factor=0.92):
    r = 1 - (1 - color.red)   * (1 - factor)
    g = 1 - (1 - color.green) * (1 - factor)
    b = 1 - (1 - color.blue)  * (1 - factor)
    return colors.Color(r, g, b)

_SLATE_100  = colors.HexColor('#f1f5f9')
_SLATE_200  = colors.HexColor('#e2e8f0')
_SLATE_400  = colors.HexColor('#94a3b8')
_SLATE_500  = colors.HexColor('#64748b')
_SLATE_800  = colors.HexColor('#1e293b')
_WHITE      = colors.white
_GREEN_BG   = colors.HexColor('#dcfce7')
_GREEN_TXT  = colors.HexColor('#166534')
_RED_BG     = colors.HexColor('#fee2e2')
_RED_TXT    = colors.HexColor('#991b1b')


# ─────────────────────────────────────────────────────────────────────────────
# Fetch image bytes from URL
# ─────────────────────────────────────────────────────────────────────────────

def _compress_image(data: bytes, max_px: int = 1200, quality: int = 72) -> bytes:
    """
    Resize and re-compress image bytes with Pillow before embedding in PDF.
    Keeps peak memory low — a 5 MB phone JPEG becomes ~120 KB after this.
    Falls back to the original bytes if Pillow is unavailable or the image
    can't be decoded (e.g. corrupt data).
    """
    try:
        from PIL import Image as _PILImage
        pil = _PILImage.open(io.BytesIO(data))
        pil = pil.convert('RGB')
        # Preserve EXIF orientation so photos aren't rotated in the PDF
        try:
            from PIL import ImageOps
            pil = ImageOps.exif_transpose(pil)
        except Exception:
            pass
        w, h = pil.size
        if w > max_px or h > max_px:
            pil.thumbnail((max_px, max_px), _PILImage.LANCZOS)
        out = io.BytesIO()
        pil.save(out, format='JPEG', quality=quality, optimize=True)
        return out.getvalue()
    except Exception:
        return data


def _fetch_image(url: str, max_w_mm: float, max_h_mm: float, link_url: str = None):
    if not url:
        return None
    try:
        if url.startswith('data:'):
            # Base64 data URI — decode directly (used for photos synced from mobile)
            import base64 as _b64
            _, b64data = url.split(',', 1)
            data = _b64.b64decode(b64data)
        else:
            req  = urllib.request.Request(url, headers={'User-Agent': 'InspectPro/1.0'})
            data = urllib.request.urlopen(req, timeout=8).read()
        data = _compress_image(data)
        buf  = io.BytesIO(data)
        img  = RLImage(buf)
        w_pt = max_w_mm * mm
        h_pt = max_h_mm * mm
        scale = min(w_pt / img.drawWidth, h_pt / img.drawHeight, 1.0)
        img.drawWidth  *= scale
        img.drawHeight *= scale
        if link_url:
            return _ClickableImage(img, link_url)
        return img
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Coloured header-bar flowable
# ─────────────────────────────────────────────────────────────────────────────

class _Anchor(Flowable):
    """Zero-height flowable that drops a named PDF destination for TOC links."""
    def __init__(self, name):
        super().__init__()
        self.name = name

    def wrap(self, available_w, available_h):
        self.width = available_w
        return available_w, 0

    def draw(self):
        self.canv.bookmarkHorizontal(self.name, 0, 0)


class _HeaderBar(Flowable):
    def __init__(self, text, bg_color, txt_color, font_size=11, anchor=None):
        super().__init__()
        self.text      = text
        self.bg_color  = bg_color
        self.txt_color = txt_color
        self.font_size = font_size
        self.height    = font_size * 1.8 + 8
        self.anchor    = anchor

    def wrap(self, available_w, available_h):
        self.width = available_w
        return available_w, self.height

    def draw(self):
        # Place PDF bookmark at the top of this header bar so TOC links jump here
        if self.anchor:
            self.canv.bookmarkHorizontal(self.anchor, 0, self.height)
        c = self.canv
        c.setFillColor(self.bg_color)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.setFillColor(self.txt_color)
        c.setFont('Helvetica-Bold', self.font_size)
        c.drawString(8, self.height * 0.25, self.text)


# ─────────────────────────────────────────────────────────────────────────────
# Clickable image wrapper
# ─────────────────────────────────────────────────────────────────────────────

class _ClickableImage(Flowable):
    """Wraps an RLImage and overlays a clickable URL annotation."""
    def __init__(self, img, url):
        super().__init__()
        self._img       = img
        self._url       = url
        self.drawWidth  = img.drawWidth
        self.drawHeight = img.drawHeight

    def wrap(self, availW, availH):
        w, h            = self._img.wrap(availW, availH)
        self.drawWidth  = w
        self.drawHeight = h
        return w, h

    def draw(self):
        self._img.drawOn(self.canv, 0, 0)
        if self._url:
            self.canv.linkURL(
                self._url,
                (0, 0, self.drawWidth, self.drawHeight),
                relative=1,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Gallery URL helpers  (must match gallery.py make_gallery_token exactly)
# ─────────────────────────────────────────────────────────────────────────────

def _gallery_token(inspection_id, sid, rid):
    import os
    secret = os.environ.get('JWT_SECRET_KEY', 'change-me-in-production')
    msg    = f'{inspection_id}:{sid}:{rid}'
    return _hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def _gallery_url(base_url, inspection_id, sid, rid):
    token = _gallery_token(inspection_id, sid, rid)
    base  = (base_url or '').rstrip('/')
    return f'{base}/api/gallery/{inspection_id}/{sid}/{rid}?token={token}'


# ─────────────────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────────────────

class _PDFBuilder:

    def __init__(self, inspection):
        self.inspection = inspection

        self.cl   = _client_dict(inspection.property.client if inspection.property else None)
        self.prop = _prop_dict(inspection.property)

        self.brand  = _hex(self.cl.get('report_color_override') or self.cl.get('primary_color') or '#1E3A8A')
        self.hdr_c  = _hex(self.cl.get('report_header_text_color') or '#FFFFFF')
        self.body_c = _hex(self.cl.get('report_body_text_color')   or '#1e293b')

        orient = (self.cl.get('report_orientation') or 'portrait').lower()
        self.pagesize = landscape(A4) if orient == 'landscape' else A4
        self.pw, self.ph = self.pagesize
        self.margin = 14 * mm

        ps = {}
        if self.cl.get('report_photo_settings'):
            try:
                ps = json.loads(self.cl['report_photo_settings']) if isinstance(self.cl['report_photo_settings'], str) else self.cl['report_photo_settings']
            except Exception:
                pass
        self.ov_pos   = ps.get('photo_room_overview',     'above')
        self.item_pos = ps.get('photo_room_item',         'below')
        self.add_ts   = ps.get('show_photo_timestamp',    False) is True
        self.act_pos  = ps.get('action_summary_position', 'bottom')

        # ── Fixed sections — from system_settings or DEFAULT_FIXED_SECTIONS ──
        self.fixed_sections = _load_fixed_sections()

        # ── Report data — loaded early so rooms can use _roomNames override ──
        self.rd = {}
        if inspection.report_data:
            try:
                self.rd = json.loads(inspection.report_data) if isinstance(inspection.report_data, str) else inspection.report_data
            except Exception:
                pass

        # ── Rooms — from template.sections filtered by section_type='room' ──
        # report_data keys rooms by String(s.id) — the DB section id.
        # Items use item.id as the row key, and item.name as the label.
        self.rooms = []
        tmpl = inspection.template
        if tmpl:
            room_names   = self.rd.get('_roomNames', {})
            hidden_rooms = set(str(x) for x in (self.rd.get('_hiddenRooms') or []))
            for s in sorted(tmpl.sections or [], key=lambda x: x.order_index):
                if s.section_type == 'room':
                    if str(s.id) in hidden_rooms:
                        continue          # room was deleted by clerk — skip entirely
                    name = room_names.get(str(s.id), s.name)
                    self.rooms.append({
                        'id':   s.id,   # used as report_data key (String(s.id))
                        'name': name,
                        'sections': [
                            {
                                'id':          item.id,
                                'name':        item.name,
                                'label':       item.name,
                                'description': item.description or '',
                                'hasCondition': item.requires_condition is not False,
                            }
                            for item in sorted(s.items or [], key=lambda i: i.order_index)
                        ],
                    })

        # ── Action catalogue — not used in current schema, empty list ────────
        self.action_catalogue = []

        itype = inspection.inspection_type or ''
        self.is_check_out    = itype == 'check_out'
        self.is_damage_report = itype == 'damage_report'
        self.type_label   = {
            'check_in':      'Inventory & Check In',
            'check_out':     'Check Out',
            'interim':       'Interim Inspection',
            'inventory':     'Inventory Report',
            'damage_report': 'Damage Report',
        }.get(itype, 'Inspection Report')

        self._init_styles()

        self.actions_summary = []
        self.action_groups   = {}
        if self.is_check_out:
            self._build_actions_summary()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _init_styles(self):
        bc = self.body_c
        self.s_body     = ParagraphStyle('body',     fontName='Helvetica',      fontSize=9,    leading=13, textColor=bc, spaceAfter=4)
        self.s_bold     = ParagraphStyle('bold',     fontName='Helvetica-Bold', fontSize=9,    leading=13, textColor=bc)
        self.s_small    = ParagraphStyle('small',    fontName='Helvetica',      fontSize=7.5,  leading=11, textColor=_SLATE_500)
        self.s_hdr_cell = ParagraphStyle('hdr_cell', fontName='Helvetica-Bold', fontSize=7.5,  leading=10, textColor=self.hdr_c)
        self.s_cell     = ParagraphStyle('cell',     fontName='Helvetica',      fontSize=8,    leading=11, textColor=bc)
        self.s_cell_sm  = ParagraphStyle('cell_sm',  fontName='Helvetica',      fontSize=7,    leading=10, textColor=_SLATE_500)
        self.s_ref      = ParagraphStyle('ref',      fontName='Helvetica-Bold', fontSize=7.5,  leading=10, textColor=bc)
        self.s_title    = ParagraphStyle('title',    fontName='Helvetica-Bold', fontSize=20,   leading=26, textColor=self.hdr_c, alignment=TA_CENTER)
        self.s_toc_num  = ParagraphStyle('toc_num',  fontName='Helvetica-Bold', fontSize=9.5,  leading=14, textColor=self.brand)
        self.s_toc_ttl  = ParagraphStyle('toc_ttl',  fontName='Helvetica',      fontSize=9.5,  leading=14, textColor=bc)
        self.s_toc_link = ParagraphStyle('toc_link', fontName='Helvetica',      fontSize=9.5,  leading=14, textColor=bc)
        self.s_decl     = ParagraphStyle('decl',     fontName='Helvetica',      fontSize=9,    leading=15, textColor=bc, spaceAfter=20)
        self.s_link     = ParagraphStyle('link',     fontName='Helvetica',      fontSize=7.5,  leading=11, textColor=colors.HexColor('#3b82f6'))

    # ── Report data accessors ─────────────────────────────────────────────────

    def _get(self, sid, rid, field):
        return (self.rd.get(str(sid)) or {}).get(str(rid), {}).get(field, '') or ''

    def _get_subs(self, sid, rid):
        return (self.rd.get(str(sid)) or {}).get(str(rid), {}).get('_subs') or []

    def _hidden(self, sid, rid):
        return str(rid) in ((self.rd.get(str(sid)) or {}).get('_hidden', []) or [])

    def _item_hidden(self, rid, iid):
        return str(iid) in ((self.rd.get(str(rid)) or {}).get('_hiddenItems', []) or [])

    def _extra(self, sid):
        return (self.rd.get(str(sid)) or {}).get('_extra', []) or []

    def _photos(self, sid, rid):
        return (self.rd.get(str(sid)) or {}).get(str(rid), {}).get('_photos', []) or []

    def _photo_ts(self, sid, rid):
        return (self.rd.get(str(sid)) or {}).get(str(rid), {}).get('_photoTs', []) or []

    def _item_actions(self, rid, iid):
        return (self.rd.get(str(rid)) or {}).get(f'_actions_{iid}', []) or []

    def _ordered_items(self, room):
        room_rd_key = str(room['id'])   # rooms keyed by String(section.id) in report_data
        stored  = (self.rd.get(room_rd_key) or {}).get('_itemOrder', None)
        # Filter items deleted by the clerk on mobile
        deleted = set(str(d) for d in ((self.rd.get(room_rd_key) or {}).get('_deleted', []) or []))
        tmpl    = [dict(i, _type='template', label=i.get('name','')) for i in (room.get('sections') or [])
                   if str(i.get('id', '')) not in deleted]
        extras  = [dict(ex, id=ex.get('_eid'), label=ex.get('label') or ex.get('name','New item'), _type='extra')
                   for ex in ((self.rd.get(room_rd_key) or {}).get('_extra', []) or [])
                   if str(ex.get('_eid', '')) not in deleted]
        all_items = tmpl + extras
        if not stored:
            return all_items
        ordered = []
        for oid in stored:
            m = next((i for i in all_items if str(i.get('id')) == str(oid) or str(i.get('_eid', '')) == str(oid)), None)
            if m:
                ordered.append(m)
        for item in all_items:
            key = str(item.get('_eid', '')) if item['_type'] == 'extra' else str(item.get('id', ''))
            if not any(str(o) == key for o in stored):
                ordered.append(item)
        return ordered

    def _action_name(self, aid):
        c = next((x for x in self.action_catalogue if str(x.get('id')) == str(aid)), None)
        return (c or {}).get('name') or str(aid) or '—'

    def _action_color(self, aid):
        c = next((x for x in self.action_catalogue if str(x.get('id')) == str(aid)), None)
        return (c or {}).get('color') or '#64748b'

    def _build_actions_summary(self):
        for room in self.rooms:
            for item in self._ordered_items(room):
                iid = item.get('_eid') if item['_type'] == 'extra' else item.get('id')
                if self._item_hidden(room['id'], iid):
                    continue
                for act in self._item_actions(room['id'], iid):
                    if not act.get('actionId'):
                        continue
                    self.actions_summary.append({'room': room.get('name', ''), 'item': item.get('label') or item.get('name') or '', **act})
        for a in self.actions_summary:
            aid = a['actionId']
            if aid not in self.action_groups:
                self.action_groups[aid] = {'name': self._action_name(aid), 'color': self._action_color(aid), 'items': []}
            self.action_groups[aid]['items'].append(a)

    # ── Misc helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_date(val):
        if not val:
            return ''
        try:
            d = val if isinstance(val, datetime) else datetime.fromisoformat(str(val).replace('Z', '+00:00'))
            return d.strftime('%d %B %Y')
        except Exception:
            return str(val)

    @staticmethod
    def _fmt_ts(val):
        if not val:
            return ''
        try:
            d = val if isinstance(val, datetime) else datetime.fromisoformat(str(val).replace('Z', '+00:00'))
            return d.strftime('%d %b %Y %H:%M')
        except Exception:
            return str(val)

    def _p(self, text, style=None):
        style = style or self.s_cell
        text  = str(text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # Convert \n line breaks to ReportLab <br/> tags so multi-line conditions render correctly
        text  = text.replace('\n', '<br/>')
        return Paragraph(text or '—', style)

    def _uw(self):
        return self.pw - 2 * self.margin

    def _table_style(self, brand=None, hdr_c=None):
        brand = brand or self.brand
        hdr_c = hdr_c or self.hdr_c
        return TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0), brand),
            ('TEXTCOLOR',      (0, 0), (-1, 0), hdr_c),
            ('FONTNAME',       (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',       (0, 0), (-1, 0), 7.5),
            ('TOPPADDING',     (0, 0), (-1, 0), 5),
            ('BOTTOMPADDING',  (0, 0), (-1, 0), 5),
            ('LEFTPADDING',    (0, 0), (-1,-1), 7),
            ('RIGHTPADDING',   (0, 0), (-1,-1), 7),
            ('TOPPADDING',     (0, 1), (-1,-1), 5),
            ('BOTTOMPADDING',  (0, 1), (-1,-1), 5),
            ('FONTNAME',       (0, 1), (-1,-1), 'Helvetica'),
            ('FONTSIZE',       (0, 1), (-1,-1), 8),
            ('VALIGN',         (0, 0), (-1,-1), 'TOP'),
            ('LINEBELOW',      (0, 1), (-1,-1), 0.5, _SLATE_100),
            ('ROWBACKGROUNDS', (0, 1), (-1,-1), [_WHITE, _SLATE_100]),
        ])

    def _photo_grid(self, sid, rid, cols=4, gallery_url=None):
        urls = self._photos(sid, rid)
        ts   = self._photo_ts(sid, rid)
        if not urls:
            return None
        uw      = self._uw()
        cell_w  = uw / cols
        cells   = []
        for i, url in enumerate(urls):
            img    = _fetch_image(url, cell_w / mm - 4, 38, link_url=gallery_url)
            ts_txt = self._fmt_ts(ts[i] if i < len(ts) else None) if self.add_ts else ''
            inner  = [img or Paragraph('(photo)', self.s_small)]
            if ts_txt:
                inner.append(Paragraph(ts_txt, self.s_small))
            cells.append(inner)
        while len(cells) % cols:
            cells.append([Paragraph('', self.s_small)])
        rows   = [cells[i:i+cols] for i in range(0, len(cells), cols)]
        tbl    = Table(rows, colWidths=[cell_w]*cols)
        tbl.setStyle(TableStyle([
            ('VALIGN',        (0,0),(-1,-1),'TOP'),
            ('ALIGN',         (0,0),(-1,-1),'CENTER'),
            ('TOPPADDING',    (0,0),(-1,-1), 2),
            ('BOTTOMPADDING', (0,0),(-1,-1), 2),
            ('LEFTPADDING',   (0,0),(-1,-1), 2),
            ('RIGHTPADDING',  (0,0),(-1,-1), 2),
        ]))
        return tbl

    def _badge(self, text, bg, fg):
        p = Paragraph(str(text or ''), ParagraphStyle('bdg', fontName='Helvetica-Bold', fontSize=7.5, leading=10, textColor=fg))
        t = Table([[p]], colWidths=[None])
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(0,0), bg),
            ('TOPPADDING',    (0,0),(0,0), 2),
            ('BOTTOMPADDING', (0,0),(0,0), 2),
            ('LEFTPADDING',   (0,0),(0,0), 5),
            ('RIGHTPADDING',  (0,0),(0,0), 5),
        ]))
        return t

    def _ans_badge(self, ans):
        if ans == 'Yes':   return self._badge(ans, _GREEN_BG, _GREEN_TXT)
        elif ans == 'No':  return self._badge(ans, _RED_BG,   _RED_TXT)
        else:              return self._badge(ans or '—', _SLATE_100, _SLATE_500)

    # ─────────────────────────────────────────────────────────────────────────
    # Build
    # ─────────────────────────────────────────────────────────────────────────

    def build(self) -> bytes:
        buf = io.BytesIO()
        uw  = self._uw()
        doc = BaseDocTemplate(buf, pagesize=self.pagesize,
                              leftMargin=self.margin, rightMargin=self.margin,
                              topMargin=self.margin,  bottomMargin=self.margin)

        # Cover page template — full-bleed, tiny frame just to hold the PageBreak
        cover_frame = Frame(0, 0, self.pw, self.ph,
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        cover_template = PageTemplate(id='cover', frames=[cover_frame],
                                      onPage=self._draw_cover)

        # Main content template — margin-constrained
        main_frame = Frame(self.margin, self.margin, uw, self.ph - 2*self.margin,
                           leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        main_template = PageTemplate(id='main', frames=[main_frame])

        doc.addPageTemplates([cover_template, main_template])

        story = []
        from reportlab.platypus import NextPageTemplate
        story += [NextPageTemplate('cover')]   # first page uses cover template
        story += self._cover()                  # emits NextPageTemplate('main') + PageBreak
        story += self._contents()
        story += self._disclaimer()
        if self.is_check_out and self.act_pos == 'top':
            story += self._action_summary()
        story += self._fixed_sections()
        story += self._rooms()
        if self.is_check_out and self.act_pos == 'bottom':
            story += self._action_summary()
        story += self._declaration()

        doc.build(story)
        return buf.getvalue()

    # ── Cover ─────────────────────────────────────────────────────────────────
    # Drawn entirely on the canvas for true edge-to-edge bleed.

    def _draw_cover(self, canvas, doc):
        """onPage callback — draws the full-bleed cover page directly on canvas.
        Layout matches PdfExportModal.vue exactly:
          - Brand header bar, logo left-aligned with padding
          - Full-width property photo
          - Type label centred below photo
          - Info rows (ADDRESS / DATE / CLIENT) centred with dividers
          - Brand footer bar pinned to very bottom
        """
        from reportlab.lib.utils import ImageReader
        canvas.saveState()
        pw, ph  = self.pagesize
        cl      = self.cl
        insp    = self.inspection
        brand   = self.brand
        hdr_c   = self.hdr_c
        margin  = self.margin          # 14mm — used for text inset only

        # ── Header bar ───────────────────────────────────────────────────────
        # Tall enough to give the logo generous space (matches cover-top padding ~48px+logo+40px)
        hdr_h = 42 * mm
        canvas.setFillColor(brand)
        canvas.rect(0, ph - hdr_h, pw, hdr_h, fill=1, stroke=0)

        # Logo — centred horizontally, vertically centred in bar
        logo_url = cl.get('logo')
        logo_drawn = False
        if logo_url:
            try:
                req  = urllib.request.Request(logo_url, headers={'User-Agent': 'InspectPro/1.0'})
                data = urllib.request.urlopen(req, timeout=8).read()
                img  = ImageReader(io.BytesIO(data))
                iw, ih = img.getSize()
                max_h = hdr_h - 12*mm
                max_w = pw - 2*margin
                scale = min(max_w/iw, max_h/ih)
                dw, dh = iw*scale, ih*scale
                x = (pw - dw) / 2
                y = ph - hdr_h + (hdr_h - dh) / 2
                canvas.drawImage(img, x, y, dw, dh, mask='auto')
                logo_drawn = True
            except Exception:
                pass
        if not logo_drawn:
            initials = ''.join(w[0] for w in (cl.get('company') or cl.get('name') or 'IP').split() if w)[:2].upper()
            canvas.setFillColor(hdr_c)
            canvas.setFont('Helvetica-Bold', 24)
            canvas.drawCentredString(pw/2, ph - hdr_h + (hdr_h - 8*mm) / 2, initials)

        # ── Property photo — full width, below header ─────────────────────────
        photo_h   = 90 * mm
        photo_y   = ph - hdr_h - photo_h
        photo_url = self.prop.get('overview_photo')
        photo_drawn = False
        if photo_url:
            try:
                req  = urllib.request.Request(photo_url, headers={'User-Agent': 'InspectPro/1.0'})
                data = urllib.request.urlopen(req, timeout=8).read()
                data = _compress_image(data, max_px=1600)
                img  = ImageReader(io.BytesIO(data))
                canvas.drawImage(img, 0, photo_y, pw, photo_h,
                                 preserveAspectRatio=False, mask='auto')
                photo_drawn = True
            except Exception:
                pass
        if not photo_drawn:
            canvas.setFillColor(_SLATE_100)
            canvas.rect(0, photo_y, pw, photo_h, fill=1, stroke=0)
            canvas.setFillColor(_SLATE_400)
            canvas.setFont('Helvetica', 11)
            canvas.drawCentredString(pw/2, photo_y + photo_h/2 - 4, 'Property overview photo')

        # ── Type label — centred below photo ──────────────────────────────────
        type_y = photo_y - 14*mm
        canvas.setFillColor(self.body_c)
        canvas.setFont('Helvetica-Bold', 18)
        canvas.drawCentredString(pw/2, type_y, self.type_label)

        # ── Info rows — centred, divider between every row ───────────────────
        footer_h = 10 * mm
        row_h    = 12 * mm
        info_rows = [
            ('ADDRESS', self.prop.get('address') or ''),
            ('DATE',    self._fmt_date(insp.conduct_date or insp.scheduled_date)),
            ('CLIENT',  cl.get('company') or cl.get('name') or ''),
        ]
        info_top = type_y - 7*mm

        for i, (lbl, val) in enumerate(info_rows):
            # top of this row
            row_top = info_top - i * row_h
            # label sits near top of row, value below it
            lbl_y = row_top - 3.5*mm
            val_y = lbl_y   - 4.5*mm
            # divider above every row
            canvas.setStrokeColor(_SLATE_100)
            canvas.setLineWidth(0.5)
            canvas.line(margin, row_top, pw - margin, row_top)
            # label
            canvas.setFillColor(_SLATE_400)
            canvas.setFont('Helvetica-Bold', 7)
            canvas.drawCentredString(pw/2, lbl_y, lbl)
            # value
            canvas.setFillColor(self.body_c)
            canvas.setFont('Helvetica-Bold', 11)
            canvas.drawCentredString(pw/2, val_y, val[:80])
        # closing divider after last row
        close_y = info_top - len(info_rows) * row_h
        canvas.setStrokeColor(_SLATE_100)
        canvas.setLineWidth(0.5)
        canvas.line(margin, close_y, pw - margin, close_y)

        # ── Footer bar — edge to edge, pinned to very bottom ─────────────────
        canvas.setFillColor(brand)
        canvas.rect(0, 0, pw, footer_h, fill=1, stroke=0)
        footer_name = cl.get('company') or cl.get('name') or 'InspectPro'
        canvas.setFillColor(hdr_c)
        canvas.setFont('Helvetica-Bold', 9)
        canvas.drawString(margin, footer_h * 0.38, footer_name)
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(pw - margin, footer_h * 0.38, 'Confidential')

        canvas.restoreState()

    def _cover(self):
        """Returns a single NextPageTemplate + PageBreak — actual drawing happens in _draw_cover."""
        from reportlab.platypus import NextPageTemplate
        return [_Anchor('anchor_cover'), NextPageTemplate('main'), PageBreak()]

    # ── Contents ──────────────────────────────────────────────────────────────

    def _contents(self):
        import re, html as _html_mod

        def _anchor_id(prefix, name=''):
            slug = re.sub(r'[^a-z0-9]', '_', name.lower()).strip('_') if name else ''
            return f'{prefix}_{slug}' if slug else prefix

        rows = []

        def add(title, anchor):
            safe = _html_mod.escape(title)
            rows.append([Paragraph(f'<a href="#{anchor}">{safe}</a>', self.s_toc_link)])

        add('Cover Page',  'anchor_cover')
        add('Contents',    'anchor_contents')
        if self.cl.get('report_disclaimer'):
            add('Disclaimers', 'anchor_disclaimers')
        if self.is_check_out and self.act_pos == 'top' and self.actions_summary:
            add('Action Summary', 'anchor_action_summary')
        for s in self.fixed_sections:
            add(s.get('name', ''), f'anchor_{s["id"]}')
        for r in self.rooms:
            add(r.get('name', ''), f'anchor_room_{r["id"]}')
        if self.is_check_out and self.act_pos == 'bottom' and self.actions_summary:
            add('Action Summary', 'anchor_action_summary')
        add('Declaration', 'anchor_declaration')

        uw  = self._uw()
        tbl = Table(rows, colWidths=[uw])
        tbl.setStyle(TableStyle([
            ('TOPPADDING',    (0,0),(-1,-1), 5),
            ('BOTTOMPADDING', (0,0),(-1,-1), 5),
            ('LEFTPADDING',   (0,0),(-1,-1), 4),
            ('LINEBELOW',     (0,0),(-1,-2), 0.5, _SLATE_100),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ]))
        return [_HeaderBar('Contents', self.brand, self.hdr_c, anchor='anchor_contents'),
                Spacer(1, 4*mm), tbl, PageBreak()]

    # ── Disclaimer ────────────────────────────────────────────────────────────

    def _disclaimer(self):
        disc = self.cl.get('report_disclaimer') or ''
        if not disc:
            return []
        text = disc.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br/>')
        return [_HeaderBar('Disclaimers', self.brand, self.hdr_c, anchor='anchor_disclaimers'), Spacer(1,4*mm), Paragraph(text, self.s_body), PageBreak()]

    # ── Fixed sections ────────────────────────────────────────────────────────

    LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    def _fixed_sections(self):
        story = []
        uw    = self._uw()

        for si, section in enumerate(self.fixed_sections):
            letter     = self.LETTERS[si] if si < len(self.LETTERS) else str(si+1)
            t          = section.get('type', '')
            sid        = section['id']
            vis_rows   = [r for r in (section.get('rows') or []) if not self._hidden(sid, r['id'])]
            extra_rows = self._extra(sid)
            n_vis      = len(vis_rows)

            def row_ref(row_id, is_extra=False):
                if not is_extra:
                    idx = next((i for i,r in enumerate(vis_rows) if str(r['id'])==str(row_id)), None)
                    if idx is not None: return f'{letter}.{idx+1}'
                else:
                    eidx = next((i for i,ex in enumerate(extra_rows) if ex.get('_eid')==row_id), None)
                    if eidx is not None: return f'{letter}.{n_vis+eidx+1}'
                return f'{letter}.?'

            def gv(r, is_extra, field):
                return (r.get(field) or '') if is_extra else (self._get(sid, r['id'], field) or r.get(field) or '')

            # All width sets must sum exactly to uw so tables are the same width.
            # vw = variable space after subtracting fixed-width columns (Ref=10mm, Answer=18mm)
            _vw  = uw - 10*mm          # variable width (no fixed Answer col)
            _vwa = uw - 10*mm - 18*mm  # variable width when Answer col present
            COL_DEFS = {
                'condition_summary': {'heads':['Ref','Name','Condition'],                                  'widths':[10*mm, _vw*0.44, _vw*0.56]},
                'cleaning_summary':  {'heads':['Ref','Area','Cleanliness','Notes'],                        'widths':[10*mm, _vw*0.30, _vw*0.22, _vw*0.48]},
                'smoke_alarms':      {'heads':['Ref','Question','Answer','Notes'],                         'widths':[10*mm, _vwa*0.55, 18*mm, _vwa*0.45]},
                'health_safety':     {'heads':['Ref','Question','Answer','Notes'],                         'widths':[10*mm, _vwa*0.55, 18*mm, _vwa*0.45]},
                'fire_door_safety':  {'heads':['Ref','Name','Question','Answer','Notes'],                  'widths':[10*mm, _vwa*0.22, _vwa*0.38, 18*mm, _vwa*0.40]},
                'keys':              {'heads':['Ref','Key / Item','Description'],                          'widths':[10*mm, _vw*0.38, _vw*0.62]},
                'meter_readings':    {'heads':['Ref','Meter','Location & Serial','Reading'],               'widths':[10*mm, _vw*0.22, _vw*0.44, _vw*0.34]},
            }
            cd = COL_DEFS.get(t, {'heads':['Ref','Item','Details'], 'widths':[10*mm, _vw*0.38, _vw*0.62]})

            tbl_data = [[Paragraph(h, self.s_hdr_cell) for h in cd['heads']]]

            def build_data_row(r, is_extra):
                rid   = r.get('_eid') if is_extra else r['id']
                ref_p = Paragraph(row_ref(rid, is_extra), self.s_ref)

                if t == 'condition_summary':
                    return [ref_p, self._p(r.get('name','')), self._p(gv(r,is_extra,'condition') or '—')]
                if t == 'cleaning_summary':
                    return [ref_p, self._p(r.get('name','')), self._p(gv(r,is_extra,'cleanliness') or '—'), self._p(gv(r,is_extra,'cleanlinessNotes') or '—', self.s_cell_sm)]
                if t in ('smoke_alarms','health_safety'):
                    ans = gv(r,is_extra,'answer') or r.get('answer','')
                    return [ref_p, self._p(r.get('question') or r.get('name','')), self._ans_badge(ans), self._p(gv(r,is_extra,'notes') or r.get('notes','') or '—', self.s_cell_sm)]
                if t == 'fire_door_safety':
                    ans = gv(r,is_extra,'answer') or r.get('answer','')
                    return [ref_p, self._p(r.get('name','')), self._p(r.get('question','')), self._ans_badge(ans), self._p(gv(r,is_extra,'notes') or r.get('notes','') or '—', self.s_cell_sm)]
                if t == 'keys':
                    return [ref_p, self._p(r.get('name','')), self._p(gv(r,is_extra,'description') or '—')]
                if t == 'meter_readings':
                    reading_p = Paragraph(gv(r,is_extra,'reading') or '—', ParagraphStyle('mono', fontName='Courier', fontSize=8, leading=11, textColor=self.body_c))
                    return [ref_p, self._p(r.get('name','')), self._p(gv(r,is_extra,'locationSerial') or '—'), reading_p]
                return [ref_p, self._p(r.get('name','')), self._p(gv(r,is_extra,'condition') or gv(r,is_extra,'description') or '—')]

            photo_row_indices = []
            for r in vis_rows:
                tbl_data.append(build_data_row(r, False))
                g_url = _gallery_url(APP_BASE_URL, self.inspection.id, sid, r['id'])
                pg = self._photo_grid(sid, r['id'], cols=6, gallery_url=g_url)
                if pg:
                    photo_row_indices.append(len(tbl_data))
                    tbl_data.append([pg] + [Paragraph('', self.s_small)]*(len(cd['heads'])-1))
            for r in extra_rows:
                tbl_data.append(build_data_row(r, True))
                rid   = r.get('_eid')
                g_url = _gallery_url(APP_BASE_URL, self.inspection.id, sid, rid)
                pg    = self._photo_grid(sid, rid, cols=6, gallery_url=g_url)
                if pg:
                    photo_row_indices.append(len(tbl_data))
                    tbl_data.append([pg] + [Paragraph('', self.s_small)]*(len(cd['heads'])-1))

            tbl = Table(tbl_data, colWidths=cd['widths'], repeatRows=1)
            ts  = self._table_style()
            for ri in photo_row_indices:
                ts.add('SPAN',           (0,ri),(-1,ri))
                ts.add('TOPPADDING',     (0,ri),(-1,ri), 2)
                ts.add('BOTTOMPADDING',  (0,ri),(-1,ri), 4)
                ts.add('BACKGROUND',     (0,ri),(-1,ri), _WHITE)
            tbl.setStyle(ts)

            is_last = (si == len(self.fixed_sections) - 1)
            story += [_HeaderBar(section.get('name',''), self.brand, self.hdr_c, anchor=f'anchor_{sid}'), Spacer(1,2*mm), tbl]
            story += [PageBreak()] if is_last else [Spacer(1, 6*mm)]

        return story

    # ── Rooms ─────────────────────────────────────────────────────────────────

    def _rooms(self):
        story = []
        uw    = self._uw()

        for ri, room in enumerate(self.rooms):
            room_num = ri + 1
            items    = self._ordered_items(room)
            co       = self.is_check_out

            ov_g_url = _gallery_url(APP_BASE_URL, self.inspection.id, room['id'], '_overview')
            ov_tbl   = self._photo_grid(room['id'], '_overview', cols=4, gallery_url=ov_g_url)

            # photo_links: iid -> gallery URL, populated for all items with photos
            photo_links = {}
            for item in items:
                iid = item.get('_eid') if item['_type'] == 'extra' else item.get('id')
                if self._photos(room['id'], iid):
                    photo_links[iid] = _gallery_url(APP_BASE_URL, self.inspection.id, room['id'], iid)

            item_photo_cells = []
            if self.item_pos != 'hyperlink':
                idx = 1
                for item in items:
                    iid = item.get('_eid') if item['_type']=='extra' else item.get('id')
                    if self._item_hidden(room['id'], iid): idx+=1; continue
                    ts_list = self._photo_ts(room['id'], iid)
                    ref     = f'{room_num}.{idx}'
                    g_url   = photo_links.get(iid)
                    for pi, url in enumerate(self._photos(room['id'], iid)):
                        img    = _fetch_image(url, uw/mm/4-4, 38, link_url=g_url)
                        ts_txt = self._fmt_ts(ts_list[pi] if pi < len(ts_list) else None) if self.add_ts else ''
                        cell   = [img or Paragraph('(photo)', self.s_small)]
                        if ts_txt: cell.append(Paragraph(ts_txt, self.s_small))
                        cell.append(Paragraph(f'Ref #{ref}', self.s_small))
                        item_photo_cells.append(cell)
                    idx += 1

            item_photo_tbl = None
            if item_photo_cells:
                cols = 4
                while len(item_photo_cells) % cols: item_photo_cells.append([Paragraph('', self.s_small)])
                rows = [item_photo_cells[i:i+cols] for i in range(0,len(item_photo_cells),cols)]
                item_photo_tbl = Table(rows, colWidths=[uw/cols]*cols)
                item_photo_tbl.setStyle(TableStyle([
                    ('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(0,0),(-1,-1),'CENTER'),
                    ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),
                    ('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2),
                ]))

            dmg = self.is_damage_report
            if co:
                heads  = ['Ref','Item','Description','Condition at Check In','Condition at Check Out','Actions']
                widths = [10*mm, uw*0.14, uw*0.19, uw*0.17, uw*0.17, uw*0.16]
            elif dmg:
                heads  = ['Ref','Item','Condition']
                widths = [10*mm, uw*0.30, uw*0.60]
            else:
                heads  = ['Ref','Item','Description','Condition']
                widths = [10*mm, uw*0.20, uw*0.35, uw*0.35]

            tbl_data = [[Paragraph(h, self.s_hdr_cell) for h in heads]]
            idx = 1
            for item in items:
                iid   = item.get('_eid') if item['_type']=='extra' else item.get('id')
                if self._item_hidden(room['id'], iid): idx+=1; continue
                ref   = f'{room_num}.{idx}'; idx+=1
                is_ex = item['_type']=='extra'
                label = item.get('label') or item.get('name') or ''
                desc  = item.get('description','') if is_ex else self._get(room['id'], item['id'], 'description')

                # "View additional photos" link for hyperlink mode
                gal = photo_links.get(iid)
                link_p = [Paragraph(
                    f'<link href="{gal}"><u>View additional photos</u></link>',
                    self.s_link
                )] if (self.item_pos == 'hyperlink' and gal) else []

                if co:
                    inv  = (item.get('inventoryCondition') or '') if is_ex else (self._get(room['id'],item['id'],'inventoryCondition') or self._get(room['id'],item['id'],'condition'))
                    co_c = (item.get('checkOutCondition')  or 'As Check In') if is_ex else (self._get(room['id'],item['id'],'checkOutCondition') or 'As Check In')
                    acts = self._item_actions(room['id'], iid)
                    act_txt = ', '.join(self._action_name(a['actionId']) for a in acts if a.get('actionId'))
                    acts_cell = [self._p(act_txt or '—', self.s_cell_sm)] + link_p
                    tbl_data.append([Paragraph(ref,self.s_ref), self._p(label,self.s_bold), self._p(desc or '—'), self._p(inv or '—'), self._p(co_c), acts_cell])
                    # Sub-items
                    if not is_ex:
                        for sub in self._get_subs(room['id'], item['id']):
                            sub_desc = sub.get('description') or ''
                            sub_inv  = sub.get('inventoryCondition') or sub.get('condition') or ''
                            sub_co   = sub.get('checkOutCondition') or ''
                            tbl_data.append([
                                Paragraph('↳', self.s_ref),
                                self._p(sub_desc, self.s_cell_sm),
                                Paragraph('', self.s_cell),
                                self._p(sub_inv or '—', self.s_cell_sm),
                                self._p(sub_co  or '—', self.s_cell_sm),
                                Paragraph('', self.s_cell),
                            ])
                elif dmg:
                    cond = (item.get('condition') or '') if is_ex else self._get(room['id'],item['id'],'condition')
                    cond_cell = [self._p(cond or '—')] + link_p
                    tbl_data.append([Paragraph(ref,self.s_ref), self._p(label,self.s_bold), cond_cell])
                else:
                    cond = (item.get('condition') or '') if is_ex else self._get(room['id'],item['id'],'condition')
                    cond_cell = [self._p(cond or '—')] + link_p
                    tbl_data.append([Paragraph(ref,self.s_ref), self._p(label,self.s_bold), self._p(desc or '—'), cond_cell])
                    # Sub-items
                    if not is_ex:
                        for sub in self._get_subs(room['id'], item['id']):
                            sub_desc = sub.get('description') or ''
                            sub_cond = sub.get('condition') or ''
                            tbl_data.append([
                                Paragraph('↳', self.s_ref),
                                self._p(sub_desc, self.s_cell_sm),
                                Paragraph('', self.s_cell),
                                self._p(sub_cond or '—', self.s_cell_sm),
                            ])

            room_tbl = Table(tbl_data, colWidths=widths, repeatRows=1)
            room_tbl.setStyle(self._table_style())

            parts = [_HeaderBar(room.get('name',''), self.brand, self.hdr_c, anchor=f'anchor_room_{room["id"]}'), Spacer(1,2*mm)]
            if ov_tbl        and self.ov_pos   == 'above': parts += [ov_tbl, Spacer(1,2*mm)]
            if item_photo_tbl and self.item_pos == 'above': parts += [item_photo_tbl, Spacer(1,2*mm)]
            parts.append(room_tbl)
            if item_photo_tbl and self.item_pos == 'below': parts += [Spacer(1,2*mm), item_photo_tbl]
            if ov_tbl        and self.ov_pos   == 'below': parts += [Spacer(1,2*mm), ov_tbl]
            parts.append(PageBreak())
            story += parts

        return story

    # ── Action summary ────────────────────────────────────────────────────────

    def _action_summary(self):
        if not self.is_check_out or self.act_pos == 'none' or not self.actions_summary:
            return []
        story = [_Anchor('anchor_action_summary')]
        uw    = self._uw()

        for group in self.action_groups.values():
            c      = _hex(group['color'])
            c_lt   = _lighten(c, 0.85)
            hdr_p  = ParagraphStyle('ah', fontName='Helvetica-Bold', fontSize=7.5, leading=10, textColor=c)
            heads  = ['Ref','Room \u203a Item','Responsibility','Condition at Check Out']
            widths = [10*mm, uw*0.35, uw*0.25, uw*0.30]
            tbl_data = [[Paragraph(h, hdr_p) for h in heads]]
            for i, a in enumerate(group['items']):
                tbl_data.append([
                    Paragraph(str(i+1), self.s_ref),
                    self._p(f"{a.get('room','')} \u203a {a.get('item','')}"),
                    self._badge(a.get('responsibility') or '—', c_lt, c),
                    self._p(a.get('condition') or '—'),
                ])
            tbl = Table(tbl_data, colWidths=widths, repeatRows=1)
            tbl.setStyle(self._table_style(brand=c, hdr_c=_WHITE))
            story += [_HeaderBar(group['name'], c, _WHITE), Spacer(1,2*mm), tbl, PageBreak()]

        return story

    # ── Declaration ───────────────────────────────────────────────────────────

    def _declaration(self):
        uw   = self._uw()
        text = ('I/We the undersigned, affirm that if I/we do not comment on the Inventory in writing '
                'within seven days of receipt of this Inventory then I/we accept the Inventory as being '
                'an accurate record of the contents and condition of the property.')
        sig_s   = ParagraphStyle('sig',   fontName='Helvetica-Bold', fontSize=9, leading=14, textColor=self.body_c)
        field_s = ParagraphStyle('field', fontName='Helvetica',      fontSize=8.5, leading=12, textColor=_SLATE_500)

        def sig_block(title):
            half = uw/2 - 10*mm
            return [
                Paragraph(title, sig_s),
                Spacer(1, 12*mm),
                HRFlowable(width=half, thickness=0.5, color=_SLATE_800),
                Spacer(1, 3*mm),
                Table([[Paragraph('Print Name', field_s), Paragraph('', field_s)],[Paragraph('Date', field_s), Paragraph('', field_s)]],
                      colWidths=[22*mm, half-22*mm], rowHeights=[10*mm,10*mm]),
            ]

        sig_tbl = Table([[sig_block('Signed by the Tenant(s)'), sig_block('Signed by the Landlord / Agent')]], colWidths=[uw/2, uw/2])
        sig_tbl.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),8)]))

        return [_HeaderBar('Declaration', self.brand, self.hdr_c, anchor='anchor_declaration'), Spacer(1,6*mm), Paragraph(text, self.s_decl), Spacer(1,8*mm), sig_tbl]


# ─────────────────────────────────────────────────────────────────────────────
# Fixed sections loader — mirrors frontend's _get_setting() + slug ID logic
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_FIXED_SECTIONS = [
    {
        "name": "Condition Summary", "enabled": True,
        "columns": ["name", "condition", "additional_notes"], "items": []
    },
    {
        "name": "Cleaning Summary", "enabled": True,
        "columns": ["name", "cleanliness", "additional_notes"], "items": []
    },
    {
        "name": "Smoke & Carbon Alarms", "enabled": True,
        "columns": ["name", "answer", "condition"],
        "items": [
            {"name": "Smoke Alarm — Hallway",    "answer": "Yes", "condition": ""},
            {"name": "Smoke Alarm — Landing",    "answer": "Yes", "condition": ""},
            {"name": "Carbon Monoxide Detector", "answer": "Yes", "condition": ""},
            {"name": "Heat Alarm — Kitchen",     "answer": "Yes", "condition": ""},
        ]
    },
    {
        "name": "Fire Door Safety", "enabled": True,
        "columns": ["name", "answer", "condition"],
        "items": [
            {"name": "Front Door — Self Closing", "answer": "Yes", "condition": ""},
            {"name": "Fire Door Signage",          "answer": "Yes", "condition": ""},
        ]
    },
    {
        "name": "Health & Safety", "enabled": True,
        "columns": ["name", "answer", "description"],
        "items": [
            {"name": "Electrical Consumer Unit",  "answer": "Yes", "description": ""},
            {"name": "Water Stop Tap Location",   "answer": "Yes", "description": ""},
        ]
    },
    {
        "name": "Keys", "enabled": True,
        "columns": ["name", "description"],
        "items": [
            {"name": "Full Sets",           "description": ""},
            {"name": "Access at Check Out", "description": ""},
        ]
    },
    {
        "name": "Utility Meter Readings", "enabled": True,
        "columns": ["name", "location_serial", "reading"],
        "items": [
            {"name": "Gas Meter",      "location_serial": "", "reading": ""},
            {"name": "Electric Meter", "location_serial": "", "reading": ""},
            {"name": "Water Meter",    "location_serial": "", "reading": ""},
        ]
    },
]

def _slugify(name: str) -> str:
    import re
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')

def _infer_type(cols: list, name: str = '') -> str:
    """Mirror of InspectionReportView._inferType(), with name hint for ambiguous cases."""
    c = cols or []
    n = name.lower()
    if 'reading'     in c: return 'meter_readings'
    if 'cleanliness' in c: return 'cleaning_summary'
    # answer-based checks must come before 'condition' check
    if 'name' in c and 'answer' in c and 'question' in c: return 'fire_door_safety'
    # Fire door and smoke alarms share identical columns — disambiguate by name
    if 'answer' in c and 'name' in c and ('fire' in n or 'door' in n): return 'fire_door_safety'
    if 'answer' in c and 'question' in c: return 'smoke_alarms'
    if 'answer' in c and 'description' in c: return 'health_safety'
    if 'answer' in c and 'name' in c: return 'smoke_alarms'
    if 'condition'   in c: return 'condition_summary'
    if 'description' in c: return 'keys'
    return 'condition_summary'

def _adapt_item(item: dict, sec_type: str, sec_idx: int, row_idx: int) -> dict:
    """Mirror of InspectionReportView._adaptItem() — produces row with same id as frontend."""
    rid = f'fs_{sec_idx}_{row_idx}'
    if sec_type == 'meter_readings':
        return {'id': rid, 'name': item.get('name',''), 'locationSerial': item.get('location_serial',''), 'reading': item.get('reading','')}
    if sec_type == 'cleaning_summary':
        return {'id': rid, 'name': item.get('name',''), 'cleanliness': '', 'cleanlinessNotes': item.get('additional_notes','')}
    if sec_type == 'condition_summary':
        return {'id': rid, 'name': item.get('name',''), 'condition': item.get('condition', item.get('description',''))}
    if sec_type == 'fire_door_safety':
        return {'id': rid, 'name': item.get('name',''), 'question': item.get('question',''), 'answer': '', 'notes': item.get('additional_notes','')}
    if sec_type in ('smoke_alarms', 'health_safety'):
        return {'id': rid, 'question': item.get('name', item.get('question','')), 'answer': '', 'notes': item.get('additional_notes','')}
    if sec_type == 'keys':
        return {'id': rid, 'name': item.get('name',''), 'description': item.get('description','')}
    return {'id': rid, 'name': item.get('name',''), 'condition': ''}

def _load_fixed_sections() -> list:
    """
    Load fixed sections from system_settings (or fall back to defaults).
    Produces the same structure the frontend builds in its fixedSections computed:
      - section id: fs_{secIdx}_{slugified_name}
      - row id:     fs_{secIdx}_{rowIdx}
    report_data is keyed by these same ids.
    """
    try:
        from models import SystemSetting
        s = SystemSetting.query.filter_by(key='fixed_sections').first()
        sections = json.loads(s.value) if (s and s.value) else DEFAULT_FIXED_SECTIONS
    except Exception:
        sections = DEFAULT_FIXED_SECTIONS

    result = []
    sec_idx = 0  # only increment for enabled sections (matches frontend filter)
    for raw in sections:
        if not raw.get('enabled', True):
            continue
        cols     = raw.get('columns', [])
        sec_type = _infer_type(cols, raw.get('name', ''))
        import re
        slug   = re.sub(r'[^a-z0-9]', '_', raw['name'].lower())
        rd_key = f'fs_{sec_idx}_{slug}'
        rows    = [_adapt_item(item, sec_type, sec_idx, ri) for ri, item in enumerate(raw.get('items') or [])]
        result.append({
            'id':      rd_key,
            'name':    raw['name'],
            'type':    sec_type,
            'columns': cols,
            'rows':    rows,
        })
        sec_idx += 1
    return result


# ─────────────────────────────────────────────────────────────────────────────
# ORM → dict helpers + recipient builder
# ─────────────────────────────────────────────────────────────────────────────

def _client_dict(client) -> dict:
    if not client:
        return {}
    return {
        'id':                       client.id,
        'name':                     client.name or '',
        'email':                    client.email or '',
        'company':                  client.company or '',
        'logo':                     client.logo or '',
        'primary_color':            client.primary_color or '#1E3A8A',
        'report_disclaimer':        client.report_disclaimer or '',
        'report_color_override':    client.report_color_override or '',
        'report_header_text_color': client.report_header_text_color or '#FFFFFF',
        'report_body_text_color':   client.report_body_text_color or '#1e293b',
        'report_orientation':       client.report_orientation or 'portrait',
        'report_photo_settings':    client.report_photo_settings or '',
    }


def _prop_dict(prop) -> dict:
    if not prop:
        return {}
    return {
        'id':             prop.id,
        'address':        prop.address or '',
        'overview_photo': prop.overview_photo or '',
        'property_type':  prop.property_type or '',
        'bedrooms':       prop.bedrooms,
        'bathrooms':      prop.bathrooms,
    }


def _get_report_recipients(inspection) -> list:
    """
    Deduplicated recipient list from the Contacts section:
      1. client_email_override if set, else client.email
         ('SUPPRESS' sentinel → no recipients, no email sent)
      2. tenant_email if set and not already included
    """
    # 'SUPPRESS' is set on backdated imports where no email should fire
    if inspection.client_email_override == 'SUPPRESS':
        return []

    recipients = []
    primary = ''
    if inspection.client_email_override:
        primary = inspection.client_email_override.strip()
    elif inspection.property and inspection.property.client:
        primary = (inspection.property.client.email or '').strip()
    if primary:
        recipients.append(primary.lower())
    if inspection.tenant_email:
        tenant = inspection.tenant_email.strip().lower()
        if tenant and tenant not in recipients:
            recipients.append(tenant)
    return recipients
