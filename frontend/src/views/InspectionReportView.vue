<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import api from '../services/api'
import { useAuthStore } from '../stores/auth'
import CheckOutActionPicker from '../components/CheckOutActionPicker.vue'
import PdfExportModal from '../components/PdfExportModal.vue'

// v-click-outside directive (registered inline for this component)
const vClickOutside = {
  mounted(el, binding) {
    el._clickOutside = e => { if (!el.contains(e.target)) binding.value(e) }
    document.addEventListener('mousedown', el._clickOutside)
  },
  unmounted(el) { document.removeEventListener('mousedown', el._clickOutside) }
}

// v-focus: auto-focus an element when mounted (used for inline rename inputs)
const vFocus = { mounted: (el) => nextTick(() => el.focus()) }

const route  = useRoute()
const router = useRouter()
const toast  = useToast()
const authStore = useAuthStore()

// ── Role-based permissions ─────────────────────────────────────────────────
const canEdit = computed(() => {
  if (authStore.isAdmin || authStore.isManager) return true
  if (authStore.isTypist) return true
  // Clerks can edit their own reports in active or review stage
  if (authStore.isClerk) {
    const editableStages = ['active', 'review']
    return editableStages.includes(inspection.value?.status)
  }
  return false
})
const canDelete = computed(() => authStore.isAdmin || authStore.isManager)
// Typist can move to Review only when inspection is in Processing
const canMoveToReview = computed(() =>
  authStore.isTypist && inspection.value?.status === 'processing'
)

// ── Auto-resize textarea directive ──────────────────────────────────────────
function autoResizeEl(el) {
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}
const vAutoResize = {
  mounted(el) {
    el.style.overflow = 'hidden'
    el.style.resize   = 'none'
    autoResizeEl(el)
    el.addEventListener('input', () => autoResizeEl(el))
  },
  updated(el) {
    el.style.overflow = 'hidden'
    autoResizeEl(el)
  }
}

const inspection        = ref(null)
const template          = ref(null)
const fixedSectionsRaw  = ref([])   // from GET /api/fixed-sections
const loading           = ref(true)
const saving       = ref(false)
const lastSaved    = ref(null)
const unsaved      = ref(false)
const activeId     = ref(null)
const mobileNavOpen = ref(false)

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
          delete reportData.value._recordings  // stored separately, restored by _restoreRecordings()
          // Restore imported source data if previously imported from PDF
          if (reportData.value._importedSource && Object.keys(sourceReportData.value).length === 0) {
            const src = reportData.value._importedSource
            // Rebuild _eid direct keys so getCI(roomId, eid, field) works after reload
            for (const roomData of Object.values(src)) {
              if (Array.isArray(roomData._extra)) {
                for (const entry of roomData._extra) {
                  if (entry._eid) roomData[entry._eid] = entry
                }
              }
            }
            sourceReportData.value = src
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
        try {
          reportData.value = JSON.parse(inspection.value.report_data)
          delete reportData.value._recordings  // stored separately, restored by _restoreRecordings()
        } catch { reportData.value = {} }
      }
    }

    if (inspection.value.property_id) {
      try {
        const pRes = await api.getProperty(inspection.value.property_id)
        currentPhoto.value = pRes.data.overview_photo || null
        if (pRes.data.client_id) inspection.value.client_id = pRes.data.client_id
      } catch {}
    }

    // Load client photo settings (for timestamp overlay etc.) and action catalogue
    await loadClientSettings()
    try {
      const aRes = await api.getActions()
      actionCatalogue.value = aRes.data.actions || []
    } catch { actionCatalogue.value = [] }

    // Load system-wide fixed sections (configured in Settings → Fixed Sections)
    try {
      const fsRes = await api.getFixedSections()
      fixedSectionsRaw.value = fsRes.data || []
    } catch { fixedSectionsRaw.value = [] }

  } catch {
    toast.error('Failed to load inspection')
    router.push('/inspections')
  } finally {
    loading.value = false
    await nextTick()
    if (allSections.value[0]) activeId.value = allSections.value[0].id
    checkAiTypist()
    checkAiKeys()
    _restoreRecordings()
  }
}

// Restore recordings saved in reportData._recordings back into the recordings ref.
// Base64 audio is converted back to Blob objects so playback works normally.
function _restoreRecordings() {
  // _importedRooms is already in reportData — rooms computed reads it reactively, no extra restore needed
  const saved = reportData.value._recordings
  if (!Array.isArray(saved) || !saved.length) return
  recordings.value = saved
    .filter(r => r.audioB64)
    .map(r => {
      const byteString = atob(r.audioB64)
      const ab = new ArrayBuffer(byteString.length)
      const ia = new Uint8Array(ab)
      for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i)
      const blob = new Blob([ab], { type: r.mimeType || 'audio/webm' })
      const url  = URL.createObjectURL(blob)
      return {
        id:         r.id,
        blob,
        url,
        _savedB64:  r.audioB64,  // cache so re-save doesn't re-encode
        mimeType:   r.mimeType,
        duration:   r.duration,
        createdAt:  r.createdAt,
        label:      r.label,
        itemKey:    r.itemKey,
        transcript: r.transcript,
        gptResult:  r.gptResult,
      }
    })
  if (recordings.value.length) loadRecording(recordings.value[0], true)
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

    const response = await api.pdfImport({ pdf: base64, templateStructure })
    const parsed = response.data
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

  const sourceBuilt  = {}   // goes into sourceReportData (Check In column)
  const reportBuilt  = {}   // goes into reportData (editable Check Out fields)
  const importedRooms = []  // rooms from PDF with no template match

  const templateRooms = (template.value?.sections || []).filter(s => s.section_type === 'room')
  const templateFixed = (template.value?.sections || []).filter(s => s.section_type !== 'room')

  // ── Rooms ────────────────────────────────────────────────────────────
  let matchedCount   = 0
  let unmatchedCount = 0

  for (const importedRoom of (parsed.rooms || [])) {
    const normImport = importedRoom.name.toLowerCase().replace(/[^a-z0-9]/g,'')

    // Fuzzy match: room names share a meaningful substring
    const match = templateRooms.find(r => {
      const normTemplate = r.name.toLowerCase().replace(/[^a-z0-9]/g,'')
      return normTemplate.includes(normImport) || normImport.includes(normTemplate)
    })

    if (match) {
      // ── Matched room → map items to template item IDs ──────────────
      matchedCount++
      const roomId = match.id
      sourceBuilt[roomId] = {}
      const tItems = (match.items || match.sections || [])

      for (const imp of (importedRoom.items || [])) {
        const normImp = imp.label.toLowerCase().replace(/[^a-z0-9]/g,'')

        // Try to match individual items within the room
        const matchItem = tItems.find(i => {
          const normT = (i.label || i.name || '').toLowerCase().replace(/[^a-z0-9]/g,'')
          return normT.includes(normImp) || normImp.includes(normT)
        })

        if (matchItem) {
          // Matched item — store under template item ID
          sourceBuilt[roomId][String(matchItem.id)] = {
            description: imp.description || '',
            condition:   imp.condition   || '',
          }
        } else {
          // Unmatched item within a matched room — add as _extra to source
          if (!sourceBuilt[roomId]._extra) sourceBuilt[roomId]._extra = []
          const eid = `rex_${Date.now()}_${Math.random().toString(36).slice(2,6)}`
          const extraEntry = {
            _eid:        eid,
            label:       imp.label       || '',
            description: imp.description || '',
            condition:   imp.condition   || '',
          }
          sourceBuilt[roomId]._extra.push(extraEntry)
          // Also key by _eid directly so getCI(roomId, eid, field) works
          sourceBuilt[roomId][eid] = extraEntry
          // Also create empty editable row in reportData
          if (!reportBuilt[roomId]) reportBuilt[roomId] = {}
          if (!reportBuilt[roomId]._extra) reportBuilt[roomId]._extra = []
          reportBuilt[roomId]._extra.push({ _eid: eid, label: imp.label || '', description: '', condition: '' })
        }
      }
    } else {
      // ── Unmatched room → create imported room with _extra items ────
      unmatchedCount++
      const roomId = 'imp_rm_' + importedRoom.name.replace(/[^a-z0-9]/gi,'_').toLowerCase() + '_' + Date.now()

      // Register as an imported room so rooms computed includes it
      importedRooms.push({ id: roomId, name: importedRoom.name, section_type: 'room' })

      // Source data: all items become _extra (Check In reference column)
      sourceBuilt[roomId] = { _extra: [] }
      // Report data: all items become editable _extra rows
      reportBuilt[roomId] = { _extra: [] }

      for (const imp of (importedRoom.items || [])) {
        const eid = `rex_${Date.now()}_${Math.random().toString(36).slice(2,6)}`
        const extraEntry = {
          _eid:        eid,
          label:       imp.label       || '',
          description: imp.description || '',
          condition:   imp.condition   || '',
        }
        sourceBuilt[roomId]._extra.push(extraEntry)
        // Also key by _eid directly so getCI(roomId, eid, field) works
        sourceBuilt[roomId][eid] = extraEntry
        reportBuilt[roomId]._extra.push({
          _eid:        eid,
          label:       imp.label || '',
          description: '',
          condition:   '',
        })
      }
    }
  }

  // ── Fixed sections ───────────────────────────────────────────────────
  for (const [type, rows] of Object.entries(parsed.fixedSections || {})) {
    const sec = templateFixed.find(s => s.type === type)
    if (!sec || !Array.isArray(rows)) continue
    sourceBuilt[sec.id] = {}
    for (const [i, row] of rows.entries()) {
      const templateRow = (sec.rows || [])[i]
      const rowId = templateRow?.id || ('imp_fx_' + i)
      sourceBuilt[sec.id][String(rowId)] = { ...row }
    }
  }

  // ── Apply ────────────────────────────────────────────────────────────
  sourceReportData.value = sourceBuilt

  // Merge reportBuilt into existing reportData (don't wipe existing entries)
  for (const [sid, sData] of Object.entries(reportBuilt)) {
    if (!reportData.value[sid]) reportData.value[sid] = {}
    Object.assign(reportData.value[sid], sData)
  }

  // Persist imported source + imported room definitions
  reportData.value._importedSource = sourceBuilt
  reportData.value._importedRooms  = [
    ...(reportData.value._importedRooms || []).filter(r => !importedRooms.find(nr => nr.id === r.id)),
    ...importedRooms,
  ]

  unsaved.value = true
  await save(false)

  pdfImport.value.applied = true
  pdfImport.value.show    = false

  const roomCount = (parsed.rooms || []).length
  const itemCount = (parsed.rooms || []).reduce((s, r) => s + (r.items || []).length, 0)

  if (unmatchedCount > 0) {
    toast.success(`Imported ${roomCount} rooms (${matchedCount} matched template, ${unmatchedCount} added as new), ${itemCount} items`)
  } else {
    toast.success(`Imported ${roomCount} rooms, ${itemCount} items from PDF`)
  }
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
      if (!reportData.value[sid][rid]._photoTs) reportData.value[sid][rid]._photoTs = []
      // Pad _photoTs to match _photos length, then set timestamp for this photo
      const idx = reportData.value[sid][rid]._photos.length - 1
      reportData.value[sid][rid]._photoTs[idx] = new Date().toISOString()
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
const photoViewer = ref({
  show: false, photos: [], index: 0, ref: '', label: '',
  sectionId: null, rowId: null, // source location for move/delete
})
// Client photo settings — loaded from report_photo_settings JSON on the client record
const clientPhotoSettings = ref({})
// All client report settings (colours, orientation) — stored separately so they're never lost
const clientReportSettings = ref({})
const showPhotoTimestamp       = computed(() => clientPhotoSettings.value.show_photo_timestamp === true)
const actionSummaryPosition    = computed(() => clientPhotoSettings.value.action_summary_position || 'bottom')

async function loadClientSettings() {
  const clientId = inspection.value?.client_id
  if (!clientId) return
  try {
    const cRes = await api.getClient(clientId)
    const ps = JSON.parse(cRes.data.report_photo_settings || '{}')
    clientPhotoSettings.value = { ...ps }
    clientReportSettings.value = {
      report_header_text_color: cRes.data.report_header_text_color || '#FFFFFF',
      report_body_text_color:   cRes.data.report_body_text_color   || '#1e293b',
      report_orientation:       cRes.data.report_orientation       || 'portrait',
      report_color_override:    cRes.data.report_color_override    || null,
      primary_color:            cRes.data.primary_color            || '#1E3A8A',
    }
    console.log('[PDF] settings loaded for client', clientId, clientReportSettings.value)
  } catch (err) {
    console.error('[PDF] loadClientSettings failed:', err)
    clientPhotoSettings.value = {}
  }
}
// Action catalogue — names + colours for the summary panel
const actionCatalogue = ref([])

// PDF export modal
const showPdfModal = ref(false)

// Build the Check Out action summary: items grouped by actionId
const actionSummaryGroups = computed(() => {
  if (!isCheckOut.value) return []
  if (actionSummaryPosition.value === 'none') return []

  const groups = {}  // actionId → { name, color, items[] }

  for (const room of rooms.value) {
    const roomData = reportData.value[String(room.id)] || {}
    const roomName = getRoomName(room)
    const orderedItems = getOrderedRoomItems(room)

    for (const item of orderedItems) {
      const itemKey = item._type === 'extra' ? item._eid : String(item.id)
      const actKey  = `_actions_${itemKey}`
      const actions = roomData[actKey]
      if (!Array.isArray(actions) || !actions.length) continue

      const itemLabel = item.label || item.name || 'Item'
      const refNum    = itemRef(room.id, orderedItems, itemKey)

      for (const a of actions) {
        if (!a.actionId) continue
        if (!groups[a.actionId]) {
          const cat = actionCatalogue.value.find(c => c.id === a.actionId)
          groups[a.actionId] = {
            actionId: a.actionId,
            name:     cat?.name  || a.actionId,
            color:    cat?.color || '#64748b',
            items:    [],
          }
        }
        groups[a.actionId].items.push({
          roomName:       roomName,
          itemLabel:      itemLabel,
          ref:            refNum,
          responsibility: a.responsibility || '',
          condition:      a.condition      || '',
        })
      }
    }
  }

  return Object.values(groups)
})
// Multi-select state: set of selected indices
const lbSelected  = ref(new Set())
const lbMoving    = ref(false)   // whether move-picker is open

function getItemPhotos(roomId, itemId) {
  return reportData.value[roomId]?.[String(itemId)]?.photos || []
}
function openItemPhotos(ref, label, photos, startIndex = 0) {
  if (!photos.length) return
  photoViewer.value = { show: true, photos, index: startIndex, ref, label, sectionId: null, rowId: null }
  lbSelected.value  = new Set()
  lbMoving.value    = false
}
function openLightbox(sectionId, rowId, index) {
  const photos = getPhotos(sectionId, rowId)
  if (!photos.length) return
  photoViewer.value = { show: true, photos, index, ref: '', label: '', sectionId, rowId: String(rowId) }
  lbSelected.value  = new Set()
  lbMoving.value    = false
}
function photoViewerNext() { if (photoViewer.value.index < photoViewer.value.photos.length - 1) photoViewer.value.index++ }
function photoViewerPrev() { if (photoViewer.value.index > 0) photoViewer.value.index-- }
function closeLightbox() { photoViewer.value.show = false; lbSelected.value = new Set(); lbMoving.value = false }

// Delete current photo, or all selected photos from the lightbox
function lbDeletePhotos() {
  const { sectionId, rowId, index } = photoViewer.value
  if (!sectionId) return
  const arr = reportData.value[sectionId]?.[rowId]?._photos
  if (!arr) return

  const toDelete = lbSelected.value.size > 0
    ? [...lbSelected.value].sort((a,b) => b - a)   // reverse for safe splice
    : [index]

  // Splice in reverse order
  toDelete.forEach(i => arr.splice(i, 1))
  unsaved.value = true
  lbSelected.value = new Set()

  if (!arr.length) { closeLightbox(); return }

  // Stay on a valid index
  const newIdx = Math.min(photoViewer.value.index, arr.length - 1)
  photoViewer.value.photos = [...arr]
  photoViewer.value.index  = newIdx
  toast.success(toDelete.length + ' photo' + (toDelete.length !== 1 ? 's' : '') + ' deleted')
}

// Delete selected photos from the grid
function gridDeletePhotos() {
  if (!gridSelected.value.size) return
  const { sectionId, rowId, allSection } = photoGrid.value

  if (allSection) {
    // Remove from their individual source arrays
    // Group by source to batch-delete
    const bySource = {}
    ;[...gridSelected.value].sort((a,b) => b-a).forEach(i => {
      const entry = pgAllPhotos.value[i]
      if (!entry) return
      const key = entry.sectionId + ':' + entry.rowId
      if (!bySource[key]) bySource[key] = { sectionId: entry.sectionId, rowId: entry.rowId, indices: [] }
      bySource[key].indices.push(entry.index)
    })
    Object.values(bySource).forEach(({ sectionId: sid, rowId: rid, indices }) => {
      const arr = reportData.value[sid]?.[rid]?._photos
      if (!arr) return
      ;[...new Set(indices)].sort((a,b) => b-a).forEach(i => arr.splice(i, 1))
    })
    unsaved.value = true
    const count = gridSelected.value.size
    gridSelected.value = new Set()
    pgMoving.value = false
    toast.success(count + ' photo' + (count !== 1 ? 's' : '') + ' deleted')
    // Rebuild the flat array
    // Re-open to refresh (find which sec/room it was)
    closePhotoGrid()
    return
  }

  const arr = reportData.value[sectionId]?.[rowId]?._photos
  if (!arr) return
  const count = gridSelected.value.size
  ;[...gridSelected.value].sort((a,b) => b-a).forEach(i => arr.splice(i, 1))
  unsaved.value = true
  gridSelected.value = new Set()
  pgMoving.value = false
  toast.success(count + ' photo' + (count !== 1 ? 's' : '') + ' deleted')
  if (!arr.length) closePhotoGrid()
}

// ── Photo grid (View All) ─────────────────────────────────────────────
const photoGrid = ref({ show: false, sectionId: null, rowId: null, label: '', allSection: false })

// Count total photos across an entire section (all rows + extras)
function sectionPhotoCount(sec) {
  let total = 0
  for (const row of (sec.rows || [])) {
    total += getPhotos(sec.id, row.id).length
  }
  for (const ex of getExtra(sec.id)) {
    total += getPhotos(sec.id, ex._eid).length
  }
  return total
}

// Count total photos across a room (overview + all items)
function roomPhotoCount(room) {
  let total = getPhotos(room.id, '_overview').length
  for (const item of getOrderedRoomItems(room)) {
    const iid = item._type === 'extra' ? item._eid : String(item.id)
    total += getPhotos(room.id, iid).length
  }
  return total
}

// Get all photos across a section as flat array of { photo, sectionId, rowId, index, label }
function getSectionAllPhotos(sec) {
  const all = []
  for (const row of (sec.rows || [])) {
    if (isHidden(sec.id, row.id)) continue
    const photos = getPhotos(sec.id, row.id)
    photos.forEach((ph, i) => all.push({ photo: ph, sectionId: sec.id, rowId: String(row.id), index: i, label: row.name }))
  }
  for (const ex of getExtra(sec.id)) {
    const photos = getPhotos(sec.id, ex._eid)
    photos.forEach((ph, i) => all.push({ photo: ph, sectionId: sec.id, rowId: ex._eid, index: i, label: ex.name || 'Extra' }))
  }
  return all
}

function getRoomAllPhotos(room) {
  const all = []
  const ov = getPhotos(room.id, '_overview')
  ov.forEach((ph, i) => all.push({ photo: ph, sectionId: room.id, rowId: '_overview', index: i, label: 'Overview' }))
  for (const item of getOrderedRoomItems(room)) {
    const iid = item._type === 'extra' ? item._eid : String(item.id)
    const photos = getPhotos(room.id, iid)
    const lbl = item.label || item._label || iid
    photos.forEach((ph, i) => all.push({ photo: ph, sectionId: room.id, rowId: iid, index: i, label: lbl }))
  }
  return all
}

// Section-level "View All" — opens grid showing all photos with sub-labels
const pgAllPhotos = ref([]) // flat array when viewing whole section/room

function openSectionPhotoGrid(sec) {
  const all = getSectionAllPhotos(sec)
  if (!all.length) return
  pgAllPhotos.value = all
  photoGrid.value = { show: true, sectionId: sec.id, rowId: null, label: sec.name, allSection: true }
  gridSelected.value = new Set()
  pgMoving.value = false
}

function openRoomPhotoGrid(room) {
  const all = getRoomAllPhotos(room)
  if (!all.length) return
  pgAllPhotos.value = all
  photoGrid.value = { show: true, sectionId: room.id, rowId: null, label: room.name, allSection: true }
  gridSelected.value = new Set()
  pgMoving.value = false
}
const gridSelected = ref(new Set())

function openPhotoGrid(sectionId, rowId, label) {
  pgAllPhotos.value = []
  photoGrid.value  = { show: true, sectionId, rowId: String(rowId), label, allSection: false }
  gridSelected.value = new Set()
  pgMoving.value = false
}
function closePhotoGrid() { photoGrid.value.show = false; gridSelected.value = new Set(); pgMoving.value = false; pgAllPhotos.value = [] }

function openFromGrid(idx) {
  const { sectionId, rowId, label } = photoGrid.value
  closePhotoGrid()
  openLightbox(sectionId, rowId, idx)
  photoViewer.value.label = label
}

function gridToggleSelect(idx) {
  const s = new Set(gridSelected.value)
  if (s.has(idx)) s.delete(idx); else s.add(idx)
  gridSelected.value = s
}
function gridSelectAll() {
  const photos = getPhotos(photoGrid.value.sectionId, photoGrid.value.rowId)
  gridSelected.value = new Set(photos.map((_, i) => i))
}
function gridClearSelection() { gridSelected.value = new Set() }

// Open selected grid photos in lightbox
function openGridSelectionInLightbox() {
  if (!gridSelected.value.size) return
  const first = Math.min(...gridSelected.value)
  const { sectionId, rowId, label } = photoGrid.value
  closePhotoGrid()
  openLightbox(sectionId, rowId, first)
  photoViewer.value.label = label
  lbSelected.value = new Set(gridSelected.value)
}

// Move selected grid photos to another section
function gridMovePhotos(destSectionId, destRowId) {
  const { sectionId, rowId, allSection } = photoGrid.value
  const indices = gridSelected.value.size > 0
    ? [...gridSelected.value].sort((a, b) => a - b)
    : []
  if (!indices.length) return

  // Add to destination (shared for both modes)
  const dsid = destSectionId, drid = String(destRowId)
  if (!reportData.value[dsid]) reportData.value[dsid] = {}
  if (!reportData.value[dsid][drid]) reportData.value[dsid][drid] = {}
  if (!reportData.value[dsid][drid]._photos) reportData.value[dsid][drid]._photos = []
  const destArr = reportData.value[dsid][drid]._photos

  if (allSection) {
    // Each pgAllPhotos entry has { photo, sectionId, rowId, index }
    // Collect photo data first, then group splices by source array
    const bySource = {}
    indices.forEach(i => {
      const entry = pgAllPhotos.value[i]
      if (!entry) return
      destArr.push(entry.photo)  // collect photo data before any splicing
      const key = entry.sectionId + '::' + entry.rowId
      if (!bySource[key]) bySource[key] = { sectionId: entry.sectionId, rowId: entry.rowId, indices: [] }
      bySource[key].indices.push(entry.index)
    })
    // Splice from each source in reverse-index order so positions don't shift
    Object.values(bySource).forEach(({ sectionId: sid, rowId: rid, indices: idxs }) => {
      const arr = reportData.value[sid]?.[rid]?._photos
      if (!arr) return
      ;[...new Set(idxs)].sort((a, b) => b - a).forEach(i => arr.splice(i, 1))
    })
    unsaved.value = true
    const count = gridSelected.value.size
    gridSelected.value = new Set()
    // Rebuild flat photo list and keep grid open
    // Re-trigger the allSection view so pgAllPhotos refreshes
    const origSec = sectionId
    const origLabel = photoGrid.value.label
    // Recollect the photos for this section/room
    const sec = fixedSections.value.find(s => s.id === origSec)
    const room = rooms.value.find(r => r.id === origSec)
    if (sec) {
      const all = getSectionAllPhotos(sec)
      pgAllPhotos.value = all
      if (!all.length) { closePhotoGrid(); toast.success(count + ' photo(s) moved'); return }
    } else if (room) {
      const all = getRoomAllPhotos(room)
      pgAllPhotos.value = all
      if (!all.length) { closePhotoGrid(); toast.success(count + ' photo(s) moved'); return }
    }
    toast.success(count + ' photo(s) moved')
    // pgMoving stays open, tree stays open
    return
  }

  // Single-item mode
  const srcArr = reportData.value[sectionId]?.[rowId]?._photos
  if (!srcArr) return
  const toMove = indices.map(i => srcArr[i])
  destArr.push(...toMove)
  ;[...indices].reverse().forEach(i => srcArr.splice(i, 1))
  unsaved.value = true
  gridSelected.value = new Set()
  // pgMoving stays open; pgTreeExpanded keeps whatever groups user had open
  toast.success(toMove.length + ' photo(s) moved')
  if (!srcArr.length) closePhotoGrid()
  // else tree stays visible for further moves
}

// Photo grid move tree state
const pgMoving = ref(false)
const pgTreeExpanded = ref(new Set())

function pgOpenMoveTree() {
  // Start collapsed — user expands what they need
  // pgTreeExpanded is preserved across opens so last-used groups stay open
  pgMoving.value = true
}
function pgTreeToggle(key) {
  const s = new Set(pgTreeExpanded.value)
  if (s.has(key)) s.delete(key); else s.add(key)
  pgTreeExpanded.value = s
}

const pgMoveTree = computed(() => {
  const tree = []
  const srcSid = photoGrid.value.sectionId
  const srcRid = photoGrid.value.rowId

  for (const sec of fixedSections.value) {
    const children = []
    for (const row of (sec.rows || [])) {
      if (isHidden(sec.id, row.id)) continue
      if (srcSid === sec.id && srcRid === String(row.id)) continue
      children.push({ key: sec.id+':'+row.id, label: fixedRowRef(sec, row.id) + ' · ' + row.name, sectionId: sec.id, rowId: String(row.id) })
    }
    for (const ex of getExtra(sec.id)) {
      if (srcSid === sec.id && srcRid === ex._eid) continue
      children.push({ key: sec.id+':'+ex._eid, label: '(extra) ' + (ex.name || ex._eid), sectionId: sec.id, rowId: ex._eid })
    }
    if (children.length) tree.push({ key: 'pgsec_'+sec.id, label: fixedSectionIndexMap.value[sec.id] + ' · ' + sec.name, type: 'fixed', children })
  }

  for (const room of rooms.value) {
    const children = []
    if (!(srcSid === room.id && srcRid === '_overview'))
      children.push({ key: room.id+'_overview', label: 'Overview', sectionId: room.id, rowId: '_overview' })
    for (const item of getOrderedRoomItems(room)) {
      const iid = item._type === 'extra' ? item._eid : String(item.id)
      if (srcSid === room.id && srcRid === iid) continue
      children.push({ key: room.id+':'+iid, label: item.label || item._label || iid, sectionId: room.id, rowId: iid })
    }
    if (children.length) tree.push({ key: 'pgroom_'+room.id, label: room.name, type: 'room', children })
  }
  return tree
})

// ── Tree-style move destinations ──────────────────────────────────────
// Groups destinations by parent section/room with expand/collapse
const lbTreeExpanded = ref(new Set())

function lbTreeToggle(key) {
  const s = new Set(lbTreeExpanded.value)
  if (s.has(key)) s.delete(key); else s.add(key)
  lbTreeExpanded.value = s
}

function lbOpenMoveTree() {
  // Start collapsed — lbTreeExpanded persists so last-used sections stay open
  lbMoving.value = true
}

const lbMoveTree = computed(() => {
  const tree = []
  const srcSid = photoViewer.value.sectionId
  const srcRid = photoViewer.value.rowId

  // Fixed sections
  for (const sec of fixedSections.value) {
    const children = []
    for (const row of (sec.rows || [])) {
      if (isHidden(sec.id, row.id)) continue
      if (srcSid === sec.id && srcRid === String(row.id)) continue
      children.push({ key: sec.id+':'+row.id, label: fixedRowRef(sec, row.id) + ' · ' + row.name, sectionId: sec.id, rowId: String(row.id) })
    }
    for (const ex of getExtra(sec.id)) {
      if (srcSid === sec.id && srcRid === ex._eid) continue
      children.push({ key: sec.id+':'+ex._eid, label: '(extra) ' + (ex.name || ex._eid), sectionId: sec.id, rowId: ex._eid })
    }
    if (children.length) tree.push({ key: 'sec_' + sec.id, label: fixedSectionIndexMap.value[sec.id] + ' · ' + sec.name, type: 'section', children })
  }

  // Rooms
  for (const room of rooms.value) {
    const children = []
    // Overview
    if (!(srcSid === room.id && srcRid === '_overview')) {
      children.push({ key: room.id+'_ov', label: 'Overview', sectionId: room.id, rowId: '_overview' })
    }
    for (const item of getOrderedRoomItems(room)) {
      const iid = item._type === 'extra' ? item._eid : String(item.id)
      if (srcSid === room.id && srcRid === iid) continue
      const lbl = item.label || item._label || iid
      children.push({ key: room.id+':'+iid, label: lbl, sectionId: room.id, rowId: iid })
    }
    if (children.length) tree.push({ key: 'room_' + room.id, label: room.name, type: 'room', children })
  }

  return tree
})



// Toggle selection of a photo by index
function lbToggleSelect(idx) {
  const s = new Set(lbSelected.value)
  if (s.has(idx)) s.delete(idx); else s.add(idx)
  lbSelected.value = s
}
function lbSelectAll() {
  lbSelected.value = new Set(photoViewer.value.photos.map((_, i) => i))
}
function lbClearSelection() { lbSelected.value = new Set() }

// Rotate current photo 90° clockwise using canvas
async function lbRotateCurrent() {
  const idx = photoViewer.value.index
  const src = photoViewer.value.photos[idx]
  if (!src) return
  const rotated = await rotateBase64(src, 90)
  photoViewer.value.photos.splice(idx, 1, rotated)
  // Persist back to reportData
  const { sectionId, rowId } = photoViewer.value
  if (sectionId && rowId) {
    const arr = reportData.value[sectionId]?.[rowId]?._photos
    if (arr) { arr.splice(idx, 1, rotated); unsaved.value = true }
  }
}

function rotateBase64(base64, degrees) {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      const swap   = degrees % 180 !== 0
      canvas.width  = swap ? img.height : img.width
      canvas.height = swap ? img.width  : img.height
      const ctx = canvas.getContext('2d')
      ctx.translate(canvas.width / 2, canvas.height / 2)
      ctx.rotate((degrees * Math.PI) / 180)
      ctx.drawImage(img, -img.width / 2, -img.height / 2)
      resolve(canvas.toDataURL('image/jpeg', 0.92))
    }
    img.src = base64
  })
}

// Move selected photos (or current if none selected) to another section/item
function lbMovePhotos(destSectionId, destRowId) {
  const { sectionId, rowId, photos } = photoViewer.value
  if (!sectionId || !rowId) { toast.warning('Cannot move — source location unknown'); return }

  const indices = lbSelected.value.size > 0
    ? [...lbSelected.value].sort((a, b) => a - b)
    : [photoViewer.value.index]

  const toMove = indices.map(i => photos[i])

  // Add to destination
  const dsid = destSectionId, drid = String(destRowId)
  if (!reportData.value[dsid]) reportData.value[dsid] = {}
  if (!reportData.value[dsid][drid]) reportData.value[dsid][drid] = {}
  if (!reportData.value[dsid][drid]._photos) reportData.value[dsid][drid]._photos = []
  reportData.value[dsid][drid]._photos.push(...toMove)

  // Remove from source (splice in reverse order so indices stay valid)
  const srcArr = reportData.value[sectionId]?.[rowId]?._photos
  if (srcArr) {
    ;[...indices].reverse().forEach(i => srcArr.splice(i, 1))
  }

  unsaved.value = true
  lbSelected.value = new Set()
  // Keep tree visible and expanded state intact for further moves

  // If no photos left, close lightbox
  if (!srcArr || srcArr.length === 0) {
    closeLightbox()
    toast.success(`${toMove.length} photo(s) moved`)
  } else {
    // Refresh viewer photos
    photoViewer.value.photos = [...srcArr]
    photoViewer.value.index  = Math.min(photoViewer.value.index, srcArr.length - 1)
    toast.success(`${toMove.length} photo(s) moved`)
    // lbMoving stays true — tree stays open
  }
}

// Build flat list of all move destinations (section + row combos)
const lbMoveDestinations = computed(() => {
  const dests = []
  for (const sec of fixedSections.value) {
    for (const row of (sec.rows || [])) {
      if (isHidden(sec.id, row.id)) continue
      const skip = photoViewer.value.sectionId === sec.id && photoViewer.value.rowId === String(row.id)
      if (skip) continue
      dests.push({ label: fixedItemLabel(sec, row.id, row.name), sectionId: sec.id, rowId: String(row.id) })
    }
    for (const ex of getExtra(sec.id)) {
      const skip = photoViewer.value.sectionId === sec.id && photoViewer.value.rowId === ex._eid
      if (skip) continue
      dests.push({ label: sec.name + ' — (extra)', sectionId: sec.id, rowId: ex._eid })
    }
  }
  for (const room of rooms.value) {
    dests.push({ label: room.name + ' — Overview', sectionId: room.id, rowId: '_overview' })
    for (const item of getOrderedRoomItems(room)) {
      const iid = item._type === 'extra' ? item._eid : String(item.id)
      const skip = photoViewer.value.sectionId === room.id && photoViewer.value.rowId === iid
      if (skip) continue
      const lbl  = item.label || item._label || ('Item ' + iid)
      dests.push({ label: room.name + ' — ' + lbl, sectionId: room.id, rowId: iid })
    }
  }
  return dests
})

// Check In condition read-only getter — reads from the source Check In's saved report_data
function getCI(sectionId, rowId, field) {
  return sourceReportData.value[sectionId]?.[String(rowId)]?.[field] ?? ''
}

// ── Parse template ────────────────────────────────────────────────────
// Fixed sections come from the system-wide API (Settings → Fixed Sections).
// Each raw section has: { name, enabled, columns: ['name','condition',...], items: [{name,...}] }
// We adapt them into the shape the renderer expects: { id, name, type, rows: [{id, ...fields}] }
//
// Column-set → legacy type mapping:
//   includes 'condition'        → condition_summary
//   includes 'cleanliness'      → cleaning_summary
//   includes 'reading'          → meter_readings
//   includes 'question','answer'+ has 'name' col → fire_door_safety
//   includes 'answer' only (no 'name' as primary label, question is the label) → smoke_alarms / health_safety
//   includes 'description' (no answer/cleanliness/reading) → keys
//   fallback                    → condition_summary

function _inferType(cols) {
  const c = cols || []
  if (c.includes('reading'))                         return 'meter_readings'
  if (c.includes('cleanliness'))                     return 'cleaning_summary'
  if (c.includes('condition'))                       return 'condition_summary'
  // Has both name + question/answer → fire door style table
  if (c.includes('name') && c.includes('answer') && c.includes('question')) return 'fire_door_safety'
  // Question-led (no name col, or question is primary) → smoke alarms style
  if (c.includes('answer') && c.includes('question'))  return 'smoke_alarms'
  if (c.includes('answer') && c.includes('name'))      return 'smoke_alarms'
  if (c.includes('description'))                     return 'keys'
  return 'condition_summary'
}

// Map an item from the new format to the row field names the renderer uses for each type
function _adaptItem(item, type, idx, secIdx) {
  const id = `fs_${secIdx}_${idx}`
  switch (type) {
    case 'meter_readings':
      return { id, name: item.name || '', locationSerial: item.location_serial || '', reading: item.reading || '' }
    case 'cleaning_summary':
      return { id, name: item.name || '', cleanliness: '', cleanlinessNotes: item.additional_notes || '' }
    case 'condition_summary':
      return { id, name: item.name || '', condition: item.condition || item.description || '' }
    case 'fire_door_safety':
      return { id, name: item.name || '', question: item.question || '', answer: '', notes: item.additional_notes || '' }
    case 'smoke_alarms':
    case 'health_safety':
      // question is the row label
      return { id, question: item.name || item.question || '', answer: '', notes: item.additional_notes || '' }
    case 'keys':
      return { id, name: item.name || '', description: item.description || '' }
    default:
      return { id, name: item.name || '', condition: '' }
  }
}

const fixedSections = computed(() =>
  (fixedSectionsRaw.value || [])
    .filter(s => s.enabled !== false)
    .map((s, secIdx) => {
      const type = _inferType(s.columns)
      const rows = (s.items || []).map((item, i) => _adaptItem(item, type, i, secIdx))
      return {
        id:   `fs_${secIdx}_${s.name.toLowerCase().replace(/[^a-z0-9]/g, '_')}`,
        name: s.name,
        type,
        rows,
      }
    })
)

// Rooms come from the template's relational sections (section_type === 'room')
// The room renderer expects room.sections as the list of items
const rooms = computed(() => {
  let templateRooms = []
  if (!template.value?.sections) {
    // Fallback: try legacy JSON blob
    try {
      const parsed = JSON.parse(template.value?.content || '{}')
      templateRooms = (parsed.rooms || []).filter(r => r.enabled !== false)
    } catch { templateRooms = [] }
  } else {
    templateRooms = template.value.sections
      .filter(s => s.section_type === 'room')
      .map(s => ({
        ...s,
        // Apply any saved name override from reportData._roomNames
        name: reportData.value._roomNames?.[String(s.id)] ?? s.name,
        sections: (s.items || []).map(item => ({
          ...item,
          label:          item.name || item.label || '',
          hasDescription: true,
          hasCondition:   item.requires_condition !== false,
        })),
      }))
  }

  // Append any rooms imported from PDF that didn't match the template
  const importedRooms = (reportData.value._importedRooms || []).map(r => ({
    ...r,
    _isImported: true,
    sections:    [],   // items are stored as _extra in reportData
  }))

  return [...templateRooms, ...importedRooms]
})
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

// ── Room name overrides ────────────────────────────────────────────────────
// Stored in reportData._roomNames: { [roomId]: customName }
// Only used in the report editor — does NOT affect the template.
function getRoomName(room) {
  return reportData.value._roomNames?.[String(room.id)] ?? room.name
}
const renamingRoomId = ref(null)
const renamingRoomVal = ref('')

function startRenameRoom(room) {
  renamingRoomId.value  = String(room.id)
  renamingRoomVal.value = getRoomName(room)
}
function commitRenameRoom(room) {
  const val = renamingRoomVal.value.trim()
  if (val && val !== room.name) {
    if (!reportData.value._roomNames) reportData.value._roomNames = {}
    reportData.value._roomNames[String(room.id)] = val
    unsaved.value = true
  } else if (!val) {
    // Empty → remove override, revert to template name
    if (reportData.value._roomNames) delete reportData.value._roomNames[String(room.id)]
  }
  renamingRoomId.value = null
}
function cancelRenameRoom() {
  renamingRoomId.value = null
}


function getItemActions(roomId, itemId) {
  const key = `_actions_${itemId}`
  return reportData.value[roomId]?.[key] ?? []
}
const expandedActions = ref({})
function toggleActionExpanded(roomId, itemId) {
  const key = `${roomId}_${itemId}`
  expandedActions.value[key] = !expandedActions.value[key]
}
function isActionExpanded(roomId, itemId) {
  const key = `${roomId}_${itemId}`
  return !!expandedActions.value[key]
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
    // Serialise recordings as base64 into reportData._recordings so they
    // survive page navigation. Blobs are in-memory only — must be converted.
    const serialisedRecs = await Promise.all(
      recordings.value.map(async (rec) => {
        let audioB64 = rec._savedB64 || null
        if (!audioB64 && rec.blob) {
          audioB64 = await _blobToBase64(rec.blob)
          rec._savedB64 = audioB64  // cache to avoid re-encoding on next save
        }
        return {
          id:         rec.id,
          audioB64,
          mimeType:   rec.mimeType,
          duration:   rec.duration,
          createdAt:  rec.createdAt,
          label:      rec.label,
          itemKey:    rec.itemKey,
          transcript: rec.transcript,
          gptResult:  rec.gptResult,
        }
      })
    )
    const dataToSave = { ...reportData.value, _recordings: serialisedRecs }
    await api.updateInspection(inspection.value.id, { report_data: JSON.stringify(dataToSave) })
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

// ── AI Transcription state ────────────────────────────────────────────
const aiProcessing     = ref(false)       // true while full-report AI call is in-flight
const aiItemProcessing = ref(new Set())   // set of "sectionId:rowId" keys currently processing
const aiError          = ref('')
const hasAiTypist      = ref(false)       // true if this inspection is assigned to AI typist
const hasHumanTypist   = ref(false)       // true if assigned to a human typist (no recording in UI)
const aiKeysAvailable  = ref(false)       // true if API keys are configured on the backend

function checkAiTypist() {
  if (!inspection.value) return
  // typist info is nested under inspection.value.typist.name (not typist_name)
  hasAiTypist.value = inspection.value.typist_is_ai === true ||
                      inspection.value.typist?.name === 'AI Typist' ||
                      inspection.value.typist_name === 'AI Typist'
  // Human typist: a typist is assigned and it's not AI
  hasHumanTypist.value = !hasAiTypist.value && !!(
    inspection.value.typist_id ||
    inspection.value.typist?.id ||
    inspection.value.typist_name
  )
}

async function checkAiKeys() {
  try {
    const res = await api.checkAiStatus()
    console.log('[AI] status:', res.data)
    // Only Anthropic key is required for item transcription (Claude fills fields)
    // OpenAI/Whisper is also needed for audio — require both for full AI typist
    aiKeysAvailable.value = !!(res.data.anthropic_key_set && res.data.openai_key_set)
    if (!aiKeysAvailable.value) {
      console.warn('[AI] keys missing — anthropic:', res.data.anthropic_key_set, 'openai:', res.data.openai_key_set)
    }
  } catch (e) {
    console.warn('[AI] checkAiKeys failed:', e.message)
    aiKeysAvailable.value = false
  }
}

function isItemAiProcessing(sid, rid) {
  return aiItemProcessing.value.has(`${sid}:${String(rid)}`)
}

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
      if (recordingChunks.value.length === 0) {
        itemRecordingKey.value = null
        return
      }
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

      // ── AI: per-item auto-transcribe ──────────────────────────────────
      // If this was a per-item recording and AI typist is assigned,
      // immediately send to Whisper + Claude
      if (itemKey && (hasAiTypist.value || aiKeysAvailable.value)) {
        const parts     = itemKey.split(':')
        const sid       = parts[0]
        const rid       = parts.slice(1).join(':')
        const baseLabel = rec.label.replace(/ \(\d+\)$/, '')
        const dashIdx   = baseLabel.indexOf(' — ')
        const roomLabel = dashIdx !== -1 ? baseLabel.slice(0, dashIdx) : ''
        const itemLabel = dashIdx !== -1 ? baseLabel.slice(dashIdx + 3) : baseLabel

        // Detect section type from the template so Claude knows which fields to fill
        const secObj    = allSections.value.find(s => String(s.id) === String(sid))
        const secType   = secObj?.type || 'room'

        _transcribeItem(rec, sid, rid, itemLabel, roomLabel, secType)
      }
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

// ── AI Transcription ─────────────────────────────────────────────────
// Convert a blob to base64
function _blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload  = () => resolve(reader.result.split(',')[1])
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}

// Per-item transcription — called immediately when a short clip stops
async function _transcribeItem(rec, sectionId, rowId, itemLabel, roomName, sectionType = 'room') {
  const key = `${sectionId}:${rowId}`
  const s   = new Set(aiItemProcessing.value)
  s.add(key)
  aiItemProcessing.value = s
  aiError.value = ''

  try {
    const audioB64 = await _blobToBase64(rec.blob)

    const response = await api.transcribeItem({
      audio:       audioB64,
      mimeType:    rec.mimeType || 'audio/webm',
      itemLabel,
      roomName,
      sectionId,
      rowId,
      sectionType,
    })

    const result = response.data
    console.log('[AI transcribe] response:', result)
    console.log('[AI transcribe] targeting sid:', sectionId, 'rid:', String(rowId))
    console.log('[AI transcribe] reportData keys:', Object.keys(reportData.value))

    // Store transcript on the recording object for reference
    rec.transcript = result.transcript
    rec.gptResult  = { description: result.description, condition: result.condition }

    // Fill report fields — only fill if currently empty to preserve manual entry
    // Always use String() for rowId — keys in reportData are always strings
    const sid = String(sectionId)
    const rid = String(rowId)

    // Ensure the nested path exists
    if (!reportData.value[sid]) reportData.value[sid] = {}
    if (!reportData.value[sid][rid]) reportData.value[sid][rid] = {}

    let changed = false
    const row = reportData.value[sid][rid]
    const st  = result.sectionType || sectionType

    // ── Edit mode helpers ─────────────────────────────────────────────────
    // editMode:  'normal' | 'overwrite' | 'append'
    // editField: 'description' | 'condition' | null
    const editMode  = result.editMode  || 'normal'
    const editField = result.editField || null

    function shouldWrite(field, value) {
      if (!value) return false
      if (editMode === 'normal')    return !row[field]           // only if empty
      if (editMode === 'overwrite') return editField === field   // overwrite target field
      if (editMode === 'append')    return editField === field   // append to target field
      return false
    }
    function writeField(field, value) {
      if (editMode === 'append' && row[field]) {
        row[field] = row[field].trimEnd() + '\n' + value
      } else {
        row[field] = value
      }
      changed = true
    }

    // ── Map returned fields to the correct reportData fields ───────────
    if (st === 'meter_readings') {
      if (result.locationSerial && !row.locationSerial) { row.locationSerial = result.locationSerial; changed = true }
      if (result.reading        && !row.reading)        { row.reading        = result.reading;        changed = true }
    } else if (st === 'keys') {
      if (shouldWrite('description', result.description)) writeField('description', result.description)
    } else if (st === 'condition_summary') {
      if (shouldWrite('condition', result.condition)) writeField('condition', result.condition)
    } else if (st === 'cleaning_summary') {
      const cn = result.cleanlinessNotes || result.notes
      if (cn && !row.cleanlinessNotes) { row.cleanlinessNotes = cn; changed = true }
    } else if (st === 'fire_door_safety' || st === 'health_safety' || st === 'smoke_alarms') {
      if (result.notes && !row.notes) { row.notes = result.notes; changed = true }
    } else {
      // Default room item — description + condition
      if (shouldWrite('description', result.description)) writeField('description', result.description)
      if (shouldWrite('condition',   result.condition))   writeField('condition',   result.condition)
    }

    console.log('[AI transcribe] changed:', changed, 'data now:', reportData.value[sid][rid])

    if (changed) {
      unsaved.value = true
      await save(false)
      if (editMode === 'overwrite') {
        toast.success(`✏️ Amended: ${itemLabel}`)
      } else if (editMode === 'append') {
        toast.success(`➕ Added to: ${itemLabel}`)
      } else {
        toast.success(`✨ AI filled: ${itemLabel}`)
      }
    } else if (result.transcript) {
      toast.info(`✨ Transcribed: ${itemLabel} (no changes made)`)
    }

  } catch (err) {
    console.error('[AI transcribe item]', err)
    aiError.value = `AI transcription failed: ${err.message}`
    toast.error(`AI transcription failed — ${err.message}`)
  } finally {
    const s2 = new Set(aiItemProcessing.value)
    s2.delete(key)
    aiItemProcessing.value = s2
  }
}

// Full inspection transcription — for continuous general recordings
async function transcribeFullInspection() {
  const generalRecs = recordings.value.filter(r => !r.itemKey)
  if (!generalRecs.length) {
    toast.warning('No continuous recording found to transcribe')
    return
  }

  aiProcessing.value = true
  aiError.value = ''
  toast.success('🎙 Processing audio — this may take a minute…')

  try {
    const rec      = generalRecs[generalRecs.length - 1]
    const audioB64 = await _blobToBase64(rec.blob)
    const templateStructure = _buildTemplateStructureForAI()

    const response = await api.transcribeFull({
      audio:    audioB64,
      mimeType: rec.mimeType || 'audio/webm',
      template: templateStructure,
    })

    const result  = response.data
    rec.transcript = result.transcript

    // Merge filled data — only overwrite empty fields
    let filledCount = 0
    for (const [sid, rows] of Object.entries(result.filled || {})) {
      if (!reportData.value[sid]) reportData.value[sid] = {}
      for (const [rid, fields] of Object.entries(rows)) {
        if (!reportData.value[sid][rid]) reportData.value[sid][rid] = {}
        if (fields.description && !reportData.value[sid][rid].description) {
          reportData.value[sid][rid].description = fields.description
          filledCount++
        }
        if (fields.condition && !reportData.value[sid][rid].condition) {
          reportData.value[sid][rid].condition = fields.condition
          filledCount++
        }
      }
    }

    unsaved.value = true
    await save(false)
    toast.success(`✨ AI filled ${filledCount} fields from transcript`)

  } catch (err) {
    console.error('[AI transcribe full]', err)
    aiError.value = `Full transcription failed: ${err.message}`
    toast.error(`Transcription failed — ${err.message}`)
  } finally {
    aiProcessing.value = false
  }
}

// Build simplified template structure for Claude to map against
function _buildTemplateStructureForAI() {
  const structure = {}
  for (const sec of fixedSections.value) {
    structure[sec.id] = { name: sec.name, type: sec.type, rows: {} }
    for (const row of (sec.rows || [])) {
      if (!isHidden(sec.id, row.id)) {
        structure[sec.id].rows[String(row.id)] = { name: row.name || row.question || '' }
      }
    }
  }
  for (const room of rooms.value) {
    structure[room.id] = { name: room.name, type: 'room', rows: {} }
    for (const item of getOrderedRoomItems(room)) {
      const iid = item._type === 'extra' ? item._eid : String(item.id)
      if (!isItemHidden(room.id, item.id || item._eid)) {
        structure[room.id].rows[iid] = { name: item.label || 'Item' }
      }
    }
  }
  return structure
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



// ── Move to Review (typist only) ───────────────────────────────────────────
async function moveToReview() {
  if (!canMoveToReview.value) return
  try {
    await api.put(`/api/inspections/${inspection.value.id}`, { status: 'review' })
    toast.success('Inspection moved to Review')
    router.push('/inspections')
  } catch (e) {
    toast.error('Failed to move to review')
  }
}
</script>

<template>
  <div v-if="loading" class="loading-screen"><div class="ring"></div><p>Loading report…</p></div>

  <div v-else-if="inspection" class="shell" :class="{ 'hide-mic-btns': hasHumanTypist }">

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
        <template v-if="canEdit">
          <button class="pdf-btn" @click="loadClientSettings(); showPdfModal = true">🖨 Export PDF</button>
          <button class="save-btn" :disabled="saving" @click="save()">Save</button>
        </template>
        <template v-if="canMoveToReview">
          <button class="pdf-btn" @click="loadClientSettings(); showPdfModal = true">🖨 Export PDF</button>
          <button class="review-btn" @click="moveToReview">Move to Review</button>
        </template>
        <template v-if="!canEdit">
          <button class="pdf-btn" @click="loadClientSettings(); showPdfModal = true">🖨 Export PDF</button>
          <span class="chip chip-readonly">👁 Read Only</span>
        </template>
      </div>
    </header>



    <div class="body">
      <nav class="sidebar">
        <!-- Mobile: collapsible toggle (hidden on desktop via CSS) -->
        <button class="mobile-nav-toggle" @click="mobileNavOpen = !mobileNavOpen">
          <span class="mobile-nav-toggle-label">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
            Sections
          </span>
          <span class="mobile-nav-toggle-arrow" :class="{ open: mobileNavOpen }">▼</span>
        </button>
        <!-- Nav body: visible on desktop always, collapsible on mobile -->
        <div class="mobile-nav-body" :class="{ 'nav-open': mobileNavOpen }">
          <div v-if="template">
            <div v-if="fixedSections.length" class="nav-grp">
              <p class="nav-lbl">Report Sections</p>
              <button v-for="s in fixedSections" :key="s.id" class="nav-btn" :class="{ active: activeId===s.id }" @click="scrollTo(s.id); mobileNavOpen=false">
                <span class="dot" :class="{ done: sectionStarted(s.id) }"></span><span class="nav-sec-letter">{{ fixedSectionIndexMap[s.id] }}</span>{{ s.name }}
              </button>
            </div>
            <div v-if="rooms.length" class="nav-grp">
              <p class="nav-lbl">Rooms</p>
              <button v-for="r in rooms" :key="r.id" class="nav-btn" :class="{ active: activeId===r.id }" @click="scrollTo(r.id); mobileNavOpen=false">
                <span class="dot" :class="{ done: sectionStarted(r.id) }"></span>{{ r.name }}
              </button>
            </div>
          </div>
          <div v-else class="sidebar-warn">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <p>No Check In report found for this property.</p>
          </div>
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

          <template v-if="actionSummaryPosition === 'top'">
          <!-- ═══ ACTION SUMMARY (Check Out only) ════════════════════ -->
          <div
            v-if="isCheckOut && actionSummaryGroups.length"
            class="card card-action-summary"
          >
            <div class="card-hd card-hd-summary">
              <h2 class="card-title">
                <span class="summary-icon">📋</span>
                Actions Summary
              </h2>
              <span class="card-hint">{{ actionSummaryGroups.reduce((n,g) => n + g.items.length, 0) }} item{{ actionSummaryGroups.reduce((n,g) => n + g.items.length, 0) !== 1 ? 's' : '' }} flagged</span>
            </div>

            <div class="summary-groups">
              <div v-for="group in actionSummaryGroups" :key="group.actionId" class="summary-group">
                <div class="summary-group-hd" :style="{ borderLeftColor: group.color }">
                  <span class="summary-group-dot" :style="{ background: group.color }"></span>
                  <span class="summary-group-name">{{ group.name }}</span>
                  <span class="summary-group-count">{{ group.items.length }} item{{ group.items.length !== 1 ? 's' : '' }}</span>
                </div>
                <table class="summary-tbl">
                  <thead>
                    <tr>
                      <th class="stbl-ref">Ref</th>
                      <th class="stbl-room">Room</th>
                      <th class="stbl-item">Item</th>
                      <th class="stbl-resp">Responsibility</th>
                      <th class="stbl-note">Condition</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(item, i) in group.items" :key="i">
                      <td class="stbl-ref">{{ item.ref }}</td>
                      <td class="stbl-room">{{ item.roomName }}</td>
                      <td class="stbl-item">{{ item.itemLabel }}</td>
                      <td class="stbl-resp">
                        <span v-if="item.responsibility" class="resp-badge" :style="{ background: group.color + '18', color: group.color, borderColor: group.color + '50' }">{{ item.responsibility }}</span>
                        <span v-else class="resp-none">—</span>
                      </td>
                      <td class="stbl-note">{{ item.condition || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          </template>

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
                <button
                  v-if="sectionPhotoCount(sec) > 0"
                  class="card-view-all-btn"
                  @click.stop="openSectionPhotoGrid(sec)"
                  :title="sectionPhotoCount(sec) + ' photos in this section'"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                  View All Photos
                  <span class="card-photo-count">{{ sectionPhotoCount(sec) }}</span>
                </button>
              </div>
            </div>

            <!-- CONDITION SUMMARY -->
            <div v-if="sec.type === 'condition_summary'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Item</th><th>Condition</th><th class="col-btn-group"></th></tr></thead>
                <tbody>
                  <template v-for="row in sec.rows" :key="row.id">
                    <tr v-show="!isHidden(sec.id, row.id)">
                      <td class="td-drag"><span class="drag-handle" title="Drag to reorder">⠿</span></td>
                      <td class="td-name"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.name }}</td>
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Describe condition…" :value="get(sec.id,row.id,'condition')" @input="set(sec.id,row.id,'condition',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" :title="getPhotos(sec.id,row.id).length + ' photo(s)'"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'cam-has mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length }" @click="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record audio for this item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button><button v-if="canDelete" class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row">
                      <td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><button v-if="getPhotos(sec.id,row.id).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,row.id,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td>
                    </tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" :disabled="!canEdit" placeholder="Item name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Describe condition…" :value="ex.condition" @input="setExtraField(sec.id,ex._eid,'condition',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" :title="getPhotos(sec.id,ex._eid).length + ' photo(s)'"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length, 'mic-ai': isItemAiProcessing(sec.id,ex._eid) }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button><button v-if="canDelete" class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row">
                      <td colspan="5" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><button v-if="getPhotos(sec.id,ex._eid).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,ex._eid,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td>
                    </tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button v-if="canEdit" class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
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
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Additional notes…" :value="get(sec.id,row.id,'cleanlinessNotes')" @input="set(sec.id,row.id,'cleanlinessNotes',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length, 'mic-ai': isItemAiProcessing(sec.id,row.id) }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button><button v-if="canDelete" class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><button v-if="getPhotos(sec.id,row.id).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,row.id,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" :disabled="!canEdit" placeholder="Area name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><select class="fld-input" :value="ex.cleanliness" @change="setExtraField(sec.id,ex._eid,'cleanliness',$event.target.value)"><option value="">Select…</option><option v-for="o in cleanlinessOpts" :key="o" :value="o">{{ o }}</option></select></td>
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Notes…" :value="ex.cleanlinessNotes" @input="setExtraField(sec.id,ex._eid,'cleanlinessNotes',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length, 'mic-ai': isItemAiProcessing(sec.id,ex._eid) }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button><button v-if="canDelete" class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><button v-if="getPhotos(sec.id,ex._eid).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,ex._eid,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button v-if="canEdit" class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
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
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="e.g. 2 × Yale keys" :value="get(sec.id,row.id,'description')" @input="set(sec.id,row.id,'description',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length, 'mic-ai': isItemAiProcessing(sec.id,row.id) }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button><button v-if="canDelete" class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="5" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><button v-if="getPhotos(sec.id,row.id).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,row.id,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" :disabled="!canEdit" placeholder="Key name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Description…" :value="ex.description" @input="setExtraField(sec.id,ex._eid,'description',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length, 'mic-ai': isItemAiProcessing(sec.id,ex._eid) }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button><button v-if="canDelete" class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="5" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><button v-if="getPhotos(sec.id,ex._eid).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,ex._eid,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button v-if="canEdit" class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- SMOKE ALARMS / HEALTH & SAFETY -->
            <div v-else-if="sec.type === 'smoke_alarms' || sec.type === 'health_safety'">
              <template v-for="row in sec.rows" :key="row.id">
                <div v-show="!isHidden(sec.id, row.id)" class="qa-row">
                  <div class="qa-row-header">
                    <span class="qa-question"><span class="sec-ref-badge">{{ fixedRowRef(sec, row.id) }}</span>{{ row.question }}</span>
                  </div>
                  <p v-if="row.guidance" class="qa-guidance">{{ row.guidance }}</p>
                  <div class="qa-row-bottom">
                    <div class="qa-controls">
                      <select class="fld-input" style="width:180px" :value="get(sec.id,row.id,'answer')" @change="set(sec.id,row.id,'answer',$event.target.value)">
                        <option value="">Select…</option>
                        <option>Yes</option><option>No</option><option>N/A</option><option>Not Tested</option>
                      </select>
                      <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" style="flex:1" placeholder="Additional notes…" :value="get(sec.id,row.id,'notes')" @input="set(sec.id,row.id,'notes',$event.target.value)"></textarea>
                    </div>
                    <div class="item-btn-col">
                      <button class="cam-btn cam-btn-item" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button>
                      <button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length, 'mic-ai': isItemAiProcessing(sec.id,row.id) }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.question))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button>
                      <button v-if="canDelete" class="del-item-icon-btn" @click="hideRow(sec.id,row.id)">×</button>
                    </div>
                  </div>
                  <div v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-inline"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><button v-if="getPhotos(sec.id,row.id).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,row.id,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div>
                </div>
              </template>
              <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                <div class="qa-row extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                  <div class="qa-extra-header">
                    <span class="drag-handle">⠿</span>
                    <span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span>
                    <input class="fld-input" type="text" :disabled="!canEdit" placeholder="Question…" :value="ex.question" @input="setExtraField(sec.id,ex._eid,'question',$event.target.value)" />
                    <button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button>
                    <button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length, 'mic-ai': isItemAiProcessing(sec.id,ex._eid) }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.question||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button>
                    <button v-if="canDelete" class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button>
                  </div>
                  <div class="qa-controls">
                    <select class="fld-input" style="width:180px" :value="ex.answer" @change="setExtraField(sec.id,ex._eid,'answer',$event.target.value)">
                      <option value="">Select…</option>
                      <option>Yes</option><option>No</option><option>N/A</option><option>Not Tested</option>
                    </select>
                    <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" style="flex:1" placeholder="Notes…" :value="ex.notes" @input="setExtraField(sec.id,ex._eid,'notes',$event.target.value)"></textarea>
                  </div>
                  <div v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-inline"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><button v-if="getPhotos(sec.id,ex._eid).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,ex._eid,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div>
                </div>
              </template>
              <div class="add-row-bar"><button v-if="canEdit" class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
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
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Notes…" :value="get(sec.id,row.id,'notes')" @input="set(sec.id,row.id,'notes',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length, 'mic-ai': isItemAiProcessing(sec.id,row.id) }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button><button v-if="canDelete" class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="7" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><button v-if="getPhotos(sec.id,row.id).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,row.id,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" :disabled="!canEdit" placeholder="Door name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><input class="fld-input" type="text" :disabled="!canEdit" placeholder="Check…" :value="ex.question" @input="setExtraField(sec.id,ex._eid,'question',$event.target.value)" /></td>
                      <td><select class="fld-input" :value="ex.answer" @change="setExtraField(sec.id,ex._eid,'answer',$event.target.value)"><option value="">Select…</option><option>Yes</option><option>No</option><option>N/A</option></select></td>
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Notes…" :value="ex.notes" @input="setExtraField(sec.id,ex._eid,'notes',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length, 'mic-ai': isItemAiProcessing(sec.id,ex._eid) }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button><button v-if="canDelete" class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="7" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><button v-if="getPhotos(sec.id,ex._eid).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,ex._eid,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button v-if="canEdit" class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
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
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="e.g. Located to understairs cupboard&#10;Serial Number: 123456" :value="get(sec.id,row.id,'locationSerial')" @input="set(sec.id,row.id,'locationSerial',$event.target.value)"></textarea></td>
                      <td><textarea v-auto-resize class="fld-textarea fld-mono" placeholder="e.g. 12345.6" :value="get(sec.id,row.id,'reading')" @input="set(sec.id,row.id,'reading',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,row.id).length }" @click="togglePanel(sec.id,row.id)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,row.id).length" class="cam-count">{{ getPhotos(sec.id,row.id).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,row.id), 'mic-has': !isItemRecording(sec.id,row.id) && getItemRecordings(sec.id,row.id).length, 'mic-ai': isItemAiProcessing(sec.id,row.id) }" @click.stop="toggleItemRecording(sec.id,row.id,fixedItemLabel(sec,row.id,row.name))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,row.id).length && !isItemRecording(sec.id,row.id)" class="cam-count mic-count">{{ getItemRecordings(sec.id,row.id).length }}</span></button><button v-if="canDelete" class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,row.id)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,row.id)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,row.id,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,row.id,pi)">×</button></div><button v-if="getPhotos(sec.id,row.id).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,row.id,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,row.id,e.target.files)" /></label></div></td></tr>
                  </template>
                  <template v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid">
                    <tr class="extra-row" draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                      <td class="td-drag"><span class="drag-handle">⠿</span></td>
                      <td class="td-extra-name"><span class="sec-ref-badge sec-ref-extra">{{ fixedRowRef(sec, ex._eid) }}</span><input class="fld-input" type="text" :disabled="!canEdit" placeholder="Meter name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                      <td><textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Location & serial…" :value="ex.locationSerial" @input="setExtraField(sec.id,ex._eid,'locationSerial',$event.target.value)"></textarea></td>
                      <td><textarea v-auto-resize class="fld-textarea fld-mono" placeholder="Reading…" :value="ex.reading" @input="setExtraField(sec.id,ex._eid,'reading',$event.target.value)"></textarea></td>
                      <td class="td-btn-group"><div class="item-btn-col"><button class="cam-btn" :class="{ 'cam-has': getPhotos(sec.id,ex._eid).length }" @click="togglePanel(sec.id,ex._eid)" title="Photos"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><span v-if="getPhotos(sec.id,ex._eid).length" class="cam-count">{{ getPhotos(sec.id,ex._eid).length }}</span></button><button class="cam-btn mic-btn" :class="{ 'mic-active': isItemRecording(sec.id,ex._eid), 'mic-has': !isItemRecording(sec.id,ex._eid) && getItemRecordings(sec.id,ex._eid).length, 'mic-ai': isItemAiProcessing(sec.id,ex._eid) }" @click.stop="toggleItemRecording(sec.id,ex._eid,fixedItemLabel(sec,ex._eid,(ex.name||'Item')))" title="Record"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg><span v-if="getItemRecordings(sec.id,ex._eid).length && !isItemRecording(sec.id,ex._eid)" class="cam-count mic-count">{{ getItemRecordings(sec.id,ex._eid).length }}</span></button><button v-if="canDelete" class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div></td>
                    </tr>
                    <tr v-if="isPanelOpen(sec.id,ex._eid)" class="photo-panel-row"><td colspan="6" class="photo-panel-cell"><div class="photo-panel"><div v-for="(ph,pi) in getPhotos(sec.id,ex._eid)" :key="pi" class="ph-thumb" style="cursor:pointer" @click="openLightbox(sec.id,ex._eid,pi)"><img :src="ph" class="ph-img-click" /><button class="ph-del" @click="removePhoto(sec.id,ex._eid,pi)">×</button></div><button v-if="getPhotos(sec.id,ex._eid).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(sec.id,ex._eid,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Upload<input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(sec.id,ex._eid,e.target.files)" /></label></div></td></tr>
                  </template>
                </tbody>
              </table>
              <div class="add-row-bar"><button v-if="canEdit" class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <div v-else class="unknown-type">Unknown section type: {{ sec.type }}</div>
          </div>

          <!-- ═══ ROOMS ═════════════════════════════════════════════ -->
          <div v-for="(room, roomIdx) in rooms" :key="room.id" :id="`sec-${room.id}`" class="card card-room">
            <div class="card-hd card-hd-room">
              <h2 class="card-title">
                <span class="room-number">{{ roomIndexMap[room.id] }}.</span>
                <template v-if="renamingRoomId === String(room.id)">
                  <input
                    class="room-name-input"
                    v-model="renamingRoomVal"
                    @blur="commitRenameRoom(room)"
                    @keyup.enter="commitRenameRoom(room)"
                    @keyup.escape="cancelRenameRoom"
                    v-focus
                  />
                </template>
                <span
                  v-else
                  class="room-name-editable"
                  @click="startRenameRoom(room)"
                  title="Click to rename for this report"
                >{{ getRoomName(room) }} <span class="room-rename-hint">✎</span></span>
              </h2>
              <div class="card-hd-right">
                <span v-if="isCheckOut" class="co-badge">Check Out</span>
                <span class="card-hint">{{ room.sections?.length || 0 }} items</span>
                <button
                  v-if="roomPhotoCount(room) > 0"
                  class="card-view-all-btn card-view-all-room"
                  @click.stop="openRoomPhotoGrid(room)"
                  :title="roomPhotoCount(room) + ' photos in this room'"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                  View All Photos
                  <span class="card-photo-count">{{ roomPhotoCount(room) }}</span>
                </button>
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
                <button class="ph-view-all-btn" @click="openPhotoGrid(room.id,'_overview','Overview')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button>
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
              <!-- ── Item header bar ── -->
              <div class="item-header-bar">
                <span class="drag-handle drag-handle-room">⠿</span>
                <span class="item-ref-num">{{ itemRef(room.id, getOrderedRoomItems(room), item._type === 'extra' ? item._eid : item.id) }}</span>
                <template v-if="item._type === 'extra'">
                  <input class="fld-input label-input item-header-name" type="text" placeholder="Item name…"
                    :value="item.label"
                    @input="setRoomExtraField(room.id, item._eid, 'label', $event.target.value)" />
                </template>
                <template v-else><span class="item-header-name">{{ item.label }}</span></template>
              </div>

              <!-- ── Item body ── -->
              <div class="room-row-right">
                <div class="room-row-fields" :class="{ 'co-layout': isCheckOut }">

                  <!-- ── STANDARD layout (Check In / Interim / Inventory) ── -->
                  <template v-if="!isCheckOut">
                    <template v-if="item._type === 'template'">
                      <!-- Desc + Condition side by side, buttons on right -->
                      <div class="item-fields-row">
                        <div class="item-fields-main">
                          <div v-if="item.hasDescription" class="room-field-desc">
                            <label class="field-lbl">Description</label>
                            <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" rows="3" :placeholder="`Describe ${item.label.toLowerCase()}…`"
                              :value="get(room.id,item.id,'description')"
                              @input="set(room.id,item.id,'description',$event.target.value)"></textarea>
                          </div>
                          <div v-if="item.hasCondition" class="room-field-cond">
                            <label class="field-lbl">Condition</label>
                            <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" rows="3" :placeholder="`Condition of ${item.label.toLowerCase()}…`"
                              :value="get(room.id,item.id,'condition')"
                              @input="set(room.id,item.id,'condition',$event.target.value)"></textarea>
                          </div>
                          <div v-if="item.hasNotes" class="room-field-notes">
                            <label class="field-lbl">Notes</label>
                            <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" placeholder="Notes…"
                              :value="get(room.id,item.id,'notes')"
                              @input="set(room.id,item.id,'notes',$event.target.value)"></textarea>
                          </div>
                          <button v-if="canEdit && item.hasDescription" class="add-sub-btn add-sub-below" @click="addSubItem(room.id, item.id)">+ Add sub-item</button>
                        </div>
                        <!-- Buttons stacked to the right -->
                        <div class="item-btn-col" v-if="item.hasCondition || item.hasDescription || (!item.hasCondition && !item.hasDescription)">
                          <button class="cam-btn cam-btn-item" :class="{ 'cam-has': getPhotos(room.id, item.id).length }" @click="togglePanel(room.id, item.id)" title="Photos">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                            <span v-if="getPhotos(room.id, item.id).length" class="cam-count">{{ getPhotos(room.id, item.id).length }}</span>
                          </button>
                          <button class="cam-btn cam-btn-item mic-btn"
                            :class="{ 'mic-active': isItemRecording(room.id, item.id), 'mic-has': !isItemRecording(room.id, item.id) && getItemRecordings(room.id, item.id).length, 'mic-ai': isItemAiProcessing(room.id, item.id) }"
                            @click.stop="toggleItemRecording(room.id, item.id, room.name + ' — ' + item.label)"
                            title="Record audio">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                            <span v-if="getItemRecordings(room.id, item.id).length && !isItemRecording(room.id, item.id)" class="cam-count mic-count">{{ getItemRecordings(room.id, item.id).length }}</span>
                          </button>
                          <button v-if="canEdit" class="del-item-icon-btn" @click="hideItem(room.id, item.id)" title="Remove item">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
                          </button>
                        </div>
                      </div>
                    </template>
                    <template v-else>
                      <!-- Extra (non-template) item -->
                      <div class="item-fields-row">
                        <div class="item-fields-main">
                          <div class="room-field-desc">
                            <label class="field-lbl">Description</label>
                            <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" rows="3" placeholder="Describe…"
                              :value="item.description"
                              @input="setRoomExtraField(room.id,item._eid,'description',$event.target.value)"></textarea>
                          </div>
                          <div class="room-field-cond">
                            <label class="field-lbl">Condition</label>
                            <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" rows="3" placeholder="Condition…"
                              :value="item.condition"
                              @input="setRoomExtraField(room.id,item._eid,'condition',$event.target.value)"></textarea>
                          </div>
                        </div>
                        <div class="item-btn-col">
                          <button class="cam-btn cam-btn-item" :class="{ 'cam-has': getPhotos(room.id, item._eid).length }" @click="togglePanel(room.id, item._eid)" title="Photos">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                            <span v-if="getPhotos(room.id, item._eid).length" class="cam-count">{{ getPhotos(room.id, item._eid).length }}</span>
                          </button>
                          <button class="cam-btn cam-btn-item mic-btn"
                            :class="{ 'mic-active': isItemRecording(room.id, item._eid), 'mic-has': !isItemRecording(room.id, item._eid) && getItemRecordings(room.id, item._eid).length }"
                            @click.stop="toggleItemRecording(room.id, item._eid, room.name + ' — ' + (item.label || 'Item'))"
                            title="Record audio">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                            <span v-if="getItemRecordings(room.id, item._eid).length && !isItemRecording(room.id, item._eid)" class="cam-count mic-count">{{ getItemRecordings(room.id, item._eid).length }}</span>
                          </button>
                          <button v-if="canEdit" class="del-item-icon-btn" @click="removeRoomExtraItem(room.id, item._eid)" title="Remove item">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
                          </button>
                        </div>
                      </div>
                    </template>
                  </template>

                  <!-- ── CHECK OUT layout ── -->
                  <template v-else>
                    <div class="item-fields-row co-fields-row">
                      <div class="item-fields-main">
                        <!-- Description — read from Check In (read-only reference) -->
                        <div class="room-field-desc">
                          <label class="field-lbl">Description</label>
                          <div class="co-inv-value" :class="{ 'co-inv-empty': !getCI(room.id, item._type==='template' ? item.id : item._eid, 'description') }">
                            {{ getCI(room.id, item._type==='template' ? item.id : item._eid, 'description') || item.label || '—' }}
                          </div>
                        </div>
                        <!-- Condition at Check In — read-only -->
                        <div class="room-field-inv">
                          <label class="field-lbl co-inv-lbl">
                            Condition at Check In
                            <span class="co-inv-badge">Inventory</span>
                          </label>
                          <div class="co-inv-value" :class="{ 'co-inv-empty': !getCI(room.id, item._type==='template' ? item.id : item._eid, 'condition') }">
                            {{ getCI(room.id, item._type==='template' ? item.id : item._eid, 'condition') || '—' }}
                          </div>
                        </div>
                        <!-- Condition at Check Out — editable -->
                        <div class="room-field-cond">
                          <label class="field-lbl">Condition at Check Out</label>
                          <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" rows="3"
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
                        <!-- Actions picker: shown on desktop always; on mobile toggled by action-trigger-btn -->
                        <div class="room-field-actions" :class="{ 'actions-expanded': isActionExpanded(room.id, item._type==='extra' ? item._eid : item.id) }">
                          <label class="field-lbl">Actions</label>
                          <CheckOutActionPicker
                            :actions="getItemActions(room.id, item._type==='extra' ? item._eid : item.id)"
                            :room-id="room.id"
                            :item-id="item._type==='extra' ? item._eid : item.id"
                            :condition-text="item._type==='template'
                              ? get(room.id, item.id, 'checkOutCondition')
                              : (item.checkOutCondition || '')"
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
                      </div>
                      <!-- Buttons stacked to the right -->
                      <div class="item-btn-col">
                        <button class="cam-btn cam-btn-item"
                          :class="{ 'cam-has': getPhotos(room.id, item._type==='template' ? item.id : item._eid).length }"
                          @click="togglePanel(room.id, item._type==='template' ? item.id : item._eid)"
                          title="Photos">
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                          <span v-if="getPhotos(room.id, item._type==='template' ? item.id : item._eid).length" class="cam-count">{{ getPhotos(room.id, item._type==='template' ? item.id : item._eid).length }}</span>
                        </button>
                        <button class="cam-btn cam-btn-item mic-btn"
                          :class="{ 'mic-active': isItemRecording(room.id, item._type==='template' ? item.id : item._eid), 'mic-has': !isItemRecording(room.id, item._type==='template' ? item.id : item._eid) && getItemRecordings(room.id, item._type==='template' ? item.id : item._eid).length, 'mic-ai': isItemAiProcessing(room.id, item._type==='template' ? item.id : item._eid) }"
                          @click.stop="toggleItemRecording(room.id, item._type==='template' ? item.id : item._eid, room.name + ' — ' + (item.label || 'Item'))"
                          title="Record audio">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                          <span v-if="getItemRecordings(room.id, item._type==='template' ? item.id : item._eid).length && !isItemRecording(room.id, item._type==='template' ? item.id : item._eid)" class="cam-count mic-count">{{ getItemRecordings(room.id, item._type==='template' ? item.id : item._eid).length }}</span>
                        </button>
                        <button
                          class="cam-btn cam-btn-item action-trigger-btn"
                          :class="{ 'action-has': getItemActions(room.id, item._type==='extra' ? item._eid : item.id).length }"
                          @click.stop="toggleActionExpanded(room.id, item._type==='extra' ? item._eid : item.id)"
                          title="Actions">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                          <span v-if="getItemActions(room.id, item._type==='extra' ? item._eid : item.id).length" class="cam-count action-count">{{ getItemActions(room.id, item._type==='extra' ? item._eid : item.id).length }}</span>
                        </button>
                      </div>
                    </div>
                  </template>

                </div>

                <!-- Sub-items (template items only) -->
                <div v-if="item._type === 'template' && getSubs(room.id, item.id).length" class="sub-items">
                  <div v-for="sub in getSubs(room.id, item.id)" :key="sub._sid" class="sub-item">
                    <div class="item-fields-row sub-fields-row">
                      <div class="item-fields-main">
                        <div class="room-field-desc">
                          <label class="field-lbl">Description</label>
                          <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" rows="2" placeholder="Describe…" :value="sub.description" @input="setSubField(room.id,item.id,sub._sid,'description',$event.target.value)"></textarea>
                        </div>
                        <div class="room-field-cond">
                          <label class="field-lbl">Condition</label>
                          <textarea v-auto-resize class="fld-textarea" :disabled="!canEdit" rows="2" placeholder="Condition…" :value="sub.condition" @input="setSubField(room.id,item.id,sub._sid,'condition',$event.target.value)"></textarea>
                        </div>
                      </div>
                      <div class="item-btn-col">
                        <button class="cam-btn cam-btn-item" :class="{ 'cam-has': getPhotos(room.id, sub._sid).length }" @click="togglePanel(room.id, sub._sid)" title="Photos">
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                          <span v-if="getPhotos(room.id, sub._sid).length" class="cam-count">{{ getPhotos(room.id, sub._sid).length }}</span>
                        </button>
                        <button class="cam-btn cam-btn-item mic-btn"
                          :class="{ 'mic-active': isItemRecording(room.id, sub._sid), 'mic-has': !isItemRecording(room.id, sub._sid) && getItemRecordings(room.id, sub._sid).length, 'mic-ai': isItemAiProcessing(room.id, sub._sid) }"
                          @click.stop="toggleItemRecording(room.id, sub._sid, room.name + ' — ' + item.label + ' (sub)')"
                          title="Record audio">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                          <span v-if="getItemRecordings(room.id, sub._sid).length && !isItemRecording(room.id, sub._sid)" class="cam-count mic-count">{{ getItemRecordings(room.id, sub._sid).length }}</span>
                        </button>
                        <button class="del-item-icon-btn" @click="removeSubItem(room.id,item.id,sub._sid)" title="Remove sub-item">
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
                        </button>
                      </div>
                    </div>
                    <!-- Sub-item inline photo panel -->
                    <div v-if="isPanelOpen(room.id, sub._sid)" class="photo-panel-inline photo-panel-sub">
                      <div v-for="(ph,pi) in getPhotos(room.id, sub._sid)" :key="pi" class="ph-thumb ph-thumb-lg" style="cursor:pointer" @click="openLightbox(room.id, sub._sid, pi)">
                        <img :src="ph" class="ph-img-click" />
                        <button class="ph-del" @click="removePhoto(room.id, sub._sid, pi)">×</button>
                      </div>
                      <label class="ph-upload-btn">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                        Upload photos
                        <input type="file" accept="image/*" multiple style="display:none" @change="e=>addPhotos(room.id, sub._sid, e.target.files)" />
                      </label>
                    </div>
                  </div>
                </div>

                <!-- Inline photo panel — shown when camera toggled -->
                <div v-if="isPanelOpen(room.id, item._type==='template' ? item.id : item._eid)" class="photo-panel-inline">
                  <div v-for="(ph,pi) in getPhotos(room.id, item._type==='template' ? item.id : item._eid)" :key="pi" class="ph-thumb ph-thumb-lg" style="cursor:pointer" @click="openLightbox(room.id, item._type==='template' ? item.id : item._eid,pi)">
                    <img :src="ph" class="ph-img-click" />
                    <button class="ph-del" @click="removePhoto(room.id, item._type==='template' ? item.id : item._eid, pi)">×</button>
                  </div>
                  <button v-if="getPhotos(room.id,item._type==='template' ? item.id : item._eid).length" class="ph-view-all-btn" @click.stop="openPhotoGrid(room.id,item._type==='template' ? item.id : item._eid,'')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> View All</button><label class="ph-upload-btn">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    Upload photos
                    <input type="file" accept="image/*" multiple style="display:none"
                      @change="e=>addPhotos(room.id, item._type==='template' ? item.id : item._eid, e.target.files)" />
                  </label>
                  <span class="ph-ref-label">Ref {{ itemRef(room.id, getOrderedRoomItems(room), item._type==='template' ? item.id : item._eid) }}</span>
                </div>

                <!-- Action bar removed — buttons now inline in item-btn-col -->
              </div>
            </div>

            <div class="add-row-bar add-row-bar-room">
              <button class="add-row-btn add-row-btn-room" @click="addRoomExtraItem(room.id)">+ Add line</button>
            </div>
          </div>

          <template v-if="actionSummaryPosition === 'bottom'">
          <!-- ═══ ACTION SUMMARY (Check Out only) ════════════════════ -->
          <div
            v-if="isCheckOut && actionSummaryGroups.length"
            class="card card-action-summary"
          >
            <div class="card-hd card-hd-summary">
              <h2 class="card-title">
                <span class="summary-icon">📋</span>
                Actions Summary
              </h2>
              <span class="card-hint">{{ actionSummaryGroups.reduce((n,g) => n + g.items.length, 0) }} item{{ actionSummaryGroups.reduce((n,g) => n + g.items.length, 0) !== 1 ? 's' : '' }} flagged</span>
            </div>

            <div class="summary-groups">
              <div v-for="group in actionSummaryGroups" :key="group.actionId" class="summary-group">
                <div class="summary-group-hd" :style="{ borderLeftColor: group.color }">
                  <span class="summary-group-dot" :style="{ background: group.color }"></span>
                  <span class="summary-group-name">{{ group.name }}</span>
                  <span class="summary-group-count">{{ group.items.length }} item{{ group.items.length !== 1 ? 's' : '' }}</span>
                </div>
                <table class="summary-tbl">
                  <thead>
                    <tr>
                      <th class="stbl-ref">Ref</th>
                      <th class="stbl-room">Room</th>
                      <th class="stbl-item">Item</th>
                      <th class="stbl-resp">Responsibility</th>
                      <th class="stbl-note">Condition</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(item, i) in group.items" :key="i">
                      <td class="stbl-ref">{{ item.ref }}</td>
                      <td class="stbl-room">{{ item.roomName }}</td>
                      <td class="stbl-item">{{ item.itemLabel }}</td>
                      <td class="stbl-resp">
                        <span v-if="item.responsibility" class="resp-badge" :style="{ background: group.color + '18', color: group.color, borderColor: group.color + '50' }">{{ item.responsibility }}</span>
                        <span v-else class="resp-none">—</span>
                      </td>
                      <td class="stbl-note">{{ item.condition || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          </template>

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
      @click.self="closeLightbox"
      @keydown.esc.window="closeLightbox"
      @keydown.left.window="photoViewerPrev"
      @keydown.right.window="photoViewerNext"
    >
      <div class="ci-lightbox ci-lightbox-wide">

        <!-- Header -->
        <div class="ci-lightbox-hd">
          <span class="ci-lightbox-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            <template v-if="photoViewer.ref || photoViewer.label">
              <span v-if="photoViewer.ref" class="lb-ref">Ref {{ photoViewer.ref }}</span>
              <span v-if="photoViewer.label" class="lb-sep">·</span>
              {{ photoViewer.label }}
            </template>
            <template v-else>Photo Viewer</template>
          </span>
          <span class="ci-lightbox-counter">{{ photoViewer.index + 1 }} / {{ photoViewer.photos.length }}</span>
          <button class="modal-close" @click="closeLightbox">×</button>
        </div>

        <!-- Toolbar -->
        <div class="lb-toolbar">
          <div class="lb-toolbar-group">
            <button class="lb-pill lb-pill-ghost" @click="lbSelectAll" title="Select all">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
              All
            </button>
            <button class="lb-pill lb-pill-ghost" @click="lbClearSelection" :disabled="lbSelected.size === 0">
              Clear
            </button>
            <span v-if="lbSelected.size > 0" class="lb-sel-pill">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polyline points="20 6 9 17 4 12" stroke="currentColor" stroke-width="3" fill="none"/></svg>
              {{ lbSelected.size }} selected
            </span>
          </div>

          <div class="lb-toolbar-group">
            <button class="lb-pill lb-pill-ghost" @click="lbRotateCurrent" title="Rotate 90°">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
              Rotate
            </button>
            <button
              v-if="photoViewer.sectionId"
              class="lb-pill lb-pill-purple"
              :class="{ active: lbMoving }"
              @click="lbMoving = !lbMoving"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 9l-3 3 3 3"/><path d="M9 5l3-3 3 3"/><path d="M15 19l-3 3-3-3"/><path d="M19 9l3 3-3 3"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>
              Move{{ lbSelected.size > 0 ? ' ' + lbSelected.size : '' }}
            </button>
            <button
              v-if="photoViewer.sectionId"
              class="lb-pill lb-pill-danger"
              @click="lbDeletePhotos"
              :title="lbSelected.size > 0 ? 'Delete ' + lbSelected.size + ' selected' : 'Delete this photo'"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
              {{ lbSelected.size > 0 ? 'Delete ' + lbSelected.size : 'Delete' }}
            </button>
          </div>
        </div>

        <!-- Move destination tree -->
        <div v-if="lbMoving" class="lb-move-panel">
          <div class="lb-move-hd">
            <span class="lb-move-hd-title">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 9l-3 3 3 3"/><path d="M9 5l3-3 3 3"/><path d="M15 19l-3 3-3-3"/><path d="M19 9l3 3-3 3"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>
              Move {{ lbSelected.size > 0 ? lbSelected.size + ' photo' + (lbSelected.size !== 1 ? 's' : '') : 'photo' }} to:
            </span>
            <button class="lb-move-cancel-btn" @click="lbMoving = false">✕</button>
          </div>
          <div class="lb-move-tree-scroll">
            <div v-for="group in lbMoveTree" :key="group.key" class="lb-tree-group-wrap">
              <button
                class="lb-tree-group-btn"
                :class="{ 'lb-tree-is-room': group.type === 'room', 'lb-tree-is-fixed': group.type === 'section' }"
                @click="lbTreeToggle(group.key)"
              >
                <svg class="lb-tree-chev" :class="{ open: lbTreeExpanded.has(group.key) }" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="9 18 15 12 9 6"/></svg>
                <svg v-if="group.type === 'room'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="lb-tree-type-icon"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/></svg>
                <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="lb-tree-type-icon"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
                <span class="lb-tree-group-label">{{ group.label }}</span>
                <span class="lb-tree-group-count">{{ group.children ? group.children.length : (group.items ? group.items.length : 0) }}</span>
              </button>
              <template v-if="lbTreeExpanded.has(group.key)">
                <!-- Fixed section has sub-groups -->
                <template v-for="child in group.children" :key="child.key">
                  <template v-if="child.type === 'group'">
                    <button class="lb-tree-sub-btn" @click="lbTreeToggle(child.key)">
                      <svg class="lb-tree-chev" :class="{ open: lbTreeExpanded.has(child.key) }" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="9 18 15 12 9 6"/></svg>
                      <span>{{ child.label }}</span>
                    </button>
                    <div v-if="lbTreeExpanded.has(child.key)" class="lb-tree-items">
                      <button v-for="item in child.children" :key="item.key" class="lb-tree-item-btn" @click="lbMovePhotos(item.sectionId, item.rowId)">
                        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                        {{ item.label }}
                      </button>
                    </div>
                  </template>
                  <button v-else class="lb-tree-item-btn" @click="lbMovePhotos(child.sectionId, child.rowId)">
                    <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                    {{ child.label }}
                  </button>
                </template>
                <!-- Room has direct items -->
                <template v-if="group.items">
                  <div class="lb-tree-items">
                    <button v-for="item in group.items" :key="item.key || (item.sectionId+item.rowId)" class="lb-tree-item-btn" @click="lbMovePhotos(item.sectionId, item.rowId)">
                      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                      {{ item.label }}
                    </button>
                  </div>
                </template>
              </template>
            </div>
          </div>
        </div>

        <!-- Main image area -->
        <div class="ci-lightbox-body">
          <button class="ci-nav ci-nav-prev" @click="photoViewerPrev" :disabled="photoViewer.index === 0">‹</button>

          <!-- Image with selection overlay -->
          <div class="lb-img-wrap" @click="lbToggleSelect(photoViewer.index)">
            <img
              :src="photoViewer.photos[photoViewer.index]"
              class="ci-lightbox-img"
              :class="{ 'lb-img-selected': lbSelected.has(photoViewer.index) }"
              :alt="photoViewer.label"
            />
            <div v-if="lbSelected.has(photoViewer.index)" class="lb-img-check">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="white" stroke="white" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
            <!-- Timestamp overlay -->
            <div
              v-if="showPhotoTimestamp && photoViewer.sectionId && reportData[photoViewer.sectionId]?.[photoViewer.rowId]?._photoTs?.[photoViewer.index]"
              class="lb-timestamp"
            >
              {{ new Date(reportData[photoViewer.sectionId][photoViewer.rowId]._photoTs[photoViewer.index]).toLocaleString('en-GB', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' }) }}
            </div>
          </div>

          <button class="ci-nav ci-nav-next" @click="photoViewerNext" :disabled="photoViewer.index === photoViewer.photos.length - 1">›</button>
        </div>

        <!-- Dot strip with selection indicators -->
        <div class="ci-lightbox-dots">
          <span
            v-for="(_, i) in photoViewer.photos"
            :key="i"
            class="ci-dot"
            :class="{ active: i === photoViewer.index, selected: lbSelected.has(i) }"
            @click="photoViewer.index = i"
          ></span>
        </div>

        <p class="lb-hint">Click photo to select · ← → navigate · Esc to close</p>
      </div>
    </div>

    <!-- PHOTO GRID (View All) -->
    <div v-if="photoGrid.show" class="pg-overlay" @click.self="closePhotoGrid" @keydown.esc.window="closePhotoGrid">
      <div class="pg-modal">

        <!-- Header -->
        <div class="pg-header">
          <div class="pg-header-left">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
            <span class="pg-title">All Photos</span>
            <span v-if="photoGrid.label" class="pg-title-sub">· {{ photoGrid.label }}</span>
            <span class="pg-count-badge">{{ photoGrid.allSection ? pgAllPhotos.length : getPhotos(photoGrid.sectionId, photoGrid.rowId).length }}</span>
          </div>
          <button class="modal-close" @click="closePhotoGrid">×</button>
        </div>

        <!-- Toolbar -->
        <div class="pg-toolbar">
          <div class="pg-toolbar-left">
            <button class="pg-pill pg-pill-ghost" @click="gridSelectAll">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
              Select All
            </button>
            <button class="pg-pill pg-pill-ghost" @click="gridClearSelection" :disabled="!gridSelected.size">Clear</button>
            <span v-if="gridSelected.size" class="pg-sel-badge">
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              {{ gridSelected.size }} selected
            </span>
          </div>
          <div class="pg-toolbar-right">
            <button v-if="gridSelected.size" class="pg-pill pg-pill-indigo" @click="openGridSelectionInLightbox">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              Open
            </button>
            <button
              v-if="gridSelected.size"
              class="pg-pill pg-pill-purple"
              :class="{ active: pgMoving }"
              @click="pgMoving ? pgMoving = false : pgOpenMoveTree()"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 9l-3 3 3 3"/><path d="M9 5l3-3 3 3"/><path d="M15 19l-3 3-3-3"/><path d="M19 9l3 3-3 3"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>
              Move {{ gridSelected.size }}
            </button>
            <button v-if="gridSelected.size" class="pg-pill pg-pill-danger" @click="gridDeletePhotos">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
              Delete {{ gridSelected.size }}
            </button>
          </div>
        </div>

        <!-- Move tree panel -->
        <div v-if="pgMoving" class="pg-move-panel">
          <div class="pg-move-hd">
            <span class="pg-move-title">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 9l-3 3 3 3"/><path d="M9 5l3-3 3 3"/><path d="M15 19l-3 3-3-3"/><path d="M19 9l3 3-3 3"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>
              Move {{ gridSelected.size }} photo{{ gridSelected.size !== 1 ? 's' : '' }} to:
            </span>
            <button class="pg-move-close" @click="pgMoving = false">✕ Cancel</button>
          </div>
          <div class="pg-move-tree">
            <div v-for="group in pgMoveTree" :key="group.key" class="pg-tree-group-wrap">
              <!-- Group header (section or room) -->
              <button
                class="pg-tree-group"
                :class="{ 'pg-tree-room': group.type === 'room', 'pg-tree-fixed': group.type === 'fixed' }"
                @click="pgTreeToggle(group.key)"
              >
                <svg class="pg-tree-chevron" :class="{ open: pgTreeExpanded.has(group.key) }" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                <span class="pg-tree-group-icon">
                  <svg v-if="group.type === 'room'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/></svg>
                  <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
                </span>
                {{ group.label }}
                <span class="pg-tree-child-count">{{ group.children.length }}</span>
              </button>
              <!-- Items inside group -->
              <div v-if="pgTreeExpanded.has(group.key)" class="pg-tree-children">
                <button
                  v-for="item in group.children"
                  :key="item.key"
                  class="pg-tree-item"
                  @click="gridMovePhotos(item.sectionId, item.rowId)"
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                  {{ item.label }}
                </button>
              </div>
            </div>
            <div v-if="!pgMoveTree.length" class="pg-move-empty">No other destinations available</div>
          </div>
        </div>

        <!-- Grid -->
        <div class="pg-grid">
          <!-- All-section mode: flat array with per-photo source labels -->
          <template v-if="photoGrid.allSection">
            <div
              v-for="(entry, pi) in pgAllPhotos"
              :key="pi"
              class="pg-cell"
              :class="{ 'pg-cell-selected': gridSelected.has(pi) }"
              @click="gridToggleSelect(pi)"
              @dblclick="openLightbox(entry.sectionId, entry.rowId, entry.index)"
            >
              <img :src="entry.photo" class="pg-img" />
              <div class="pg-cell-label">{{ entry.label }}</div>
              <div class="pg-cell-num">{{ pi + 1 }}</div>
              <div class="pg-cell-check" :class="{ visible: gridSelected.has(pi) }">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="white" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
              <button class="pg-cell-open" @click.stop="openLightbox(entry.sectionId, entry.rowId, entry.index)" title="Open in lightbox">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
              </button>
            </div>
            <div v-if="!pgAllPhotos.length" class="pg-empty">No photos in this section</div>
          </template>

          <!-- Single-item mode: original behaviour -->
          <template v-else>
            <div
              v-for="(ph, pi) in getPhotos(photoGrid.sectionId, photoGrid.rowId)"
              :key="pi"
              class="pg-cell"
              :class="{ 'pg-cell-selected': gridSelected.has(pi) }"
              @click="gridToggleSelect(pi)"
              @dblclick="openFromGrid(pi)"
            >
              <img :src="ph" class="pg-img" />
              <div class="pg-cell-num">{{ pi + 1 }}</div>
              <div class="pg-cell-check" :class="{ visible: gridSelected.has(pi) }">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="white" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
              <button class="pg-cell-open" @click.stop="openFromGrid(pi)" title="Open in lightbox">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
              </button>
            </div>
            <div v-if="!getPhotos(photoGrid.sectionId, photoGrid.rowId).length" class="pg-empty">
              No photos in this section
            </div>
          </template>
        </div>

        <div class="pg-footer">
          <span class="pg-footer-hint">Click to select · Double-click to open full view</span>
          <span v-if="gridSelected.size" class="pg-footer-sel">{{ gridSelected.size }} photo{{ gridSelected.size !== 1 ? 's' : '' }} selected</span>
        </div>

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
  <div class="audio-module" :class="{ 'am-collapsed': !audioModule.expanded, 'am-human-typist': hasHumanTypist }">
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

        <!-- Record (general) — hidden when human typist assigned (recordings come from mobile app) -->
        <button v-if="!hasHumanTypist" class="am-btn am-btn-rec" :class="{ recording: audioModule.mode === 'recording' && !itemRecordingKey }"
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

      <!-- AI Status bar -->
      <div v-if="aiProcessing" class="am-ai-status am-ai-processing">
        <svg class="spin-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
        ✨ AI is processing your recording…
      </div>
      <div v-else-if="aiError" class="am-ai-status am-ai-error">
        <span>⚠ {{ aiError }}</span>
        <button class="am-ai-error-dismiss" @click="aiError = ''">×</button>
      </div>
      <div v-else-if="hasAiTypist || aiKeysAvailable" class="am-ai-status am-ai-ready">
        <span>✨ AI Typist active — item recordings fill automatically</span>
        <button
          v-if="recordings.filter(r => !r.itemKey).length"
          class="am-ai-process-btn"
          @click="transcribeFullInspection"
        >Process continuous recording</button>
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

  <!-- PDF Export Modal -->
  <PdfExportModal
    v-if="showPdfModal"
    :inspection="inspection"
    :fixed-sections="fixedSections"
    :rooms="rooms"
    :report-data="reportData"
    :action-catalogue="actionCatalogue"
    :photo-settings="clientPhotoSettings"
    :client-settings="clientReportSettings"
    @close="showPdfModal = false"
  />

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
.pdf-btn{padding:6px 14px;background:#0f172a;color:white;border:none;border-radius:5px;font-size:13px;font-weight:600;cursor:pointer;transition:background 0.15s;white-space:nowrap}
.pdf-btn:hover{background:#1e293b}
.review-btn{padding:8px 20px;background:#16a34a;color:white;border:none;border-radius:6px;font-size:13px;font-weight:700;cursor:pointer;transition:background 0.15s}
.review-btn:hover{background:#15803d}
.chip-readonly{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;background:#f1f5f9;color:#64748b;border-radius:20px;font-size:12px;font-weight:500}
.fld-textarea:disabled,.fld-input:disabled{background:#f8fafc;color:#64748b;cursor:default;border-color:#e2e8f0}
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
.del-btn-sub{margin-top:8px}
.room-name-editable{cursor:pointer;border-radius:4px;padding:1px 4px;transition:background 0.15s;display:inline}
.room-name-editable:hover{background:rgba(255,255,255,0.15)}
.room-rename-hint{font-size:12px;opacity:0.55}
.room-name-input{font-size:18px;font-weight:700;color:white;background:rgba(255,255,255,0.15);border:2px solid rgba(255,255,255,0.6);border-radius:6px;padding:2px 8px;outline:none;min-width:160px;max-width:400px}
.photo-panel-sub{margin-top:6px;margin-left:0}

/* Q&A */
.qa-row{padding:16px 20px;border-bottom:1px solid #f1f5f9;display:flex;flex-direction:column;gap:10px}
.qa-row:last-child{border-bottom:none}
.qa-row-header{display:flex;align-items:flex-start;gap:8px}
.qa-row-bottom{display:flex;align-items:flex-start;gap:0}
.qa-row-bottom .qa-controls{flex:1;min-width:0}
.qa-row-bottom .item-btn-col{padding-top:4px;padding-left:12px}
.qa-extra-header{display:flex;align-items:center;gap:8px}
.qa-question{font-size:13px;font-weight:600;color:#1e293b;line-height:1.4;flex:1}
.qa-guidance{font-size:12px;color:#64748b;line-height:1.5;background:#fffbeb;border-left:3px solid #fbbf24;padding:8px 12px;border-radius:0 4px 4px 0}
.qa-controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap}

/* Room rows — new layout */
.room-row{border-bottom:1px solid #f1f5f9;background:white}
.room-row:last-child{border-bottom:none}

/* Item header bar — full width, contains drag handle + ref + name */
.item-header-bar{display:flex;align-items:center;gap:8px;padding:10px 16px 6px;border-bottom:1px solid #f8fafc;background:#fafbfd}
.item-header-name{font-size:13px;font-weight:700;color:#1e293b;flex:1}
.item-header-name.fld-input{font-weight:700;font-size:13px;border:none;background:transparent;padding:0;outline:none}
.item-header-name.fld-input:focus{background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;padding:2px 6px}

/* Item body — fields + button column */
.room-row-right{display:flex;flex-direction:column}

/* Main fields row: textareas left, buttons right */
.item-fields-row{display:flex;align-items:flex-start;gap:0;padding:10px 16px 8px}
.item-fields-main{display:grid;grid-template-columns:1fr 1fr;gap:12px;flex:1;min-width:0}
.room-field-desc{grid-column:1}
.room-field-cond{grid-column:2}
.room-field-inv{grid-column:1}
.room-field-notes{grid-column:1/-1}
.room-field-actions{grid-column:1/-1}
.room-field-ci-photos{grid-column:1/-1}

/* Check Out: 3 stacked read-only + editable fields */
.co-fields-row .item-fields-main{grid-template-columns:1fr 1fr;gap:10px}
.co-fields-row .room-field-inv{grid-column:2}
.co-fields-row .room-field-cond{grid-column:1/-1}

/* Button column — stacked to the right */
.item-btn-col{display:flex;flex-direction:column;gap:6px;padding-left:12px;padding-top:18px;flex-shrink:0;align-items:center}
.cam-btn-item{width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;color:#94a3b8;cursor:pointer;transition:all 0.15s;position:relative;flex-shrink:0}
.cam-btn-item:hover{background:#f1f5f9;border-color:#94a3b8;color:#475569}
.cam-btn-item.cam-has{background:#eff6ff;border-color:#93c5fd;color:#2563eb}
.cam-btn-item.mic-btn{color:#64748b}
.cam-btn-item.mic-btn:hover{background:#fdf4ff;border-color:#d8b4fe;color:#7c3aed}
.cam-btn-item.mic-btn.mic-has{background:#fdf4ff;border-color:#d8b4fe;color:#7c3aed}
.cam-btn-item.mic-btn.mic-active{background:#7c3aed;border-color:#7c3aed;color:white;animation:mic-pulse 1s ease-in-out infinite}
.cam-btn-item.mic-btn.mic-ai{background:#fdf4ff;border-color:#d8b4fe;color:#7c3aed;animation:mic-pulse 1.5s ease-in-out infinite}

/* Delete icon button */
.del-item-icon-btn{width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;background:none;border:1px solid #fca5a5;border-radius:6px;color:#ef4444;cursor:pointer;transition:all 0.12s;flex-shrink:0}
.del-item-icon-btn:hover{background:#fef2f2;border-color:#ef4444}

/* Add sub-item link — sits below description box */
.add-sub-inline{display:block;background:none;border:none;color:#7c3aed;font-size:11px;font-weight:600;cursor:pointer;padding:4px 0 0;text-align:left;width:100%}
.add-sub-inline:hover{text-decoration:underline}

/* room-row-fields is a passthrough wrapper */
.room-row-fields{display:contents}

/* Field labels */
.field-lbl{display:block;margin-bottom:4px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8}

/* Check Out read-only values */
.co-inv-lbl{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.co-inv-badge{padding:1px 7px;background:#e0e7ff;color:#4338ca;border-radius:8px;font-size:10px;font-weight:600;flex-shrink:0}
.co-inv-value{padding:8px 10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;color:#64748b;min-height:60px;line-height:1.5;white-space:pre-wrap}

/* Sub-items */
.sub-items{display:flex;flex-direction:column;border-top:1px dashed #e5e7eb;background:#fdfcff}
.sub-item{border-bottom:1px dashed #f1f5f9}
.sub-item:last-child{border-bottom:none}
.sub-fields-row{padding:8px 16px 8px 32px !important}
.sub-fields-row .item-fields-main{grid-template-columns:1fr 1fr}

/* Inputs */
.fld-input{width:100%;padding:6px 10px;border:1px solid #e2e8f0;border-radius:5px;font-size:13px;color:#1e293b;font-family:inherit;background:white;transition:border-color 0.15s}
.fld-input:focus{outline:none;border-color:#6366f1;box-shadow:0 0 0 2px rgba(99,102,241,0.08)}
.fld-textarea{width:100%;padding:7px 10px;border:1px solid #e2e8f0;border-radius:5px;font-size:13px;color:#1e293b;font-family:inherit;resize:none;overflow:hidden;line-height:1.5;background:white;transition:border-color 0.15s;min-height:36px}
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
/* Inline panel "View All" pill button */
.ph-view-all-btn{display:inline-flex;align-items:center;gap:5px;padding:5px 11px;font-size:11px;font-weight:700;border-radius:20px;cursor:pointer;border:1.5px solid #c7d2fe;background:linear-gradient(135deg,#eef2ff,#e0e7ff);color:#4338ca;font-family:inherit;transition:all 0.18s;letter-spacing:0.01em;box-shadow:0 1px 4px rgba(99,102,241,0.1);white-space:nowrap}
.ph-view-all-btn:hover{background:linear-gradient(135deg,#6366f1,#4f46e5);color:white;border-color:#6366f1;box-shadow:0 2px 10px rgba(99,102,241,0.3);transform:translateY(-1px)}
.ph-img-click{cursor:zoom-in}
/* CI photos link */
.room-field-ci-photos{margin-top:8px}
.btn-ci-photos{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;font-size:12px;font-weight:600;color:#0284c7;cursor:pointer;transition:all 0.15s}
.btn-ci-photos:hover{background:#e0f2fe;border-color:#7dd3fc}
.ci-photo-count{background:#0284c7;color:#fff;border-radius:10px;padding:1px 6px;font-size:11px;font-weight:700}

/* CI Lightbox */
.ci-lightbox-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px}
.ci-lightbox{background:#1e293b;border-radius:12px;width:min(680px,95vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 60px rgba(0,0,0,0.6)}
.ci-lightbox-wide{width:min(780px,96vw)}
.ci-lightbox-hd{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #334155;flex-shrink:0}
.ci-lightbox-title{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;color:#e2e8f0;flex:1}
.ci-lightbox-counter{font-size:12px;color:#64748b;font-weight:600}
.ci-lightbox-body{position:relative;display:flex;align-items:center;justify-content:center;flex:1;min-height:280px;background:#0a0f1a;padding:16px 56px}
.ci-lightbox-img{max-width:100%;max-height:55vh;object-fit:contain;border-radius:6px;transition:outline 0.1s}
/* Nav buttons — solid outline style */
.ci-nav{position:absolute;top:50%;transform:translateY(-50%);background:#1e293b;border:2px solid #6366f1;color:#fff;font-size:26px;width:44px;height:44px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background 0.15s,border-color 0.15s;z-index:2;box-shadow:0 2px 12px rgba(0,0,0,0.5)}
.ci-nav:hover:not(:disabled){background:#6366f1;border-color:#818cf8}
.ci-nav:disabled{opacity:0.25;cursor:default;border-color:#334155}
.ci-nav-prev{left:8px}.ci-nav-next{right:8px}
/* Dots */
.ci-lightbox-dots{display:flex;justify-content:center;gap:6px;padding:8px;flex-shrink:0}
.ci-dot{width:7px;height:7px;border-radius:50%;background:#334155;cursor:pointer;transition:background 0.15s}
.ci-dot.active{background:#6366f1}
.ci-dot.selected{background:#f59e0b;outline:2px solid #fbbf24;outline-offset:1px}
.ci-dot.active.selected{background:#f59e0b}
/* Labels */
.lb-ref{font-weight:700;color:#818cf8}
.lb-sep{color:#475569;margin:0 2px}
.lb-hint{text-align:center;font-size:11px;color:#475569;margin:0;padding:2px 0 8px;flex-shrink:0}
/* Toolbar */
.lb-toolbar{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;background:#0f172a;border-bottom:1px solid #1e293b;gap:10px;flex-shrink:0}
.lb-toolbar-group{display:flex;align-items:center;gap:6px;flex-wrap:wrap}

/* Pill buttons — shared base */
.lb-pill{display:inline-flex;align-items:center;gap:5px;padding:5px 12px;font-size:12px;font-weight:600;border-radius:20px;cursor:pointer;border:1.5px solid transparent;font-family:inherit;transition:all 0.15s;white-space:nowrap;letter-spacing:0.01em}
.lb-pill:disabled{opacity:0.35;cursor:default;pointer-events:none}
.lb-pill-ghost{background:rgba(255,255,255,0.05);border-color:#334155;color:#94a3b8}
.lb-pill-ghost:hover{background:rgba(255,255,255,0.1);border-color:#475569;color:#e2e8f0}
.lb-pill-purple{background:linear-gradient(135deg,#4c1d95,#5b21b6);border-color:#7c3aed;color:#e9d5ff;box-shadow:0 1px 8px rgba(124,58,237,0.25)}
.lb-pill-purple:hover,.lb-pill-purple.active{background:linear-gradient(135deg,#5b21b6,#7c3aed);border-color:#a78bfa;color:#fff;box-shadow:0 2px 12px rgba(124,58,237,0.4)}
.lb-pill-danger{background:linear-gradient(135deg,#7f1d1d,#991b1b);border-color:#dc2626;color:#fca5a5;box-shadow:0 1px 8px rgba(220,38,38,0.2)}
.lb-pill-danger:hover{background:linear-gradient(135deg,#991b1b,#dc2626);border-color:#f87171;color:#fff;box-shadow:0 2px 12px rgba(220,38,38,0.35)}
.lb-sel-pill{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:700;color:#fbbf24;padding:4px 10px;background:rgba(251,191,36,0.1);border-radius:20px;border:1.5px solid rgba(251,191,36,0.3)}
/* Image selection */
.lb-img-wrap{position:relative;display:inline-flex;cursor:pointer}
.lb-img-selected{outline:3px solid #f59e0b;border-radius:6px}
.lb-img-check{position:absolute;top:8px;right:8px;width:28px;height:28px;background:#f59e0b;border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.4)}
/* Move panel */
.lb-move-panel{background:#080e1a;border-bottom:2px solid #1e293b;flex-shrink:0;display:flex;flex-direction:column;max-height:240px}
.lb-move-hd{display:flex;align-items:center;justify-content:space-between;padding:9px 16px;border-bottom:1px solid #1a2840;flex-shrink:0}
.lb-move-hd-title{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:700;color:#a78bfa;text-transform:uppercase;letter-spacing:0.5px}
.lb-move-cancel-btn{width:22px;height:22px;border-radius:50%;background:#1e293b;border:1px solid #334155;color:#64748b;cursor:pointer;font-size:11px;display:flex;align-items:center;justify-content:center;transition:all 0.12s;font-family:inherit}
.lb-move-cancel-btn:hover{background:#334155;color:#e2e8f0;border-color:#475569}
.lb-move-tree-scroll{overflow-y:auto;padding:6px 10px;display:flex;flex-direction:column;gap:1px}

/* Tree groups */
.lb-tree-group-wrap{display:flex;flex-direction:column}
.lb-tree-group-btn{display:flex;align-items:center;gap:6px;padding:6px 10px;font-size:12px;font-weight:700;border-radius:8px;cursor:pointer;border:none;text-align:left;width:100%;font-family:inherit;transition:all 0.12s;background:transparent}
.lb-tree-is-room{color:#34d399}
.lb-tree-is-room:hover{background:rgba(52,211,153,0.08)}
.lb-tree-is-fixed{color:#818cf8}
.lb-tree-is-fixed:hover{background:rgba(129,140,248,0.08)}
.lb-tree-group-btn:not(.lb-tree-is-room):not(.lb-tree-is-fixed){color:#cbd5e1}
.lb-tree-group-btn:not(.lb-tree-is-room):not(.lb-tree-is-fixed):hover{background:#1e293b}
.lb-tree-group-label{flex:1}
.lb-tree-group-count{font-size:10px;font-weight:700;background:#1e293b;color:#475569;padding:1px 6px;border-radius:8px}
.lb-tree-chev{transition:transform 0.15s;opacity:0.5;flex-shrink:0}
.lb-tree-chev.open{transform:rotate(90deg)}
.lb-tree-type-icon{opacity:0.6;flex-shrink:0}
.lb-tree-sub-btn{display:flex;align-items:center;gap:6px;padding:5px 10px 5px 22px;font-size:11px;font-weight:600;color:#94a3b8;border-radius:6px;cursor:pointer;border:none;text-align:left;width:100%;font-family:inherit;background:transparent;transition:all 0.12s}
.lb-tree-sub-btn:hover{background:#1e293b;color:#e2e8f0}
.lb-tree-items{display:flex;flex-direction:column;gap:1px;padding-left:28px}
.lb-tree-item-btn{display:flex;align-items:center;gap:5px;padding:5px 10px;font-size:11px;color:#64748b;background:transparent;border:1px solid transparent;border-radius:6px;cursor:pointer;text-align:left;width:100%;font-family:inherit;transition:all 0.12s}
.lb-tree-item-btn:hover{background:#1e3a5f;color:#93c5fd;border-color:rgba(59,130,246,0.3)}

/* ═══════════════════════════════════════════════════════════════════ */
/* AUDIO MODULE                                                        */
/* ═══════════════════════════════════════════════════════════════════ */
/* Hide per-item mic buttons when human typist assigned */
.hide-mic-btns .mic-btn { display: none !important }
/* Show a playback-only indicator in the audio module */
.am-human-typist .am-btn-rec { display: none !important }
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

/* ═══════════════════════════════════════════════════════════════════ */
/* PHOTO GRID (View All)                                               */
/* ═══════════════════════════════════════════════════════════════════ */
.pg-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.82);z-index:1100;display:flex;align-items:center;justify-content:center;padding:20px}
.pg-modal{background:#1e293b;border-radius:14px;width:min(920px,96vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,0.6)}

/* Header */
.pg-header{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #334155;flex-shrink:0}
.pg-header-left{display:flex;align-items:center;gap:9px}
.pg-title{font-size:14px;font-weight:800;color:#f1f5f9}
.pg-title-sub{font-size:13px;color:#64748b;font-weight:500}
.pg-count-badge{background:#334155;color:#94a3b8;font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px}

/* Toolbar */
.pg-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 16px;background:#0f172a;border-bottom:1px solid #1e293b;flex-shrink:0;flex-wrap:wrap}
.pg-toolbar-left,.pg-toolbar-right{display:flex;align-items:center;gap:6px;flex-wrap:wrap}

/* Pill buttons for photo grid — mirrors lb-pill system */
.pg-pill{display:inline-flex;align-items:center;gap:5px;padding:5px 12px;font-size:12px;font-weight:600;border-radius:20px;cursor:pointer;border:1.5px solid transparent;font-family:inherit;transition:all 0.15s;white-space:nowrap}
.pg-pill:disabled{opacity:0.35;cursor:default;pointer-events:none}
.pg-pill-ghost{background:rgba(255,255,255,0.05);border-color:#334155;color:#94a3b8}
.pg-pill-ghost:hover{background:rgba(255,255,255,0.1);border-color:#475569;color:#e2e8f0}
.pg-pill-indigo{background:linear-gradient(135deg,#1e1b4b,#312e81);border-color:#6366f1;color:#c7d2fe;box-shadow:0 1px 8px rgba(99,102,241,0.2)}
.pg-pill-indigo:hover{background:linear-gradient(135deg,#312e81,#4f46e5);border-color:#818cf8;color:#fff;box-shadow:0 2px 12px rgba(99,102,241,0.4)}
.pg-pill-purple{background:linear-gradient(135deg,#4c1d95,#5b21b6);border-color:#7c3aed;color:#e9d5ff;box-shadow:0 1px 8px rgba(124,58,237,0.2)}
.pg-pill-purple:hover,.pg-pill-purple.active{background:linear-gradient(135deg,#5b21b6,#7c3aed);border-color:#a78bfa;color:#fff;box-shadow:0 2px 12px rgba(124,58,237,0.4)}
.pg-pill-danger{background:linear-gradient(135deg,#7f1d1d,#991b1b);border-color:#dc2626;color:#fca5a5;box-shadow:0 1px 8px rgba(220,38,38,0.15)}
.pg-pill-danger:hover{background:linear-gradient(135deg,#991b1b,#dc2626);border-color:#f87171;color:#fff;box-shadow:0 2px 12px rgba(220,38,38,0.3)}
.pg-sel-badge{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:700;color:#fbbf24;padding:4px 10px;background:rgba(251,191,36,0.1);border-radius:20px;border:1.5px solid rgba(251,191,36,0.3)}

/* Move tree panel */
.pg-move-panel{background:#080e1a;border-bottom:2px solid #1e293b;flex-shrink:0;display:flex;flex-direction:column;max-height:240px}
.pg-move-hd{display:flex;align-items:center;justify-content:space-between;padding:9px 16px;border-bottom:1px solid #1a2840;flex-shrink:0}
.pg-move-title{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:700;color:#a78bfa;text-transform:uppercase;letter-spacing:0.5px}
.pg-move-close{width:22px;height:22px;border-radius:50%;background:#1e293b;border:1px solid #334155;color:#64748b;cursor:pointer;font-size:11px;display:flex;align-items:center;justify-content:center;transition:all 0.12s;font-family:inherit}
.pg-move-close:hover{background:#334155;color:#e2e8f0;border-color:#475569}
.pg-move-tree{overflow-y:auto;padding:6px 10px;display:flex;flex-direction:column;gap:1px}
.pg-move-empty{font-size:12px;color:#475569;padding:12px;text-align:center}

/* Tree items — shared style between pg and lb trees */
.pg-tree-group-wrap{display:flex;flex-direction:column}
.pg-tree-group{display:flex;align-items:center;gap:6px;padding:6px 10px;font-size:12px;font-weight:700;border-radius:8px;cursor:pointer;border:none;text-align:left;width:100%;font-family:inherit;transition:all 0.12s;background:transparent}
.pg-tree-fixed{color:#818cf8}.pg-tree-fixed:hover{background:rgba(129,140,248,0.08)}
.pg-tree-room{color:#34d399}.pg-tree-room:hover{background:rgba(52,211,153,0.08)}
.pg-tree-group:not(.pg-tree-fixed):not(.pg-tree-room){color:#cbd5e1}.pg-tree-group:not(.pg-tree-fixed):not(.pg-tree-room):hover{background:#1e293b}
.pg-tree-group-icon{opacity:0.6;display:flex;align-items:center;flex-shrink:0}
.pg-tree-chevron{transition:transform 0.15s;flex-shrink:0;opacity:0.5}
.pg-tree-chevron.open{transform:rotate(90deg)}
.pg-tree-child-count{margin-left:auto;font-size:10px;font-weight:700;background:#1e293b;color:#475569;padding:1px 6px;border-radius:8px}
.pg-tree-children{display:flex;flex-direction:column;gap:1px;padding:2px 0 4px 24px}
.pg-tree-item{display:flex;align-items:center;gap:5px;padding:5px 10px;font-size:11px;color:#64748b;background:transparent;border:1px solid transparent;border-radius:6px;cursor:pointer;text-align:left;width:100%;font-family:inherit;transition:all 0.12s}
.pg-tree-item:hover{background:#1e3a5f;color:#93c5fd;border-color:rgba(59,130,246,0.3)}

/* Grid */
.pg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;padding:14px;overflow-y:auto;flex:1;min-height:0;background:#0f172a}
.pg-cell{position:relative;border-radius:8px;overflow:hidden;aspect-ratio:1;cursor:pointer;border:2px solid transparent;transition:border-color 0.12s,transform 0.1s;background:#1e293b}
.pg-cell:hover{transform:scale(1.02);border-color:#475569}
.pg-cell-selected{border-color:#f59e0b !important;box-shadow:0 0 0 1px #f59e0b}
.pg-img{width:100%;height:100%;object-fit:cover;display:block}
.pg-cell-num{position:absolute;bottom:5px;left:6px;font-size:10px;font-weight:700;color:rgba(255,255,255,0.7);background:rgba(0,0,0,0.5);padding:1px 5px;border-radius:4px;pointer-events:none}
.pg-cell-check{position:absolute;top:6px;left:6px;width:22px;height:22px;background:#f59e0b;border-radius:50%;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity 0.12s;pointer-events:none}
.pg-cell-check.visible{opacity:1}
.pg-cell-open{position:absolute;top:5px;right:5px;width:24px;height:24px;background:rgba(0,0,0,0.55);border:1px solid rgba(255,255,255,0.2);border-radius:5px;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity 0.15s;cursor:pointer;color:white}
.pg-cell:hover .pg-cell-open{opacity:1}
.pg-cell-open:hover{background:rgba(99,102,241,0.8) !important}

.pg-empty{grid-column:1/-1;text-align:center;color:#475569;padding:40px;font-size:14px}

/* Footer */
.pg-footer{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-top:1px solid #1e293b;flex-shrink:0}
.pg-footer-hint{font-size:11px;color:#475569}
.pg-footer-sel{font-size:12px;font-weight:700;color:#f59e0b}

/* Card-level View All Photos button */
.card-view-all-btn{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;font-size:11px;font-weight:700;border-radius:20px;cursor:pointer;border:1.5px solid #c7d2fe;background:linear-gradient(135deg,#eef2ff,#e0e7ff);color:#4338ca;font-family:inherit;transition:all 0.18s;letter-spacing:0.01em;box-shadow:0 1px 4px rgba(99,102,241,0.12)}
.card-view-all-btn:hover{background:linear-gradient(135deg,#6366f1,#4f46e5);color:white;border-color:#6366f1;box-shadow:0 2px 12px rgba(99,102,241,0.35);transform:translateY(-1px)}
.card-view-all-room{border-color:#ddd6fe;background:linear-gradient(135deg,#f5f3ff,#ede9fe);color:#6d28d9;box-shadow:0 1px 4px rgba(124,58,237,0.12)}
.card-view-all-room:hover{background:linear-gradient(135deg,#7c3aed,#6d28d9);color:white;border-color:#7c3aed;box-shadow:0 2px 12px rgba(124,58,237,0.35);transform:translateY(-1px)}
.card-photo-count{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 5px;font-size:10px;font-weight:800;border-radius:9px;background:#6366f1;color:white;line-height:1}
.card-view-all-room .card-photo-count{background:#7c3aed}
.card-view-all-btn:hover .card-photo-count,.card-view-all-room:hover .card-photo-count{background:rgba(255,255,255,0.3)}

/* Photo cell sub-label (allSection mode) */
.pg-cell-label{position:absolute;bottom:0;left:0;right:0;font-size:9px;font-weight:700;color:rgba(255,255,255,0.9);background:linear-gradient(transparent,rgba(0,0,0,0.7));padding:12px 5px 4px;text-align:center;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}


/* ── AI Transcription styles ───────────────────────────────────────── */
.am-ai-status{display:flex;align-items:center;gap:8px;padding:7px 14px;font-size:12px;font-weight:600;border-radius:6px;margin-top:6px;flex-wrap:wrap}
.am-ai-processing{background:rgba(99,102,241,0.12);color:#a5b4fc;border:1px solid rgba(99,102,241,0.25)}
.am-ai-ready{background:rgba(16,185,129,0.08);color:#6ee7b7;border:1px solid rgba(16,185,129,0.2);justify-content:space-between}
.am-ai-error{background:rgba(220,38,38,0.1);color:#fca5a5;border:1px solid rgba(220,38,38,0.2);justify-content:space-between}
.am-ai-error-dismiss{background:none;border:none;color:#fca5a5;cursor:pointer;font-size:16px;padding:0 4px;line-height:1;font-family:inherit}
.am-ai-process-btn{padding:4px 10px;background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);border-radius:4px;font-size:11px;font-weight:700;color:#6ee7b7;cursor:pointer;transition:all 0.12s;font-family:inherit;white-space:nowrap}
.am-ai-process-btn:hover{background:rgba(16,185,129,0.25);color:#a7f3d0}
/* Item mic button AI processing state — pulsing indigo */
.mic-ai{background:rgba(99,102,241,0.15)!important;border-color:#6366f1!important;animation:mic-ai-pulse 1.2s ease-in-out infinite}
@keyframes mic-ai-pulse{0%,100%{opacity:1}50%{opacity:0.5}}

/* ── Photo timestamp overlay ─────────────────────────────────────────────── */
.lb-timestamp {
  position: absolute;
  bottom: 10px;
  right: 10px;
  background: rgba(0, 0, 0, 0.62);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 9px;
  border-radius: 5px;
  letter-spacing: 0.02em;
  pointer-events: none;
  font-family: 'Courier New', monospace;
}

/* ── Action Summary card ─────────────────────────────────────────────────── */
.card-action-summary { border-top: 3px solid #f59e0b; }
.card-hd-summary { background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); }
.summary-icon { font-size: 16px; margin-right: 2px; }
.summary-groups { display: flex; flex-direction: column; gap: 18px; padding: 4px 0; }

.summary-group-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f8fafc;
  border-left: 4px solid;
  border-radius: 0 6px 6px 0;
  margin-bottom: 8px;
}
.summary-group-dot  { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.summary-group-name { font-size: 14px; font-weight: 700; color: #1e293b; flex: 1; }
.summary-group-count { font-size: 11px; color: #64748b; font-weight: 600; }

.summary-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.summary-tbl th {
  padding: 7px 10px;
  text-align: left;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #94a3b8;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
}
.summary-tbl td {
  padding: 8px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
  vertical-align: top;
}
.summary-tbl tr:last-child td { border-bottom: none; }
.summary-tbl tr:hover td { background: #fafafa; }

.stbl-ref  { width: 54px; color: #64748b; font-size: 12px; font-weight: 600; white-space: nowrap; }
.stbl-room { width: 160px; font-weight: 600; }
.stbl-resp { width: 130px; }
.stbl-note { width: 200px; color: #64748b; font-size: 12px; }

.resp-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.resp-none { color: #cbd5e1; font-size: 12px; }


.add-sub-below{display:block;background:none;border:none;color:#7c3aed;font-size:11px;font-weight:600;cursor:pointer;padding:4px 0 2px;text-align:left;width:auto;grid-column:1 / -1}
.add-sub-below:hover{text-decoration:underline}
.action-trigger-btn{color:#f59e0b !important;border-color:rgba(245,158,11,0.25) !important}
.action-trigger-btn:hover{background:rgba(245,158,11,0.1) !important;border-color:rgba(245,158,11,0.4) !important}
.action-trigger-btn.action-has{background:rgba(245,158,11,0.08) !important;border-color:rgba(245,158,11,0.35) !important}
.action-count{background:#f59e0b !important}
.td-btn-group{padding:0}

/* ══════════════════════════════════════════════════════════════════
   REPORT EDITOR — MOBILE  ≤ 768px
══════════════════════════════════════════════════════════════════ */

/* Mobile nav toggle: hidden on desktop, shown on mobile */
.mobile-nav-toggle { display: none; }
/* Nav body: always visible on desktop */
.mobile-nav-body { display: block; }

@media (max-width: 768px) {

  /* ── Shell ── */
  .shell { height: 100dvh; overflow: hidden; }

  /* ── Topbar ── */
  .topbar { padding: 0 12px; height: 48px; gap: 8px; }
  .prog, .crumb-sep, .crumb-type, .crumb-who { display: none !important; }
  .crumb-addr { font-size: 12px; max-width: 140px; }
  .back-btn { padding: 4px 8px; font-size: 11px; }
  .save-btn { padding: 5px 12px; font-size: 12px; }
  .photo-btn span, .review-btn-label { display: none; }

  /* ── Body ── */
  .body { display: flex; flex-direction: column; grid-template-columns: unset; overflow: hidden; }

  /* ── Sidebar: collapsible ── */
  .sidebar {
    width: 100% !important; height: auto !important; overflow: visible !important;
    display: flex !important; flex-direction: column !important; padding: 0 !important;
    border-right: none !important; border-bottom: 1px solid #0d1726 !important;
    background: #172033 !important; flex-shrink: 0;
  }
  .mobile-nav-toggle {
    display: flex; align-items: center; justify-content: space-between;
    width: 100%; padding: 10px 14px; background: none; border: none; cursor: pointer;
    color: #a5b4fc; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px;
  }
  .mobile-nav-toggle-label { display: flex; align-items: center; gap: 7px; }
  .mobile-nav-toggle-arrow { font-size: 9px; transition: transform 0.2s; color: #4b6282; }
  .mobile-nav-toggle-arrow.open { transform: rotate(180deg); color: #a5b4fc; }
  .mobile-nav-body { display: none; padding: 0 10px 10px; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
  .mobile-nav-body::-webkit-scrollbar { display: none; }
  .mobile-nav-body.nav-open { display: block; }
  .nav-grp { margin-bottom: 4px; }
  .nav-lbl { padding: 8px 4px 4px; font-size: 9px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: #2d4a6b; display: block; }
  .nav-btn {
    display: inline-flex; white-space: nowrap; margin: 2px;
    padding: 5px 10px !important; border-radius: 14px !important;
    border-left: none !important; border: 1px solid rgba(255,255,255,0.06) !important;
    font-size: 11px !important; font-weight: 600 !important;
    background: rgba(255,255,255,0.04) !important; color: #6b8caf !important;
    min-width: 0 !important; width: auto !important;
  }
  .nav-btn.active { background: #6366f1 !important; color: white !important; border-color: transparent !important; }
  .sidebar-warn { display: none !important; }

  /* ── Main ── */
  .main { padding: 14px 12px 100px !important; flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; gap: 14px !important; }

  /* ── Cards ── */
  .card { border-radius: 10px !important; margin-bottom: 0 !important; }
  .card-hd { padding: 10px 14px !important; }
  .card-title { font-size: 13px !important; }

  /* ── Fixed section table rows ── */
  .tbl thead, .tbl th { display: none !important; }
  .tbl tbody tr {
    display: flex !important; flex-direction: column !important;
    padding: 10px 12px !important; border-bottom: 1px solid #f1f5f9 !important; gap: 6px !important;
  }
  .tbl tbody tr td { display: block !important; width: 100% !important; padding: 0 !important; border: none !important; box-sizing: border-box !important; }
  .tbl tbody tr .td-drag { display: none !important; }
  .tbl tbody tr .td-name { font-size: 13px !important; font-weight: 700 !important; color: #1e293b !important; white-space: normal !important; }
  .tbl tbody tr td textarea,
  .tbl tbody tr td select,
  .tbl tbody tr td input[type="text"] { width: 100% !important; min-height: 38px !important; font-size: 14px !important; padding: 8px 10px !important; border-radius: 7px !important; box-sizing: border-box !important; }
  .td-btn-group { width: 100% !important; padding: 0 !important; }
  .tbl tbody .photo-panel-row { display: block !important; width: 100% !important; }
  .photo-panel-row td { width: 100% !important; display: block !important; padding: 0 !important; }

  /* ── QA rows (Health and Safety) ── */
  .qa-row { padding: 12px !important; }
  .qa-row-header { display: flex !important; align-items: flex-start !important; gap: 6px !important; }
  .qa-question { flex: 1 !important; }
  .qa-row-bottom { flex-direction: column !important; gap: 8px !important; }
  .qa-row-bottom .qa-controls { flex-direction: column !important; width: 100% !important; }
  .qa-row-bottom .qa-controls select { width: 100% !important; }
  .qa-row-bottom .item-btn-col { flex-direction: row !important; width: 100% !important; padding-left: 0 !important; padding-top: 0 !important; }
  .qa-controls { flex-wrap: wrap; gap: 8px; }

  /* ── Room item layout ── */
  .item-fields-row { flex-direction: column !important; gap: 8px !important; padding: 10px 12px 8px !important; }
  .item-fields-main { grid-template-columns: 1fr !important; gap: 8px !important; width: 100% !important; }
  .room-field-desc, .room-field-cond, .room-field-notes { grid-column: 1 !important; width: 100% !important; }
  .item-btn-col { display: flex !important; flex-direction: row !important; gap: 6px !important; width: 100% !important; }
  .item-header-bar { padding: 8px 12px 6px !important; }
  .cam-btn { min-width: 38px !important; min-height: 36px !important; }
  .del-btn  { min-width: 34px !important; min-height: 36px !important; }

  /* ── Actions picker: hidden on mobile until action-trigger-btn tapped ── */
  .room-field-actions { display: none !important; }
  .room-field-actions.actions-expanded { display: block !important; }

  /* ── Photo panels ── */
  .photo-panel, .photo-panel-inline, .photo-panel-sub {
    display: flex !important; flex-direction: row !important; overflow-x: auto !important;
    gap: 8px !important; padding: 8px !important; -webkit-overflow-scrolling: touch;
    scrollbar-width: none; flex-wrap: nowrap !important;
  }
  .photo-panel::-webkit-scrollbar, .photo-panel-inline::-webkit-scrollbar { display: none; }
  .ph-thumb { flex-shrink: 0 !important; width: 70px !important; height: 70px !important; }
  .ph-img-click { width: 70px !important; height: 70px !important; object-fit: cover !important; border-radius: 6px !important; }
  .ph-upload-btn, .ph-view-all-btn {
    flex-shrink: 0 !important; white-space: nowrap !important; align-self: center !important;
    padding: 8px 12px !important; font-size: 12px !important; min-height: 38px !important;
    display: flex !important; align-items: center !important; gap: 5px !important;
  }

  /* ── Misc ── */
  .fld-textarea, .fld-select, .fld-input { width: 100% !important; min-height: 38px !important; font-size: 14px !important; padding: 8px 10px !important; border-radius: 7px !important; }
  .add-row-bar { padding: 10px 12px !important; }
  .room-header-bar { flex-wrap: wrap; gap: 8px; padding: 10px 12px !important; }
  .room-name-input { min-width: 120px !important; max-width: 100% !important; font-size: 15px !important; }
  .topbar-r { gap: 6px; }
  .save-btn { min-width: 60px; min-height: 36px; }
  .review-btn { min-width: 60px; min-height: 36px; padding: 6px 14px !important; font-size: 12px !important; }
  .pg-modal, .lightbox-modal {
    inset: 0 !important; border-radius: 0 !important;
    width: 100% !important; height: 100% !important;
    max-width: 100% !important; max-height: 100% !important;
  }
  .pg-grid { grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)) !important; gap: 6px !important; }
  .co-fields-row .item-fields-main { grid-template-columns: 1fr !important; }
  .sub-fields-row .item-fields-main { grid-template-columns: 1fr !important; }
  .meter-row, .key-row { flex-direction: column !important; gap: 6px !important; }
}

@media (max-width: 400px) {
  .topbar { padding: 0 8px; gap: 6px; }
  .crumb-addr { max-width: 100px; font-size: 11px; }
  .save-btn { font-size: 11px; padding: 5px 10px; }
}
</style>