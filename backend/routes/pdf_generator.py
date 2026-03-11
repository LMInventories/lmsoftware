"""
pdf_generator.py — Server-side PDF generation for InspectPro.

Mirrors the HTML builder in PdfExportModal.vue exactly so the server-generated
PDF is visually identical to the browser-printed version.

Uses xhtml2pdf — pure Python, no system libraries required, works on Render free tier.

Usage:
    from routes.pdf_generator import generate_inspection_pdf
    pdf_bytes = generate_inspection_pdf(inspection_id)
    # returns bytes on success, raises on failure
"""

import io
import json
from html import escape as _esc
from datetime import datetime

from models import db, Inspection, Client, Template


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_inspection_pdf(inspection_id: int) -> bytes:
    """
    Generate a PDF for the given inspection and return raw bytes.
    Uses xhtml2pdf — pure Python, no system libraries required.
    Raises ValueError if the inspection doesn't exist.
    """
    try:
        from xhtml2pdf import pisa
    except ImportError:
        raise ImportError(
            'xhtml2pdf is not installed. Add xhtml2pdf to requirements.txt.'
        )
    import io

    inspection = Inspection.query.get(inspection_id)
    if not inspection:
        raise ValueError(f'Inspection {inspection_id} not found')

    html_string = _build_report_html(inspection)
    buf = io.BytesIO()
    result = pisa.CreatePDF(html_string, dest=buf, encoding='utf-8')
    if result.err:
        raise RuntimeError(f'PDF generation failed with {result.err} error(s)')
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# HTML builder — mirrors PdfExportModal.vue buildReportHTML() exactly
# ─────────────────────────────────────────────────────────────────────────────

def _build_report_html(inspection: 'Inspection') -> str:
    # ── Gather data ──────────────────────────────────────────────────────────
    report_data = {}
    if inspection.report_data:
        try:
            report_data = json.loads(inspection.report_data) if isinstance(inspection.report_data, str) else inspection.report_data
        except Exception:
            report_data = {}

    # Client settings
    client = None
    if inspection.property and inspection.property.client:
        client = inspection.property.client
    cl = _client_dict(client)

    # Property
    prop = _prop_dict(inspection.property)

    # Template → fixed sections + rooms
    template = inspection.template
    fixed_sections = []
    rooms = []
    if template and template.template_data:
        try:
            tdata = json.loads(template.template_data) if isinstance(template.template_data, str) else template.template_data
            fixed_sections = tdata.get('fixedSections', [])
            rooms = tdata.get('rooms', [])
        except Exception:
            pass

    # Action catalogue (from template or report_data)
    action_catalogue = []
    if template and template.template_data:
        try:
            tdata = json.loads(template.template_data) if isinstance(template.template_data, str) else template.template_data
            action_catalogue = tdata.get('actionCatalogue', [])
        except Exception:
            pass

    # Client settings (colours / orientation / photo layout)
    brand_color       = cl.get('report_color_override') or cl.get('primary_color') or '#1E3A8A'
    hdr_txt           = cl.get('report_header_text_color') or '#FFFFFF'
    body_txt          = cl.get('report_body_text_color')   or '#1e293b'
    orient            = cl.get('report_orientation')       or 'portrait'

    photo_settings = {}
    if cl.get('report_photo_settings'):
        try:
            photo_settings = json.loads(cl['report_photo_settings']) if isinstance(cl['report_photo_settings'], str) else cl['report_photo_settings']
        except Exception:
            pass

    ov_pos      = photo_settings.get('photo_room_overview',     'above')
    item_pos    = photo_settings.get('photo_room_item',         'below')
    add_ts      = photo_settings.get('show_photo_timestamp',    False) is True
    act_pos     = photo_settings.get('action_summary_position', 'bottom')

    insp_type   = inspection.inspection_type or ''
    is_check_out = insp_type == 'check_out'
    type_label  = {
        'check_in':  'Inventory & Check In',
        'check_out': 'Check Out',
        'interim':   'Interim Inspection',
        'inventory': 'Inventory Report',
    }.get(insp_type, 'Inspection Report')

    # ── Helpers ──────────────────────────────────────────────────────────────

    def e(s):
        if s is None:
            return ''
        return _esc(str(s))

    def fmt_date(iso):
        if not iso:
            return ''
        try:
            if isinstance(iso, datetime):
                d = iso
            else:
                d = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
            return d.strftime('%d %B %Y')
        except Exception:
            return str(iso)

    def fmt_ts(iso):
        if not iso:
            return ''
        try:
            if isinstance(iso, datetime):
                d = iso
            else:
                d = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
            return d.strftime('%d %b %Y %H:%M')
        except Exception:
            return str(iso)

    # report_data accessors
    def get_val(section_id, row_id, field):
        sid = str(section_id)
        rid = str(row_id)
        return (report_data.get(sid) or {}).get(rid, {}).get(field, '') or ''

    def is_hidden(section_id, row_id):
        sid = str(section_id)
        rid = str(row_id)
        return rid in ((report_data.get(sid) or {}).get('_hidden', []) or [])

    def is_item_hidden(room_id, item_id):
        rid = str(room_id)
        iid = str(item_id)
        return iid in ((report_data.get(rid) or {}).get('_hiddenItems', []) or [])

    def get_extra(section_id):
        sid = str(section_id)
        return (report_data.get(sid) or {}).get('_extra', []) or []

    def get_photos(section_id, row_id):
        sid = str(section_id)
        rid = str(row_id)
        return (report_data.get(sid) or {}).get(rid, {}).get('_photos', []) or []

    def get_photo_ts(section_id, row_id):
        sid = str(section_id)
        rid = str(row_id)
        return (report_data.get(sid) or {}).get(rid, {}).get('_photoTs', []) or []

    def get_item_actions(room_id, item_id):
        rid = str(room_id)
        key = f'_actions_{item_id}'
        return (report_data.get(rid) or {}).get(key, []) or []

    def get_ordered_room_items(room):
        stored_order    = (report_data.get(str(room['id'])) or {}).get('_itemOrder', None)
        template_items  = [dict(item, _type='template') for item in (room.get('sections') or [])]
        extra_raw       = (report_data.get(str(room['id'])) or {}).get('_extra', []) or []
        extra_items     = [dict(ex, id=ex.get('_eid'), label=ex.get('label', 'New item'), _type='extra') for ex in extra_raw]
        all_items       = template_items + extra_items
        if not stored_order:
            return all_items
        ordered = []
        for oid in stored_order:
            match = next((i for i in all_items if str(i.get('id')) == str(oid) or str(i.get('_eid', '')) == str(oid)), None)
            if match:
                ordered.append(match)
        for item in all_items:
            key = str(item.get('_eid', '')) if item['_type'] == 'extra' else str(item.get('id', ''))
            if not any(str(o) == key for o in stored_order):
                ordered.append(item)
        return ordered

    # Action catalogue helpers
    def catalogue_lookup(action_id):
        return next((c for c in action_catalogue if str(c.get('id')) == str(action_id)), None)

    def action_name(action_id):
        c = catalogue_lookup(action_id)
        return (c or {}).get('name') or action_id or '—'

    def action_color(action_id):
        c = catalogue_lookup(action_id)
        return (c or {}).get('color') or '#64748b'

    # actions summary (check out only)
    actions_summary = []
    if is_check_out:
        for room in rooms:
            for item in get_ordered_room_items(room):
                item_id = item.get('_eid') if item['_type'] == 'extra' else item.get('id')
                if is_item_hidden(room['id'], item_id):
                    continue
                for act in get_item_actions(room['id'], item_id):
                    if not act.get('actionId'):
                        continue
                    actions_summary.append({
                        'room':     room.get('name', ''),
                        'item':     item.get('label') or item.get('name') or '',
                        **act,
                    })

    action_groups = {}
    for a in actions_summary:
        aid = a['actionId']
        if aid not in action_groups:
            action_groups[aid] = {'name': action_name(aid), 'color': action_color(aid), 'items': []}
        action_groups[aid]['items'].append(a)

    # ── Photo HTML ────────────────────────────────────────────────────────────

    def photo_unit(src, ts, ref_label):
        ts_html = ''
        if add_ts and ts:
            ts_html = f'<div class="photo-ts">{e(fmt_ts(ts))}</div>'
        return (
            f'<div class="photo-unit">'
            f'<div class="photo-wrap"><img src="{e(src)}" />{ts_html}</div>'
            f'<div class="photo-ref">Ref #{e(ref_label)}</div>'
            f'</div>'
        )

    def photo_units(section_id, row_id, ref_label):
        ps = get_photos(section_id, row_id)
        ts = get_photo_ts(section_id, row_id)
        return [photo_unit(src, ts[i] if i < len(ts) else None, ref_label) for i, src in enumerate(ps)]

    def photo_grid(units, inline=False):
        if not units:
            return ''
        cls = ' photo-grid--inline' if inline else ''
        return f'<div class="photo-grid{cls}">{"".join(units)}</div>'

    # ── Section header ────────────────────────────────────────────────────────

    def section_hdr(title):
        return f'<div class="section-hdr" style="background:{e(brand_color)};color:{e(hdr_txt)};">{e(title)}</div>'

    def page(content):
        return f'<div class="page">{content}</div>'

    # ── Cover page ────────────────────────────────────────────────────────────

    def build_cover():
        if cl.get('logo'):
            logo_html = f'<img src="{e(cl["logo"])}" class="cover-logo-img" alt="logo">'
        else:
            initials = ''.join(w[0] for w in (cl.get('company') or cl.get('name') or 'IP').split() if w)[:2].upper()
            logo_html = f'<div class="cover-logo-fallback">{e(initials)}</div>'

        if prop.get('overview_photo'):
            prop_photo_html = f'<img src="{e(prop["overview_photo"])}" class="cover-photo-img" alt="Property">'
        else:
            prop_photo_html = '<div class="cover-photo-placeholder"><span>Property overview photo</span></div>'

        insp_date   = fmt_date(inspection.conduct_date or inspection.scheduled_date)
        clerk_name  = inspection.inspector.name if inspection.inspector else ''
        client_name = cl.get('company') or cl.get('name') or ''
        address     = prop.get('address') or ''

        info_rows = [
            ('Address', address),
            ('Date',    insp_date),
            ('Clerk',   clerk_name),
            ('Client',  client_name),
        ]
        if inspection.typist and inspection.typist.name != 'AI Typist':
            info_rows.append(('Typist', inspection.typist.name))

        info_html = ''.join(
            f'<div class="cover-info-row">'
            f'<div class="cover-info-lbl">{e(lbl)}</div>'
            f'<div class="cover-info-val" style="color:{e(body_txt)};">{e(val)}</div>'
            f'</div>'
            for lbl, val in info_rows
        )

        footer_name = cl.get('company') or cl.get('name') or 'InspectPro'

        return (
            f'<div class="page page-cover">'
            f'<div class="cover-top" style="background:{e(brand_color)};-webkit-print-color-adjust:exact;print-color-adjust:exact;">'
            f'<div class="cover-logo-centered">{logo_html}</div>'
            f'<div class="cover-type-badge" style="color:{e(hdr_txt)};">{e(type_label)}</div>'
            f'</div>'
            f'<div class="cover-photo-area">{prop_photo_html}</div>'
            f'<div class="cover-info-block">{info_html}</div>'
            f'<div class="cover-footer" style="background:{e(brand_color)};color:{e(hdr_txt)};-webkit-print-color-adjust:exact;print-color-adjust:exact;">'
            f'<span>{e(footer_name)}</span>'
            f'<span>Confidential</span>'
            f'</div>'
            f'</div>'
        )

    # ── Contents page ─────────────────────────────────────────────────────────

    def build_contents():
        rows = []
        n = 1
        rows.append((n, 'Cover Page',  'front'));  n += 1
        rows.append((n, 'Contents',    'front'));  n += 1
        if cl.get('report_disclaimer'):
            rows.append((n, 'Disclaimers', 'front')); n += 1
        if is_check_out and act_pos == 'top' and actions_summary:
            rows.append((n, 'Action Summary', 'action')); n += 1
        for s in fixed_sections:
            rows.append((n, s.get('name', ''), 'fixed')); n += 1
        for r in rooms:
            rows.append((n, r.get('name', ''), 'room')); n += 1
        if is_check_out and act_pos == 'bottom' and actions_summary:
            rows.append((n, 'Action Summary', 'action')); n += 1
        rows.append((n, 'Declaration', 'front'))

        rows_html = ''.join(
            f'<tr>'
            f'<td class="toc-num" style="color:{e(brand_color)};">{num}</td>'
            f'<td class="toc-title">{e(title)}</td>'
            f'<td class="toc-dots"></td>'
            f'<td class="toc-page">—</td>'
            f'</tr>'
            for num, title, _ in rows
        )
        return page(section_hdr('Contents') + f'<table class="toc-table"><tbody>{rows_html}</tbody></table>')

    # ── Disclaimer ────────────────────────────────────────────────────────────

    def build_disclaimer():
        if not cl.get('report_disclaimer'):
            return ''
        return page(section_hdr('Disclaimers') + f'<div class="disclaimer-body">{e(cl["report_disclaimer"])}</div>')

    # ── Fixed sections ────────────────────────────────────────────────────────

    LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    def build_fixed_sections():
        parts = []
        for si, section in enumerate(fixed_sections):
            letter    = LETTERS[si] if si < len(LETTERS) else str(si + 1)
            t         = section.get('type', '')
            vis_rows  = [r for r in (section.get('rows') or []) if not is_hidden(section['id'], r['id'])]
            extra_rows = get_extra(section['id'])

            def row_ref(row_id):
                idx = next((i for i, r in enumerate(vis_rows) if str(r['id']) == str(row_id)), None)
                if idx is not None:
                    return f'{letter}.{idx + 1}'
                eidx = next((i for i, ex in enumerate(extra_rows) if ex.get('_eid') == row_id), None)
                if eidx is not None:
                    return f'{letter}.{len(vis_rows) + eidx + 1}'
                return f'{letter}.?'

            def inline_photo_row(row_id, ref, colspan):
                units = photo_units(section['id'], row_id, ref)
                if not units:
                    return ''
                return (
                    f'<tr class="photo-tr">'
                    f'<td colspan="{colspan}" class="photo-td">{photo_grid(units, inline=True)}</td>'
                    f'</tr>'
                )

            def build_row(r, is_extra):
                rid = r.get('_eid') if is_extra else r['id']
                ref = row_ref(rid)
                gv  = (lambda f: r.get(f) or '') if is_extra else (lambda f: get_val(section['id'], rid, f) or r.get(f) or '')

                if t == 'condition_summary':
                    return (
                        f'<tr><td class="col-ref">{e(ref)}</td><td>{e(r.get("name",""))}</td>'
                        f'<td>{e(gv("condition")) or "—"}</td></tr>'
                    ) + inline_photo_row(rid, ref, 3)

                if t == 'cleaning_summary':
                    return (
                        f'<tr><td class="col-ref">{e(ref)}</td><td>{e(r.get("name",""))}</td>'
                        f'<td>{e(gv("cleanliness")) or "—"}</td>'
                        f'<td class="notes">{e(gv("cleanlinessNotes")) or "—"}</td></tr>'
                    ) + inline_photo_row(rid, ref, 4)

                if t in ('smoke_alarms', 'health_safety'):
                    ans = gv('answer') or r.get('answer') or ''
                    cls = 'ans-yes' if ans == 'Yes' else ('ans-no' if ans == 'No' else 'ans-na')
                    return (
                        f'<tr><td class="col-ref">{e(ref)}</td><td>{e(r.get("question") or r.get("name",""))}</td>'
                        f'<td><span class="ans-badge {cls}">{e(ans) or "—"}</span></td>'
                        f'<td class="notes">{e(gv("notes") or r.get("notes","")) or "—"}</td></tr>'
                    ) + inline_photo_row(rid, ref, 4)

                if t == 'fire_door_safety':
                    ans = gv('answer') or r.get('answer') or ''
                    cls = 'ans-yes' if ans == 'Yes' else ('ans-no' if ans == 'No' else 'ans-na')
                    return (
                        f'<tr><td class="col-ref">{e(ref)}</td><td>{e(r.get("name",""))}</td>'
                        f'<td>{e(r.get("question",""))}</td>'
                        f'<td><span class="ans-badge {cls}">{e(ans) or "—"}</span></td>'
                        f'<td class="notes">{e(gv("notes") or r.get("notes","")) or "—"}</td></tr>'
                    ) + inline_photo_row(rid, ref, 5)

                if t == 'keys':
                    return (
                        f'<tr><td class="col-ref">{e(ref)}</td><td>{e(r.get("name",""))}</td>'
                        f'<td>{e(gv("description")) or "—"}</td></tr>'
                    ) + inline_photo_row(rid, ref, 3)

                if t == 'meter_readings':
                    return (
                        f'<tr><td class="col-ref">{e(ref)}</td><td>{e(r.get("name",""))}</td>'
                        f'<td>{e(gv("locationSerial")) or "—"}</td>'
                        f'<td class="reading">{e(gv("reading")) or "—"}</td></tr>'
                    ) + inline_photo_row(rid, ref, 4)

                # Generic fallback
                return (
                    f'<tr><td class="col-ref">{e(ref)}</td><td>{e(r.get("name",""))}</td>'
                    f'<td>{e(gv("condition") or gv("description")) or "—"}</td></tr>'
                ) + inline_photo_row(rid, ref, 3)

            thead_map = {
                'condition_summary': '<tr><th>Ref</th><th>Name</th><th>Condition</th></tr>',
                'cleaning_summary':  '<tr><th>Ref</th><th>Area</th><th>Cleanliness</th><th>Additional Notes</th></tr>',
                'smoke_alarms':      '<tr><th>Ref</th><th>Question</th><th>Answer</th><th>Additional Notes</th></tr>',
                'health_safety':     '<tr><th>Ref</th><th>Question</th><th>Answer</th><th>Additional Notes</th></tr>',
                'fire_door_safety':  '<tr><th>Ref</th><th>Name</th><th>Question</th><th>Answer</th><th>Additional Notes</th></tr>',
                'keys':              '<tr><th>Ref</th><th>Key / Item</th><th>Description</th></tr>',
                'meter_readings':    '<tr><th>Ref</th><th>Meter</th><th>Location &amp; Serial</th><th>Reading</th></tr>',
            }
            thead = thead_map.get(t, '<tr><th>Ref</th><th>Item</th><th>Details</th></tr>')
            body  = ''.join(build_row(r, False) for r in vis_rows)
            body += ''.join(build_row(r, True)  for r in extra_rows)

            parts.append(page(
                section_hdr(section.get('name', '')) +
                f'<table>'
                f'<thead style="background:{e(brand_color)};color:{e(hdr_txt)};">{thead}</thead>'
                f'<tbody>{body}</tbody>'
                f'</table>'
            ))
        return ''.join(parts)

    # ── Room pages ────────────────────────────────────────────────────────────

    def build_rooms():
        parts = []
        for ri, room in enumerate(rooms):
            room_num = ri + 1
            items    = get_ordered_room_items(room)

            # Overview photos
            ov_units = photo_units(room['id'], '_overview', str(room_num))
            ov_block = ''
            if ov_units:
                ov_block = f'<div class="ov-label">Room Overview</div>{photo_grid(ov_units)}'

            # Item photos
            item_units = []
            if item_pos != 'hyperlink':
                idx = 1
                for item in items:
                    iid = item.get('_eid') if item['_type'] == 'extra' else item.get('id')
                    if is_item_hidden(room['id'], iid):
                        idx += 1
                        continue
                    ref = f'{room_num}.{idx}'
                    item_units.extend(photo_units(room['id'], str(iid), ref))
                    idx += 1
            item_photo_block = photo_grid(item_units)

            # Data table
            if is_check_out:
                thead = (
                    '<tr>'
                    '<th class="col-ref">Ref</th><th class="col-item">Item</th>'
                    '<th class="col-desc">Description</th><th class="col-cond">Condition at Check In</th>'
                    '<th class="col-co">Condition at Check Out</th><th class="col-act">Actions</th>'
                    '</tr>'
                )
            else:
                thead = (
                    '<tr>'
                    '<th class="col-ref">Ref</th><th class="col-item">Item</th>'
                    '<th class="col-desc">Description</th><th class="col-cond">Condition</th>'
                    '</tr>'
                )

            body = ''
            idx  = 1
            for item in items:
                iid   = item.get('_eid') if item['_type'] == 'extra' else item.get('id')
                if is_item_hidden(room['id'], iid):
                    idx += 1
                    continue
                ref   = f'{room_num}.{idx}'
                idx  += 1
                is_ex = item['_type'] == 'extra'
                label = item.get('label') or item.get('name') or ''
                desc  = item.get('description', '') if is_ex else get_val(room['id'], item['id'], 'description')

                if is_check_out:
                    inv  = (item.get('inventoryCondition') or '') if is_ex else (get_val(room['id'], item['id'], 'inventoryCondition') or get_val(room['id'], item['id'], 'condition'))
                    co_c = (item.get('checkOutCondition') or 'As Inventory &amp; Check In') if is_ex else (get_val(room['id'], item['id'], 'checkOutCondition') or 'As Inventory &amp; Check In')
                    acts = get_item_actions(room['id'], iid)
                    act_html = ''.join(
                        f'<span class="act-tag" style="background:{action_color(a["actionId"])}22;color:{action_color(a["actionId"])};border:1px solid {action_color(a["actionId"])}55;">'
                        f'{e(action_name(a["actionId"]))}'
                        + (f'<br><small>{e(a.get("responsibility",""))}</small>' if a.get('responsibility') else '')
                        + '</span>'
                        for a in acts
                    )
                    body += (
                        f'<tr>'
                        f'<td class="col-ref">{e(ref)}</td><td class="col-item">{e(label)}</td>'
                        f'<td>{e(desc) or "—"}</td><td>{e(inv) or "—"}</td>'
                        f'<td>{co_c}</td><td>{act_html}</td>'
                        f'</tr>'
                    )
                else:
                    cond = (item.get('condition') or '') if is_ex else get_val(room['id'], item['id'], 'condition')
                    body += (
                        f'<tr>'
                        f'<td class="col-ref">{e(ref)}</td><td class="col-item">{e(label)}</td>'
                        f'<td>{e(desc) or "—"}</td><td>{e(cond) or "—"}</td>'
                        f'</tr>'
                    )

            table_block = (
                f'<table>'
                f'<thead style="background:{e(brand_color)};color:{e(hdr_txt)};">{thead}</thead>'
                f'<tbody>{body}</tbody>'
                f'</table>'
            )

            page_parts = [section_hdr(room.get('name', ''))]
            if ov_block        and ov_pos   == 'above': page_parts.append(ov_block)
            if item_photo_block and item_pos == 'above': page_parts.append(item_photo_block)
            page_parts.append(table_block)
            if item_photo_block and item_pos == 'below': page_parts.append(item_photo_block)
            if ov_block        and ov_pos   == 'below': page_parts.append(ov_block)

            parts.append(page(''.join(page_parts)))
        return ''.join(parts)

    # ── Action summary (Check Out only) ───────────────────────────────────────

    def build_action_summary():
        if not is_check_out or act_pos == 'none' or not actions_summary:
            return ''
        result = []
        for group in action_groups.values():
            c    = group['color']
            rows = ''.join(
                f'<tr>'
                f'<td class="col-ref">{i + 1}</td>'
                f'<td>{e(a["room"])} › {e(a["item"])}</td>'
                f'<td><span class="resp-tag" style="background:{c}22;color:{c};border:1px solid {c}55;">{e(a.get("responsibility")) or "—"}</span></td>'
                f'<td>{e(a.get("condition")) or "—"}</td>'
                f'</tr>'
                for i, a in enumerate(group['items'])
            )
            result.append(page(
                f'<div class="section-hdr" style="background:{e(c)};color:white;">{e(group["name"])}</div>'
                f'<table>'
                f'<thead style="background:{c}22;">'
                f'<tr>'
                f'<th style="color:{e(c)};">Ref</th>'
                f'<th style="color:{e(c)};">Room › Item</th>'
                f'<th style="color:{e(c)};">Responsibility</th>'
                f'<th style="color:{e(c)};">Condition at Check Out</th>'
                f'</tr>'
                f'</thead>'
                f'<tbody>{rows}</tbody>'
                f'</table>'
            ))
        return ''.join(result)

    # ── Declaration ───────────────────────────────────────────────────────────

    def build_declaration():
        return page(
            section_hdr('Declaration') +
            '<div class="decl-body">'
            '<p class="decl-text">I/We the undersigned, affirm that if I/we do not comment on the Inventory in '
            'writing within seven days of receipt of this Inventory then I/we accept the Inventory as being an '
            'accurate record of the contents and condition of the property.</p>'
            '<div class="decl-sigs">'
            '<div class="decl-sig-block">'
            '<div class="decl-sig-label">Signed by the Tenant(s)</div>'
            '<div class="decl-sig-line"></div>'
            '<div class="decl-field"><span>Print Name</span><div class="decl-field-line"></div></div>'
            '<div class="decl-field"><span>Date</span><div class="decl-field-line"></div></div>'
            '</div>'
            '<div class="decl-sig-block">'
            '<div class="decl-sig-label">Signed by the Landlord / Agent</div>'
            '<div class="decl-sig-line"></div>'
            '<div class="decl-field"><span>Print Name</span><div class="decl-field-line"></div></div>'
            '<div class="decl-field"><span>Date</span><div class="decl-field-line"></div></div>'
            '</div>'
            '</div>'
            '</div>'
        )

    # ── Assemble ──────────────────────────────────────────────────────────────

    body_html = ''
    body_html += build_cover()
    body_html += build_contents()
    body_html += build_disclaimer()
    if is_check_out and act_pos == 'top':
        body_html += build_action_summary()
    body_html += build_fixed_sections()
    body_html += build_rooms()
    if is_check_out and act_pos == 'bottom':
        body_html += build_action_summary()
    body_html += build_declaration()

    # ── CSS — identical to PdfExportModal.vue ─────────────────────────────────

    page_size = 'A4 landscape' if orient == 'landscape' else 'A4 portrait'
    css = f"""
    @page {{ size: {page_size}; margin: 12mm 14mm; }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      font-size: 9pt; color: {body_txt}; background: white;
    }}

    /* Pages */
    .page {{ page-break-after: always; }}
    .page:last-child {{ page-break-after: auto; }}
    .page-cover {{ page-break-after: always; }}

    /* Section header bar */
    .section-hdr {{
      font-size: 11pt; font-weight: 700; letter-spacing: 0.3px;
      padding: 8px 12px; margin-bottom: 10px; break-after: avoid;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}

    /* Tables */
    table {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; margin-bottom: 8px; }}
    thead tr {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    thead th {{ padding: 7px 10px; text-align: left; font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; color: {hdr_txt}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    tbody td {{ padding: 7px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: top; line-height: 1.5; }}
    tbody tr:nth-child(even) td {{ background: #f8fafc; }}
    tr.photo-tr td {{ background: white !important; padding: 4px 10px 8px; border-bottom: 1px solid #f1f5f9; }}

    .col-ref  {{ width: 5%;  font-weight: 700; color: {brand_color}; white-space: nowrap; font-size: 8pt; }}
    .col-item {{ width: 18%; font-weight: 600; }}
    .col-desc {{ width: 25%; }}
    .col-cond {{ width: 20%; }}
    .col-co   {{ width: 18%; }}
    .col-act  {{ width: 14%; }}
    .reading  {{ font-family: 'Courier New', monospace; font-weight: 600; }}
    .notes    {{ font-size: 8pt; color: #64748b; }}

    /* Badges */
    .ans-badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: 700; }}
    .ans-yes   {{ background: #dcfce7; color: #166534; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .ans-no    {{ background: #fee2e2; color: #991b1b; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .ans-na    {{ background: #f1f5f9; color: #64748b; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .act-tag   {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 7.5pt; font-weight: 600; margin: 1px 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .act-tag small {{ display: block; font-size: 7pt; font-weight: 400; opacity: 0.8; }}
    .resp-tag  {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: 600; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}

    /* TOC */
    .toc-table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
    .toc-table td {{ padding: 6px 0; border: none; font-size: 9.5pt; vertical-align: baseline; }}
    .toc-table tbody tr:nth-child(even) td {{ background: transparent; }}
    .toc-num   {{ width: 30px; font-weight: 700; }}
    .toc-dots  {{ border-bottom: 1.5px dotted #cbd5e1; width: auto; }}
    .toc-page  {{ width: 36px; text-align: right; font-weight: 700; color: {brand_color}; }}

    /* Disclaimer */
    .disclaimer-body {{ font-size: 9pt; line-height: 1.75; white-space: pre-wrap; }}

    /* Cover */
    .cover-top {{
      padding: 36px 0 28px;
      display: flex; flex-direction: column; align-items: center; gap: 16px;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}
    .cover-logo-centered {{ display: flex; justify-content: center; width: 100%; }}
    .cover-logo-img {{ max-height: 90px; max-width: 380px; width: auto; height: auto; object-fit: contain; display: block; }}
    .cover-logo-fallback {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 90px; height: 90px; background: rgba(255,255,255,0.18); border-radius: 10px;
      font-size: 30px; font-weight: 700; color: white;
    }}
    .cover-type-badge {{ font-size: 20pt; font-weight: 700; text-align: center; padding: 0 20px; }}
    .cover-photo-area {{ background: #f1f5f9; margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .cover-photo-img  {{ width: 100%; height: 300px; object-fit: cover; display: block; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .cover-photo-placeholder {{ height: 220px; display: flex; align-items: center; justify-content: center; color: #94a3b8; font-size: 10pt; }}
    .cover-info-block {{ margin: 0; }}
    .cover-info-row {{ display: flex; padding: 10px 14px; border-bottom: 1px solid #f1f5f9; align-items: baseline; gap: 14px; }}
    .cover-info-lbl {{ width: 120px; font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; color: #94a3b8; flex-shrink: 0; }}
    .cover-info-val {{ font-size: 11pt; font-weight: 600; }}
    .cover-footer {{
      display: flex; justify-content: space-between; padding: 10px 14px;
      font-size: 9pt; font-weight: 500;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}

    /* Photos */
    .ov-label {{ font-size: 8pt; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin: 8px 0 4px; }}
    .photo-grid {{ display: flex; flex-wrap: wrap; margin: 6px 0 10px; }}
    .photo-unit {{ width: 25%; padding: 3px; }}
    .photo-unit img {{
      width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block;
      border: 1px solid #e2e8f0;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}
    .photo-ref {{ font-size: 7pt; font-style: italic; color: #64748b; text-align: center; padding: 2px 0 4px; }}
    .photo-grid--inline .photo-unit {{ width: 16.66%; }}
    .photo-wrap {{ position: relative; }}
    .photo-ts {{
      position: absolute; bottom: 0; left: 0; right: 0;
      text-align: center; font-size: 5.5pt; color: white;
      background: rgba(0,0,0,0.58); padding: 1px 2px;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}

    /* Declaration */
    .decl-body  {{ padding: 8px 0; }}
    .decl-text  {{ font-size: 9pt; line-height: 1.7; margin-bottom: 44px; }}
    .decl-sigs  {{ display: flex; gap: 40px; }}
    .decl-sig-block {{ flex: 1; }}
    .decl-sig-label {{ font-size: 9pt; font-weight: 700; margin-bottom: 50px; }}
    .decl-sig-line  {{ border-bottom: 1px solid #374151; margin-bottom: 14px; }}
    .decl-field {{
      display: flex; align-items: center; gap: 12px;
      font-size: 8.5pt; color: #475569; margin-bottom: 22px;
    }}
    .decl-field-line {{ flex: 1; border-bottom: 1px solid #cbd5e1; }}

    @media print {{
      body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
    """

    addr = e(prop.get('address') or '')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{e(type_label)} — {addr}</title>
  <style>{css}</style>
</head>
<body>{body_html}</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers — dict representations of ORM objects
# ─────────────────────────────────────────────────────────────────────────────

def _client_dict(client) -> dict:
    if not client:
        return {}
    return {
        'id':                      client.id,
        'name':                    client.name or '',
        'email':                   client.email or '',
        'company':                 client.company or '',
        'logo':                    client.logo or '',
        'primary_color':           client.primary_color or '#1E3A8A',
        'report_disclaimer':       client.report_disclaimer or '',
        'report_color_override':   client.report_color_override or '',
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


def _get_report_recipients(inspection) -> list[str]:
    """
    Build a deduplicated list of recipient email addresses from the Contacts
    section of an inspection:
      1. client_email_override  (if set), else  client.email
      2. tenant_email           (if set and not already included)

    Returns a list of unique, non-empty email strings.
    """
    recipients = []

    # Primary contact: override takes precedence over client default
    primary = ''
    if inspection.client_email_override:
        primary = inspection.client_email_override.strip()
    elif inspection.property and inspection.property.client:
        primary = (inspection.property.client.email or '').strip()

    if primary:
        recipients.append(primary.lower())

    # Tenant email — add only if not already in the list
    if inspection.tenant_email:
        tenant = inspection.tenant_email.strip().lower()
        if tenant and tenant not in recipients:
            recipients.append(tenant)

    return recipients
