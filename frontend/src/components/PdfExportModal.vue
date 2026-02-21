<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  inspection: { type: Object, required: true },
  template:   { type: Object, default: null },
  reportData: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close'])

// ── Data helpers ──────────────────────────────────────────────────────────
const parsed = computed(() => {
  if (!props.template?.content) return { fixedSections: [], rooms: [] }
  try { return JSON.parse(props.template.content) } catch { return { fixedSections: [], rooms: [] } }
})

const fixedSections = computed(() => (parsed.value.fixedSections || []).filter(s => s.enabled !== false))
const rooms         = computed(() => (parsed.value.rooms        || []).filter(r => r.enabled !== false))
const isCheckOut    = computed(() => props.inspection.inspection_type === 'check_out')

function get(sectionId, rowId, field) {
  return props.reportData[sectionId]?.[String(rowId)]?.[field] ?? ''
}
function getExtra(sectionId) { return props.reportData[sectionId]?._extra ?? [] }

function getOrderedRoomItems(room) {
  const storedOrder = props.reportData[room.id]?._itemOrder
  const templateItems = (room.sections || []).map(i => ({ ...i, _type: 'template' }))
  const extraItems    = (props.reportData[room.id]?._extra || []).map(ex => ({
    ...ex, id: ex._eid, label: ex.label || '', _type: 'extra'
  }))
  const all = [...templateItems, ...extraItems]
  if (!storedOrder?.length) return all
  const ordered = []
  for (const id of storedOrder) {
    const found = all.find(i => String(i.id) === String(id) || String(i._eid) === String(id))
    if (found) ordered.push(found)
  }
  for (const item of all) {
    const key = item._type === 'extra' ? item._eid : String(item.id)
    if (!storedOrder.some(o => String(o) === key)) ordered.push(item)
  }
  return ordered
}

function isHidden(sectionId, rowId) {
  return props.reportData[sectionId]?._hidden?.includes(String(rowId)) ?? false
}
function isItemHidden(roomId, itemId) {
  return props.reportData[roomId]?._hiddenItems?.includes(String(itemId)) ?? false
}
function getItemActions(roomId, itemId) {
  return props.reportData[roomId]?.[`_actions_${itemId}`] ?? []
}

const typeLabel = computed(() => ({
  check_in:  'Check In Report',
  check_out: 'Check Out Report',
  interim:   'Interim Inspection Report',
  inventory: 'Inventory Report',
})[props.inspection.inspection_type] ?? 'Inspection Report')

const primaryColor = computed(() => props.inspection.client?.primary_color || '#1E3A8A')

const formattedDate = computed(() => {
  if (!props.inspection.conduct_date) return ''
  return new Date(props.inspection.conduct_date).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'long', year: 'numeric'
  })
})

const actionsSummary = computed(() => {
  const result = []
  for (const room of rooms.value) {
    for (const item of getOrderedRoomItems(room)) {
      const itemId = item._type === 'extra' ? item._eid : item.id
      if (isItemHidden(room.id, itemId)) continue
      for (const act of getItemActions(room.id, itemId)) {
        result.push({ room: room.name, item: item.label, ...act })
      }
    }
  }
  return result
})

const actionGroups = computed(() => {
  const groups = {}
  for (const a of actionsSummary.value) {
    if (!groups[a.actionName]) groups[a.actionName] = []
    groups[a.actionName].push(a)
  }
  return groups
})

// ─────────────────────────────────────────────────────────────────────────────
// buildReportHTML
// Generates a complete, self-contained HTML document for the report.
// This is written into a hidden iframe and printed from there — which means
// ONLY the report prints, never the surrounding web application.
// ─────────────────────────────────────────────────────────────────────────────
function buildReportHTML() {
  const brand  = primaryColor.value
  const insp   = props.inspection
  const client = insp.client   || {}
  const prop   = insp.property || {}

  // Escape HTML special chars
  function e(s) {
    if (s == null) return ''
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  // ── CSS — mirrors TemplatePreviewModal exactly ──────────────────────────
  const css = `
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
      font-size: 10pt; color: #1a1a1a; background: #fff;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }

    /* ── Every page except the cover gets padding and a page break ── */
    .page {
      page-break-after: always;
      padding: 12mm 14mm;
    }
    .page:last-child { page-break-after: auto; }

    /* ── Cover page — NO padding; sections are full-bleed ─────────── */
    .page-cover {
      page-break-after: always;
      display: flex;
      flex-direction: column;
      min-height: 297mm;
    }

    /* Full-bleed brand-colour top block — logo centred, badge bottom-left */
    .cover-top {
      background: ${brand};
      padding: 48px 56px 40px;
      display: flex;
      flex-direction: column;
      gap: 24px;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .cover-logo-wrap {
      display: flex;
      justify-content: center;
    }
    /* Real logo: full-width centred, auto height, no clipping */
    .cover-logo-img {
      width: 400px;
      max-width: 100%;
      height: auto;
      display: block;
      object-fit: contain;
    }
    /* Fallback initials when no logo */
    .cover-logo-fallback {
      width: 400px;
      max-width: 100%;
      height: 80px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .cover-logo-text {
      font-size: 32px; font-weight: 700;
      color: rgba(255,255,255,0.6);
      letter-spacing: -1px;
    }
    /* Inspection type badge — semi-transparent white pill, bottom-left */
    .cover-type-badge {
      display: inline-block;
      padding: 10px 20px;
      background: rgba(255,255,255,0.15);
      border: 1px solid rgba(255,255,255,0.3);
      border-radius: 6px;
      color: white;
      font-size: 15pt;
      font-weight: 400;
      font-family: Georgia, serif;
      letter-spacing: 0.5px;
      align-self: flex-start;
    }

    /* Property photo — full width, no side margins */
    .cover-photo-area {
      background: #f1f5f9;
      display: flex;
      align-items: center;
      justify-content: center;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .cover-photo-img {
      width: 100%;
      max-height: 320px;
      object-fit: cover;
      display: block;
    }
    .cover-photo-placeholder {
      width: 100%;
      min-height: 220px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      color: #94a3b8;
      font-size: 12pt;
    }

    /* Info grid — individual cell borders, matching Preview exactly */
    .cover-info-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      border-top: 2px solid ${brand};
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .cover-info-cell {
      padding: 18px 28px;
      border-right: 1px solid #e5e7eb;
      border-bottom: 1px solid #e5e7eb;
    }
    .cover-info-cell:nth-child(even) { border-right: none; }
    .cover-info-lbl {
      font-size: 8pt; font-weight: 700;
      text-transform: uppercase; letter-spacing: 1px;
      color: #94a3b8; margin-bottom: 4px;
    }
    .cover-info-val {
      font-size: 13pt; font-weight: 600; color: #1e293b;
    }

    /* Footer strip — brand colour, full bleed, white text */
    .cover-footer-strip {
      margin-top: auto;
      background: ${brand};
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 28px;
      font-size: 10pt;
      color: rgba(255,255,255,0.8);
      font-weight: 500;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }

    /* ── Section/room pages ─────────────────────────────────────────── */
    .section-hdr {
      background: ${brand}; color: #fff;
      padding: 8px 16px; font-size: 13pt; font-weight: 700;
      border-radius: 4px; margin-bottom: 14px;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .section-hdr-red { background: #dc2626 !important; }

    table { width: 100%; border-collapse: collapse; font-size: 9pt; }
    th {
      background: #f1f5f9;
      padding: 7px 10px; text-align: left;
      font-weight: 700; font-size: 8pt;
      text-transform: uppercase; letter-spacing: 0.3px;
      border-bottom: 2px solid #e2e8f0;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    td { padding: 7px 10px; vertical-align: top; border-bottom: 1px solid #f1f5f9; line-height: 1.45; }
    tr:last-child td { border-bottom: none; }
    tr:nth-child(even) td {
      background: #fafafa;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }

    .c-item  { width: 18%; font-weight: 600; color: #374151; }
    .c-desc  { width: 26%; }
    .c-cond  { width: 22%; }
    .c-co    { width: 20%; }
    .c-act   { width: 16%; }
    .c-orig  { color: #64748b; font-style: italic; }

    .action-tag {
      display: inline-block; padding: 2px 7px; border-radius: 8px;
      font-size: 7.5pt; font-weight: 600; margin: 2px 0; line-height: 1.5;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }
    .ref-num { font-weight: 700; color: ${brand}; }
    .resp-tag {
      background: #e0e7ff; color: #4338ca;
      padding: 1px 7px; border-radius: 6px;
      font-size: 8pt; font-weight: 600;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }

    .disclaimer-body { font-size: 10pt; line-height: 1.7; color: #374151; }

    .decl-body  { font-size: 10pt; line-height: 1.6; color: #374151; margin-bottom: 36px; }
    .sig-grid   { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; margin-top: 20px; }
    .sig-lbl    { font-size: 9pt; font-weight: 600; color: #64748b; margin-bottom: 6px; }
    .sig-line   { height: 30px; border-bottom: 1.5px solid #94a3b8; margin-bottom: 20px; }
    .sig-sub    { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 10px; }
    .sig-short  { height: 26px; border-bottom: 1.5px solid #94a3b8; }

    @page { size: A4 portrait; margin: 0; }
  `

  // ── Fixed section rows ─────────────────────────────────────────────────
  function fixedRows(section) {
    const t = section.type
    let thead = '', body = ''

    const rowData = (section.rows || []).filter(r => !isHidden(section.id, r.id))
    const extraData = getExtra(section.id)

    if (t === 'condition_summary') {
      thead = '<tr><th>Item</th><th>Condition</th></tr>'
      rowData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(get(section.id, r.id, 'condition') || r.condition) || '—'}</td></tr>` })
      extraData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(r.condition) || '—'}</td></tr>` })
    } else if (t === 'cleaning_summary') {
      thead = '<tr><th>Area</th><th>Cleanliness</th><th>Notes</th></tr>'
      rowData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(get(section.id, r.id, 'cleanliness')) || '—'}</td><td>${e(get(section.id, r.id, 'cleanlinessNotes')) || '—'}</td></tr>` })
      extraData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(r.cleanliness) || '—'}</td><td>${e(r.cleanlinessNotes) || '—'}</td></tr>` })
    } else if (t === 'keys') {
      thead = '<tr><th>Key / Item</th><th>Description / Qty</th></tr>'
      rowData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(get(section.id, r.id, 'description')) || '—'}</td></tr>` })
      extraData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(r.description) || '—'}</td></tr>` })
    } else if (t === 'meter_readings') {
      thead = '<tr><th>Meter</th><th>Location / Serial</th><th>Reading</th></tr>'
      rowData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(get(section.id, r.id, 'locationSerial')) || '—'}</td><td>${e(get(section.id, r.id, 'reading')) || '—'}</td></tr>` })
      extraData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(r.locationSerial) || '—'}</td><td>${e(r.reading) || '—'}</td></tr>` })
    } else if (['smoke_alarms', 'health_safety', 'fire_door_safety'].includes(t)) {
      const fd = t === 'fire_door_safety'
      thead = fd ? '<tr><th>Item</th><th>Question</th><th>Answer</th><th>Notes</th></tr>'
                 : '<tr><th>Question / Item</th><th>Answer</th><th>Notes</th></tr>'
      rowData.forEach(r => {
        body += `<tr>${fd ? `<td>${e(r.name)}</td>` : ''}<td>${e(r.question || r.name)}</td><td>${e(get(section.id, r.id, 'answer')) || '—'}</td><td>${e(get(section.id, r.id, 'notes')) || '—'}</td></tr>`
      })
      extraData.forEach(r => {
        body += `<tr>${fd ? `<td>${e(r.name)}</td>` : ''}<td>${e(r.question) || '—'}</td><td>${e(r.answer) || '—'}</td><td>${e(r.notes) || '—'}</td></tr>`
      })
    } else {
      thead = '<tr><th>Item</th><th>Details</th></tr>'
      rowData.forEach(r => { body += `<tr><td>${e(r.name)}</td><td>${e(get(section.id, r.id, 'condition') || get(section.id, r.id, 'description')) || '—'}</td></tr>` })
    }

    return `<div class="page">
      <div class="section-hdr">${e(section.name)}</div>
      <table><thead>${thead}</thead><tbody>${body}</tbody></table>
    </div>`
  }

  // ── Room section ───────────────────────────────────────────────────────
  function roomPage(room) {
    const items = getOrderedRoomItems(room)
    const co = isCheckOut.value

    const thead = co
      ? '<tr><th class="c-item">Item</th><th class="c-desc">Description</th><th class="c-cond">Condition at Check In</th><th class="c-co">Condition at Check Out</th><th class="c-act">Actions</th></tr>'
      : '<tr><th class="c-item">Item</th><th class="c-desc">Description</th><th class="c-cond">Condition</th></tr>'

    let body = ''
    for (const item of items) {
      const iid = item._type === 'extra' ? item._eid : item.id
      if (isItemHidden(room.id, iid)) continue
      const desc = item._type === 'template' ? get(room.id, item.id, 'description') : item.description

      if (co) {
        const inv = item._type === 'template'
          ? (get(room.id, item.id, 'inventoryCondition') || get(room.id, item.id, 'condition'))
          : item.inventoryCondition
        const coC = item._type === 'template'
          ? (get(room.id, item.id, 'checkOutCondition') || 'As Inventory &amp; Check In')
          : (item.checkOutCondition || 'As Inventory &amp; Check In')

        const acts = getItemActions(room.id, iid)
        const actHTML = acts.map(a => {
          const bg = (a.actionColor || '#666') + '22'
          const fg = a.actionColor || '#666'
          const bd = (a.actionColor || '#666') + '55'
          return `<span class="action-tag" style="background:${bg};color:${fg};border:1px solid ${bd}">${e(a.actionName)}<br><small>${e(a.responsibility)}</small></span>`
        }).join(' ')

        body += `<tr>
          <td class="c-item">${e(item.label)}</td>
          <td class="c-desc">${e(desc) || '—'}</td>
          <td class="c-cond c-orig">${e(inv) || '—'}</td>
          <td class="c-co">${e(coC)}</td>
          <td class="c-act">${actHTML}</td>
        </tr>`
      } else {
        const cond = item._type === 'template' ? get(room.id, item.id, 'condition') : item.condition
        body += `<tr>
          <td class="c-item">${e(item.label)}</td>
          <td class="c-desc">${e(desc) || '—'}</td>
          <td class="c-cond">${e(cond) || '—'}</td>
        </tr>`
      }
    }

    return `<div class="page">
      <div class="section-hdr">${e(room.name)}</div>
      <table><thead>${thead}</thead><tbody>${body}</tbody></table>
    </div>`
  }

  // ── Actions summary (Check Out only) ──────────────────────────────────
  function actionsPages() {
    if (!isCheckOut.value || !actionsSummary.value.length) return ''
    let html = ''
    for (const [group, acts] of Object.entries(actionGroups.value)) {
      let rows = ''
      acts.forEach((a, i) => {
        rows += `<tr>
          <td class="ref-num">${i + 1}</td>
          <td>${e(a.room)} › ${e(a.item)}</td>
          <td><span class="resp-tag">${e(a.responsibility)}</span></td>
          <td>${e(a.checkOutCondition) || '—'}</td>
          <td>${e(a.note) || '—'}</td>
        </tr>`
      })
      html += `<div class="page">
        <div class="section-hdr section-hdr-red">${e(group)}</div>
        <table>
          <thead><tr><th>Ref</th><th>Room › Item</th><th>Responsibility</th><th>Check Out Condition</th><th>Note</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`
    }
    return html
  }

  // ── Cover — mirrors TemplatePreviewModal's cover-page structure exactly ──
  // Full-bleed brand top: logo centred + large, type badge bottom-left
  // Full-width property photo below
  // Info grid with individual cell borders (matching Preview)
  // Brand-colour footer strip full-bleed at bottom

  const logoInner = client.logo
    ? `<img src="${e(client.logo)}" class="cover-logo-img" alt="Logo">`
    : `<div class="cover-logo-fallback"><span class="cover-logo-text">${e((client.name || 'IN').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase())}</span></div>`

  const photoInner = prop.overview_photo
    ? `<img src="${e(prop.overview_photo)}" class="cover-photo-img" alt="Property">`
    : `<div class="cover-photo-placeholder">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <circle cx="8.5" cy="8.5" r="1.5"/>
          <polyline points="21 15 16 10 5 21"/>
        </svg>
        <span>Property overview photo</span>
      </div>`

  // Build info cells — always show these four, plus optional extras
  const infoCells = [
    { lbl: 'Property Address', val: prop.address || insp.property_address },
    { lbl: 'Inspection Date',  val: formattedDate.value || 'Not set' },
    { lbl: 'Inspector',        val: insp.inspector?.name || '—' },
    { lbl: 'Reference',        val: insp.reference || `CHK-${new Date().getFullYear()}-${String(insp.id).padStart(4,'0')}` },
  ]
  if (insp.typist)  infoCells.push({ lbl: 'Typist',  val: insp.typist.name })
  if (client.name)  infoCells.push({ lbl: 'Client',  val: client.name })

  // Pad to even number of cells so grid stays symmetrical
  if (infoCells.length % 2 !== 0) infoCells.push({ lbl: '', val: '' })

  const infoGridHTML = infoCells.map(c =>
    `<div class="cover-info-cell">
      <div class="cover-info-lbl">${e(c.lbl)}</div>
      <div class="cover-info-val">${e(c.val)}</div>
    </div>`
  ).join('')

  const cover = `<div class="page-cover">

    <!-- ① Full-bleed brand-colour top: logo + type badge -->
    <div class="cover-top">
      <div class="cover-logo-wrap">${logoInner}</div>
      <div class="cover-type-badge">${e(typeLabel.value)}</div>
    </div>

    <!-- ② Property photo — full width -->
    <div class="cover-photo-area">${photoInner}</div>

    <!-- ③ Info grid with cell borders -->
    <div class="cover-info-grid">${infoGridHTML}</div>

    <!-- ④ Brand-colour footer strip -->
    <div class="cover-footer-strip">
      <span>Prepared by ${e(client.company || client.name || 'L&amp;M Inventories')}</span>
      <span>Confidential</span>
    </div>

  </div>`

  // ── Disclaimer ────────────────────────────────────────────────────────
  const disclaimer = client.report_disclaimer
    ? `<div class="page"><div class="section-hdr">Disclaimer</div><div class="disclaimer-body">${e(client.report_disclaimer)}</div></div>`
    : ''

  // ── Declaration ───────────────────────────────────────────────────────
  const declaration = `<div class="page">
    <div class="section-hdr">Declaration</div>
    <p class="decl-body">I/We the undersigned, affirm that if I/we do not comment on the Inventory in writing within seven days of receipt of this Inventory then I/we accept the Inventory as being an accurate record of the contents and condition of the property.</p>
    <div class="sig-grid">
      <div>
        <p class="sig-lbl">Signed by the Tenant(s)</p>
        <div class="sig-line"></div>
        <div class="sig-sub">
          <div><p class="sig-lbl">Print Name</p><div class="sig-short"></div></div>
          <div><p class="sig-lbl">Date</p><div class="sig-short"></div></div>
        </div>
      </div>
      <div>
        <p class="sig-lbl">Signed by the Agent / Landlord</p>
        <div class="sig-line"></div>
        <div class="sig-sub">
          <div><p class="sig-lbl">Print Name</p><div class="sig-short"></div></div>
          <div><p class="sig-lbl">Date</p><div class="sig-short"></div></div>
        </div>
      </div>
    </div>
  </div>`

  // ── Assemble ──────────────────────────────────────────────────────────
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${e(typeLabel.value)} — ${e(prop.address || '')}</title>
  <style>${css}</style>
</head>
<body>
  ${cover}
  ${disclaimer}
  ${fixedSections.value.map(fixedRows).join('')}
  ${rooms.value.map(roomPage).join('')}
  ${actionsPages()}
  ${declaration}
</body>
</html>`
}

// ─────────────────────────────────────────────────────────────────────────────
// triggerPrint — injects a hidden iframe, writes the report HTML into it,
// and calls iframe.contentWindow.print().
//
// WHY IFRAME INSTEAD OF POPUP WINDOW:
//   • popup.print() in Chrome/Edge also triggers window.print() on the opener
//     page — printing the whole web app alongside the report.
//   • iframe.contentWindow.print() is guaranteed to print ONLY the iframe.
//   • No popup-blocker issues; no race condition between onload and print.
// ─────────────────────────────────────────────────────────────────────────────
const printing = ref(false)

async function triggerPrint() {
  if (printing.value) return
  printing.value = true

  await nextTick()

  const html = buildReportHTML()

  // 1. Create invisible iframe
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  iframe.style.cssText = 'position:fixed;top:0;left:-9999px;width:210mm;height:297mm;border:0;'
  document.body.appendChild(iframe)

  // 2. Write the complete HTML document into it
  const doc = iframe.contentDocument || iframe.contentWindow.document
  doc.open()
  doc.write(html)
  doc.close()

  // 3. Wait for all images inside the iframe to finish loading
  await new Promise(resolve => {
    const imgs = Array.from(doc.querySelectorAll('img'))
    if (!imgs.length) return resolve()
    let pending = imgs.length
    const done = () => { if (--pending <= 0) resolve() }
    imgs.forEach(img => {
      if (img.complete) done()
      else { img.onload = done; img.onerror = done }
    })
    setTimeout(resolve, 5000) // safety net
  })

  // 4. Print ONLY the iframe — never touches the parent page
  iframe.contentWindow.focus()
  iframe.contentWindow.print()

  // 5. Clean up after the print dialog closes
  setTimeout(() => {
    try { document.body.removeChild(iframe) } catch {}
    printing.value = false
  }, 2000)
}

function handleKeydown(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', handleKeydown))
onUnmounted(() => document.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <div class="pdf-overlay" @click.self="$emit('close')">
    <div class="pdf-modal">

      <div class="pdf-modal-header">
        <div>
          <h2>Export Report as PDF</h2>
          <p>Prints only the report — not the web page.</p>
        </div>
        <button class="btn-close" @click="$emit('close')">✕</button>
      </div>

      <div class="pdf-preview-info">
        <div class="info-row"><span class="info-lbl">Property</span><span>{{ inspection.property?.address || inspection.property_address }}</span></div>
        <div class="info-row"><span class="info-lbl">Type</span><span>{{ typeLabel }}</span></div>
        <div class="info-row"><span class="info-lbl">Date</span><span>{{ formattedDate || 'Not set' }}</span></div>
        <div class="info-row"><span class="info-lbl">Clerk</span><span>{{ inspection.inspector?.name || '—' }}</span></div>
        <div class="info-row"><span class="info-lbl">Sections</span><span>{{ fixedSections.length }} fixed + {{ rooms.length }} rooms</span></div>
      </div>

      <div class="pdf-tips">
        <strong>💡 Tips for best output</strong>
        <ul>
          <li>Set <strong>Destination → Save as PDF</strong></li>
          <li>Layout: <strong>Portrait</strong>, paper: <strong>A4</strong></li>
          <li>Enable <strong>Background graphics</strong> for coloured section headers</li>
          <li>Margins: <strong>Default</strong> or <strong>Minimum</strong></li>
        </ul>
      </div>

      <div class="pdf-modal-footer">
        <button class="btn-cancel" @click="$emit('close')">Cancel</button>
        <button class="btn-print" :disabled="printing" @click="triggerPrint">
          <span v-if="printing">⏳ Preparing…</span>
          <span v-else>🖨&nbsp;&nbsp;Print / Save as PDF</span>
        </button>
      </div>

    </div>
  </div>
</template>

<style scoped>
.pdf-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 9000;
  display: flex; align-items: center; justify-content: center;
}
.pdf-modal {
  background: white; border-radius: 16px;
  padding: 32px; width: 520px; max-width: 95vw;
  box-shadow: 0 25px 60px rgba(0,0,0,0.3);
}
.pdf-modal-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px;
}
.pdf-modal-header h2 { font-size: 20px; font-weight: 700; color: #1e293b; }
.pdf-modal-header p  { font-size: 13px; color: #64748b; margin-top: 4px; }

.btn-close {
  background: none; border: none; font-size: 18px; cursor: pointer;
  color: #94a3b8; padding: 4px 8px; border-radius: 6px; flex-shrink: 0;
}
.btn-close:hover { background: #f1f5f9; color: #475569; }

.pdf-preview-info {
  background: #f8fafc; border: 1px solid #e2e8f0;
  border-radius: 10px; padding: 16px; margin-bottom: 20px;
}
.info-row {
  display: flex; gap: 12px; font-size: 13px;
  padding: 5px 0; border-bottom: 1px solid #f1f5f9;
}
.info-row:last-child { border-bottom: none; }
.info-lbl { font-weight: 600; color: #64748b; width: 80px; flex-shrink: 0; }

.pdf-tips {
  background: #fffbeb; border: 1px solid #fde68a;
  border-radius: 10px; padding: 16px; font-size: 13px;
  margin-bottom: 24px;
}
.pdf-tips strong { display: block; margin-bottom: 8px; color: #92400e; }
.pdf-tips ul { padding-left: 18px; color: #78350f; line-height: 1.8; }

.pdf-modal-footer { display: flex; justify-content: flex-end; gap: 12px; }

.btn-cancel {
  padding: 9px 20px; background: white;
  border: 1px solid #e5e7eb; border-radius: 8px;
  font-size: 14px; font-weight: 600; color: #64748b; cursor: pointer;
}
.btn-cancel:hover { background: #f8fafc; }

.btn-print {
  padding: 9px 24px; background: #1e3a8a; border: none;
  border-radius: 8px; font-size: 14px; font-weight: 700;
  color: white; cursor: pointer; min-width: 170px;
  transition: background 0.15s;
}
.btn-print:hover:not(:disabled) { background: #1e40af; }
.btn-print:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
