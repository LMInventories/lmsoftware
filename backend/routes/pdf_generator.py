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
import urllib.request
from datetime import datetime

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

def _fetch_image(url: str, max_w_mm: float, max_h_mm: float):
    if not url:
        return None
    try:
        req  = urllib.request.Request(url, headers={'User-Agent': 'InspectPro/1.0'})
        data = urllib.request.urlopen(req, timeout=8).read()
        buf  = io.BytesIO(data)
        img  = RLImage(buf)
        w_pt = max_w_mm * mm
        h_pt = max_h_mm * mm
        scale = min(w_pt / img.drawWidth, h_pt / img.drawHeight, 1.0)
        img.drawWidth  *= scale
        img.drawHeight *= scale
        return img
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Coloured header-bar flowable
# ─────────────────────────────────────────────────────────────────────────────

class _HeaderBar(Flowable):
    def __init__(self, text, bg_color, txt_color, font_size=11):
        super().__init__()
        self.text      = text
        self.bg_color  = bg_color
        self.txt_color = txt_color
        self.font_size = font_size
        self.height    = font_size * 1.8 + 8

    def wrap(self, available_w, available_h):
        self.width = available_w
        return available_w, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg_color)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.setFillColor(self.txt_color)
        c.setFont('Helvetica-Bold', self.font_size)
        c.drawString(8, self.height * 0.25, self.text)


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

        self.fixed_sections   = []
        self.rooms            = []
        self.action_catalogue = []
        tmpl = inspection.template
        if tmpl and tmpl.template_data:
            try:
                td = json.loads(tmpl.template_data) if isinstance(tmpl.template_data, str) else tmpl.template_data
                self.fixed_sections   = td.get('fixedSections', [])
                self.rooms            = td.get('rooms', [])
                self.action_catalogue = td.get('actionCatalogue', [])
            except Exception:
                pass

        self.rd = {}
        if inspection.report_data:
            try:
                self.rd = json.loads(inspection.report_data) if isinstance(inspection.report_data, str) else inspection.report_data
            except Exception:
                pass

        itype = inspection.inspection_type or ''
        self.is_check_out = itype == 'check_out'
        self.type_label   = {
            'check_in':  'Inventory & Check In',
            'check_out': 'Check Out',
            'interim':   'Interim Inspection',
            'inventory': 'Inventory Report',
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
        self.s_ref      = ParagraphStyle('ref',      fontName='Helvetica-Bold', fontSize=7.5,  leading=10, textColor=self.brand)
        self.s_title    = ParagraphStyle('title',    fontName='Helvetica-Bold', fontSize=20,   leading=26, textColor=self.hdr_c, alignment=TA_CENTER)
        self.s_toc_num  = ParagraphStyle('toc_num',  fontName='Helvetica-Bold', fontSize=9.5,  leading=14, textColor=self.brand)
        self.s_toc_ttl  = ParagraphStyle('toc_ttl',  fontName='Helvetica',      fontSize=9.5,  leading=14, textColor=bc)
        self.s_decl     = ParagraphStyle('decl',     fontName='Helvetica',      fontSize=9,    leading=15, textColor=bc, spaceAfter=20)

    # ── Report data accessors ─────────────────────────────────────────────────

    def _get(self, sid, rid, field):
        return (self.rd.get(str(sid)) or {}).get(str(rid), {}).get(field, '') or ''

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
        stored = (self.rd.get(str(room['id'])) or {}).get('_itemOrder', None)
        tmpl   = [dict(i, _type='template') for i in (room.get('sections') or [])]
        extras = [dict(ex, id=ex.get('_eid'), label=ex.get('label', 'New item'), _type='extra')
                  for ex in ((self.rd.get(str(room['id'])) or {}).get('_extra', []) or [])]
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

    def _photo_grid(self, sid, rid, cols=4):
        urls = self._photos(sid, rid)
        ts   = self._photo_ts(sid, rid)
        if not urls:
            return None
        uw      = self._uw()
        cell_w  = uw / cols
        cells   = []
        for i, url in enumerate(urls):
            img    = _fetch_image(url, cell_w / mm - 4, 38)
            ts_txt = self._fmt_ts(ts[i] if i < len(ts) else None) if self.add_ts else ''
            inner  = [img or Paragraph('(photo)', self.s_small)]
            if ts_txt:
                inner.append(Paragraph(ts_txt, self.s_small))
            cells.append(inner)
        while len(cells) % cols:
            cells.append([''])
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
        frame = Frame(self.margin, self.margin, uw, self.ph - 2*self.margin,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates([PageTemplate(id='main', frames=[frame])])

        story = []
        story += self._cover()
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

    def _cover(self):
        uw   = self._uw()
        cl   = self.cl
        insp = self.inspection

        logo_img = _fetch_image(cl.get('logo'), 60, 22)
        if not logo_img:
            initials = ''.join(w[0] for w in (cl.get('company') or cl.get('name') or 'IP').split() if w)[:2].upper()
            logo_img = Paragraph(initials, ParagraphStyle('init', fontName='Helvetica-Bold', fontSize=22, textColor=self.hdr_c))

        hdr_tbl = Table([[logo_img, Paragraph(self.type_label, self.s_title)]], colWidths=[65*mm, uw-65*mm])
        hdr_tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), self.brand),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('ALIGN',         (1,0),(1,0),   'CENTER'),
            ('TOPPADDING',    (0,0),(-1,-1), 16),
            ('BOTTOMPADDING', (0,0),(-1,-1), 16),
            ('LEFTPADDING',   (0,0),(0,0),   12),
            ('RIGHTPADDING',  (0,0),(-1,-1), 12),
        ]))

        prop_img = _fetch_image(self.prop.get('overview_photo'), uw/mm, 72)
        if prop_img:
            prop_img.drawWidth  = uw
            prop_img.drawHeight = min(prop_img.drawHeight, 72*mm)
            photo_flow = prop_img
        else:
            ph = Table([[Paragraph('Property overview photo', ParagraphStyle('ph', fontName='Helvetica',
                fontSize=10, textColor=_SLATE_400, alignment=TA_CENTER))]],
                colWidths=[uw], rowHeights=[52*mm])
            ph.setStyle(TableStyle([('BACKGROUND',(0,0),(0,0),_SLATE_100),('VALIGN',(0,0),(0,0),'MIDDLE'),('ALIGN',(0,0),(0,0),'CENTER')]))
            photo_flow = ph

        info_rows = [
            ('ADDRESS', self.prop.get('address') or ''),
            ('DATE',    self._fmt_date(insp.conduct_date or insp.scheduled_date)),
            ('CLERK',   insp.inspector.name if insp.inspector else ''),
            ('CLIENT',  cl.get('company') or cl.get('name') or ''),
        ]
        if insp.typist and insp.typist.name != 'AI Typist':
            info_rows.append(('TYPIST', insp.typist.name))

        lbl_s = ParagraphStyle('il', fontName='Helvetica-Bold', fontSize=7,  leading=10, textColor=_SLATE_400)
        val_s = ParagraphStyle('iv', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=self.body_c)
        info_tbl = Table([[Paragraph(l, lbl_s), Paragraph(v, val_s)] for l,v in info_rows], colWidths=[30*mm, uw-30*mm])
        info_tbl.setStyle(TableStyle([
            ('TOPPADDING',    (0,0),(-1,-1), 6),
            ('BOTTOMPADDING', (0,0),(-1,-1), 6),
            ('LEFTPADDING',   (0,0),(-1,-1), 10),
            ('LINEBELOW',     (0,0),(-1,-2), 0.5, _SLATE_100),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ]))

        footer_name = cl.get('company') or cl.get('name') or 'InspectPro'
        footer_tbl = Table([
            [Paragraph(footer_name, ParagraphStyle('fl', fontName='Helvetica-Bold', fontSize=9, textColor=self.hdr_c)),
             Paragraph('Confidential', ParagraphStyle('fr', fontName='Helvetica', fontSize=9, textColor=self.hdr_c, alignment=TA_RIGHT))]
        ], colWidths=[uw/2, uw/2])
        footer_tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), self.brand),
            ('TOPPADDING',    (0,0),(-1,-1), 8),
            ('BOTTOMPADDING', (0,0),(-1,-1), 8),
            ('LEFTPADDING',   (0,0),(0,0),   10),
            ('RIGHTPADDING',  (-1,0),(-1,0), 10),
        ]))

        return [hdr_tbl, photo_flow, Spacer(1,3*mm), info_tbl, Spacer(1,3*mm), footer_tbl, PageBreak()]

    # ── Contents ──────────────────────────────────────────────────────────────

    def _contents(self):
        rows = []
        n    = 1
        def add(title):
            nonlocal n
            rows.append([Paragraph(str(n), self.s_toc_num), Paragraph(title, self.s_toc_ttl)])
            n += 1

        add('Cover Page'); add('Contents')
        if self.cl.get('report_disclaimer'):           add('Disclaimers')
        if self.is_check_out and self.act_pos == 'top' and self.actions_summary: add('Action Summary')
        for s in self.fixed_sections:  add(s.get('name',''))
        for r in self.rooms:           add(r.get('name',''))
        if self.is_check_out and self.act_pos == 'bottom' and self.actions_summary: add('Action Summary')
        add('Declaration')

        uw  = self._uw()
        tbl = Table(rows, colWidths=[12*mm, uw-12*mm])
        tbl.setStyle(TableStyle([
            ('TOPPADDING',    (0,0),(-1,-1), 4),
            ('BOTTOMPADDING', (0,0),(-1,-1), 4),
            ('LINEBELOW',     (0,0),(-1,-2), 0.5, _SLATE_100),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ]))
        return [_HeaderBar('Contents', self.brand, self.hdr_c), Spacer(1,4*mm), tbl, PageBreak()]

    # ── Disclaimer ────────────────────────────────────────────────────────────

    def _disclaimer(self):
        disc = self.cl.get('report_disclaimer') or ''
        if not disc:
            return []
        text = disc.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br/>')
        return [_HeaderBar('Disclaimers', self.brand, self.hdr_c), Spacer(1,4*mm), Paragraph(text, self.s_body), PageBreak()]

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

            COL_DEFS = {
                'condition_summary': {'heads':['Ref','Name','Condition'],                                  'widths':[10*mm,uw*0.40,uw*0.50]},
                'cleaning_summary':  {'heads':['Ref','Area','Cleanliness','Notes'],                        'widths':[10*mm,uw*0.28,uw*0.20,uw*0.42]},
                'smoke_alarms':      {'heads':['Ref','Question','Answer','Notes'],                         'widths':[10*mm,uw*0.40,18*mm,uw*0.34]},
                'health_safety':     {'heads':['Ref','Question','Answer','Notes'],                         'widths':[10*mm,uw*0.40,18*mm,uw*0.34]},
                'fire_door_safety':  {'heads':['Ref','Name','Question','Answer','Notes'],                  'widths':[10*mm,uw*0.18,uw*0.28,18*mm,uw*0.24]},
                'keys':              {'heads':['Ref','Key / Item','Description'],                          'widths':[10*mm,uw*0.35,uw*0.55]},
                'meter_readings':    {'heads':['Ref','Meter','Location & Serial','Reading'],               'widths':[10*mm,uw*0.22,uw*0.40,uw*0.28]},
            }
            cd = COL_DEFS.get(t, {'heads':['Ref','Item','Details'], 'widths':[10*mm,uw*0.35,uw*0.55]})

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
                pg = self._photo_grid(sid, r['id'], cols=6)
                if pg:
                    photo_row_indices.append(len(tbl_data))
                    tbl_data.append([pg] + ['']*(len(cd['heads'])-1))
            for r in extra_rows:
                tbl_data.append(build_data_row(r, True))
                rid = r.get('_eid')
                pg  = self._photo_grid(sid, rid, cols=6)
                if pg:
                    photo_row_indices.append(len(tbl_data))
                    tbl_data.append([pg] + ['']*(len(cd['heads'])-1))

            tbl = Table(tbl_data, colWidths=cd['widths'], repeatRows=1)
            ts  = self._table_style()
            for ri in photo_row_indices:
                ts.add('SPAN',           (0,ri),(-1,ri))
                ts.add('TOPPADDING',     (0,ri),(-1,ri), 2)
                ts.add('BOTTOMPADDING',  (0,ri),(-1,ri), 4)
                ts.add('BACKGROUND',     (0,ri),(-1,ri), _WHITE)
            tbl.setStyle(ts)

            story += [_HeaderBar(section.get('name',''), self.brand, self.hdr_c), Spacer(1,2*mm), tbl, PageBreak()]

        return story

    # ── Rooms ─────────────────────────────────────────────────────────────────

    def _rooms(self):
        story = []
        uw    = self._uw()

        for ri, room in enumerate(self.rooms):
            room_num = ri + 1
            items    = self._ordered_items(room)
            co       = self.is_check_out

            ov_tbl = self._photo_grid(room['id'], '_overview', cols=4)

            item_photo_cells = []
            if self.item_pos != 'hyperlink':
                idx = 1
                for item in items:
                    iid = item.get('_eid') if item['_type']=='extra' else item.get('id')
                    if self._item_hidden(room['id'], iid): idx+=1; continue
                    ts_list = self._photo_ts(room['id'], iid)
                    ref = f'{room_num}.{idx}'
                    for pi, url in enumerate(self._photos(room['id'], iid)):
                        img    = _fetch_image(url, uw/mm/4-4, 38)
                        ts_txt = self._fmt_ts(ts_list[pi] if pi < len(ts_list) else None) if self.add_ts else ''
                        cell   = [img or Paragraph('(photo)', self.s_small)]
                        if ts_txt: cell.append(Paragraph(ts_txt, self.s_small))
                        cell.append(Paragraph(f'Ref #{ref}', self.s_small))
                        item_photo_cells.append(cell)
                    idx += 1

            item_photo_tbl = None
            if item_photo_cells:
                cols = 4
                while len(item_photo_cells) % cols: item_photo_cells.append([''])
                rows = [item_photo_cells[i:i+cols] for i in range(0,len(item_photo_cells),cols)]
                item_photo_tbl = Table(rows, colWidths=[uw/cols]*cols)
                item_photo_tbl.setStyle(TableStyle([
                    ('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(0,0),(-1,-1),'CENTER'),
                    ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),
                    ('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2),
                ]))

            if co:
                heads  = ['Ref','Item','Description','Condition at Check In','Condition at Check Out','Actions']
                widths = [10*mm, uw*0.14, uw*0.19, uw*0.17, uw*0.17, uw*0.16]
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

                if co:
                    inv  = (item.get('inventoryCondition') or '') if is_ex else (self._get(room['id'],item['id'],'inventoryCondition') or self._get(room['id'],item['id'],'condition'))
                    co_c = (item.get('checkOutCondition')  or 'As Check In') if is_ex else (self._get(room['id'],item['id'],'checkOutCondition') or 'As Check In')
                    acts = self._item_actions(room['id'], iid)
                    act_txt = ', '.join(self._action_name(a['actionId']) for a in acts if a.get('actionId'))
                    tbl_data.append([Paragraph(ref,self.s_ref), self._p(label,self.s_bold), self._p(desc or '—'), self._p(inv or '—'), self._p(co_c), self._p(act_txt or '—',self.s_cell_sm)])
                else:
                    cond = (item.get('condition') or '') if is_ex else self._get(room['id'],item['id'],'condition')
                    tbl_data.append([Paragraph(ref,self.s_ref), self._p(label,self.s_bold), self._p(desc or '—'), self._p(cond or '—')])

            room_tbl = Table(tbl_data, colWidths=widths, repeatRows=1)
            room_tbl.setStyle(self._table_style())

            parts = [_HeaderBar(room.get('name',''), self.brand, self.hdr_c), Spacer(1,2*mm)]
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
        story = []
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
                Table([[Paragraph('Print Name', field_s),''],[Paragraph('Date', field_s),'']],
                      colWidths=[22*mm, half-22*mm], rowHeights=[10*mm,10*mm]),
            ]

        sig_tbl = Table([[sig_block('Signed by the Tenant(s)'), sig_block('Signed by the Landlord / Agent')]], colWidths=[uw/2, uw/2])
        sig_tbl.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),8)]))

        return [_HeaderBar('Declaration', self.brand, self.hdr_c), Spacer(1,6*mm), Paragraph(text, self.s_decl), Spacer(1,8*mm), sig_tbl]


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
      2. tenant_email if set and not already included
    """
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
