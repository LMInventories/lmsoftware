"""
Property templates — bake a completed Check In's layout into a template of its own.

A report's layout is normally a shared Template plus an overlay inside report_data
(rooms the clerk added, renames, deleted items, extra items, ordering). That
overlay is lost or half-copied whenever the next inspection is seeded. Baking
turns the overlay into real Section/Item rows on a private, transient Template
so the Check Out (and the next Check In) start from exactly the layout the
clerk left behind, and report_data keys line up with the template again.

Transient templates are hidden from the Templates list (see routes/templates.py);
only "Save as Template" produces a visible one.
"""
import json

from models import db, Template, Section, Item

# Top-level report_data keys that only exist to describe layout. Once baked
# into the template they are meaningless (and would double-apply) so they are
# dropped from the rewritten report_data.
LAYOUT_META_KEYS = ('_customRooms', '_roomNames', '_hiddenRooms', '_roomOrder', '_importedRooms')

# Per-room keys that describe layout and are consumed by baking.
ROOM_LAYOUT_KEYS = ('_extra', '_deleted', '_itemOrder', '_hiddenItems')

_EXTRA_STRUCT_KEYS = ('_eid', 'name', 'label')


def _load(rd):
    if isinstance(rd, str):
        try:
            rd = json.loads(rd)
        except Exception:
            return {}
    return rd if isinstance(rd, dict) else {}


def _answer_options(item):
    return item.answer_options or ''


def resolve_layout(template, rd):
    """
    Resolve what a report actually shows — the same rules the web editor,
    mobile app and PDF follow — as an ordered list of rooms:

        [{'key', 'name', 'section', 'items': [{'key', 'name', 'item', 'extra'}]}]

    `section` / `item` are the source Section / Item rows (None for rooms and
    items that exist only in the overlay). Non-room template sections are not
    included; they are copied verbatim by bake_property_template().
    """
    rd = _load(rd)
    hidden = {str(x) for x in (rd.get('_hiddenRooms') or [])}
    names = rd.get('_roomNames') or {}

    rooms = []
    if template is not None:
        for s in sorted(template.sections or [], key=lambda x: x.order_index or 0):
            if s.section_type != 'room' or str(s.id) in hidden:
                continue
            rooms.append({'key': str(s.id), 'name': names.get(str(s.id)) or s.name,
                          'section': s, 'tmpl_items': sorted(s.items or [], key=lambda i: i.order_index or 0)})

    for r in (rd.get('_importedRooms') or []):
        key = str(r.get('id') or r.get('key') or '')
        if key and key not in hidden:
            rooms.append({'key': key, 'name': names.get(key) or r.get('name') or 'Room',
                          'section': None, 'tmpl_items': []})

    for r in (rd.get('_customRooms') or []):
        key = str(r.get('key') or '')
        if key and key not in hidden:
            rooms.append({'key': key, 'name': names.get(key) or r.get('name') or 'Room',
                          'section': None, 'tmpl_items': []})

    order = [str(k) for k in (rd.get('_roomOrder') or [])]
    if order:
        rooms.sort(key=lambda r: order.index(r['key']) if r['key'] in order else len(order))

    for room in rooms:
        sec_rd = rd.get(room['key']) if isinstance(rd.get(room['key']), dict) else {}
        deleted = {str(d) for d in (sec_rd.get('_deleted') or [])}
        items = [{'key': str(i.id), 'name': i.name, 'item': i, 'extra': None}
                 for i in room['tmpl_items'] if str(i.id) not in deleted]
        for ex in (sec_rd.get('_extra') or []):
            eid = str(ex.get('_eid') or '')
            if not eid or eid in deleted:
                continue
            indexed = sec_rd.get(eid) if isinstance(sec_rd.get(eid), dict) else {}
            name = (ex.get('label') or ex.get('name') or indexed.get('_name') or 'New item')
            items.append({'key': eid, 'name': name, 'item': None, 'extra': ex})
        item_order = [str(k) for k in (sec_rd.get('_itemOrder') or [])]
        if item_order:
            # Items missing from the stored order keep their relative position at the end.
            items.sort(key=lambda it: item_order.index(it['key']) if it['key'] in item_order else len(item_order))
        room['items'] = items
        del room['tmpl_items']
    return rooms


def layout_signature(rooms):
    """Comparable summary of a resolved layout: [(room name, [item names])]."""
    return [(r['name'], [i['name'] for i in r['items']]) for r in rooms]


def is_property_template(template):
    return bool(template and template.is_transient and (template.name or '').endswith(' (property)'))


def has_layout_overlay(rd):
    """True when report_data still carries layout changes on top of its template."""
    rd = _load(rd)
    if any(rd.get(k) for k in LAYOUT_META_KEYS):
        return True
    return any(isinstance(v, dict) and any(v.get(k) for k in ROOM_LAYOUT_KEYS)
               for k, v in rd.items() if not k.startswith('_'))


# Keys inside a room's data that describe layout rather than content.
_STRUCT_KEYS = set(ROOM_LAYOUT_KEYS) | {'_hidden', '_name', '_eid'}


def _has_content(v):
    """True when `v` holds something a reader of the report would see."""
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, list):
        return any(_has_content(x) for x in v)
    if isinstance(v, dict):
        return any(_has_content(x) for k, x in v.items() if k not in _STRUCT_KEYS)
    return False


def _data_section_keys(rd):
    """Numeric top-level keys (section ids) that carry content, excluding rooms the phone invented."""
    custom = {str(r.get('key') or '') for r in (rd.get('_customRooms') or [])}
    custom |= {str(r.get('id') or r.get('key') or '') for r in (rd.get('_importedRooms') or [])}
    return {k for k, v in rd.items()
            if k.isdigit() and k not in custom and isinstance(v, dict) and _has_content(v)}


def orphan_room_keys(inspection):
    """
    Section ids holding report content that the inspection's template does not contain.
    Content under such keys is invisible in the web editor and the PDF - the sign of a
    report whose data was keyed to a different template than the one the server holds.
    """
    rd = _load(inspection.report_data)
    template = inspection.template
    valid = {str(s.id) for s in (template.sections if template is not None else [])}
    valid |= {str(x) for x in (rd.get('_hiddenRooms') or [])}
    return sorted(_data_section_keys(rd) - valid, key=int)


def reconcile_template(inspection):
    """
    Re-point the inspection at the template its report data was actually keyed to.

    A clerk can switch template on the phone; that choice used to stay on the device, so
    the server kept the booked template and mapped the phone's data against the wrong
    section ids (the data silently landed in no room). The report's own keys tell us
    which template was used: when more of its content keys belong to another template
    than to the current one, switch to that template. Returns the new Template, or None
    when nothing needed changing. The caller commits.
    """
    keys = _data_section_keys(_load(inspection.report_data))
    if not keys:
        return None
    current = inspection.template
    current_ids = {str(s.id) for s in (current.sections if current is not None else [])}
    matched_now = len(keys & current_ids)
    if matched_now == len(keys):
        return None
    counts = {}
    for _sid, tid in db.session.query(Section.id, Section.template_id).filter(
            Section.id.in_([int(k) for k in keys])).all():
        counts[tid] = counts.get(tid, 0) + 1
    if not counts:
        return None
    best_tid, best = max(counts.items(), key=lambda kv: kv[1])
    if best <= matched_now or best_tid == inspection.template_id:
        return None
    best_tpl = db.session.get(Template, best_tid)
    if best_tpl is None:
        return None
    inspection.template = best_tpl
    inspection.template_id = best_tpl.id
    return best_tpl


def report_completeness(inspection):
    """{'rooms': rooms shown, 'with_content': rooms with anything in them, 'orphans': unmatched keys}."""
    rd = _load(inspection.report_data)
    rooms = resolve_layout(inspection.template, rd)
    with_content = sum(1 for r in rooms if isinstance(rd.get(r['key']), dict) and _has_content(rd[r['key']]))
    return {'rooms': len(rooms), 'with_content': with_content, 'orphans': orphan_room_keys(inspection)}


# Auto-sending is held when at least this many rooms exist and fewer than half have content.
_MIN_ROOMS_FOR_RATIO = 4


def completeness_problem(inspection):
    """
    Why this report should NOT be emailed automatically, or None when it looks fine.
    Applies to room-based reports only. A held report can still be sent by hand with
    Share PDF once someone has checked it.
    """
    if inspection.inspection_type not in ('check_in', 'inventory', 'check_out'):
        return None
    c = report_completeness(inspection)
    if c['orphans']:
        return f"{len(c['orphans'])} room(s) of data don't match the template layout"
    if c['rooms'] >= _MIN_ROOMS_FOR_RATIO and c['with_content'] * 2 < c['rooms']:
        return f"only {c['with_content']} of {c['rooms']} rooms have content"
    return None


def bake_property_template(inspection):
    """
    Create a transient property template from `inspection`'s final layout and
    rewrite the inspection to use it (new template_id, report_data re-keyed to
    the new section/item ids). Returns the new Template, or None when there is
    nothing to bake. The caller commits.

    The rendered report is unchanged by design: resolve_layout() of the new
    (template, report_data) pair equals resolve_layout() of the old pair.
    """
    rd = _load(inspection.report_data)
    switched = reconcile_template(inspection)
    if switched is not None:
        print(f'[property-template] inspection {inspection.id}: report data belongs to template '
              f'{switched.id} ({switched.name!r}), not the booked one - switched before baking')
    template = inspection.template
    orphans = orphan_room_keys(inspection)
    if orphans:
        # Baking would re-key by the wrong template and drop this content from view.
        print(f'[property-template] inspection {inspection.id}: NOT baking - content under section ids '
              f'{orphans} does not belong to template {inspection.template_id}')
        return None
    rooms = resolve_layout(template, rd)
    if template is None and not rooms:
        return None
    if is_property_template(template) and not has_layout_overlay(rd):
        return None   # already baked, nothing new on top of it

    address = (inspection.property.address if inspection.property else '') or f'Inspection {inspection.id}'
    new_tpl = Template(
        name=f'{address[:80]} (property)',
        inspection_type=inspection.inspection_type,
        content='{}',
        is_default=False,
        is_transient=True,
    )
    db.session.add(new_tpl)
    db.session.flush()

    new_rd = {}
    section_map = {}   # old section key -> new section id (str)

    def _add_section(name, section_type, is_required, order_index):
        sec = Section(template_id=new_tpl.id, name=name[:200], section_type=section_type,
                      order_index=order_index, is_required=bool(is_required))
        db.session.add(sec)
        db.session.flush()
        return sec

    order_index = 0
    for room in rooms:
        src_sec = room['section']
        new_sec = _add_section(room['name'], 'room', src_sec.is_required if src_sec else False, order_index)
        order_index += 1
        section_map[room['key']] = str(new_sec.id)

        old_room = rd.get(room['key']) if isinstance(rd.get(room['key']), dict) else {}
        new_room = {}
        item_map = {}   # old item key -> new item id (str)
        for idx, it in enumerate(room['items']):
            src_item = it['item']
            new_item = Item(
                section_id=new_sec.id,
                name=(it['name'] or 'Item')[:200],
                description=src_item.description if src_item else '',
                requires_photo=src_item.requires_photo if src_item else True,
                requires_condition=src_item.requires_condition if src_item else True,
                answer_options=_answer_options(src_item) if src_item else '',
                order_index=idx,
            )
            db.session.add(new_item)
            db.session.flush()
            item_map[it['key']] = str(new_item.id)
            data = dict(old_room.get(it['key']) or {}) if isinstance(old_room.get(it['key']), dict) else {}
            if it['extra']:
                # Inline fields on the _extra entry win over the keyed row (matches the web editor).
                data.update({k: v for k, v in it['extra'].items() if k not in _EXTRA_STRUCT_KEYS})
            if data or it['key'] in old_room:
                new_room[str(new_item.id)] = data

        deleted = {str(d) for d in (old_room.get('_deleted') or [])}
        for k, v in old_room.items():
            if k in ROOM_LAYOUT_KEYS or k in item_map or k in deleted:
                continue
            new_room[k] = v   # _hidden, _customItems, sub-item photo rows, etc.
        new_rd[str(new_sec.id)] = new_room

    # Non-room template sections (fixed-type) are carried over untouched.
    if template is not None:
        for s in sorted(template.sections or [], key=lambda x: x.order_index or 0):
            if s.section_type == 'room':
                continue
            new_sec = _add_section(s.name, s.section_type, s.is_required, order_index)
            order_index += 1
            section_map[str(s.id)] = str(new_sec.id)
            item_map = {}
            for idx, i in enumerate(sorted(s.items or [], key=lambda x: x.order_index or 0)):
                ni = Item(section_id=new_sec.id, name=i.name, description=i.description,
                          requires_photo=i.requires_photo, requires_condition=i.requires_condition,
                          answer_options=i.answer_options, order_index=idx)
                db.session.add(ni)
                db.session.flush()
                item_map[str(i.id)] = str(ni.id)
            old_sec = rd.get(str(s.id)) if isinstance(rd.get(str(s.id)), dict) else {}
            new_rd[str(new_sec.id)] = {item_map.get(k, k): v for k, v in old_sec.items()}

    # Everything else (fixed-section data keyed fs_*, _overview, _signatures, hidden-room
    # data, ...) is untouched, minus the layout meta that has now been baked in.
    for k, v in rd.items():
        if k in section_map or k in LAYOUT_META_KEYS:
            continue
        new_rd.setdefault(k, v)

    inspection.template_id = new_tpl.id
    inspection.report_data = json.dumps(new_rd)
    return new_tpl
