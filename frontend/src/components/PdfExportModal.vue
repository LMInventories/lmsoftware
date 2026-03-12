<script setup>
import { computed } from 'vue'

// ─────────────────────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────────────────────
const props = defineProps({
  inspection:      { type: Object, required: true },
  fixedSections:   { type: Array,  default: () => [] },
  rooms:           { type: Array,  default: () => [] },
  reportData:      { type: Object, default: () => ({}) },
  actionCatalogue: { type: Array,  default: () => [] },
  // photoSettings — photo placement prefs (photo_room_overview, photo_room_item, etc.)
  photoSettings:   { type: Object, default: () => ({}) },
  // clientSettings — report branding settings (colours, orientation)
  clientSettings:  { type: Object, default: () => ({}) },
})
const emit = defineEmits(['close'])

// ─────────────────────────────────────────────────────────────────────────────
// Derived values
// ─────────────────────────────────────────────────────────────────────────────
const isCheckOut = computed(() => props.inspection.inspection_type === 'check_out')

const typeLabel = computed(() => ({
  check_in:  'Inventory & Check In',
  check_out: 'Check Out',
  interim:   'Interim Inspection',
  inventory: 'Inventory Report',
})[props.inspection.inspection_type] ?? 'Inspection Report')

// Client + property — embedded on inspection object by the API
const client = computed(() => props.inspection.client   || {})
const prop   = computed(() => props.inspection.property || {})

// Branding: report_color_override takes precedence over primary_color
const brandColor      = computed(() => props.clientSettings.report_color_override || props.clientSettings.primary_color || '#1E3A8A')
const headerTextColor = computed(() => props.clientSettings.report_header_text_color || '#FFFFFF')
const bodyTextColor   = computed(() => props.clientSettings.report_body_text_color   || '#1e293b')
const orientation     = computed(() => props.clientSettings.report_orientation       || 'portrait')

// Photo + layout settings (from report_photo_settings JSON — passed as photoSettings prop)
const photoRoomOverview = computed(() => props.photoSettings.photo_room_overview    || 'above')
const photoRoomItem     = computed(() => props.photoSettings.photo_room_item        || 'below')
const showTimestamp     = computed(() => props.photoSettings.show_photo_timestamp   === true)
const actionSummaryPos  = computed(() => props.photoSettings.action_summary_position || 'bottom')

// Action catalogue helpers
function catalogueLookup(actionId) { return props.actionCatalogue.find(c => c.id === actionId) || null }
function actionName(actionId)  { return catalogueLookup(actionId)?.name  || actionId || '—' }
function actionColor(actionId) { return catalogueLookup(actionId)?.color || '#64748b' }

// ─────────────────────────────────────────────────────────────────────────────
// Report data accessors (mirror InspectionReportView helpers exactly)
// ─────────────────────────────────────────────────────────────────────────────
function get(sectionId, rowId, field) {
  return props.reportData[sectionId]?.[String(rowId)]?.[field] ?? ''
}
function isHidden(sectionId, rowId) {
  return props.reportData[sectionId]?._hidden?.includes(String(rowId)) ?? false
}
function isItemHidden(roomId, itemId) {
  return props.reportData[roomId]?._hiddenItems?.includes(String(itemId)) ?? false
}
function getExtra(sectionId) {
  return props.reportData[sectionId]?._extra ?? []
}
function getItemActions(roomId, itemId) {
  return props.reportData[roomId]?.[`_actions_${itemId}`] ?? []
}
function getOrderedRoomItems(room) {
  const storedOrder   = props.reportData[room.id]?._itemOrder
  const templateItems = (room.sections || []).map(item => ({ ...item, _type: 'template' }))
  const extraItems    = (props.reportData[room.id]?._extra || []).map(ex => ({
    ...ex, id: ex._eid, label: ex.label || 'New item', _type: 'extra',
  }))
  const all = [...templateItems, ...extraItems]
  if (!storedOrder?.length) return all
  const ordered = storedOrder
    .map(id => all.find(i => String(i.id) === String(id) || String(i._eid) === String(id)))
    .filter(Boolean)
  for (const item of all) {
    const key = item._type === 'extra' ? item._eid : String(item.id)
    if (!storedOrder.some(o => String(o) === key)) ordered.push(item)
  }
  return ordered
}

// Action summary data (Check Out only)
const actionsSummary = computed(() => {
  if (!isCheckOut.value) return []
  const result = []
  for (const room of props.rooms) {
    for (const item of getOrderedRoomItems(room)) {
      const itemId = item._type === 'extra' ? item._eid : item.id
      if (isItemHidden(room.id, itemId)) continue
      for (const act of getItemActions(room.id, itemId)) {
        if (!act.actionId) continue
        result.push({ room: room.name, item: item.label || item.name || '', ...act })
      }
    }
  }
  return result
})

const actionGroups = computed(() => {
  const groups = {}
  for (const a of actionsSummary.value) {
    if (!groups[a.actionId]) {
      groups[a.actionId] = { name: actionName(a.actionId), color: actionColor(a.actionId), items: [] }
    }
    groups[a.actionId].items.push(a)
  }
  return groups
})

// ─────────────────────────────────────────────────────────────────────────────
// Print
// ─────────────────────────────────────────────────────────────────────────────
function printReport() {
  const html = buildReportHTML()
  const iframe = document.createElement('iframe')
  iframe.style.cssText = 'position:fixed;top:-9999px;left:-9999px;width:1px;height:1px;'
  document.body.appendChild(iframe)
  iframe.contentDocument.open()
  iframe.contentDocument.write(html)
  iframe.contentDocument.close()
  iframe.contentWindow.focus()
  setTimeout(() => {
    iframe.contentWindow.print()
    setTimeout(() => document.body.removeChild(iframe), 2000)
  }, 800)
}

// ─────────────────────────────────────────────────────────────────────────────
// HTML builder
// ─────────────────────────────────────────────────────────────────────────────
function buildReportHTML() {
  const brand    = brandColor.value
  const hdrTxt   = headerTextColor.value
  const bodyTxt  = bodyTextColor.value
  const orient   = orientation.value
  const ovPos    = photoRoomOverview.value     // 'above' | 'below'
  const itemPos  = photoRoomItem.value         // 'above' | 'below' | 'hyperlink'
  const addTs    = showTimestamp.value
  const actPos   = actionSummaryPos.value      // 'top' | 'bottom' | 'none'

  const insp = props.inspection
  const cl   = client.value
  const pr   = prop.value

  // ── Escape ────────────────────────────────────────────────────────────────
  function e(s) {
    if (s == null) return ''
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
  }

  function fmtDate(iso) {
    if (!iso) return ''
    return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' })
  }

  function fmtTs(iso) {
    if (!iso) return ''
    return new Date(iso).toLocaleString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  }

  // ── Photo helpers ─────────────────────────────────────────────────────────
  function getPhotos(sectionId, rowId) {
    return props.reportData[sectionId]?.[String(rowId)]?._photos || []
  }
  function getPhotoTs(sectionId, rowId) {
    return props.reportData[sectionId]?.[String(rowId)]?._photoTs || []
  }

  // Render a single .photo-unit
  function photoUnit(src, ts, refLabel) {
    const tsHtml = addTs && ts
      ? `<div class="photo-ts">${e(fmtTs(ts))}</div>` : ''
    return `<div class="photo-unit">
      <div class="photo-wrap"><img src="${e(src)}" />${tsHtml}</div>
      <div class="photo-ref">Ref #${e(refLabel)}</div>
    </div>`
  }

  // Build array of photo-unit strings for a section+row
  function photoUnits(sectionId, rowId, refLabel) {
    const ps = getPhotos(sectionId, rowId)
    const ts = getPhotoTs(sectionId, rowId)
    return ps.map((src, i) => photoUnit(src, ts[i], refLabel))
  }

  // Wrap units in a .photo-grid div
  function photoGrid(units, inline = false) {
    if (!units.length) return ''
    const cls = inline ? ' photo-grid--inline' : ''
    return `<div class="photo-grid${cls}">${units.join('')}</div>`
  }

  // ── Section header ────────────────────────────────────────────────────────
  function sectionHdr(title) {
    return `<div class="section-hdr" style="background:${e(brand)};color:${e(hdrTxt)};">${e(title)}</div>`
  }

  // ── Page wrapper ──────────────────────────────────────────────────────────
  function page(content) {
    return `<div class="page">${content}</div>`
  }

  // ─────────────────────────────────────────────────────────────────────────
  // COVER PAGE
  // ─────────────────────────────────────────────────────────────────────────
  function buildCover() {
    const logoHtml = cl.logo
      ? `<img src="${e(cl.logo)}" class="cover-logo-img" alt="logo">`
      : `<div class="cover-logo-fallback">${e((cl.company || cl.name || 'IP').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase())}</div>`

    const propPhotoHtml = pr.overview_photo
      ? `<img src="${e(pr.overview_photo)}" class="cover-photo-img" alt="Property">`
      : `<div class="cover-photo-placeholder"><span>Property overview photo</span></div>`

    const infoRows = [
      { label: 'Address', value: pr.address || insp.property_address || '' },
      { label: 'Date',    value: fmtDate(insp.conduct_date) },
      { label: 'Client',  value: cl.company || cl.name || '' },
    ]
    const infoHtml = infoRows.map(r =>
      `<div class="cover-info-row">
        <div class="cover-info-lbl">${e(r.label)}</div>
        <div class="cover-info-val" style="color:${e(bodyTxt)};">${e(r.value)}</div>
      </div>`
    ).join('')

    return `<div class="page page-cover">
      <div class="cover-top" style="background:${e(brand)};-webkit-print-color-adjust:exact;print-color-adjust:exact;">
        ${logoHtml}
      </div>
      <div class="cover-photo-area">${propPhotoHtml}</div>
      <div class="cover-type-label" style="color:${e(bodyTxt)};">${e(typeLabel.value)}</div>
      <div class="cover-info-block">${infoHtml}</div>
      <div class="cover-footer" style="background:${e(brand)};color:${e(hdrTxt)};-webkit-print-color-adjust:exact;print-color-adjust:exact;">
        <span>${e(cl.company || cl.name || 'InspectPro')}</span>
        <span>Confidential</span>
      </div>
    </div>`
  }

  // ─────────────────────────────────────────────────────────────────────────
  // CONTENTS PAGE
  // ─────────────────────────────────────────────────────────────────────────
  function buildContents() {
    const rows = []
    let n = 1
    rows.push({ n: n++, title: 'Cover Page',  cls: 'front' })
    rows.push({ n: n++, title: 'Contents',    cls: 'front' })
    if (cl.report_disclaimer) rows.push({ n: n++, title: 'Disclaimers', cls: 'front' })
    if (isCheckOut.value && actPos === 'top' && actionsSummary.value.length) {
      rows.push({ n: n++, title: 'Action Summary', cls: 'action' })
    }
    for (const s of props.fixedSections) rows.push({ n: n++, title: s.name, cls: 'fixed' })
    for (const r of props.rooms)         rows.push({ n: n++, title: r.name, cls: 'room' })
    if (isCheckOut.value && actPos === 'bottom' && actionsSummary.value.length) {
      rows.push({ n: n++, title: 'Action Summary', cls: 'action' })
    }
    rows.push({ n: n++, title: 'Declaration', cls: 'front' })

    const rowsHtml = rows.map(r =>
      `<tr>
        <td class="toc-num" style="color:${e(brand)};">${r.n}</td>
        <td class="toc-title">${e(r.title)}</td>
        <td class="toc-dots"></td>
        <td class="toc-page">—</td>
      </tr>`
    ).join('')

    return page(sectionHdr('Contents') + `<table class="toc-table"><tbody>${rowsHtml}</tbody></table>`)
  }

  // ─────────────────────────────────────────────────────────────────────────
  // DISCLAIMER
  // Uses pre-wrap so line breaks in the disclaimer text are preserved.
  // Long disclaimers flow naturally across pages.
  // ─────────────────────────────────────────────────────────────────────────
  function buildDisclaimer() {
    if (!cl.report_disclaimer) return ''
    return page(sectionHdr('Disclaimers') + `<div class="disclaimer-body">${e(cl.report_disclaimer)}</div>`)
  }

  // ─────────────────────────────────────────────────────────────────────────
  // FIXED SECTIONS
  // Photos are placed inline — immediately after their own row inside the table.
  // This matches the reference PDF (74 Linwood Close) where each item's photos
  // appear directly below that item's data row, before the next item.
  // ─────────────────────────────────────────────────────────────────────────
  const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

  function buildFixedSections() {
    return props.fixedSections.map((section, si) => {
      const letter     = LETTERS[si] ?? String(si + 1)
      const t          = section.type
      const visRows    = (section.rows || []).filter(r => !isHidden(section.id, r.id))
      const extraRows  = getExtra(section.id)

      // Row ref: A.1, A.2 … for visible rows; continues numbering for extras
      function rowRef(rowId) {
        const i = visRows.findIndex(r => String(r.id) === String(rowId))
        if (i >= 0) return `${letter}.${i + 1}`
        const ei = extraRows.findIndex(ex => ex._eid === rowId)
        if (ei >= 0) return `${letter}.${visRows.length + ei + 1}`
        return `${letter}.?`
      }

      // Inline photo row spanning all columns, inserted after data row
      function inlinePhotoRow(rowId, ref, colspan) {
        const units = photoUnits(section.id, rowId, ref)
        if (!units.length) return ''
        return `<tr class="photo-tr">
          <td colspan="${colspan}" class="photo-td">${photoGrid(units, true)}</td>
        </tr>`
      }

      // Build one data row + optional inline photo row
      function buildRow(r, isExtra) {
        const rid  = isExtra ? r._eid : r.id
        const ref  = rowRef(rid)
        const gv   = (f) => isExtra ? (r[f] || '') : (get(section.id, rid, f) || r[f] || '')

        if (t === 'condition_summary') {
          return `<tr>
            <td class="col-ref">${e(ref)}</td><td>${e(r.name)}</td>
            <td>${e(gv('condition')) || '—'}</td>
          </tr>` + inlinePhotoRow(rid, ref, 3)
        }
        if (t === 'cleaning_summary') {
          return `<tr>
            <td class="col-ref">${e(ref)}</td><td>${e(r.name)}</td>
            <td>${e(gv('cleanliness')) || '—'}</td>
            <td class="notes">${e(gv('cleanlinessNotes')) || '—'}</td>
          </tr>` + inlinePhotoRow(rid, ref, 4)
        }
        if (t === 'smoke_alarms' || t === 'health_safety') {
          const ans = gv('answer') || r.answer || ''
          const cls = ans === 'Yes' ? 'ans-yes' : ans === 'No' ? 'ans-no' : 'ans-na'
          return `<tr>
            <td class="col-ref">${e(ref)}</td><td>${e(r.question || r.name)}</td>
            <td><span class="ans-badge ${cls}">${e(ans) || '—'}</span></td>
            <td class="notes">${e(gv('notes') || r.notes || '—')}</td>
          </tr>` + inlinePhotoRow(rid, ref, 4)
        }
        if (t === 'fire_door_safety') {
          const ans = gv('answer') || r.answer || ''
          const cls = ans === 'Yes' ? 'ans-yes' : ans === 'No' ? 'ans-no' : 'ans-na'
          return `<tr>
            <td class="col-ref">${e(ref)}</td><td>${e(r.name)}</td>
            <td>${e(r.question)}</td>
            <td><span class="ans-badge ${cls}">${e(ans) || '—'}</span></td>
            <td class="notes">${e(gv('notes') || r.notes || '—')}</td>
          </tr>` + inlinePhotoRow(rid, ref, 5)
        }
        if (t === 'keys') {
          return `<tr>
            <td class="col-ref">${e(ref)}</td><td>${e(r.name)}</td>
            <td>${e(gv('description')) || '—'}</td>
          </tr>` + inlinePhotoRow(rid, ref, 3)
        }
        if (t === 'meter_readings') {
          return `<tr>
            <td class="col-ref">${e(ref)}</td><td>${e(r.name)}</td>
            <td>${e(gv('locationSerial')) || '—'}</td>
            <td class="reading">${e(gv('reading')) || '—'}</td>
          </tr>` + inlinePhotoRow(rid, ref, 4)
        }
        // Generic
        return `<tr>
          <td class="col-ref">${e(ref)}</td><td>${e(r.name)}</td>
          <td>${e(gv('condition') || gv('description')) || '—'}</td>
        </tr>` + inlinePhotoRow(rid, ref, 3)
      }

      const theadMap = {
        condition_summary:  `<tr><th>Ref</th><th>Name</th><th>Condition</th></tr>`,
        cleaning_summary:   `<tr><th>Ref</th><th>Area</th><th>Cleanliness</th><th>Additional Notes</th></tr>`,
        smoke_alarms:       `<tr><th>Ref</th><th>Question</th><th>Answer</th><th>Additional Notes</th></tr>`,
        health_safety:      `<tr><th>Ref</th><th>Question</th><th>Answer</th><th>Additional Notes</th></tr>`,
        fire_door_safety:   `<tr><th>Ref</th><th>Name</th><th>Question</th><th>Answer</th><th>Additional Notes</th></tr>`,
        keys:               `<tr><th>Ref</th><th>Key / Item</th><th>Description</th></tr>`,
        meter_readings:     `<tr><th>Ref</th><th>Meter</th><th>Location &amp; Serial</th><th>Reading</th></tr>`,
      }
      const thead = theadMap[t] || `<tr><th>Ref</th><th>Item</th><th>Details</th></tr>`
      const body  = visRows.map(r => buildRow(r, false)).join('')
                  + extraRows.map(r => buildRow(r, true)).join('')

      return page(
        sectionHdr(section.name) +
        `<table>
          <thead style="background:${e(brand)};color:${e(hdrTxt)};">${thead}</thead>
          <tbody>${body}</tbody>
        </table>`
      )
    }).join('')
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ROOM PAGES
  //
  // Layout within each room page (order depends on client settings):
  //
  //   ovPos === 'above'    → room overview photo grid  ← always first if above
  //   itemPos === 'above'  → all item photo grids
  //   [data table always in the middle]
  //   itemPos === 'below'  → all item photo grids
  //   ovPos === 'below'    → room overview photo grid  ← always last if below
  //
  // Room overview photos are always shown regardless of itemPos.
  // Item photos are skipped entirely when itemPos === 'hyperlink'.
  // All photos are labelled: overview = "Ref #N", items = "Ref #N.M"
  // ─────────────────────────────────────────────────────────────────────────
  function buildRooms() {
    return props.rooms.map((room, ri) => {
      const roomNum = ri + 1
      const items   = getOrderedRoomItems(room)
      const co      = isCheckOut.value

      // ── Overview photos ─────────────────────────────────────────────────
      const ovUnits = photoUnits(room.id, '_overview', String(roomNum))
      const ovBlock = ovUnits.length
        ? `<div class="ov-label">Room Overview</div>${photoGrid(ovUnits)}`
        : ''

      // ── Item photo grid ─────────────────────────────────────────────────
      const itemUnits = []
      if (itemPos !== 'hyperlink') {
        let idx = 1
        for (const item of items) {
          const iid = item._type === 'extra' ? item._eid : item.id
          if (isItemHidden(room.id, iid)) { idx++; continue }
          const ref = `${roomNum}.${idx}`
          itemUnits.push(...photoUnits(room.id, String(iid), ref))
          idx++
        }
      }
      const itemPhotoBlock = photoGrid(itemUnits)

      // ── Data table ──────────────────────────────────────────────────────
      let thead, body = '', idx = 1
      if (co) {
        thead = `<tr>
          <th class="col-ref">Ref</th><th class="col-item">Item</th>
          <th class="col-desc">Description</th><th class="col-cond">Condition at Check In</th>
          <th class="col-co">Condition at Check Out</th><th class="col-act">Actions</th>
        </tr>`
      } else {
        thead = `<tr>
          <th class="col-ref">Ref</th><th class="col-item">Item</th>
          <th class="col-desc">Description</th><th class="col-cond">Condition</th>
        </tr>`
      }

      for (const item of items) {
        const iid    = item._type === 'extra' ? item._eid : item.id
        if (isItemHidden(room.id, iid)) { idx++; continue }
        const ref    = `${roomNum}.${idx++}`
        const isEx   = item._type === 'extra'
        const label  = item.label || item.name || ''
        const desc   = isEx ? (item.description || '') : get(room.id, item.id, 'description')

        if (co) {
          const inv  = isEx ? (item.inventoryCondition || '') : (get(room.id, item.id, 'inventoryCondition') || get(room.id, item.id, 'condition'))
          const coC  = isEx ? (item.checkOutCondition  || 'As Inventory &amp; Check In') : (get(room.id, item.id, 'checkOutCondition') || 'As Inventory &amp; Check In')
          const acts = getItemActions(room.id, iid)
          const actHtml = acts.map(a => {
            const ac = actionColor(a.actionId)
            return `<span class="act-tag" style="background:${ac}22;color:${ac};border:1px solid ${ac}55;">${e(actionName(a.actionId))}${a.responsibility ? `<br><small>${e(a.responsibility)}</small>` : ''}</span>`
          }).join('')
          body += `<tr>
            <td class="col-ref">${e(ref)}</td><td class="col-item">${e(label)}</td>
            <td>${e(desc) || '—'}</td><td>${e(inv) || '—'}</td>
            <td>${coC}</td><td>${actHtml}</td>
          </tr>`
        } else {
          const cond = isEx ? (item.condition || '') : get(room.id, item.id, 'condition')
          body += `<tr>
            <td class="col-ref">${e(ref)}</td><td class="col-item">${e(label)}</td>
            <td>${e(desc) || '—'}</td><td>${e(cond) || '—'}</td>
          </tr>`
        }
      }

      const tableBlock = `<table>
        <thead style="background:${e(brand)};color:${e(hdrTxt)};">${thead}</thead>
        <tbody>${body}</tbody>
      </table>`

      // ── Assemble page in correct order ──────────────────────────────────
      const parts = [sectionHdr(room.name)]
      if (ovBlock        && ovPos   === 'above') parts.push(ovBlock)
      if (itemPhotoBlock && itemPos === 'above') parts.push(itemPhotoBlock)
      parts.push(tableBlock)
      if (itemPhotoBlock && itemPos === 'below') parts.push(itemPhotoBlock)
      if (ovBlock        && ovPos   === 'below') parts.push(ovBlock)

      return page(parts.join(''))
    }).join('')
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ACTION SUMMARY (Check Out only)
  // ─────────────────────────────────────────────────────────────────────────
  function buildActionSummary() {
    if (!isCheckOut.value || actPos === 'none' || !actionsSummary.value.length) return ''
    return Object.values(actionGroups.value).map(group => {
      const c = group.color
      const rows = group.items.map((a, i) =>
        `<tr>
          <td class="col-ref">${i + 1}</td>
          <td>${e(a.room)} › ${e(a.item)}</td>
          <td><span class="resp-tag" style="background:${c}22;color:${c};border:1px solid ${c}55;">${e(a.responsibility) || '—'}</span></td>
          <td>${e(a.condition) || '—'}</td>
        </tr>`
      ).join('')
      return page(
        `<div class="section-hdr" style="background:${e(c)};color:white;">${e(group.name)}</div>
        <table>
          <thead style="background:${e(c)}22;">
            <tr>
              <th style="color:${e(c)};">Ref</th>
              <th style="color:${e(c)};">Room › Item</th>
              <th style="color:${e(c)};">Responsibility</th>
              <th style="color:${e(c)};">Condition at Check Out</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>`
      )
    }).join('')
  }

  // ─────────────────────────────────────────────────────────────────────────
  // DECLARATION
  // ─────────────────────────────────────────────────────────────────────────
  function buildDeclaration() {
    return page(
      sectionHdr('Declaration') +
      `<div class="decl-body">
        <p class="decl-text">I/We the undersigned, affirm that if I/we do not comment on the Inventory in writing within seven days of receipt of this Inventory then I/we accept the Inventory as being an accurate record of the contents and condition of the property.</p>
        <div class="decl-sigs">
          <div class="decl-sig-block">
            <div class="decl-sig-label">Signed by the Tenant(s)</div>
            <div class="decl-sig-line"></div>
            <div class="decl-field"><span>Print Name</span><div class="decl-field-line"></div></div>
            <div class="decl-field"><span>Date</span><div class="decl-field-line"></div></div>
          </div>
          <div class="decl-sig-block">
            <div class="decl-sig-label">Signed by the Landlord / Agent</div>
            <div class="decl-sig-line"></div>
            <div class="decl-field"><span>Print Name</span><div class="decl-field-line"></div></div>
            <div class="decl-field"><span>Date</span><div class="decl-field-line"></div></div>
          </div>
        </div>
      </div>`
    )
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ASSEMBLE FULL REPORT
  // ─────────────────────────────────────────────────────────────────────────
  let body = ''
  body += buildCover()
  body += buildContents()
  body += buildDisclaimer()
  if (isCheckOut.value && actPos === 'top')    body += buildActionSummary()
  body += buildFixedSections()
  body += buildRooms()
  if (isCheckOut.value && actPos === 'bottom') body += buildActionSummary()
  body += buildDeclaration()

  // ─────────────────────────────────────────────────────────────────────────
  // CSS
  // ─────────────────────────────────────────────────────────────────────────
  const pageSize = orient === 'landscape' ? 'A4 landscape' : 'A4 portrait'
  const css = `
    @page           { size: ${pageSize}; margin: 12mm 14mm; }
    @page :first    { size: ${pageSize}; margin: 0; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
      font-size: 9pt; color: ${bodyTxt}; background: white;
    }

    /* ── Pages ── */
    .page { page-break-after: always; }
    .page:last-child { page-break-after: auto; }

    /* ── Section header bar ── */
    .section-hdr {
      font-size: 11pt; font-weight: 700; letter-spacing: 0.3px;
      padding: 8px 12px; margin-bottom: 10px; break-after: avoid;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }

    /* ── Tables ── */
    table { width: 100%; border-collapse: collapse; font-size: 8.5pt; margin-bottom: 8px; }
    thead tr { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    thead th { padding: 7px 10px; text-align: left; font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; color: ${hdrTxt}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    tbody td { padding: 7px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: top; line-height: 1.5; }
    tbody tr:nth-child(even) td { background: #f8fafc; }
    /* Photo rows inside tables never get zebra stripe */
    tr.photo-tr td { background: white !important; padding: 4px 10px 8px; border-bottom: 1px solid #f1f5f9; }

    .col-ref  { width: 5%;  font-weight: 700; color: ${brand}; white-space: nowrap; font-size: 8pt; }
    .col-item { width: 18%; font-weight: 600; }
    .col-desc { width: 25%; }
    .col-cond { width: 20%; }
    .col-co   { width: 18%; }
    .col-act  { width: 14%; }
    .reading  { font-family: 'Courier New', monospace; font-weight: 600; }
    .notes    { font-size: 8pt; color: #64748b; }

    /* ── Badges ── */
    .ans-badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: 700; }
    .ans-yes   { background: #dcfce7; color: #166534; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .ans-no    { background: #fee2e2; color: #991b1b; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .ans-na    { background: #f1f5f9; color: #64748b; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .act-tag   { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 7.5pt; font-weight: 600; margin: 1px 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .act-tag small { display: block; font-size: 7pt; font-weight: 400; opacity: 0.8; }
    .resp-tag  { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: 600; -webkit-print-color-adjust: exact; print-color-adjust: exact; }

    /* ── TOC ── */
    .toc-table { border-collapse: collapse; width: 100%; margin-top: 8px; }
    .toc-table td { padding: 6px 0; border: none; font-size: 9.5pt; vertical-align: baseline; }
    .toc-table tbody tr:nth-child(even) td { background: transparent; }
    .toc-num   { width: 30px; font-weight: 700; }
    .toc-dots  { border-bottom: 1.5px dotted #cbd5e1; width: auto; }
    .toc-page  { width: 36px; text-align: right; font-weight: 700; color: ${brand}; }

    /* ── Disclaimer ── */
    .disclaimer-body { font-size: 9pt; line-height: 1.75; white-space: pre-wrap; }

    /* ── Cover ── */
    /* @page :first { margin:0 } — all cover elements are naturally full-bleed.
       .page-cover is exactly 297mm tall; footer is absolute at bottom. */
    .page-cover { page-break-after: always; position: relative; height: 297mm; overflow: hidden; }
    .cover-top {
      padding: 20px 14mm 16px;
      display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 42mm;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .cover-logo-img { max-height: 28mm; max-width: calc(100% - 28mm); width: auto; height: auto; object-fit: contain; display: block; }
    .cover-logo-fallback {
      display: inline-flex; align-items: center; justify-content: center;
      width: 70px; height: 70px; background: rgba(255,255,255,0.18); border-radius: 10px;
      font-size: 26px; font-weight: 700; color: white;
    }
    .cover-photo-area { background: #f1f5f9; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .cover-photo-img  { width: 100%; height: 90mm; object-fit: cover; display: block; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .cover-photo-placeholder { height: 90mm; display: flex; align-items: center; justify-content: center; color: #94a3b8; font-size: 10pt; }
    .cover-type-label { font-size: 18pt; font-weight: 700; text-align: center; padding: 14px 14mm 6px; }
    .cover-info-block { padding: 0 14mm; }
    .cover-info-row { display: flex; flex-direction: column; align-items: center; padding: 7px 0; border-top: 1px solid #f1f5f9; }
    .cover-info-row:last-child { border-bottom: 1px solid #f1f5f9; }
    .cover-info-lbl { font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; color: #94a3b8; }
    .cover-info-val { font-size: 11pt; font-weight: 600; text-align: center; }
    .cover-footer {
      position: absolute; bottom: 0; left: 0; right: 0;
      display: flex; justify-content: space-between; padding: 10px 14mm;
      font-size: 9pt; font-weight: 500;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }

    /* ── Photos ── */
    .ov-label { font-size: 8pt; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin: 8px 0 4px; }

    /* 4-across grid */
    .photo-grid { display: flex; flex-wrap: wrap; margin: 6px 0 10px; }
    .photo-unit { width: 25%; padding: 3px; }
    .photo-unit img {
      width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block;
      border: 1px solid #e2e8f0;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .photo-ref { font-size: 7pt; font-style: italic; color: #64748b; text-align: center; padding: 2px 0 4px; }

    /* Inline grid inside fixed section tables — 6-across, slightly smaller */
    .photo-grid--inline .photo-unit { width: 16.66%; }

    /* Timestamp overlay */
    .photo-wrap { position: relative; }
    .photo-ts {
      position: absolute; bottom: 0; left: 0; right: 0;
      text-align: center; font-size: 5.5pt; color: white;
      background: rgba(0,0,0,0.58); padding: 1px 2px;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }

    /* ── Declaration ── */
    .decl-body  { padding: 8px 0; }
    .decl-text  { font-size: 9pt; line-height: 1.7; margin-bottom: 44px; }
    .decl-sigs  { display: flex; gap: 40px; }
    .decl-sig-block { flex: 1; }
    .decl-sig-label { font-size: 9pt; font-weight: 700; margin-bottom: 50px; }
    .decl-sig-line  { border-bottom: 1px solid #374151; margin-bottom: 14px; }
    .decl-field {
      display: flex; align-items: center; gap: 12px;
      font-size: 8.5pt; color: #475569; margin-bottom: 22px;
    }
    .decl-field-line { flex: 1; border-bottom: 1px solid #cbd5e1; }

    /* ── Print colour enforcement ── */
    @media print {
      body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    }
  `

  const addr = e(pr.address || insp.property_address || '')
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>${e(typeLabel.value)} — ${addr}</title>
  <style>${css}</style>
</head>
<body>${body}</body>
</html>`
}
</script>

<template>
  <div class="pdf-overlay" @click.self="emit('close')">
    <div class="pdf-modal">

      <div class="pdf-modal-hdr">
        <div class="pdf-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          Export Report PDF
        </div>
        <button class="close-btn" @click="emit('close')">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>

      <div class="pdf-modal-body">

        <!-- Settings at a glance -->
        <div class="settings-card">
          <div class="sc-row">
            <span class="sc-lbl">Brand colour</span>
            <span class="sc-val">
              <span class="color-dot" :style="{ background: brandColor }"></span>
              {{ brandColor }}
            </span>
          </div>
          <div class="sc-row">
            <span class="sc-lbl">Header text</span>
            <span class="sc-val">
              <span class="color-dot" :style="{ background: headerTextColor, border: '1px solid #cbd5e1' }"></span>
              {{ headerTextColor }}
            </span>
          </div>
          <div class="sc-row">
            <span class="sc-lbl">Body text</span>
            <span class="sc-val">
              <span class="color-dot" :style="{ background: bodyTextColor, border: '1px solid #cbd5e1' }"></span>
              {{ bodyTextColor }}
            </span>
          </div>
          <div class="sc-row">
            <span class="sc-lbl">Orientation</span>
            <span class="sc-val">{{ orientation === 'landscape' ? 'Landscape' : 'Portrait' }}</span>
          </div>
          <div class="sc-row">
            <span class="sc-lbl">Overview photos</span>
            <span class="sc-val">{{ photoRoomOverview === 'above' ? 'Above data' : 'Below data' }}</span>
          </div>
          <div class="sc-row">
            <span class="sc-lbl">Item photos</span>
            <span class="sc-val">{{ photoRoomItem === 'above' ? 'Above data' : photoRoomItem === 'hyperlink' ? 'Hyperlink only' : 'Below data' }}</span>
          </div>
          <div class="sc-row" v-if="isCheckOut && actionsSummary.length">
            <span class="sc-lbl">Action summary</span>
            <span class="sc-val">{{ actionSummaryPos === 'top' ? 'Top of report' : actionSummaryPos === 'bottom' ? 'Bottom of report' : 'Not included' }}</span>
          </div>
          <div class="sc-note">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            Settings configured per-client in Settings → Reports
          </div>
        </div>

        <!-- Section list -->
        <div class="section-list">
          <div class="sl-hdr">Report structure</div>
          <div class="sl-chips">
            <span class="chip chip--front">Cover</span>
            <span class="chip chip--front">Contents</span>
            <span v-if="client.report_disclaimer" class="chip chip--front">Disclaimers</span>
            <span v-if="isCheckOut && actionSummaryPos === 'top' && actionsSummary.length" class="chip chip--action">Action Summary ↑</span>
            <span v-for="s in fixedSections" :key="s.id" class="chip chip--fixed">{{ s.name }}</span>
            <span v-for="r in rooms" :key="r.id" class="chip chip--room">{{ r.name }}</span>
            <span v-if="isCheckOut && actionSummaryPos === 'bottom' && actionsSummary.length" class="chip chip--action">Action Summary ↓</span>
            <span class="chip chip--front">Declaration</span>
          </div>
        </div>

      </div>

      <div class="pdf-modal-ftr">
        <button class="btn-cancel" @click="emit('close')">Cancel</button>
        <button class="btn-print" @click="printReport">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
          Print / Save as PDF
        </button>
      </div>

    </div>
  </div>
</template>

<style scoped>
.pdf-overlay {
  position: fixed; inset: 0; background: rgba(15,23,42,0.7);
  z-index: 9000; display: flex; align-items: center; justify-content: center;
}

.pdf-modal {
  background: white; border-radius: 12px; width: 460px; max-width: 95vw;
  box-shadow: 0 20px 60px rgba(0,0,0,0.3);
  display: flex; flex-direction: column; overflow: hidden;
}

.pdf-modal-hdr {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid #f1f5f9;
}

.pdf-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 15px; font-weight: 700; color: #1e293b;
}

.close-btn {
  width: 28px; height: 28px; border: none; background: #f1f5f9;
  border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: #64748b; transition: background 0.15s;
}
.close-btn:hover { background: #e2e8f0; }

.pdf-modal-body { padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }

/* Settings card */
.settings-card {
  background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 7px;
}
.sc-row { display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
.sc-lbl { color: #64748b; }
.sc-val { font-weight: 600; color: #1e293b; display: flex; align-items: center; gap: 6px; }
.color-dot { width: 12px; height: 12px; border-radius: 50%; border: 1px solid rgba(0,0,0,0.1); flex-shrink: 0; }
.sc-note {
  display: flex; align-items: center; gap: 5px;
  font-size: 11px; color: #94a3b8; padding-top: 8px; margin-top: 2px; border-top: 1px solid #e5e7eb;
}

/* Section list */
.sl-hdr { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 7px; }
.sl-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip { padding: 3px 9px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.chip--front  { background: #f1f5f9; color: #475569; }
.chip--fixed  { background: #dbeafe; color: #1e40af; }
.chip--room   { background: #ede9fe; color: #5b21b6; }
.chip--action { background: #fef3c7; color: #92400e; }

.pdf-modal-ftr {
  padding: 14px 20px; border-top: 1px solid #f1f5f9;
  display: flex; justify-content: flex-end; gap: 10px;
}

.btn-cancel {
  padding: 8px 18px; border: 1px solid #e5e7eb; background: white;
  border-radius: 7px; font-size: 13px; font-weight: 600; color: #64748b; cursor: pointer;
}
.btn-cancel:hover { background: #f8fafc; }

.btn-print {
  display: flex; align-items: center; gap: 7px;
  padding: 8px 20px; background: #0f172a; color: white;
  border: none; border-radius: 7px; font-size: 13px; font-weight: 700; cursor: pointer;
  transition: background 0.15s;
}
.btn-print:hover { background: #1e293b; }
</style>
