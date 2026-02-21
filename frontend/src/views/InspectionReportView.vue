<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import api from '../services/api'
import CheckOutActionPicker from '../components/CheckOutActionPicker.vue'

// v-click-outside directive (registered inline for this component)
const vClickOutside = {
  mounted(el, binding) {
    el._clickOutside = e => { if (!el.contains(e.target)) binding.value(e) }
    document.addEventListener('mousedown', el._clickOutside)
  },
  unmounted(el) { document.removeEventListener('mousedown', el._clickOutside) }
}

const route  = useRoute()
const router = useRouter()
const toast  = useToast()

const inspection   = ref(null)
const template     = ref(null)
const loading      = ref(true)
const saving       = ref(false)
const lastSaved    = ref(null)
const unsaved      = ref(false)
const activeId     = ref(null)
const showPhotoModal = ref(false)
const photoUploading = ref(false)
const currentPhoto   = ref(null)

// Drag state
const dragFixedFrom = ref(null)
const dragRoomFrom  = ref(null)

const reportData = ref({})

// ── Load ──────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const iRes = await api.getInspection(route.params.id)
    inspection.value = iRes.data

    const iType = inspection.value.inspection_type
    const isCheckOutType = iType === 'check_out'

    if (isCheckOutType) {
      // ── CHECK OUT: build structure from source Check In ────────────────
      // Find source: use saved link or auto-detect from property history
      let sourceId = inspection.value.source_inspection_id
      if (!sourceId) {
        try {
          const histRes = await api.getPropertyHistory(inspection.value.property_id)
          const found = histRes.data.find(h =>
            h.id !== inspection.value.id &&
            ['check_in', 'inventory'].includes(h.inspection_type)
            // any check in qualifies — even without saved data, we can use its template structure
          )
          if (found) {
            sourceId = found.id
            // Persist the link
            await api.updateInspection(inspection.value.id, { source_inspection_id: sourceId })
            inspection.value.source_inspection_id = sourceId
          }
        } catch { /* silent */ }
      }

      if (sourceId) {
        try {
          const srcRes = await api.getInspection(sourceId)
          const srcData = srcRes.data
          // Load template from source inspection
          if (srcData.template_id) {
            const tRes = await api.getTemplate(srcData.template_id)
            template.value = tRes.data
          } else {
            // Source has no template — fall back to any available template
            try {
              const allTRes = await api.getTemplates()
              const fallback = allTRes.data.find(t => t.is_default) || allTRes.data[0]
              if (fallback) template.value = fallback
            } catch { /* no templates */ }
          }
          // Store Check In's report_data as read-only reference for CO columns
          if (srcData.report_data) {
            try { sourceReportData.value = JSON.parse(srcData.report_data) } catch { sourceReportData.value = {} }
          }
        } catch { /* source gone */ }
      }

      // Load this Check Out's own saved data (checkout conditions + actions only)
      if (inspection.value.report_data) {
        try {
          reportData.value = JSON.parse(inspection.value.report_data)
          // Restore imported source data if previously imported from PDF
          if (reportData.value._importedSource && Object.keys(sourceReportData.value).length === 0) {
            sourceReportData.value = reportData.value._importedSource
          }
        } catch { reportData.value = {} }
      }

    } else {
      // ── CHECK IN / INVENTORY / INTERIM: normal template-based flow ─────
      if (inspection.value.template_id) {
        const tRes = await api.getTemplate(inspection.value.template_id)
        template.value = tRes.data
      }
      if (inspection.value.report_data) {
        try { reportData.value = JSON.parse(inspection.value.report_data) } catch { reportData.value = {} }
      }
    }

    if (inspection.value.property_id) {
      try {
        const pRes = await api.getProperty(inspection.value.property_id)
        currentPhoto.value = pRes.data.overview_photo || null
      } catch {}
    }
  } catch {
    toast.error('Failed to load inspection')
    router.push('/inspections')
  } finally {
    loading.value = false
    await nextTick()
    if (allSections.value[0]) activeId.value = allSections.value[0].id
  }
}

// Source Check In data (read-only reference for Check Out)
const sourceReportData = ref({})

// ── PDF Import state (used when no Check In source is found) ──────────
const pdfImport = ref({
  show:     false,
  file:     null,
  fileName: '',
  loading:  false,
  error:    '',
  preview:  null,
  applied:  false,
})

async function onPdfSelected(e) {
  const file = e.target?.files?.[0] || e.dataTransfer?.files?.[0]
  if (!file) return
  if (file.type !== 'application/pdf') { pdfImport.value.error = 'Please upload a PDF file'; return }
  pdfImport.value.file     = file
  pdfImport.value.fileName = file.name
  pdfImport.value.error    = ''
  pdfImport.value.preview  = null
  pdfImport.value.applied  = false
}

async function runPdfImport() {
  if (!pdfImport.value.file) return
  pdfImport.value.loading = true
  pdfImport.value.error   = ''
  pdfImport.value.preview = null

  try {
    const base64 = await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload  = e => resolve(e.target.result.split(',')[1])
      reader.onerror = reject
      reader.readAsDataURL(pdfImport.value.file)
    })

    const templateStructure = template.value ? JSON.stringify({
      fixedSections: (template.value.sections || [])
        .filter(s => !s.is_room)
        .map(s => ({ id: s.id, name: s.name, type: s.type, rows: (s.rows || []).map(r => ({ id: r.id, name: r.name || r.question })) })),
      rooms: (template.value.sections || [])
        .filter(s => s.is_room)
        .map(r => ({ id: r.id, name: r.name, items: (r.sections || r.items || []).map(i => ({ id: i.id, label: i.label })) }))
    }, null, 2) : 'No template — infer structure from PDF'

    const prompt = `You are parsing a UK property inspection report PDF (inventory or check-in) to extract structured data for a Check Out system.

Template structure available to match against:
${templateStructure}

Extract ALL rooms and items. For each item:
- label: the item name
- description: physical description of the item
- condition: condition at time of check-in

PDF format is typically: [Room.Item] [Item Name] [Description] [Condition at Check In] [Condition at Check Out]

Return ONLY valid JSON — no markdown, no explanation:
{
  "rooms": [
    {
      "name": "Lounge",
      "items": [
        { "label": "Door, Frame, Threshold & Furniture", "description": "White painted panel door with chrome handle", "condition": "Appears in good condition" }
      ]
    }
  ],
  "fixedSections": {
    "condition_summary": [{ "name": "General Condition", "condition": "Good overall" }],
    "keys": [{ "name": "Front Door Key", "description": "2x Yale, 1x Deadlock" }],
    "meter_readings": [{ "name": "Gas Meter", "locationSerial": "Under stairs SN123", "reading": "12345.6" }],
    "cleaning_summary": [{ "name": "General Cleanliness", "cleanliness": "Professionally Cleaned", "cleanlinessNotes": "" }]
  }
}`

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model:      'claude-opus-4-6',
        max_tokens: 8000,
        messages: [{
          role:    'user',
          content: [
            { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: base64 } },
            { type: 'text',     text:   prompt }
          ]
        }]
      })
    })

    if (!response.ok) {
      const errBody = await response.text()
      throw new Error(`API ${response.status}: ${errBody.slice(0, 200)}`)
    }
    const apiData = await response.json()
    const rawText = (apiData.content || []).map(b => b.text || '').join('')
    const clean   = rawText.replace(/```json[\s\S]*?```|```[\s\S]*?```/g, s => s.replace(/```json|```/g, '')).trim()
    const parsed  = JSON.parse(clean)
    pdfImport.value.preview = parsed
  } catch (err) {
    console.error('PDF import error:', err)
    pdfImport.value.error = 'Import failed: ' + err.message
  } finally {
    pdfImport.value.loading = false
  }
}

async function applyPdfImport() {
  const parsed = pdfImport.value.preview
  if (!parsed) return

  // Ensure we have a template
  if (!template.value) {
    try {
      const allTRes = await api.getTemplates()
      const fallback = allTRes.data.find(t => t.is_default) || allTRes.data[0]
      if (fallback) template.value = fallback
    } catch { /* silent */ }
  }

  const built = {}
  const templateRooms = (template.value?.sections || []).filter(s => s.is_room)
  const templateFixed = (template.value?.sections || []).filter(s => !s.is_room)

  // Map imported rooms → template room IDs (fuzzy name match)
  for (const importedRoom of (parsed.rooms || [])) {
    const match = templateRooms.find(r =>
      r.name.toLowerCase().replace(/\s+/g,'').includes(importedRoom.name.toLowerCase().replace(/\s+/g,'')) ||
      importedRoom.name.toLowerCase().replace(/\s+/g,'').includes(r.name.toLowerCase().replace(/\s+/g,''))
    )
    const roomId = match?.id || ('imp_rm_' + importedRoom.name.replace(/[^a-z0-9]/gi,'_').toLowerCase())
    built[roomId] = {}
    const tItems = match?.sections || match?.items || []
    for (const imp of (importedRoom.items || [])) {
      const matchItem = tItems.find(i => {
        const a = (i.label || '').toLowerCase().replace(/[^a-z0-9]/g,'')
        const b = imp.label.toLowerCase().replace(/[^a-z0-9]/g,'')
        return a.includes(b) || b.includes(a)
      })
      const itemId = matchItem?.id || ('imp_it_' + imp.label.replace(/[^a-z0-9]/gi,'_').toLowerCase())
      built[roomId][String(itemId)] = {
        description: imp.description || '',
        condition:   imp.condition   || '',
      }
    }
  }

  // Map fixed sections by type
  for (const [type, rows] of Object.entries(parsed.fixedSections || {})) {
    const sec = templateFixed.find(s => s.type === type)
    if (!sec || !Array.isArray(rows)) continue
    built[sec.id] = {}
    for (const [i, row] of rows.entries()) {
      const templateRow = sec.rows?.[i]
      const rowId = templateRow?.id || ('imp_fx_' + i)
      built[sec.id][String(rowId)] = { ...row }
    }
  }

  sourceReportData.value = built
  // Persist so it survives page reload
  reportData.value._importedSource = built
  unsaved.value = true
  await save(false)

  pdfImport.value.applied = true
  pdfImport.value.show    = false
  const roomCount = (parsed.rooms || []).length
  const itemCount = (parsed.rooms || []).reduce((s, r) => s + (r.items || []).length, 0)
  toast.success(`Imported ${roomCount} rooms, ${itemCount} items from PDF`)
}

// ── Check In photo viewer (for Check Out clerks) ──────────────────────
const ciPhotoViewer = ref({ show: false, photos: [], index: 0, label: '' })
function openCIPhotos(roomId, itemId, itemLabel) {
  const id = String(itemId)
  const photos = sourceReportData.value[roomId]?.[id]?.photos || []
  if (!photos.length) { toast.warning('No Check In photos for this item'); return }
  ciPhotoViewer.value = { show: true, photos, index: 0, label: itemLabel }
}
function ciPhotoNext() {
  if (ciPhotoViewer.value.index < ciPhotoViewer.value.photos.length - 1)
    ciPhotoViewer.value.index++
}
function ciPhotoPrev() {
  if (ciPhotoViewer.value.index > 0) ciPhotoViewer.value.index--
}

// ── Inline photo panels ──────────────────────────────────────────────────
// openPanels: Set of "sectionId:rowId" strings whose photo panel is expanded
const openPanels = ref(new Set())
function photoKey(sectionId, rowId) { return `${sectionId}:${String(rowId)}` }
function isPanelOpen(sectionId, rowId) { return openPanels.value.has(photoKey(sectionId, rowId)) }
function togglePanel(sectionId, rowId) {
  const k = photoKey(sectionId, rowId)
  const s = new Set(openPanels.value)
  if (s.has(k)) s.delete(k); else s.add(k)
  openPanels.value = s
}
function getPhotos(sectionId, rowId) {
  return reportData.value[sectionId]?.[String(rowId)]?._photos || []
}
function addPhotos(sectionId, rowId, files) {
  const sid = sectionId, rid = String(rowId)
  if (!reportData.value[sid]) reportData.value[sid] = {}
  if (!reportData.value[sid][rid]) reportData.value[sid][rid] = {}
  if (!reportData.value[sid][rid]._photos) reportData.value[sid][rid]._photos = []
  for (const file of files) {
    if (file.size > 10 * 1024 * 1024) { toast.error(`${file.name} exceeds 10MB`); continue }
    const reader = new FileReader()
    reader.onload = ev => {
      reportData.value[sid][rid]._photos.push(ev.target.result)
      unsaved.value = true
    }
    reader.readAsDataURL(file)
  }
}
function removePhoto(sectionId, rowId, idx) {
  reportData.value[sectionId]?.[String(rowId)]?._photos?.splice(idx, 1)
  unsaved.value = true
}

// ── Item numbering ─────────────────────────────────────────────────────
// Rooms are numbered from 1 upward (matching fixed sections count before rooms).
// Items within a room are numbered 1, 2, 3… Photo refs: e.g. "3.2.1"
const roomIndexMap = computed(() => {
  const map = {}
  rooms.value.forEach((r, i) => { map[r.id] = i + 1 })
  return map
})
function itemRef(roomId, orderedItems, itemKey) {
  const rn = roomIndexMap.value[roomId] ?? '?'
  const idx = orderedItems.findIndex(i => {
    const k = i._type === 'extra' ? i._eid : String(i.id)
    return k === String(itemKey)
  })
  return `${rn}.${idx >= 0 ? idx + 1 : '?'}`
}

// ── Fixed section numbering (A.1, A.2 … B.1, B.2 …) ─────────────────
// Letters for fixed sections; numbers for rooms — visually distinct at a glance.
const SECTION_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
const fixedSectionIndexMap = computed(() => {
  const map = {}
  fixedSections.value.forEach((s, i) => { map[s.id] = SECTION_LETTERS[i] ?? String(i + 1) })
  return map
})

// Returns "A.3"-style ref for any fixed-section row (template or extra).
function fixedRowRef(sec, rowId) {
  const letter = fixedSectionIndexMap.value[sec.id] ?? '?'
  const visibleRows = (sec.rows || []).filter(r => !isHidden(sec.id, r.id))
  const ti = visibleRows.findIndex(r => String(r.id) === String(rowId))
  if (ti >= 0) return letter + '.' + (ti + 1)
  const extras = getExtra(sec.id)
  const ei = extras.findIndex(e => e._eid === rowId)
  if (ei >= 0) return letter + '.' + (visibleRows.length + ei + 1)
  return letter + '.?'
}

// Full label used in recordings/photo panels: "A.3 · Condition Summary — Walls"
function fixedItemLabel(sec, rowId, rowName) {
  return fixedRowRef(sec, rowId) + ' · ' + sec.name + ' — ' + rowName
}

// ── Photo viewer (per item, all inspection types) ────────────────────
// Reads photos from reportData[roomId][itemId].photos — populated by mobile app later.
// This is a placeholder: shows "no photos" gracefully until photos exist.
const photoViewer = ref({ show: false, photos: [], index: 0, ref: '', label: '' })
function getItemPhotos(roomId, itemId) {
  return reportData.value[roomId]?.[String(itemId)]?.photos || []
}
function openItemPhotos(ref, label, photos, startIndex = 0) {
  if (!photos.length) return
  photoViewer.value = { show: true, photos, index: startIndex, ref, label }
}
function photoViewerNext() { if (photoViewer.value.index < photoViewer.value.photos.length - 1) photoViewer.value.index++ }
function photoViewerPrev() { if (photoViewer.value.index > 0) photoViewer.value.index-- }
// Open lightbox at a specific thumbnail index — called from inline photo panels
function openLightbox(sectionId, rowId, index) {
  const photos = getPhotos(sectionId, rowId)
  if (!photos.length) return
  photoViewer.value = { show: true, photos, index, ref: '', label: '' }
}

// Check In condition read-only getter — reads from the source Check In's saved report_data
function getCI(sectionId, rowId, field) {
  return sourceReportData.value[sectionId]?.[String(rowId)]?.[field] ?? ''
}

// ── Parse template ────────────────────────────────────────────────────
const parsed = computed(() => {
  if (!template.value?.content) return { fixedSections: [], rooms: [] }
  try { return JSON.parse(template.value.content) } catch { return { fixedSections: [], rooms: [] } }
})

const fixedSections = computed(() => (parsed.value.fixedSections || []).filter(s => s.enabled !== false))
const rooms         = computed(() => (parsed.value.rooms || []).filter(r => r.enabled !== false))
const allSections   = computed(() => [...fixedSections.value, ...rooms.value])

// ── Template row data ─────────────────────────────────────────────────
function get(sectionId, rowId, field) {
  return reportData.value[sectionId]?.[String(rowId)]?.[field] ?? ''
}
function set(sectionId, rowId, field, value) {
  const sid = sectionId, rid = String(rowId)
  if (!reportData.value[sid]) reportData.value[sid] = {}
  if (!reportData.value[sid][rid]) reportData.value[sid][rid] = {}
  reportData.value[sid][rid][field] = value
  unsaved.value = true
}

// ── Hide template rows ────────────────────────────────────────────────
function isHidden(sectionId, rowId) {
  return reportData.value[sectionId]?._hidden?.includes(String(rowId)) ?? false
}
function hideRow(sectionId, rowId) {
  const sid = sectionId, rid = String(rowId)
  if (!reportData.value[sid]) reportData.value[sid] = {}
  if (!reportData.value[sid]._hidden) reportData.value[sid]._hidden = []
  if (!reportData.value[sid]._hidden.includes(rid)) reportData.value[sid]._hidden.push(rid)
  unsaved.value = true
}
const hasHidden = (sid) => (reportData.value[sid]?._hidden?.length ?? 0) > 0

// ── Hide room items ───────────────────────────────────────────────────
function isItemHidden(roomId, itemId) {
  return reportData.value[roomId]?._hiddenItems?.includes(String(itemId)) ?? false
}
function hideItem(roomId, itemId) {
  const rid = String(itemId)
  if (!reportData.value[roomId]) reportData.value[roomId] = {}
  if (!reportData.value[roomId]._hiddenItems) reportData.value[roomId]._hiddenItems = []
  if (!reportData.value[roomId]._hiddenItems.includes(rid)) reportData.value[roomId]._hiddenItems.push(rid)
  unsaved.value = true
}

// ── Ordered room items (template items + extras, respecting stored order) ──
function getOrderedRoomItems(room) {
  const storedOrder = reportData.value[room.id]?._itemOrder
  const templateItems = (room.sections || []).map(item => ({ ...item, _type: 'template' }))
  const extraItems = (reportData.value[room.id]?._extra || []).map(ex => ({
    ...ex, id: ex._eid, label: ex.label || 'New item', _type: 'extra'
  }))
  const all = [...templateItems, ...extraItems]

  if (!storedOrder || storedOrder.length === 0) return all

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

function saveRoomItemOrder(roomId, orderedItems) {
  if (!reportData.value[roomId]) reportData.value[roomId] = {}
  reportData.value[roomId]._itemOrder = orderedItems.map(i => i._type === 'extra' ? i._eid : String(i.id))
  unsaved.value = true
}

// ── Extra rows (fixed sections) ───────────────────────────────────────
function getExtra(sectionId) { return reportData.value[sectionId]?._extra ?? [] }
function setExtraField(sectionId, eid, field, value) {
  if (!reportData.value[sectionId]) reportData.value[sectionId] = {}
  if (!reportData.value[sectionId]._extra) reportData.value[sectionId]._extra = []
  const row = reportData.value[sectionId]._extra.find(r => r._eid === eid)
  if (row) row[field] = value
  unsaved.value = true
}
function addExtraRow(sectionId, type) {
  if (!reportData.value[sectionId]) reportData.value[sectionId] = {}
  if (!reportData.value[sectionId]._extra) reportData.value[sectionId]._extra = []
  const eid = `ex_${Date.now()}_${Math.random().toString(36).slice(2,6)}`
  const blank = { _eid: eid }
  if (type === 'condition_summary')     { blank.name=''; blank.condition='' }
  else if (type === 'cleaning_summary') { blank.name=''; blank.cleanliness=''; blank.cleanlinessNotes='' }
  else if (type === 'smoke_alarms' || type === 'health_safety') { blank.question=''; blank.answer=''; blank.notes='' }
  else if (type === 'fire_door_safety') { blank.name=''; blank.question=''; blank.answer=''; blank.notes='' }
  else if (type === 'keys')             { blank.name=''; blank.description='' }
  else if (type === 'meter_readings')   { blank.name=''; blank.locationSerial=''; blank.reading='' }
  reportData.value[sectionId]._extra.push(blank)
  unsaved.value = true
}
function removeExtraRow(sectionId, eid) {
  if (!reportData.value[sectionId]?._extra) return
  reportData.value[sectionId]._extra = reportData.value[sectionId]._extra.filter(r => r._eid !== eid)
  unsaved.value = true
}

// ── Room extra items ──────────────────────────────────────────────────
function addRoomExtraItem(roomId) {
  if (!reportData.value[roomId]) reportData.value[roomId] = {}
  if (!reportData.value[roomId]._extra) reportData.value[roomId]._extra = []
  const eid = `rex_${Date.now()}_${Math.random().toString(36).slice(2,6)}`
  reportData.value[roomId]._extra.push({ _eid: eid, label: '', description: '', condition: '' })
  if (reportData.value[roomId]._itemOrder) reportData.value[roomId]._itemOrder.push(eid)
  unsaved.value = true
}
function setRoomExtraField(roomId, eid, field, value) {
  if (!reportData.value[roomId]) reportData.value[roomId] = {}
  if (!reportData.value[roomId]._extra) reportData.value[roomId]._extra = []
  const row = reportData.value[roomId]._extra.find(r => r._eid === eid)
  if (row) row[field] = value
  unsaved.value = true
}
function removeRoomExtraItem(roomId, eid) {
  if (!reportData.value[roomId]?._extra) return
  reportData.value[roomId]._extra = reportData.value[roomId]._extra.filter(r => r._eid !== eid)
  if (reportData.value[roomId]._itemOrder) {
    reportData.value[roomId]._itemOrder = reportData.value[roomId]._itemOrder.filter(o => o !== eid)
  }
  unsaved.value = true
}

// ── Sub-items ─────────────────────────────────────────────────────────
function getSubs(roomId, itemId) { return reportData.value[roomId]?.[itemId]?._subs ?? [] }
function setSubField(roomId, itemId, sid, field, value) {
  if (!reportData.value[roomId]) reportData.value[roomId] = {}
  if (!reportData.value[roomId][itemId]) reportData.value[roomId][itemId] = {}
  if (!reportData.value[roomId][itemId]._subs) reportData.value[roomId][itemId]._subs = []
  const sub = reportData.value[roomId][itemId]._subs.find(s => s._sid === sid)
  if (sub) sub[field] = value
  unsaved.value = true
}
function addSubItem(roomId, itemId) {
  if (!reportData.value[roomId]) reportData.value[roomId] = {}
  if (!reportData.value[roomId][itemId]) reportData.value[roomId][itemId] = {}
  if (!reportData.value[roomId][itemId]._subs) reportData.value[roomId][itemId]._subs = []
  const sid = `sub_${Date.now()}_${Math.random().toString(36).slice(2,6)}`
  reportData.value[roomId][itemId]._subs.push({ _sid: sid, description: '', condition: '' })
  unsaved.value = true
}
function removeSubItem(roomId, itemId, sid) {
  if (!reportData.value[roomId]?.[itemId]?._subs) return
  reportData.value[roomId][itemId]._subs = reportData.value[roomId][itemId]._subs.filter(s => s._sid !== sid)
  unsaved.value = true
}


function getItemActions(roomId, itemId) {
  const key = `_actions_${itemId}`
  return reportData.value[roomId]?.[key] ?? []
}
function setItemActions(roomId, itemId, actions) {
  const key = `_actions_${itemId}`
  if (!reportData.value[roomId]) reportData.value[roomId] = {}
  reportData.value[roomId][key] = actions
  unsaved.value = true
}

// ── Drag to reorder (fixed section extra rows) ────────────────────────
function onFixedDragStart(sectionId, idx) {
  dragFixedFrom.value = { sectionId, idx }
}
function onFixedDrop(sectionId, toIdx) {
  if (!dragFixedFrom.value || dragFixedFrom.value.sectionId !== sectionId) return
  const extra = reportData.value[sectionId]._extra
  const from  = dragFixedFrom.value.idx
  if (from === toIdx) return
  const [moved] = extra.splice(from, 1)
  extra.splice(toIdx, 0, moved)
  dragFixedFrom.value = null
  unsaved.value = true
}

// ── Drag to reorder (room items) ──────────────────────────────────────
function onRoomDragStart(roomId, idx) { dragRoomFrom.value = { roomId, idx } }
function onRoomDrop(room, toIdx) {
  if (!dragRoomFrom.value || dragRoomFrom.value.roomId !== room.id) return
  const items = getOrderedRoomItems(room)
  const from  = dragRoomFrom.value.idx
  if (from === toIdx) return
  const [moved] = items.splice(from, 1)
  items.splice(toIdx, 0, moved)
  saveRoomItemOrder(room.id, items)
  dragRoomFrom.value = null
}

// ── Property photo ────────────────────────────────────────────────────
function onPhotoFileChange(e) {
  const file = e.target.files[0]
  if (!file) return
  if (file.size > 8 * 1024 * 1024) { toast.error('Photo must be under 8MB'); return }
  const reader = new FileReader()
  reader.onload = (ev) => { currentPhoto.value = ev.target.result }
  reader.readAsDataURL(file)
}
async function savePhoto() {
  if (!inspection.value?.property_id) return
  photoUploading.value = true
  try {
    await api.updateProperty(inspection.value.property_id, { overview_photo: currentPhoto.value })
    toast.success('Property photo saved')
    showPhotoModal.value = false
  } catch { toast.error('Failed to save photo') }
  finally { photoUploading.value = false }
}

// ── Save report ───────────────────────────────────────────────────────
async function save(feedback = true) {
  saving.value = true
  try {
    await api.updateInspection(inspection.value.id, { report_data: JSON.stringify(reportData.value) })
    unsaved.value = false
    lastSaved.value = new Date()
    if (feedback) toast.success('Report saved')
  } catch { toast.error('Save failed — please try again') }
  finally { saving.value = false }
}

let timer = null
onMounted(() => { load(); timer = setInterval(() => { if (unsaved.value && !saving.value) save(false) }, 90000) })
onBeforeUnmount(() => clearInterval(timer))

async function exit() { if (unsaved.value) await save(false); router.push(`/inspections/${route.params.id}`) }
function scrollTo(id) { activeId.value = id; document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
function onScroll(e) {
  const top = e.target.scrollTop
  for (let i = allSections.value.length - 1; i >= 0; i--) {
    const el = document.getElementById(`sec-${allSections.value[i].id}`)
    if (el && el.offsetTop - top <= 140) { activeId.value = allSections.value[i].id; break }
  }
}

const cleanlinessOpts = [
  'Professionally Cleaned',
  'Professionally Cleaned — Receipt Seen',
  'Professionally Cleaned with Omissions',
  'Domestically Cleaned',
  'Domestically Cleaned with Omissions',
  'Not Clean'
]

const typeLabel  = computed(() => ({ check_in:'Check In', check_out:'Check Out', interim:'Interim Inspection', inventory:'Inventory' })[inspection.value?.inspection_type] ?? '')
const isCheckOut = computed(() => inspection.value?.inspection_type === 'check_out')
const savedTime  = computed(() => lastSaved.value ? lastSaved.value.toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit' }) : null)

function sectionStarted(sectionId) {
  const d = reportData.value[sectionId]
  if (!d) return false
  return Object.values(d).some(row => row && typeof row === 'object' && Object.values(row).some(v => v !== '' && v != null))
}
const startedCount = computed(() => allSections.value.filter(s => sectionStarted(s.id)).length)
// ═══════════════════════════════════════════════════════════════════════
// AUDIO MODULE
// Recording shape: { id, blob, url, duration, createdAt, label,
//   itemKey, transcript, gptResult }
// itemKey = "sectionId:rowId" — null for general recordings.
// transcript / gptResult are null until Whisper/GPT integrated.
// ═══════════════════════════════════════════════════════════════════════

// ── State ─────────────────────────────────────────────────────────────
const audioModule = ref({
  expanded: true,
  mode:     'idle', // 'idle' | 'recording' | 'playing' | 'paused'
})

// Active recorder — shared for both general + per-item recording
const activeRecorder    = ref(null)
const recordingChunks   = ref([])
const recordingSeconds  = ref(0)
let   recordingTimer    = null

// itemRecordingKey = "sectionId:rowId" while recording an item; null for general/idle
const itemRecordingKey  = ref(null)

// All recordings — shape: { id, blob, url, duration, createdAt, label, itemKey, transcript, gptResult }
const recordings = ref([])
const activeRec  = ref(null)

// Playback
const audioEl       = ref(null)
const playbackTime  = ref(0)
const playbackSpeed = ref(1)
const speedOptions  = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2]
const showSpeedMenu = ref(false)
const showRecMenu   = ref(false)
const audioDuration = ref(0)

// ── Helpers ───────────────────────────────────────────────────────────
function fmtTime(secs) {
  const s = Math.floor(secs || 0)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
function itemRecKey(sid, rid) { return `${sid}:${String(rid)}` }
function isItemRecording(sid, rid) { return itemRecordingKey.value === itemRecKey(sid, rid) }
function getItemRecordings(sid, rid) {
  const k = itemRecKey(sid, rid)
  return recordings.value.filter(r => r.itemKey === k)
}

// ── Core record/stop ──────────────────────────────────────────────────
async function _startRecording(label, itemKey = null) {
  // Stop any in-progress recording first — guard against null
  if (activeRecorder.value && activeRecorder.value.state !== 'inactive') {
    activeRecorder.value.stop()
    await new Promise(r => setTimeout(r, 120))
  }

  let stream = null
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (err) {
    toast.error('Microphone access denied — please allow mic in browser settings')
    console.error('getUserMedia failed:', err)
    return
  }

  try {
    const mr = new MediaRecorder(stream)
    activeRecorder.value   = mr
    recordingChunks.value  = []
    recordingSeconds.value = 0
    itemRecordingKey.value = itemKey
    audioModule.value.mode = 'recording'

    mr.ondataavailable = e => { if (e.data.size > 0) recordingChunks.value.push(e.data) }

    mr.onstop = () => {
      stream.getTracks().forEach(t => t.stop())
      if (recordingChunks.value.length === 0) return // nothing recorded
      const blob = new Blob(recordingChunks.value, { type: mr.mimeType || 'audio/webm' })
      const url  = URL.createObjectURL(blob)
      const existing = itemKey ? recordings.value.filter(r => r.itemKey === itemKey).length : 0
      const rec = {
        id:         Date.now(),
        blob, url,
        mimeType:   mr.mimeType,
        duration:   recordingSeconds.value,
        createdAt:  new Date(),
        label:      existing > 0 ? `${label} (${existing + 1})` : label,
        itemKey,
        transcript: null,
        gptResult:  null,
      }
      recordings.value.push(rec)
      loadRecording(rec, false)
      audioModule.value.mode = 'idle'
      itemRecordingKey.value = null
    }

    mr.onerror = (e) => {
      console.error('MediaRecorder error:', e)
      toast.error('Recording error — please try again')
      stream.getTracks().forEach(t => t.stop())
      audioModule.value.mode = 'idle'
      itemRecordingKey.value = null
    }

    mr.start(250)
    clearInterval(recordingTimer)
    recordingTimer = setInterval(() => recordingSeconds.value++, 1000)
  } catch (err) {
    console.error('MediaRecorder setup failed:', err)
    toast.error('Could not start recording — please try again')
    stream?.getTracks().forEach(t => t.stop())
    audioModule.value.mode = 'idle'
    itemRecordingKey.value = null
  }
}

function _stopRecording() {
  clearInterval(recordingTimer)
  recordingTimer = null
  if (activeRecorder.value && activeRecorder.value.state !== 'inactive') {
    activeRecorder.value.stop()
  }
  audioModule.value.mode = 'idle'
  itemRecordingKey.value = null
}

// General record button (footer bar)
function toggleGeneralRecording() {
  if (audioModule.value.mode === 'recording') {
    _stopRecording()
  } else {
    const n = recordings.value.filter(r => !r.itemKey).length
    _startRecording(n === 0 ? 'General Recording' : `General Recording ${n + 1}`, null)
  }
}

// Per-item mic button — called from every item type
async function toggleItemRecording(sid, rid, label) {
  const key = itemRecKey(sid, rid)
  if (itemRecordingKey.value === key) {
    _stopRecording()
  } else {
    await _startRecording(label, key)
  }
}

// ── Playback ──────────────────────────────────────────────────────────
function loadRecording(rec, autoPlay = false) {
  activeRec.value    = rec
  playbackTime.value = 0
  audioDuration.value = rec.duration
  if (!autoPlay) audioModule.value.mode = 'idle'
  nextTick(() => {
    if (!audioEl.value) return
    audioEl.value.src         = rec.url
    audioEl.value.playbackRate = playbackSpeed.value
    audioEl.value.ontimeupdate     = () => { playbackTime.value = audioEl.value.currentTime }
    audioEl.value.onloadedmetadata = () => { audioDuration.value = audioEl.value.duration }
    audioEl.value.onended = () => {
      const idx  = recordings.value.findIndex(r => r.id === activeRec.value?.id)
      const next = recordings.value[idx + 1]
      if (next) { loadRecording(next, true) }
      else { audioModule.value.mode = 'idle' }
    }
    if (autoPlay) { audioEl.value.play(); audioModule.value.mode = 'playing' }
  })
}

function togglePlay() {
  if (!audioEl.value) return
  if (!activeRec.value && recordings.value.length) loadRecording(recordings.value[0], true)
  else if (audioModule.value.mode === 'playing') { audioEl.value.pause(); audioModule.value.mode = 'paused' }
  else { audioEl.value.play(); audioModule.value.mode = 'playing' }
}

function seekAudio(e) {
  if (!audioEl.value || !audioDuration.value) return
  const rect = e.currentTarget.getBoundingClientRect()
  const pct  = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  audioEl.value.currentTime = pct * audioDuration.value
  playbackTime.value = audioEl.value.currentTime
}

function setSpeed(s) {
  playbackSpeed.value = s
  if (audioEl.value) audioEl.value.playbackRate = s
  showSpeedMenu.value = false
}

function deleteRecording(rec) {
  URL.revokeObjectURL(rec.url)
  recordings.value = recordings.value.filter(r => r.id !== rec.id)
  if (activeRec.value?.id === rec.id) { activeRec.value = null; audioModule.value.mode = 'idle' }
}

// ── Grouped recordings for dropdown ──────────────────────────────────
const groupedRecordings = computed(() => {
  const groups = []
  const seen   = new Map()
  for (const rec of recordings.value) {
    const key = rec.itemKey || '__general__'
    if (!seen.has(key)) { seen.set(key, []); groups.push({ key, items: seen.get(key) }) }
    seen.get(key).push(rec)
  }
  return groups
})

function groupDisplayLabel(group) {
  if (group.key === '__general__') return 'General'
  // Use the base label of the first recording (strip trailing " (N)")
  const base = group.items[0]?.label || ''
  return base.replace(/ \(\d+\)$/, '')
}

// Close dropdown on outside click
function onRecMenuOutside() { showRecMenu.value = false }

// Clean up
onBeforeUnmount(() => {
  recordings.value.forEach(r => URL.revokeObjectURL(r.url))
  clearInterval(recordingTimer)
  if (activeRecorder.value && activeRecorder.value.state !== 'inactive') {
    activeRecorder.value.stop()
  }
})


</script>

<template>
  <div v-if="loading" class="loading-screen"><div class="ring"></div><p>Loading report…</p></div>

  <div v-else-if="inspection" class="shell">

    <header class="topbar">
      <div class="topbar-l">
        <button class="back-btn" @click="exit">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="15 18 9 12 15 6"/></svg>
          Overview
        </button>
        <div class="crumbs">
          <span class="crumb-addr">{{ inspection.property_address }}</span>
          <span class="crumb-dot">·</span>
          <span class="crumb-type">{{ typeLabel }}</span>
          <template v-if="inspection.inspector_name">
            <span class="crumb-dot">·</span>
            <span class="crumb-who">{{ inspection.inspector_name }}</span>
          </template>
        </div>
      </div>
      <div class="topbar-r">
        <div v-if="allSections.length" class="prog">
          <div class="prog-track"><div class="prog-fill" :style="{ width: `${Math.round(startedCount/allSections.length*100)}%` }"></div></div>
          <span class="prog-lbl">{{ startedCount }}/{{ allSections.length }}</span>
        </div>
        <button class="photo-btn" @click="showPhotoModal = true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          {{ currentPhoto ? 'Edit Photo' : 'Add Photo' }}
        </button>
        <span v-if="saving" class="chip chip-saving"><svg class="spin-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>Saving</span>
        <span v-else-if="savedTime && !unsaved" class="chip chip-saved"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Saved {{ savedTime }}</span>
        <span v-else-if="unsaved" class="chip chip-unsaved">● Unsaved</span>
        <button class="save-btn" :disabled="saving" @click="save()">Save</button>
      </div>
    </header>



    <div class="body">
      <nav class="sidebar">
        <div v-if="template">
          <div v-if="fixedSections.length" class="nav-grp">
            <p class="nav-lbl">Report Sections</p>
            <button v-for="s in fixedSections" :key="s.id" class="nav-btn" :class="{ active: activeId===s.id }" @click="scrollTo(s.id)">
              <span class="dot" :class="{ done: sectionStarted(s.id) }"></span><span class="nav-sec-letter">{{ fixedSectionIndexMap[s.id] }}</span>{{ s.name }}
            </button>
          </div>
          <div v-if="rooms.length" class="nav-grp">
            <p class="nav-lbl">Rooms</p>
            <button v-for="r in rooms" :key="r.id" class="nav-btn" :class="{ active: activeId===r.id }" @click="scrollTo(r.id)">
              <span class="dot" :class="{ done: sectionStarted(r.id) }"></span>{{ r.name }}
            </button>
          </div>
        </div>
        <div v-else class="sidebar-warn">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <p>No Check In report found for this property.</p>
        </div>
      </nav>

      <main class="main" @scroll="onScroll">
        <div v-if="!template && inspection.inspection_type !== 'check_out'" class="empty-state">
          <h3>No template assigned</h3>
          <p>This inspection has no template assigned. Go back and assign one.</p>
          <button class="btn-ghost" @click="router.push(`/inspections/${inspection.id}`)">← Back to Overview</button>
        </div>

        <!-- No source Check In found — offer PDF import -->
        <div v-if="!template && inspection.inspection_type === 'check_out'" class="pdf-import-shell">
          <div class="pdf-import-card">

            <div class="pdf-import-icon">📄</div>
            <h2 class="pdf-import-title">No linked Check In found</h2>
            <p class="pdf-import-sub">Import a Check In / Inventory report from another system to use as the reference for this Check Out.</p>

            <!-- Drop zone -->
            <label class="pdf-dropzone"
              :class="{ 'pdf-dropzone-has': pdfImport.fileName, 'pdf-dropzone-loading': pdfImport.loading }"
              @dragover.prevent
              @drop.prevent="onPdfSelected">
              <div v-if="!pdfImport.fileName" class="pdf-dz-inner">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
                <p>Drop PDF here or <span class="pdf-dz-link">browse</span></p>
                <p class="pdf-dz-hint">Check In or Inventory report from any system</p>
              </div>
              <div v-else class="pdf-dz-inner pdf-dz-has">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <p class="pdf-dz-name">{{ pdfImport.fileName }}</p>
                <p class="pdf-dz-hint">Click to choose a different file</p>
              </div>
              <input type="file" accept="application/pdf" style="display:none" @change="onPdfSelected" />
            </label>

            <!-- Error -->
            <p v-if="pdfImport.error" class="pdf-error">⚠ {{ pdfImport.error }}</p>

            <!-- Preview of parsed data -->
            <div v-if="pdfImport.preview" class="pdf-preview">
              <div class="pdf-preview-hd">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                Parsed successfully
              </div>
              <div class="pdf-preview-stats">
                <span class="pdf-stat">
                  <strong>{{ (pdfImport.preview.rooms || []).length }}</strong> rooms
                </span>
                <span class="pdf-stat">
                  <strong>{{ (pdfImport.preview.rooms || []).reduce((s, r) => s + (r.items || []).length, 0) }}</strong> items
                </span>
                <span v-for="(rows, type) in (pdfImport.preview.fixedSections || {})" :key="type" class="pdf-stat">
                  <strong>{{ rows.length }}</strong> {{ type.replace(/_/g, ' ') }}
                </span>
              </div>
              <!-- Room list preview -->
              <div class="pdf-preview-rooms">
                <div v-for="room in (pdfImport.preview.rooms || [])" :key="room.name" class="pdf-preview-room">
                  <strong>{{ room.name }}</strong>
                  <span class="pdf-room-count">{{ (room.items || []).length }} items</span>
                  <ul class="pdf-room-items">
                    <li v-for="item in (room.items || []).slice(0,4)" :key="item.label">
                      <span class="pdf-item-label">{{ item.label }}</span>
                      <span class="pdf-item-cond">{{ item.condition }}</span>
                    </li>
                    <li v-if="(room.items || []).length > 4" class="pdf-more">+ {{ (room.items || []).length - 4 }} more…</li>
                  </ul>
                </div>
              </div>
            </div>

            <!-- Actions -->
            <div class="pdf-import-actions">
              <button class="btn-ghost" @click="router.push(`/inspections/${inspection.id}`)">← Back</button>
              <button v-if="!pdfImport.preview" class="btn-pdf-parse"
                :disabled="!pdfImport.file || pdfImport.loading"
                @click="runPdfImport">
                <template v-if="pdfImport.loading">
                  <svg class="spin-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
                  Analysing PDF…
                </template>
                <template v-else>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                  Analyse PDF
                </template>
              </button>
              <template v-if="pdfImport.preview">
                <button class="btn-ghost" @click="pdfImport.preview = null; pdfImport.file = null; pdfImport.fileName = ''">
                  Try different file
                </button>
                <button class="btn-pdf-apply" @click="applyPdfImport">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                  Use this data
                </button>
              </template>
            </div>

          </div>
        </div>

        <div v-if="template">

          <!-- ═══ FIXED SECTIONS ═══════════════════════════════════ -->
          <div v-for="sec in fixedSections" :key="sec.id" :id="`sec-${sec.id}`" class="card">
            <div class="card-hd">
              <h2 class="card-title">
                <span class="sec-letter-badge">{{ fixedSectionIndexMap[sec.id] }}</span>
                {{ sec.name }}
              </h2>
              <div class="card-hd-right">
                <span v-if="hasHidden(sec.id)" class="hidden-badge">{{ reportData[sec.id]?._hidden?.length }} hidden</span>
                <span class="card-hint">{{ sec.rows?.length || 0 }} items</span>
              </div>
            </div>

            <!-- CONDITION SUMMARY -->
            <div v-if="sec.type === 'condition_summary'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Item</th><th>Condition</th><th class="col-cam"></th><th class="col-cam"></th><th class="col-del"></th></tr></thead>
                <tbody>
                  <template v-for="row in sec.rows" :key="row.id">
                    <tr v-show="!isHidden(sec.id, row.id)">
                      <td class="td-drag"><span class="drag-handle" title="Drag to reorder">⠿</span></td>
                      <td class="td-name"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.name }}</td>
                      <td><input class="fld-input" type="text" placeholder="Describe condition…" :value="get(sec.id,row.id,'condition')" @input="set(sec.id,row.id,'condition',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" :title="getPhotos(sec.id,row.id).length + ' photo(s)'"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'cam-has mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length }" @click="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record audio for this item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row">
                      <td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td>
                    </tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" placeholder="Item name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><input class="fld-input" type="text" placeholder="Describe condition…" :value="ex.condition" @input="setExtraField(sec.id,ex._eid,'condition',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" :title="getPhotos(sec.id,ex._eid).length + ' photo(s)'"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row">
                      <td colspan="5" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td>
                    </tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- CLEANING SUMMARY -->
            <div v-else-if="sec.type === 'cleaning_summary'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Area</th><th class="col-clean">Cleanliness</th><th>Notes</th><th class="col-cam"></th><th class="col-del"></th></tr></thead>
                <tbody>
                  <template v-for="row in sec.rows" :key="row.id">
                    <tr v-show="!isHidden(sec.id, row.id)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-name"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.name }}</td>
                      <td><select class="fld-input" :value="get(sec.id,row.id,'cleanliness')" @change="set(sec.id,row.id,'cleanliness',$event.target.value)"><option value="">Select…</option><option v-for="o in cleanlinessOpts" :key="o" :value="o">{{ o }}</option></select></td>
                      <td><input class="fld-input" type="text" placeholder="Additional notes…" :value="get(sec.id,row.id,'cleanlinessNotes')" @input="set(sec.id,row.id,'cleanlinessNotes',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" placeholder="Area name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><select class="fld-input" :value="ex.cleanliness" @change="setExtraField(sec.id,ex._eid,'cleanliness',$event.target.value)"><option value="">Select…</option><option v-for="o in cleanlinessOpts" :key="o" :value="o">{{ o }}</option></select></td>
                      <td><input class="fld-input" type="text" placeholder="Notes…" :value="ex.cleanlinessNotes" @input="setExtraField(sec.id,ex._eid,'cleanlinessNotes',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- KEYS -->
            <div v-else-if="sec.type === 'keys'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Key / Fob</th><th>Description / Quantity</th><th class="col-cam"></th><th class="col-del"></th></tr></thead>
                <tbody>
                  <template v-for="row in sec.rows" :key="row.id">
                    <tr v-show="!isHidden(sec.id, row.id)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-name"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.name }}</td>
                      <td><input class="fld-input" type="text" placeholder="e.g. 2 × Yale keys" :value="get(sec.id,row.id,'description')" @input="set(sec.id,row.id,'description',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="5" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" placeholder="Key name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><input class="fld-input" type="text" placeholder="Description…" :value="ex.description" @input="setExtraField(sec.id,ex._eid,'description',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="5" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- SMOKE ALARMS / HEALTH & SAFETY -->
            <div v-else-if="sec.type === 'smoke_alarms' || sec.type === 'health_safety'">
              <template v-for="row in sec.rows" :key="row.id">
                <div v-show="!isHidden(sec.id, row.id)" class="qa-row">
                  <div class="qa-row-header">
                    <span class="qa-question"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.question }}</span>
                    <button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button>
                    <button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.question))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button>
                    <button class="del-btn" @click="hideRow(sec.id,row.id)">×</button>
                  </div>
                  <p v-if="row.guidance" class="qa-guidance">{{ row.guidance }}</p>
                  <div class="qa-controls">
                    <select class="fld-input" style="width:180px" :value="get(sec.id,row.id,'answer')" @change="set(sec.id,row.id,'answer',$event.target.value)">
                      <option value="">Select…</option>
                      <option>Yes</option><option>No</option><option>N/A</option><option>Not Tested</option>
                    </select>
                    <input class="fld-input" style="flex:1" type="text" placeholder="Additional notes…" :value="get(sec.id,row.id,'notes')" @input="set(sec.id,row.id,'notes',$event.target.value)" />
                  </div>
                  <div v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-inline"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div>
                </div>
              </template>
              <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                <div class="qa-row extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                  <div class="qa-extra-header">
                    <span class="drag-handle">⠿</span>
                    <span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span>
                    <input class="fld-input" type="text" placeholder="Question…" :value="ex.question" @input="setExtraField(sec.id,ex._eid,'question',$event.target.value)" />
                    <button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button>
                    <button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.question||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button>
                    <button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button>
                  </div>
                  <div class="qa-controls">
                    <select class="fld-input" style="width:180px" :value="ex.answer" @change="setExtraField(sec.id,ex._eid,'answer',$event.target.value)">
                      <option value="">Select…</option>
                      <option>Yes</option><option>No</option><option>N/A</option><option>Not Tested</option>
                    </select>
                    <input class="fld-input" style="flex:1" type="text" placeholder="Notes…" :value="ex.notes" @input="setExtraField(sec.id,ex._eid,'notes',$event.target.value)" />
                  </div>
                  <div v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-inline"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div>
                </div>
              </template>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- FIRE DOOR SAFETY -->
            <div v-else-if="sec.type === 'fire_door_safety'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Door / Location</th><th>Question / Check</th><th style="width:140px">Answer</th><th>Notes</th><th class="col-cam"></th><th class="col-del"></th></tr></thead>
                <tbody>
                  <template v-for="row in sec.rows" :key="row.id">
                    <tr v-show="!isHidden(sec.id, row.id)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-name"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.name }}</td>
                      <td>{{ row.question }}</td>
                      <td><select class="fld-input" :value="get(sec.id,row.id,'answer')" @change="set(sec.id,row.id,'answer',$event.target.value)"><option value="">Select…</option><option>Yes</option><option>No</option><option>N/A</option></select></td>
                      <td><input class="fld-input" type="text" placeholder="Notes…" :value="get(sec.id,row.id,'notes')" @input="set(sec.id,row.id,'notes',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="7" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" placeholder="Door name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><input class="fld-input" type="text" placeholder="Check…" :value="ex.question" @input="setExtraField(sec.id,ex._eid,'question',$event.target.value)" /></td>
                      <td><select class="fld-input" :value="ex.answer" @change="setExtraField(sec.id,ex._eid,'answer',$event.target.value)"><option value="">Select…</option><option>Yes</option><option>No</option><option>N/A</option></select></td>
                      <td><input class="fld-input" type="text" placeholder="Notes…" :value="ex.notes" @input="setExtraField(sec.id,ex._eid,'notes',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="7" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- METER READINGS -->
            <div v-else-if="sec.type === 'meter_readings'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Meter</th><th>Location & Serial No.</th><th class="col-reading">Reading</th><th class="col-cam"></th><th class="col-del"></th></tr></thead>
                <tbody>
                  <template v-for="row in sec.rows" :key="row.id">
                    <tr v-show="!isHidden(sec.id, row.id)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-name"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.name }}</td>
                      <td><input class="fld-input" type="text" placeholder="e.g. Understairs cupboard — SN 123456" :value="get(sec.id,row.id,'locationSerial')" @input="set(sec.id,row.id,'locationSerial',$event.target.value)" /></td>
                      <td><input class="fld-input fld-mono" type="text" placeholder="e.g. 12345.6" :value="get(sec.id,row.id,'reading')" @input="set(sec.id,row.id,'reading',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" placeholder="Meter name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><input class="fld-input" type="text" placeholder="Location & serial…" :value="ex.locationSerial" @input="setExtraField(sec.id,ex._eid,'locationSerial',$event.target.value)" /></td>
                      <td><input class="fld-input fld-mono" type="text" placeholder="Reading…" :value="ex.reading" @input="setExtraField(sec.id,ex._eid,'reading',$event.target.value)" /></td>
                      <td class="td-cam"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-cam"><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button></td>
                      <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <div v-else class="unknown-type">Unknown section type: {{ sec.type }}</div>
          </div>

          <!-- ═══ ROOMS ═════════════════════════════════════════════ -->
          <div v-for="(room, roomIdx) in rooms" :key="room.id" :id="`sec-${room.id}`" class="card card-room">
            <div class="card-hd card-hd-room">
              <h2 class="card-title">
                <span class="room-number">{{ roomIndexMap[room.id] }}.</span>
                {{ room.name }}
              </h2>
              <div class="card-hd-right">
                <span v-if="isCheckOut" class="co-badge">Check Out</span>
                <span class="card-hint">{{ room.sections?.length || 0 }} items</span>
              </div>
            </div>

            <!-- ── Room Overview Photos ──────────────────────────────── -->
            <div class="room-overview-strip">
              <div class="room-overview-header">
                <span class="room-overview-lbl">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                  Room Overview Photos
                </span>
                <label class="ph-upload-btn ph-upload-btn-sm">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                  Upload
                  <input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(room.id,'_overview',e.target.files)" />
                </label>
              </div>
              <div v-if="getPhotos(room.id,'_overview').length" class="room-overview-thumbs">
                <div v-for="(ph,pi) in getPhotos(room.id,'_overview')" :key="pi" class="ph-thumb ph-thumb-lg" style="cursor:pointer" @click="openLightbox(room.id,'_overview',pi)">
                  <img :src="ph" class="ph-img-click" />
                  <button class="ph-del" @click="removePhoto(room.id,'_overview',pi)">×</button>
                </div>
              </div>
              <p v-else class="room-overview-empty">No overview photos yet — upload above or use the mobile app</p>
            </div>

            <!-- All items (template + extra) in drag-sortable order -->
            <div
              v-for="(item, idx) in getOrderedRoomItems(room)"
              :key="item._type === 'extra' ? item._eid : item.id"
              class="room-row"
              draggable="true"
              @dragstart="onRoomDragStart(room.id, idx)"
              @dragover.prevent
              @drop.prevent="onRoomDrop(room, idx)"
            >
              <!-- Label column — with item ref number + mic -->
              <div class="room-row-label">
                <span class="drag-handle drag-handle-room">⠿</span>
                <span class="item-ref-num">{{ itemRef(room.id, getOrderedRoomItems(room), item._type === 'extra' ? item._eid : item.id) }}</span>
                <template v-if="item._type === 'extra'">
                  <input class="fld-input label-input" type="text" placeholder="Item name…"
                    :value="item.label"
                    @input="setRoomExtraField(room.id, item._eid, 'label', $event.target.value)" />
                </template>
                <template v-else>{{ item.label }}</template>
              </div>

              <!-- Fields column -->
              <div class="room-row-right">
                <div class="room-row-fields" :class="{ 'co-layout': isCheckOut }">

                  <!-- ── STANDARD layout (Check In / Interim / Inventory) ── -->
                  <template v-if="!isCheckOut">
                    <template v-if="item._type === 'template'">
                      <div v-if="item.hasDescription" class="room-field-desc">
                        <label class="field-lbl">Description</label>
                        <textarea class="fld-textarea" rows="3" :placeholder="`Describe ${item.label.toLowerCase()}…`"
                          :value="get(room.id,item.id,'description')"
                          @input="set(room.id,item.id,'description',$event.target.value)"></textarea>
                      </div>
                      <div v-if="item.hasCondition" class="room-field-cond room-field-with-cam">
                        <div class="field-cond-inner">
                          <label class="field-lbl">Condition</label>
                          <textarea class="fld-textarea" rows="3" :placeholder="`Condition of ${item.label.toLowerCase()}…`"
                            :value="get(room.id,item.id,'condition')"
                            @input="set(room.id,item.id,'condition',$event.target.value)"></textarea>
                        </div>
                        <div class="room-btn-stack">
                          <button class="cam-btn cam-btn-room" :class="{ 'cam-has': getPhotos(room.id, item.id).length }" @click="togglePanel(room.id, item.id)" title="Photos">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                            <span v-if="getPhotos(room.id, item.id).length" class="cam-count">{{ getPhotos(room.id, item.id).length }}</span>
                          </button>
                          <button class="cam-btn cam-btn-room mic-btn"
                            :class="{ 'mic-active': isItemRecording(room.id, item.id), 'mic-has': !isItemRecording(room.id, item.id) && getItemRecordings(room.id, item.id).length }"
                            @click.stop="toggleItemRecording(room.id, item.id, room.name + ' — ' + item.label)"
                            title="Record audio">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                            <span v-if="getItemRecordings(room.id, item.id).length && !isItemRecording(room.id, item.id)" class="cam-count mic-count">{{ getItemRecordings(room.id, item.id).length }}</span>
                          </button>
                        </div>
                      </div>
                      <div v-else-if="!item.hasCondition && !item.hasDescription" class="room-field-cam-only">
                        <button class="cam-btn cam-btn-room" :class="{ 'cam-has': getPhotos(room.id, item.id).length }" @click="togglePanel(room.id, item.id)" title="Photos">
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                          <span v-if="getPhotos(room.id, item.id).length" class="cam-count">{{ getPhotos(room.id, item.id).length }}</span>
                        </button>
                        <button class="cam-btn cam-btn-room mic-btn"
                          :class="{ 'mic-active': isItemRecording(room.id, item.id), 'mic-has': !isItemRecording(room.id, item.id) && getItemRecordings(room.id, item.id).length }"
                          @click.stop="toggleItemRecording(room.id, item.id, room.name + ' — ' + item.label)"
                          title="Record audio">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                          <span v-if="getItemRecordings(room.id, item.id).length && !isItemRecording(room.id, item.id)" class="cam-count mic-count">{{ getItemRecordings(room.id, item.id).length }}</span>
                        </button>
                      </div>
                      <div v-if="item.hasNotes" class="room-field-notes">
                        <label class="field-lbl">Notes</label>
                        <input class="fld-input" type="text" placeholder="Notes…"
                          :value="get(room.id,item.id,'notes')"
                          @input="set(room.id,item.id,'notes',$event.target.value)" />
                      </div>
                    </template>
                    <template v-else>
                      <div class="room-field-desc">
                        <label class="field-lbl">Description</label>
                        <textarea class="fld-textarea" rows="3" placeholder="Describe…"
                          :value="item.description"
                          @input="setRoomExtraField(room.id,item._eid,'description',$event.target.value)"></textarea>
                      </div>
                      <div class="room-field-cond room-field-with-cam">
                        <div class="field-cond-inner">
                          <label class="field-lbl">Condition</label>
                          <textarea class="fld-textarea" rows="3" placeholder="Condition…"
                            :value="item.condition"
                            @input="setRoomExtraField(room.id,item._eid,'condition',$event.target.value)"></textarea>
                        </div>
                        <div class="room-btn-stack">
                          <button class="cam-btn cam-btn-room" :class="{ 'cam-has': getPhotos(room.id, item._eid).length }" @click="togglePanel(room.id, item._eid)" title="Photos">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                            <span v-if="getPhotos(room.id, item._eid).length" class="cam-count">{{ getPhotos(room.id, item._eid).length }}</span>
                          </button>
                          <button class="cam-btn cam-btn-room mic-btn"
                            :class="{ 'mic-active': isItemRecording(room.id, item._eid), 'mic-has': !isItemRecording(room.id, item._eid) && getItemRecordings(room.id, item._eid).length }"
                            @click.stop="toggleItemRecording(room.id, item._eid, room.name + ' — ' + (item.label || 'Item'))"
                            title="Record audio">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                            <span v-if="getItemRecordings(room.id, item._eid).length && !isItemRecording(room.id, item._eid)" class="cam-count mic-count">{{ getItemRecordings(room.id, item._eid).length }}</span>
                          </button>
                        </div>
                      </div>
                    </template>
                  </template>

                  <!-- ── CHECK OUT layout ── -->
                  <template v-else>
                    <!-- Description — read from Check In (read-only reference) -->
                    <div class="room-field-desc">
                      <label class="field-lbl">Description</label>
                      <div class="co-inv-value" :class="{ 'co-inv-empty': !getCI(room.id, item._type==='template' ? item.id : item._eid, 'description') }">
                        {{ getCI(room.id, item._type==='template' ? item.id : item._eid, 'description') || item.label || '—' }}
                      </div>
                    </div>

                    <!-- Condition at Check In — read-only from source Check In report_data -->
                    <div class="room-field-inv">
                      <label class="field-lbl co-inv-lbl">
                        Condition at Check In
                        <span class="co-inv-badge">Inventory</span>
                      </label>
                      <div class="co-inv-value" :class="{ 'co-inv-empty': !getCI(room.id, item._type==='template' ? item.id : item._eid, 'condition') }">
                        {{ getCI(room.id, item._type==='template' ? item.id : item._eid, 'condition') || '—' }}
                      </div>
                    </div>

                    <!-- Condition at Check Out — editable, with camera inline -->
                    <div class="room-field-cond room-field-with-cam">
                      <div class="field-cond-inner">
                        <label class="field-lbl">Condition at Check Out</label>
                        <textarea class="fld-textarea" rows="3"
                          placeholder="As Inventory &amp; Check In"
                          :value="item._type==='template'
                            ? (get(room.id,item.id,'checkOutCondition') || '')
                            : (item.checkOutCondition || '')"
                          @focus="e => {
                            const cur = item._type==='template'
                              ? get(room.id,item.id,'checkOutCondition')
                              : item.checkOutCondition
                            if (!cur) {
                              item._type==='template'
                                ? set(room.id,item.id,'checkOutCondition','As Inventory & Check In')
                                : setRoomExtraField(room.id,item._eid,'checkOutCondition','As Inventory & Check In')
                            }
                          }"
                          @input="item._type==='template'
                            ? set(room.id,item.id,'checkOutCondition',$event.target.value)
                            : setRoomExtraField(room.id,item._eid,'checkOutCondition',$event.target.value)"></textarea>
                      </div>
                      <button class="cam-btn cam-btn-room"
                        :class="{ 'cam-has': getPhotos(room.id, item._type==='template' ? item.id : item._eid).length }"
                        @click="togglePanel(room.id, item._type==='template' ? item.id : item._eid)"
                        title="Photos">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                        <span v-if="getPhotos(room.id, item._type==='template' ? item.id : item._eid).length" class="cam-count">{{ getPhotos(room.id, item._type==='template' ? item.id : item._eid).length }}</span>
                      </button>
                      <button class="cam-btn cam-btn-room mic-btn"
                        :class="{ 'mic-active': isItemRecording(room.id, item._type==='template' ? item.id : item._eid), 'mic-has': !isItemRecording(room.id, item._type==='template' ? item.id : item._eid) && getItemRecordings(room.id, item._type==='template' ? item.id : item._eid).length }"
                        @click.stop="toggleItemRecording(room.id, item._type==='template' ? item.id : item._eid, room.name + ' — ' + (item.label || 'Item'))"
                        title="Record audio">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                        <span v-if="getItemRecordings(room.id, item._type==='template' ? item.id : item._eid).length && !isItemRecording(room.id, item._type==='template' ? item.id : item._eid)" class="cam-count mic-count">{{ getItemRecordings(room.id, item._type==='template' ? item.id : item._eid).length }}</span>
                      </button>
                    </div>

                    <!-- ⚠ Action picker -->
                    <div class="room-field-actions">
                      <label class="field-lbl">Actions</label>
                      <CheckOutActionPicker
                        :actions="getItemActions(room.id, item._type==='extra' ? item._eid : item.id)"
                        :room-id="room.id"
                        :item-id="item._type==='extra' ? item._eid : item.id"
                        @update:actions="val => setItemActions(room.id, item._type==='extra' ? item._eid : item.id, val)"
                      />
                    </div>

                    <!-- View Check In photos link -->
                    <div class="room-field-ci-photos">
                      <button class="btn-ci-photos" @click="openCIPhotos(room.id, item._type==='template' ? item.id : item._eid, item.label)">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                        View Check In photos
                        <span v-if="(sourceReportData[room.id]?.[String(item._type==='template' ? item.id : item._eid)]?._photos || []).length" class="ci-photo-count">
                          {{ (sourceReportData[room.id]?.[String(item._type==='template' ? item.id : item._eid)]?._photos || []).length }}
                        </span>
                      </button>
                    </div>
                  </template>

                </div>

                <!-- Sub-items (template items only) -->
                <div v-if="item._type === 'template' && getSubs(room.id, item.id).length" class="sub-items">
                  <div v-for="sub in getSubs(room.id, item.id)" :key="sub._sid" class="sub-item">
                    <div class="sub-item-fields">
                      <div class="room-field-desc"><label class="field-lbl">Description</label><textarea class="fld-textarea" rows="2" placeholder="Describe…" :value="sub.description" @input="setSubField(room.id,item.id,sub._sid,'description',$event.target.value)"></textarea></div>
                      <div class="room-field-cond"><label class="field-lbl">Condition</label><textarea class="fld-textarea" rows="2" placeholder="Condition…" :value="sub.condition" @input="setSubField(room.id,item.id,sub._sid,'condition',$event.target.value)"></textarea></div>
                    </div>
                    <button class="del-btn del-btn-sub" @click="removeSubItem(room.id,item.id,sub._sid)">×</button>
                  </div>
                </div>

                <!-- Inline photo panel — shown when camera toggled -->
                <div v-if="isPanelOpen(room.id, item._type==='template' ? item.id : item._eid)" class="photo-panel-inline">
                  <div v-for="(ph,pi) in getPhotos(room.id, item._type==='template' ? item.id : item._eid)" :key="pi" class="ph-thumb ph-thumb-lg" style="cursor:pointer" @click="openLightbox(room.id, item._type==='template' ? item.id : item._eid,pi)">
                    <img :src="ph" class="ph-img-click" />
                    <button class="ph-del" @click="removePhoto(room.id, item._type==='template' ? item.id : item._eid, pi)">×</button>
                  </div>
                  <label class="ph-upload-btn">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    Upload photos
                    <input type="file" accept="image/*" multiple style="display:none"
                      @change="e=>addPhotos(room.id, item._type==='template' ? item.id : item._eid, e.target.files)" />
                  </label>
                  <span class="ph-ref-label">Ref {{ itemRef(room.id, getOrderedRoomItems(room), item._type==='template' ? item.id : item._eid) }}</span>
                </div>

                <!-- Action bar -->
                <div class="item-action-bar">
                  <button v-if="item._type === 'template'" class="add-sub-btn" @click="addSubItem(room.id, item.id)">+ Add sub-item</button>
                  <button
                    v-if="item._type === 'template'"
                    class="del-item-btn"
                    @click="hideItem(room.id, item.id)"
                  >× Remove item</button>
                  <button
                    v-else
                    class="del-item-btn"
                    @click="removeRoomExtraItem(room.id, item._eid)"
                  >× Remove item</button>
                </div>
              </div>
            </div>

            <div class="add-row-bar add-row-bar-room">
              <button class="add-row-btn add-row-btn-room" @click="addRoomExtraItem(room.id)">+ Add line</button>
            </div>
          </div>

          <div class="foot">
            <button class="btn-ghost" @click="exit">← Back to Overview</button>
            <button class="btn-save-lg" :disabled="saving" @click="save()">{{ saving ? 'Saving…' : '💾  Save Report' }}</button>
          </div>
        </div>
      </main>
    </div>

    <!-- ITEM PHOTO VIEWER LIGHTBOX -->
    <div
      v-if="photoViewer.show"
      class="ci-lightbox-overlay"
      @click.self="photoViewer.show = false"
      @keydown.esc.window="photoViewer.show = false"
      @keydown.left.window="photoViewerPrev"
      @keydown.right.window="photoViewerNext"
    >
      <div class="ci-lightbox">
        <div class="ci-lightbox-hd">
          <span class="ci-lightbox-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            <template v-if="photoViewer.ref || photoViewer.label">
              <span v-if="photoViewer.ref" class="lb-ref">Ref {{ photoViewer.ref }}</span>
              <span v-if="photoViewer.label" class="lb-sep">·</span>
              {{ photoViewer.label }}
            </template>
            <template v-else>Photo</template>
          </span>
          <span class="ci-lightbox-counter">{{ photoViewer.index + 1 }} / {{ photoViewer.photos.length }}</span>
          <button class="modal-close" @click="photoViewer.show = false">×</button>
        </div>
        <div class="ci-lightbox-body">
          <button class="ci-nav ci-nav-prev" @click="photoViewerPrev" :disabled="photoViewer.index === 0">‹</button>
          <img :src="photoViewer.photos[photoViewer.index]" class="ci-lightbox-img" :alt="photoViewer.label" />
          <button class="ci-nav ci-nav-next" @click="photoViewerNext" :disabled="photoViewer.index === photoViewer.photos.length - 1">›</button>
        </div>
        <div class="ci-lightbox-dots">
          <span v-for="(_, i) in photoViewer.photos" :key="i" class="ci-dot" :class="{ active: i === photoViewer.index }" @click="photoViewer.index = i"></span>
        </div>
        <p class="lb-hint">← → to navigate · Esc or click outside to close</p>
      </div>
    </div>

    <!-- CHECK IN PHOTOS LIGHTBOX -->
    <div v-if="ciPhotoViewer.show" class="ci-lightbox-overlay" @click.self="ciPhotoViewer.show = false">
      <div class="ci-lightbox">
        <div class="ci-lightbox-hd">
          <span class="ci-lightbox-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            Check In · {{ ciPhotoViewer.label }}
          </span>
          <span class="ci-lightbox-counter">{{ ciPhotoViewer.index + 1 }} / {{ ciPhotoViewer.photos.length }}</span>
          <button class="modal-close" @click="ciPhotoViewer.show = false">×</button>
        </div>
        <div class="ci-lightbox-body">
          <button class="ci-nav ci-nav-prev" @click="ciPhotoPrev" :disabled="ciPhotoViewer.index === 0">‹</button>
          <img :src="ciPhotoViewer.photos[ciPhotoViewer.index]" class="ci-lightbox-img" :alt="ciPhotoViewer.label" />
          <button class="ci-nav ci-nav-next" @click="ciPhotoNext" :disabled="ciPhotoViewer.index === ciPhotoViewer.photos.length - 1">›</button>
        </div>
        <div class="ci-lightbox-dots">
          <span
            v-for="(_, i) in ciPhotoViewer.photos"
            :key="i"
            class="ci-dot"
            :class="{ active: i === ciPhotoViewer.index }"
            @click="ciPhotoViewer.index = i"
          ></span>
        </div>
      </div>
    </div>

    <!-- PHOTO MODAL -->
    <div v-if="showPhotoModal" class="modal-overlay" @click.self="showPhotoModal = false">
      <div class="photo-modal">
        <div class="photo-modal-hd">
          <h3>Property Overview Photo</h3>
          <button class="modal-close" @click="showPhotoModal = false">×</button>
        </div>
        <div class="photo-modal-body">
          <div v-if="currentPhoto" class="photo-preview">
            <img :src="currentPhoto" alt="Property overview" class="photo-preview-img" />
            <button class="photo-remove-btn" @click="currentPhoto = null">× Remove photo</button>
          </div>
          <div v-else class="photo-dropzone">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            <p>No photo uploaded yet</p><p class="photo-hint">Appears on the report cover page</p>
          </div>
          <label class="photo-upload-btn">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            {{ currentPhoto ? 'Replace photo' : 'Upload photo' }}
            <input type="file" accept="image/*" style="display:none" @change="onPhotoFileChange" />
          </label>
          <p class="photo-hint-sm">JPG, PNG, WEBP — max 8MB</p>
        </div>
        <div class="photo-modal-ft">
          <button class="btn-ghost" @click="showPhotoModal = false">Cancel</button>
          <button class="btn-save-lg" :disabled="photoUploading || !currentPhoto" @click="savePhoto">{{ photoUploading ? 'Saving…' : 'Save Photo' }}</button>
        </div>
      </div>
    </div>

  <!-- AUDIO MODULE — fixed footer -->
  <div class="audio-module" :class="{ 'am-collapsed': !audioModule.expanded }">
    <audio ref="audioEl" style="display:none" />

    <!-- Topbar -->
    <div class="am-topbar" @click="audioModule.expanded = !audioModule.expanded">
      <div class="am-title">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
        Audio Module
        <span v-if="audioModule.mode === 'recording'" class="am-rec-pill">
          <span class="am-rec-dot"></span>
          REC {{ fmtTime(recordingSeconds) }}
          <span v-if="itemRecordingKey" class="am-rec-item-label">— {{ recordings.find(r => r.itemKey === itemRecordingKey && recordings.indexOf(r) === recordings.length - 1)?.label?.replace(/ \(\d+\)$/, '') || '' }}</span>
        </span>
        <span v-else-if="recordings.length" class="am-rec-count">{{ recordings.length }} clip{{ recordings.length !== 1 ? 's' : '' }}</span>
      </div>
      <button class="am-collapse-btn" @click.stop="audioModule.expanded = !audioModule.expanded">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline v-if="audioModule.expanded" points="18 15 12 9 6 15"/>
          <polyline v-else points="6 9 12 15 18 9"/>
        </svg>
      </button>
    </div>

    <!-- Body -->
    <div v-if="audioModule.expanded" class="am-body">

      <!-- Transport -->
      <div class="am-transport">

        <!-- Record (general) -->
        <button class="am-btn am-btn-rec" :class="{ recording: audioModule.mode === 'recording' && !itemRecordingKey }"
          @click="toggleGeneralRecording"
          :title="audioModule.mode === 'recording' && !itemRecordingKey ? 'Stop recording' : 'Record general audio'">
          <svg v-if="!(audioModule.mode === 'recording' && !itemRecordingKey)" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="8"/></svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
        </button>

        <!-- Play/Pause -->
        <button class="am-btn am-btn-play" :disabled="!recordings.length" @click="togglePlay"
          :title="audioModule.mode === 'playing' ? 'Pause' : 'Play'">
          <svg v-if="audioModule.mode !== 'playing'" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
        </button>

        <!-- Time -->
        <div class="am-time">
          <span class="am-time-cur">{{ fmtTime(audioModule.mode === 'recording' ? recordingSeconds : playbackTime) }}</span>
          <span class="am-time-sep">/</span>
          <span class="am-time-dur">{{ fmtTime(audioModule.mode === 'recording' ? recordingSeconds : audioDuration) }}</span>
        </div>

        <!-- Scrub bar -->
        <div class="am-progress" @click="seekAudio">
          <div class="am-track">
            <div class="am-fill" :class="{ 'am-fill-rec': audioModule.mode === 'recording' }"
              :style="{ width: audioModule.mode === 'recording' ? '100%' : audioDuration > 0 ? `${(playbackTime / audioDuration) * 100}%` : '0%' }">
            </div>
          </div>
        </div>

        <!-- Speed -->
        <div class="am-speed-wrap">
          <button class="am-speed-btn" @click.stop="showSpeedMenu = !showSpeedMenu; showRecMenu = false">{{ playbackSpeed }}×</button>
          <div v-if="showSpeedMenu" class="am-speed-menu">
            <button v-for="s in speedOptions" :key="s" class="am-speed-opt" :class="{ active: s === playbackSpeed }" @click="setSpeed(s)">{{ s }}×</button>
          </div>
        </div>

        <!-- Recordings dropdown toggle -->
        <div class="am-queue-wrap" v-click-outside="onRecMenuOutside">
          <button class="am-queue-btn" :class="{ active: showRecMenu }"
            @click.stop="showRecMenu = !showRecMenu; showSpeedMenu = false"
            :title="`${recordings.length} recording${recordings.length !== 1 ? 's' : ''}`">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
            <span v-if="recordings.length" class="am-queue-count">{{ recordings.length }}</span>
          </button>

          <!-- Dropdown panel -->
          <div v-if="showRecMenu" class="am-rec-dropdown">
            <div class="am-rec-dropdown-hd">
              <span>Recordings</span>
              <span class="am-rec-dropdown-total">{{ recordings.length }} clip{{ recordings.length !== 1 ? 's' : '' }}</span>
            </div>

            <div class="am-rec-dropdown-body">
              <div v-if="!recordings.length" class="am-rec-dropdown-empty">No recordings yet</div>

              <template v-for="group in groupedRecordings" :key="group.key">
                <!-- Group heading -->
                <div class="am-rec-group-hd">{{ groupDisplayLabel(group) }}</div>

                <!-- Clips in group -->
                <div v-for="rec in group.items" :key="rec.id"
                  class="am-rec-row"
                  :class="{
                    'am-rec-row-active': activeRec?.id === rec.id,
                    'am-rec-row-playing': activeRec?.id === rec.id && audioModule.mode === 'playing'
                  }"
                  @click="loadRecording(rec, false); showRecMenu = false"
                >
                  <!-- Playing indicator -->
                  <span v-if="activeRec?.id === rec.id && audioModule.mode === 'playing'" class="am-playing-bars">
                    <span></span><span></span><span></span>
                  </span>
                  <svg v-else-if="activeRec?.id === rec.id" width="10" height="10" viewBox="0 0 24 24" fill="#6366f1"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  <svg v-else width="10" height="10" viewBox="0 0 24 24" fill="currentColor" style="opacity:0.35"><polygon points="5 3 19 12 5 21 5 3"/></svg>

                  <div class="am-rec-row-info">
                    <span class="am-rec-row-label">{{ rec.label }}</span>
                    <span class="am-rec-row-meta">{{ fmtTime(rec.duration) }} · {{ rec.createdAt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) }}</span>
                  </div>

                  <!-- Future: transcript / GPT status badges -->
                  <span v-if="rec.transcript" class="am-pill am-pill-t" title="Transcript ready">T</span>
                  <span v-if="rec.gptResult"  class="am-pill am-pill-g" title="GPT result ready">AI</span>

                  <button class="am-rec-del" @click.stop="deleteRecording(rec)" title="Delete">×</button>
                </div>
              </template>
            </div>
          </div>
        </div>

      </div>

      <!-- Currently playing label -->
      <div v-if="activeRec" class="am-now-playing">
        <span class="am-now-label">{{ activeRec.label }}</span>
        <span class="am-now-status" v-if="audioModule.mode === 'playing'">▶ Playing</span>
        <span class="am-now-status" v-else-if="audioModule.mode === 'paused'">⏸ Paused</span>
      </div>
      <div v-else-if="!recordings.length" class="am-empty">
        Press <strong>●</strong> to record · or use the <strong>🎤</strong> icon on any item
      </div>

    </div>
  </div>

  </div>
</template>
<style scoped>
*{box-sizing:border-box}

/* Layout */
.shell{display:flex;flex-direction:column;height:100vh;overflow:hidden;background:#f1f5f9}
.loading-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:14px;background:#f8fafc}
.loading-screen p{font-size:14px;color:#64748b}
.ring{width:36px;height:36px;border:3px solid #e2e8f0;border-top-color:#6366f1;border-radius:50%;animation:spin 0.7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* Topbar */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:0 20px;height:52px;background:#0f172a;border-bottom:1px solid #1e293b;flex-shrink:0;z-index:10;gap:12px}
.topbar-l{display:flex;align-items:center;gap:12px;min-width:0}
.topbar-r{display:flex;align-items:center;gap:10px;flex-shrink:0}
.back-btn{display:flex;align-items:center;gap:5px;padding:5px 10px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:5px;font-size:12px;color:#94a3b8;cursor:pointer;transition:all 0.15s;flex-shrink:0}
.back-btn:hover{background:rgba(255,255,255,0.1);color:#e2e8f0}
.crumbs{display:flex;align-items:center;gap:6px;min-width:0}
.crumb-addr{font-size:13px;font-weight:700;color:#e2e8f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.crumb-dot{color:#334155}
.crumb-type{font-size:12px;font-weight:600;color:#6366f1;white-space:nowrap}
.crumb-who{font-size:12px;color:#64748b;white-space:nowrap}
.prog{display:flex;align-items:center;gap:8px}
.prog-track{width:80px;height:5px;background:#1e293b;border-radius:3px;overflow:hidden}
.prog-fill{height:100%;background:#6366f1;border-radius:3px;transition:width 0.4s}
.prog-lbl{font-size:11px;color:#64748b;font-weight:600;white-space:nowrap}
.chip{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:5px;font-size:11px;font-weight:600}
.chip-saving{background:#1e293b;color:#64748b}
.chip-saved{background:#052e16;color:#4ade80}
.chip-unsaved{background:#431407;color:#f97316}
.spin-icon{animation:spin 1s linear infinite}
.photo-btn{display:flex;align-items:center;gap:6px;padding:5px 11px;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.1);border-radius:5px;font-size:12px;color:#94a3b8;cursor:pointer;transition:all 0.15s}
.photo-btn:hover{background:rgba(255,255,255,0.13);color:#e2e8f0}
.save-btn{padding:6px 16px;background:#6366f1;color:white;border:none;border-radius:5px;font-size:13px;font-weight:700;cursor:pointer;transition:background 0.15s}
.save-btn:hover:not(:disabled){background:#4f46e5}.save-btn:disabled{background:#1e3a5f;color:#475569;cursor:not-allowed}

/* Body */
.body{display:grid;grid-template-columns:210px 1fr;flex:1;overflow:hidden}

/* Sidebar */
.sidebar{background:#172033;border-right:1px solid #0d1726;overflow-y:auto;padding:16px 0 40px}
.nav-grp{margin-bottom:4px}.nav-lbl{padding:12px 14px 5px;font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:1.2px;color:#2d4a6b}
.nav-btn{display:flex;align-items:center;gap:9px;width:100%;padding:8px 14px;background:none;border:none;border-left:3px solid transparent;font-size:12.5px;font-weight:500;color:#4b6282;text-align:left;cursor:pointer;transition:all 0.12s}
.nav-btn:hover{background:rgba(255,255,255,0.03);color:#64748b}.nav-btn.active{background:rgba(99,102,241,0.1);color:#a5b4fc;border-left-color:#6366f1;font-weight:600}
.dot{width:7px;height:7px;border-radius:50%;background:transparent;border:1.5px solid #2d4a6b;flex-shrink:0;transition:all 0.2s}.dot.done{background:#22c55e;border-color:#22c55e}
.sidebar-warn{padding:20px 14px;display:flex;flex-direction:column;align-items:flex-start;gap:10px}.sidebar-warn p{font-size:12px;color:#4b6282;line-height:1.5}

/* Main */
.main{overflow-y:auto;padding:28px 40px 140px;display:flex;flex-direction:column;gap:24px}
.empty-state{display:flex;flex-direction:column;align-items:center;gap:14px;padding:80px 20px;text-align:center}
.empty-state h3{font-size:20px;font-weight:600;color:#1e293b}.empty-state p{font-size:14px;color:#64748b;max-width:400px;line-height:1.6}

/* Cards */
.card{background:white;border-radius:10px;border:1px solid #e2e8f0;overflow:hidden;scroll-margin-top:28px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}
.card-room{border-color:#ddd6fe}
.card-hd{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;background:#fafbfd;border-bottom:1px solid #f1f5f9}
.card-hd-room{background:#f5f3ff;border-bottom-color:#ede9fe}
.card-hd-right{display:flex;align-items:center;gap:10px}
.card-title{font-size:14px;font-weight:700;color:#0f172a;letter-spacing:-0.1px}.card-hd-room .card-title{color:#4c1d95}
.card-hint{font-size:11px;color:#94a3b8}
.hidden-badge{font-size:11px;color:#f59e0b;background:#fffbeb;border:1px solid #fde68a;border-radius:4px;padding:2px 7px}
.unknown-type{padding:16px 20px;font-size:13px;color:#f59e0b}
.co-badge{font-size:11px;color:#7c3aed;background:#f5f3ff;border:1px solid #ddd6fe;border-radius:4px;padding:2px 7px;font-weight:700}

/* Drag handle */
.drag-handle{cursor:grab;color:#cbd5e1;font-size:16px;line-height:1;user-select:none;padding:0 4px}
.drag-handle:active{cursor:grabbing}
.drag-handle-room{margin-right:8px;flex-shrink:0}

/* Tables */
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl thead{background:#f8fafc}
.tbl th{padding:9px 16px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.7px;color:#94a3b8;border-bottom:1px solid #e5e7eb;text-align:left;white-space:nowrap}
.tbl td{padding:8px 16px;border-bottom:1px solid #f1f5f9;vertical-align:middle}
.tbl tbody tr:last-child td{border-bottom:none}
.tbl tbody tr:hover{background:#fafbfd}
.col-drag{width:28px}.col-item{width:20%;min-width:130px}.col-clean{width:280px}.col-reading{width:150px}.col-del{width:36px}
.td-name{font-size:13px;font-weight:600;color:#374151;white-space:nowrap}
.td-drag{text-align:center;padding-left:8px!important}.td-del{text-align:center}
.extra-row td{background:white}

/* Add row bar */
.add-row-bar{padding:10px 16px;border-top:1px dashed #e5e7eb;background:#fafbfd}
.add-row-bar-room{background:#f5f3ff;border-top-color:#ddd6fe}
.add-row-btn{padding:5px 12px;background:none;border:1px dashed #6366f1;border-radius:5px;font-size:12px;font-weight:600;color:#6366f1;cursor:pointer;transition:all 0.12s}
.add-row-btn:hover{background:#eff6ff}
.add-row-btn-room{border-color:#a78bfa;color:#7c3aed}.add-row-btn-room:hover{background:#f5f3ff}

/* Delete */
.del-btn{width:24px;height:24px;background:none;border:1px solid #fca5a5;border-radius:4px;font-size:14px;color:#ef4444;cursor:pointer;transition:all 0.12s;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0}
.del-btn:hover{background:#fef2f2;border-color:#ef4444}
.del-btn-sub{margin-top:20px}

/* Q&A */
.qa-row{padding:16px 20px;border-bottom:1px solid #f1f5f9;display:flex;flex-direction:column;gap:10px}
.qa-row:last-child{border-bottom:none}
.qa-row-header{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.qa-extra-header{display:flex;align-items:center;gap:8px}
.qa-question{font-size:13px;font-weight:600;color:#1e293b;line-height:1.4;flex:1}
.qa-guidance{font-size:12px;color:#64748b;line-height:1.5;background:#fffbeb;border-left:3px solid #fbbf24;padding:8px 12px;border-radius:0 4px 4px 0}
.qa-controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap}

/* Room rows */
.room-row{display:grid;grid-template-columns:190px 1fr;border-bottom:1px solid #f1f5f9}
.room-row:last-child{border-bottom:none}
.room-row-label{display:flex;align-items:flex-start;padding:14px 10px;font-size:13px;font-weight:700;color:#374151;border-right:1px solid #f1f5f9;background:#fafbfd;line-height:1.3;gap:5px;flex-wrap:wrap}
.label-input{font-weight:700;font-size:13px}
.room-row-right{display:flex;flex-direction:column}

/* Standard layout (2-col: description + condition) */
.room-row-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px 16px;align-items:start}
.room-field-desc{grid-column:1}.room-field-cond{grid-column:2}.room-field-notes{grid-column:1/-1}

/* Check Out layout (4-col: description | check-in | check-out | actions) */
.co-layout{grid-template-columns:1fr 1fr 1fr auto;gap:8px}
.room-field-inv{}
.co-inv-lbl{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.co-inv-badge{padding:1px 7px;background:#e0e7ff;color:#4338ca;border-radius:8px;font-size:10px;font-weight:600;flex-shrink:0}
.co-inv-value{padding:8px 10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;color:#64748b;min-height:60px;line-height:1.5;white-space:pre-wrap}
.room-field-actions{display:flex;flex-direction:column;padding-top:0}
.field-lbl{display:block;margin-bottom:4px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8}

/* Item action bar */
.item-action-bar{display:flex;align-items:center;gap:12px;padding:6px 16px 10px;border-top:1px solid #f8fafc}
.add-sub-btn{background:none;border:none;color:#7c3aed;font-size:12px;font-weight:600;cursor:pointer;padding:2px 0}
.add-sub-btn:hover{text-decoration:underline}
.del-item-btn{background:none;border:none;color:#ef4444;font-size:12px;font-weight:600;cursor:pointer;padding:2px 0;margin-left:auto}
.del-item-btn:hover{text-decoration:underline}

/* Sub-items */
.sub-items{display:flex;flex-direction:column;border-top:1px dashed #e5e7eb}
.sub-item{display:flex;align-items:flex-start;gap:8px;padding:10px 16px;border-bottom:1px dashed #f1f5f9}
.sub-item-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;flex:1}

/* Inputs */
.fld-input{width:100%;padding:6px 10px;border:1px solid #e2e8f0;border-radius:5px;font-size:13px;color:#1e293b;font-family:inherit;background:white;transition:border-color 0.15s}
.fld-input:focus{outline:none;border-color:#6366f1;box-shadow:0 0 0 2px rgba(99,102,241,0.08)}
.fld-textarea{width:100%;padding:7px 10px;border:1px solid #e2e8f0;border-radius:5px;font-size:13px;color:#1e293b;font-family:inherit;resize:vertical;line-height:1.5;background:white;transition:border-color 0.15s}
.fld-textarea:focus{outline:none;border-color:#6366f1;box-shadow:0 0 0 2px rgba(99,102,241,0.08)}
.fld-mono{font-family:'Courier New',monospace}

/* Foot */
.foot{display:flex;align-items:center;justify-content:space-between;padding:20px 0}
.btn-ghost{padding:10px 20px;background:white;border:1px solid #e2e8f0;border-radius:7px;font-size:14px;font-weight:600;color:#475569;cursor:pointer;transition:all 0.15s;font-family:inherit}
.btn-ghost:hover{background:#f8fafc}
.btn-save-lg{padding:10px 28px;background:#6366f1;color:white;border:none;border-radius:7px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;transition:background 0.15s}
.btn-save-lg:hover:not(:disabled){background:#4f46e5}.btn-save-lg:disabled{background:#94a3b8;cursor:not-allowed}

/* Seed banner */
.seed-banner{background:#eef2ff;border-bottom:1px solid #c7d2fe;flex-shrink:0;z-index:9}
.seed-banner-inner{display:flex;align-items:center;gap:16px;padding:12px 24px;flex-wrap:wrap}
.seed-banner-icon{font-size:20px;flex-shrink:0}
.seed-banner-text{flex:1;min-width:200px}
.seed-banner-text strong{display:block;font-size:13px;font-weight:700;color:#3730a3;margin-bottom:2px}
.seed-banner-text span{font-size:12px;color:#4338ca;line-height:1.5}
.seed-banner-actions{display:flex;align-items:center;gap:10px;flex-shrink:0}
.btn-seed{padding:7px 16px;background:#4f46e5;color:white;border:none;border-radius:6px;font-size:13px;font-weight:700;cursor:pointer;transition:background 0.15s;white-space:nowrap}
.btn-seed:hover:not(:disabled){background:#4338ca}.btn-seed:disabled{background:#a5b4fc;cursor:not-allowed}
.btn-seed-dismiss{padding:7px 12px;background:none;border:1px solid #c7d2fe;border-radius:6px;font-size:12px;font-weight:600;color:#6366f1;cursor:pointer;transition:all 0.15s}
.btn-seed-dismiss:hover{background:#e0e7ff}
.co-inv-empty{color:#94a3b8;font-style:italic;font-size:12px}

/* Photo modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:100}
.photo-modal{background:white;border-radius:12px;width:520px;max-width:95vw;box-shadow:0 20px 60px rgba(0,0,0,0.2);overflow:hidden}
.photo-modal-hd{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #f1f5f9}
.photo-modal-hd h3{font-size:15px;font-weight:700;color:#0f172a}
.modal-close{background:none;border:none;font-size:20px;color:#94a3b8;cursor:pointer;line-height:1;padding:2px 6px;border-radius:4px}
.modal-close:hover{background:#f1f5f9;color:#475569}
.photo-modal-body{padding:20px;display:flex;flex-direction:column;gap:14px}
.photo-preview{display:flex;flex-direction:column;gap:10px}
.photo-preview-img{width:100%;height:auto;max-height:280px;object-fit:cover;border-radius:8px;border:1px solid #e2e8f0}
.photo-remove-btn{background:none;border:none;color:#ef4444;font-size:13px;font-weight:600;cursor:pointer;text-align:left;padding:0}
.photo-remove-btn:hover{text-decoration:underline}
.photo-dropzone{display:flex;flex-direction:column;align-items:center;gap:8px;padding:40px 20px;background:#f8fafc;border:2px dashed #e2e8f0;border-radius:8px;text-align:center}
.photo-dropzone p{font-size:14px;color:#64748b}
.photo-hint{font-size:12px;color:#94a3b8!important}
.photo-upload-btn{display:inline-flex;align-items:center;gap:7px;padding:9px 18px;background:#6366f1;color:white;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;transition:background 0.15s;width:fit-content}
.photo-upload-btn:hover{background:#4f46e5}
.photo-hint-sm{font-size:12px;color:#94a3b8}
.photo-modal-ft{display:flex;justify-content:flex-end;gap:10px;padding:14px 20px;border-top:1px solid #f1f5f9;background:#fafbfd}

/* Item ref & room number */
.room-number{color:#94a3b8;font-weight:500;margin-right:4px;font-size:0.9em}
.item-ref-num{font-size:11px;font-weight:700;color:#6366f1;background:#eff0ff;border-radius:4px;padding:1px 5px;flex-shrink:0;min-width:28px;text-align:center}

/* Fixed section ref badges */
.sec-letter-badge{
  display:inline-flex;align-items:center;justify-content:center;
  width:22px;height:22px;border-radius:5px;
  background:#0f172a;color:#e2e8f0;
  font-size:12px;font-weight:800;letter-spacing:-0.5px;
  flex-shrink:0;margin-right:6px;
}
.sec-ref-badge{
  display:inline-flex;align-items:center;justify-content:center;
  font-size:10px;font-weight:700;color:#6366f1;background:#eff0ff;
  border-radius:4px;padding:1px 5px;margin-right:5px;
  flex-shrink:0;min-width:28px;text-align:center;white-space:nowrap;
}
.sec-ref-extra{ color:#7c3aed;background:#f5f3ff }
/* Extra name cells — ref badge + input side by side */
.td-extra-name{ display:flex;align-items:center;gap:4px }
.td-extra-name .fld-input{ flex:1;min-width:0 }
/* Sidebar letter prefix */
.nav-sec-letter{
  font-size:10px;font-weight:800;color:#4b6282;
  background:#1a2a3a;border-radius:3px;padding:0 4px;
  margin-right:4px;flex-shrink:0;
}
.nav-btn.active .nav-sec-letter{ color:#a5b4fc;background:rgba(99,102,241,0.2) }

/* Camera / mic buttons — universal */
.col-cam{width:34px}
.td-cam{text-align:center;padding:4px 4px}
.cam-btn{display:inline-flex;align-items:center;justify-content:center;width:28px;height:26px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:5px;color:#94a3b8;cursor:pointer;transition:all 0.15s;position:relative;flex-shrink:0}
.cam-btn:hover{background:#f1f5f9;border-color:#94a3b8;color:#475569}
.cam-btn.cam-has{background:#eff6ff;border-color:#93c5fd;color:#2563eb}
.cam-btn-room{width:30px;height:30px;margin-top:18px;align-self:flex-start}
.cam-count{position:absolute;top:-6px;right:-6px;border-radius:10px;padding:0 4px;font-size:9px;font-weight:700;min-width:14px;text-align:center;line-height:14px;background:#2563eb;color:#fff}

/* Mic button variants */
.mic-btn{ color:#64748b }
.mic-btn:hover{ background:#fdf4ff;border-color:#d8b4fe;color:#7c3aed }
.mic-btn.mic-has{ background:#fdf4ff;border-color:#d8b4fe;color:#7c3aed }
.mic-btn.mic-active{
  background:#dc2626;border-color:#dc2626;color:#fff;
  box-shadow:0 0 0 3px rgba(220,38,38,0.3);
  animation:am-pulse 1.4s infinite;
}
.mic-count{ background:#7c3aed !important }


/* Room item — condition + camera/mic stack side by side */
.room-field-with-cam{display:flex;gap:6px;align-items:flex-start}
.field-cond-inner{flex:1;min-width:0}
.room-btn-stack{display:flex;flex-direction:column;gap:4px;padding-top:18px;flex-shrink:0}
.room-field-cam-only{display:flex;gap:4px;justify-content:flex-end;padding:4px 0}

/* Room overview strip */
.room-overview-strip{padding:12px 20px;border-bottom:1px solid #f1f5f9;background:#fafbfc}
.room-overview-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.room-overview-lbl{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:#64748b}
.room-overview-thumbs{display:flex;flex-wrap:wrap;gap:8px}
.room-overview-empty{font-size:12px;color:#94a3b8;margin:0;font-style:italic}

/* Photo panel — inline below item */
.photo-panel-inline{display:flex;flex-wrap:wrap;gap:8px;padding:10px 12px;background:#f8fafc;border:1px dashed #cbd5e1;border-radius:8px;margin-top:8px;align-items:center}
.ph-ref-label{font-size:11px;color:#94a3b8;font-weight:600;margin-left:auto}
/* Photo panel — table row version */
.photo-panel-row td{padding:0!important}
.photo-panel-cell{padding:0!important}
.photo-panel{display:flex;flex-wrap:wrap;gap:8px;padding:10px 16px;background:#f8fafc;border-top:1px dashed #e2e8f0;align-items:center}
/* Thumbnails */
.ph-thumb{position:relative;width:72px;height:72px;border-radius:6px;overflow:hidden;border:1px solid #e2e8f0;flex-shrink:0}
.ph-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.ph-thumb-lg{width:90px;height:90px}
.ph-del{position:absolute;top:2px;right:2px;width:18px;height:18px;border-radius:50%;background:rgba(0,0,0,0.6);border:none;color:#fff;font-size:11px;cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:1}
/* Upload button */
.ph-upload-btn{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;background:#fff;border:1.5px dashed #94a3b8;border-radius:6px;font-size:12px;color:#475569;cursor:pointer;transition:all 0.15s;white-space:nowrap}
.ph-upload-btn:hover{border-color:#6366f1;color:#6366f1;background:#f5f3ff}
.ph-upload-btn-sm{padding:4px 9px;font-size:11px}
.ph-img-click{cursor:zoom-in}
/* CI photos link */
.room-field-ci-photos{margin-top:8px}
.btn-ci-photos{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;font-size:12px;font-weight:600;color:#0284c7;cursor:pointer;transition:all 0.15s}
.btn-ci-photos:hover{background:#e0f2fe;border-color:#7dd3fc}
.ci-photo-count{background:#0284c7;color:#fff;border-radius:10px;padding:1px 6px;font-size:11px;font-weight:700}

/* CI Lightbox */
.ci-lightbox-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px}
.ci-lightbox{background:#1e293b;border-radius:12px;width:min(680px,95vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 60px rgba(0,0,0,0.5)}
.ci-lightbox-hd{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #334155}
.ci-lightbox-title{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;color:#e2e8f0;flex:1}
.ci-lightbox-counter{font-size:12px;color:#64748b;font-weight:600}
.ci-lightbox-body{position:relative;display:flex;align-items:center;justify-content:center;flex:1;min-height:300px;background:#0f172a;padding:12px}
.ci-lightbox-img{max-width:100%;max-height:60vh;object-fit:contain;border-radius:6px}
.ci-nav{position:absolute;top:50%;transform:translateY(-50%);background:rgba(255,255,255,0.1);border:none;color:#fff;font-size:28px;width:40px;height:40px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background 0.15s;z-index:2}
.ci-nav:hover:not(:disabled){background:rgba(255,255,255,0.2)}
.ci-nav:disabled{opacity:0.2;cursor:default}
.ci-nav-prev{left:12px}.ci-nav-next{right:12px}
.ci-lightbox-dots{display:flex;justify-content:center;gap:6px;padding:10px}
.ci-dot{width:7px;height:7px;border-radius:50%;background:#334155;cursor:pointer;transition:background 0.15s}
.ci-dot.active{background:#6366f1}
.lb-ref{font-weight:700;color:#818cf8}
.lb-sep{color:#475569;margin:0 2px}
.lb-hint{text-align:center;font-size:11px;color:#475569;margin:0;padding:0 0 10px}

/* ═══════════════════════════════════════════════════════════════════ */
/* AUDIO MODULE                                                        */
/* ═══════════════════════════════════════════════════════════════════ */
.audio-module{
  position:fixed;bottom:0;left:0;right:0;z-index:200;
  background:#0f172a;border-top:2px solid #1e293b;
  box-shadow:0 -4px 24px rgba(0,0,0,0.35);font-family:inherit;
}
.am-collapsed{ height:40px;overflow:hidden }
.am-topbar{display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:40px;cursor:pointer;user-select:none}
.am-title{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:700;color:#94a3b8;letter-spacing:0.5px;text-transform:uppercase}
.am-rec-pill{display:inline-flex;align-items:center;gap:5px;background:#dc2626;color:#fff;border-radius:10px;padding:2px 9px;font-size:11px;font-weight:700;text-transform:none;letter-spacing:0}
.am-rec-item-label{opacity:0.8;font-weight:400}
.am-rec-dot{width:7px;height:7px;border-radius:50%;background:#fca5a5;animation:am-blink 1s infinite;flex-shrink:0}
@keyframes am-blink{0%,100%{opacity:1}50%{opacity:0.3}}
.am-rec-count{background:#1e293b;color:#64748b;border-radius:8px;padding:1px 8px;font-size:11px;font-weight:600;text-transform:none;letter-spacing:0}
.am-collapse-btn{background:none;border:none;color:#64748b;cursor:pointer;padding:4px;border-radius:4px;display:flex;align-items:center;justify-content:center}
.am-collapse-btn:hover{color:#e2e8f0;background:#1e293b}
.am-body{display:flex;align-items:center;gap:12px;padding:8px 16px 12px;border-top:1px solid #1e293b;flex-wrap:wrap}
.am-transport{display:flex;align-items:center;gap:10px;flex:1;min-width:300px}
.am-btn{width:38px;height:38px;border-radius:50%;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all 0.15s;flex-shrink:0}
.am-btn-rec{background:#dc2626;color:#fff}
.am-btn-rec:hover{background:#b91c1c}
.am-btn-rec.recording{background:#dc2626;animation:am-pulse 1.4s infinite}
@keyframes am-pulse{0%,100%{box-shadow:0 0 0 4px rgba(220,38,38,0.35)}50%{box-shadow:0 0 0 8px rgba(220,38,38,0.1)}}
.am-btn-play{background:#6366f1;color:#fff}
.am-btn-play:hover:not(:disabled){background:#4f46e5}
.am-btn-play:disabled{background:#334155;color:#64748b;cursor:not-allowed}
.am-time{display:flex;align-items:center;gap:3px;font-family:'Courier New',monospace;font-size:14px;font-weight:700;color:#e2e8f0;white-space:nowrap;flex-shrink:0}
.am-time-sep{color:#475569}.am-time-dur{color:#64748b}
.am-progress{flex:1;cursor:pointer;padding:10px 0}
.am-track{height:4px;background:#1e293b;border-radius:4px;overflow:hidden;transition:height 0.15s}
.am-progress:hover .am-track{height:6px}
.am-fill{height:100%;background:#6366f1;border-radius:4px;transition:width 0.1s linear}
.am-fill-rec{background:linear-gradient(90deg,#dc2626,#f87171);animation:am-rec-sweep 2s ease-in-out infinite alternate}
@keyframes am-rec-sweep{from{opacity:0.7}to{opacity:1}}
.am-speed-wrap{position:relative;flex-shrink:0}
.am-speed-btn{padding:5px 10px;background:#1e293b;border:1px solid #334155;border-radius:6px;font-size:12px;font-weight:700;color:#94a3b8;cursor:pointer;transition:all 0.15s}
.am-speed-btn:hover{background:#334155;color:#e2e8f0}
.am-speed-menu{position:absolute;bottom:calc(100% + 6px);right:0;background:#1e293b;border:1px solid #334155;border-radius:8px;padding:4px;display:flex;flex-direction:column;gap:2px;box-shadow:0 8px 24px rgba(0,0,0,0.4);z-index:210;min-width:70px}
.am-speed-opt{padding:5px 12px;background:none;border:none;border-radius:5px;font-size:12px;font-weight:600;color:#94a3b8;cursor:pointer;text-align:center;transition:all 0.12s}
.am-speed-opt:hover{background:#334155;color:#e2e8f0}
.am-speed-opt.active{background:#6366f1;color:#fff}
/* Queue button */
.am-queue-wrap{position:relative;flex-shrink:0}
.am-queue-btn{display:inline-flex;align-items:center;gap:5px;padding:5px 10px;background:#1e293b;border:1px solid #334155;border-radius:6px;font-size:12px;font-weight:700;color:#94a3b8;cursor:pointer;transition:all 0.15s}
.am-queue-btn:hover{background:#334155;color:#e2e8f0}
.am-queue-btn.active{border-color:#6366f1;color:#a5b4fc;background:#1e1e3f}
.am-queue-count{background:#6366f1;color:#fff;border-radius:10px;padding:0 5px;font-size:10px;font-weight:700;min-width:16px;text-align:center}
/* Dropdown panel */
.am-rec-dropdown{position:absolute;bottom:calc(100% + 8px);right:0;width:340px;max-height:420px;background:#0f172a;border:1px solid #334155;border-radius:12px;box-shadow:0 -8px 32px rgba(0,0,0,0.5);z-index:210;display:flex;flex-direction:column;overflow:hidden}
.am-rec-dropdown-hd{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #1e293b;font-size:12px;font-weight:700;color:#94a3b8;flex-shrink:0}
.am-rec-dropdown-total{color:#475569;font-weight:500}
.am-rec-dropdown-body{overflow-y:auto;flex:1;padding:6px 0}
.am-rec-dropdown-empty{padding:20px;text-align:center;font-size:12px;color:#475569;font-style:italic}
.am-rec-group-hd{padding:8px 14px 4px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;color:#334155}
.am-rec-row{display:flex;align-items:center;gap:8px;padding:7px 14px;cursor:pointer;transition:background 0.12s}
.am-rec-row:hover{background:#1e293b}
.am-rec-row-active{background:#1e1e3f}
.am-rec-row-info{flex:1;min-width:0}
.am-rec-row-label{display:block;font-size:12px;font-weight:600;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.am-rec-row-active .am-rec-row-label{color:#a5b4fc}
.am-rec-row-meta{display:block;font-size:11px;color:#475569;font-family:'Courier New',monospace}
.am-rec-del{background:none;border:none;color:#475569;cursor:pointer;font-size:15px;line-height:1;padding:0 2px;transition:color 0.12s;flex-shrink:0}
.am-rec-del:hover{color:#ef4444}
/* Equaliser bars */
.am-playing-bars{display:inline-flex;align-items:flex-end;gap:2px;height:12px;flex-shrink:0}
.am-playing-bars span{display:block;width:3px;border-radius:2px;background:#6366f1;animation:am-bar 0.8s ease-in-out infinite alternate}
.am-playing-bars span:nth-child(1){height:5px;animation-delay:0s}
.am-playing-bars span:nth-child(2){height:12px;animation-delay:0.2s}
.am-playing-bars span:nth-child(3){height:8px;animation-delay:0.4s}
@keyframes am-bar{from{transform:scaleY(0.3);opacity:0.6}to{transform:scaleY(1);opacity:1}}
/* Now playing / empty */
.am-now-playing{display:flex;align-items:center;gap:8px;font-size:12px;color:#64748b;white-space:nowrap;overflow:hidden}
.am-now-label{color:#94a3b8;font-weight:600;overflow:hidden;text-overflow:ellipsis;max-width:260px}
.am-now-status{color:#475569;font-size:11px;flex-shrink:0}
.am-empty{font-size:12px;color:#475569}
.am-empty strong{color:#94a3b8}
/* Whisper/GPT pills */
.am-pill{font-size:9px;font-weight:700;border-radius:4px;padding:1px 4px;flex-shrink:0}
.am-pill-t{background:#065f46;color:#6ee7b7}
.am-pill-g{background:#312e81;color:#a5b4fc}

/* ═══════════════════════════════════════════════════════════════════ */
/* PDF IMPORT                                                          */
/* ═══════════════════════════════════════════════════════════════════ */
.pdf-import-shell{
  display:flex;align-items:flex-start;justify-content:center;
  padding:40px 20px;min-height:400px;
}
.pdf-import-card{
  width:100%;max-width:680px;background:white;border-radius:14px;
  border:1px solid #e2e8f0;padding:40px;box-shadow:0 4px 24px rgba(0,0,0,0.06);
  display:flex;flex-direction:column;gap:20px;
}
.pdf-import-icon{ font-size:40px;text-align:center }
.pdf-import-title{ font-size:22px;font-weight:700;color:#0f172a;text-align:center;margin:0 }
.pdf-import-sub{ font-size:14px;color:#64748b;text-align:center;line-height:1.6;margin:0 }

/* Drop zone */
.pdf-dropzone{
  display:flex;align-items:center;justify-content:center;
  border:2px dashed #e2e8f0;border-radius:10px;padding:32px;
  cursor:pointer;transition:all 0.2s;background:#fafbfc;
}
.pdf-dropzone:hover,.pdf-dropzone-has{ border-color:#6366f1;background:#f5f3ff }
.pdf-dropzone-loading{ pointer-events:none;opacity:0.6 }
.pdf-dz-inner{
  display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center;
}
.pdf-dz-inner p{ font-size:14px;color:#64748b;margin:0 }
.pdf-dz-link{ color:#6366f1;font-weight:600;text-decoration:underline }
.pdf-dz-hint{ font-size:12px;color:#94a3b8 !important }
.pdf-dz-has p{ color:#4338ca }
.pdf-dz-name{ font-size:14px;font-weight:600;color:#4338ca !important }

/* Error */
.pdf-error{ font-size:13px;color:#dc2626;background:#fef2f2;border:1px solid #fca5a5;border-radius:7px;padding:10px 14px;margin:0 }

/* Preview */
.pdf-preview{ background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden }
.pdf-preview-hd{
  display:flex;align-items:center;gap:8px;padding:12px 16px;
  border-bottom:1px solid #e2e8f0;font-size:13px;font-weight:700;color:#16a34a;
  background:#f0fdf4;
}
.pdf-preview-stats{
  display:flex;flex-wrap:wrap;gap:8px;padding:12px 16px;border-bottom:1px solid #f1f5f9;
}
.pdf-stat{
  font-size:12px;color:#64748b;background:white;border:1px solid #e2e8f0;
  border-radius:6px;padding:3px 10px;
}
.pdf-stat strong{ color:#0f172a;font-weight:700 }
.pdf-preview-rooms{
  max-height:280px;overflow-y:auto;display:flex;flex-direction:column;gap:0;
}
.pdf-preview-room{
  padding:10px 16px;border-bottom:1px solid #f1f5f9;
}
.pdf-preview-room:last-child{ border-bottom:none }
.pdf-preview-room strong{ font-size:13px;font-weight:700;color:#374151 }
.pdf-room-count{ font-size:11px;color:#94a3b8;margin-left:8px }
.pdf-room-items{ list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:3px }
.pdf-room-items li{ display:flex;justify-content:space-between;gap:16px;font-size:12px }
.pdf-item-label{ color:#475569;font-weight:500 }
.pdf-item-cond{ color:#94a3b8;font-style:italic;text-align:right;flex-shrink:0 }
.pdf-more{ color:#94a3b8;font-size:11px;font-style:italic }

/* Action buttons */
.pdf-import-actions{
  display:flex;align-items:center;justify-content:flex-end;gap:10px;
  padding-top:4px;border-top:1px solid #f1f5f9;flex-wrap:wrap;
}
.pdf-import-actions .btn-ghost{ margin-right:auto }
.btn-pdf-parse{
  display:inline-flex;align-items:center;gap:7px;
  padding:10px 22px;background:#6366f1;color:white;border:none;border-radius:8px;
  font-size:14px;font-weight:700;cursor:pointer;transition:background 0.15s;font-family:inherit;
}
.btn-pdf-parse:hover:not(:disabled){ background:#4f46e5 }
.btn-pdf-parse:disabled{ background:#94a3b8;cursor:not-allowed }
.btn-pdf-apply{
  display:inline-flex;align-items:center;gap:7px;
  padding:10px 22px;background:#16a34a;color:white;border:none;border-radius:8px;
  font-size:14px;font-weight:700;cursor:pointer;transition:background 0.15s;font-family:inherit;
}
.btn-pdf-apply:hover{ background:#15803d }

</style>