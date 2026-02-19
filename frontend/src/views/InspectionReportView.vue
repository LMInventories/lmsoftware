<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import api from '../services/api'

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
const drag = ref({ sectionId: null, fromIdx: null, type: null }) // type: 'fixed'|'room'

const reportData = ref({})

// ── Load ──────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const iRes = await api.getInspection(route.params.id)
    inspection.value = iRes.data

    if (inspection.value.template_id) {
      const tRes = await api.getTemplate(inspection.value.template_id)
      template.value = tRes.data
    }

    if (inspection.value.report_data) {
      try { reportData.value = JSON.parse(inspection.value.report_data) } catch { reportData.value = {} }
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
  const extraItems = (reportData.value[room.id]?._extra || []).map(ex => ({ ...ex, id: ex._eid, label: ex.label || 'New item', _type: 'extra' }))
  const all = [...templateItems, ...extraItems]

  if (!storedOrder || storedOrder.length === 0) return all

  // Reorder by storedOrder, append any new items not in order list
  const ordered = []
  for (const id of storedOrder) {
    const found = all.find(i => String(i.id) === String(id) || String(i._eid) === String(id))
    if (found) ordered.push(found)
  }
  // Append anything not yet in order
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
  if (type === 'condition_summary')  { blank.name=''; blank.condition='' }
  else if (type === 'cleaning_summary') { blank.name=''; blank.cleanliness=''; blank.cleanlinessNotes='' }
  else if (type === 'smoke_alarms' || type === 'health_safety') { blank.question=''; blank.answer=''; blank.notes='' }
  else if (type === 'fire_door_safety') { blank.name=''; blank.question=''; blank.answer=''; blank.notes='' }
  else if (type === 'keys')         { blank.name=''; blank.description='' }
  else if (type === 'meter_readings') { blank.name=''; blank.locationSerial=''; blank.reading='' }
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
  // If there's an _itemOrder, append new eid to it
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

// ── Drag to reorder (fixed section extra rows) ────────────────────────
const dragFixedFrom = ref(null)
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
const dragRoomFrom = ref(null)
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

const cleanlinessOpts = ['Professionally Cleaned','Professionally Cleaned — Receipt Seen','Professionally Cleaned with Omissions','Domestically Cleaned','Domestically Cleaned with Omissions','Not Clean']

const typeLabel = computed(() => ({ check_in:'Check In', check_out:'Check Out', interim:'Interim Inspection', inventory:'Inventory' })[inspection.value?.inspection_type] ?? '')
const savedTime = computed(() => lastSaved.value ? lastSaved.value.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'}) : null)

function sectionStarted(sectionId) {
  const d = reportData.value[sectionId]
  if (!d) return false
  return Object.values(d).some(row => row && typeof row === 'object' && Object.values(row).some(v => v !== '' && v != null))
}
const startedCount = computed(() => allSections.value.filter(s => sectionStarted(s.id)).length)
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
              <span class="dot" :class="{ done: sectionStarted(s.id) }"></span>{{ s.name }}
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
          <p>No template assigned.</p>
        </div>
      </nav>

      <main class="main" @scroll="onScroll">
        <div v-if="!template" class="empty-state">
          <h3>No template assigned</h3>
          <p>Assign a template from the inspection overview first.</p>
          <button class="btn-ghost" @click="router.push(`/inspections/${inspection.id}`)">← Back to Overview</button>
        </div>

        <div v-else>

          <!-- ═══ FIXED SECTIONS ═══════════════════════════════════ -->
          <div v-for="sec in fixedSections" :key="sec.id" :id="`sec-${sec.id}`" class="card">
            <div class="card-hd">
              <h2 class="card-title">{{ sec.name }}</h2>
              <div class="card-hd-right">
                <span v-if="hasHidden(sec.id)" class="hidden-badge">{{ reportData[sec.id]?._hidden?.length }} hidden</span>
                <span class="card-hint">{{ sec.rows?.length || 0 }} items</span>
              </div>
            </div>

            <!-- CONDITION SUMMARY -->
            <div v-if="sec.type === 'condition_summary'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Item</th><th>Condition</th><th class="col-del"></th></tr></thead>
                <tbody>
                  <tr v-for="row in sec.rows" :key="row.id" v-show="!isHidden(sec.id, row.id)">
                    <td class="td-drag"><span class="drag-handle" title="Drag to reorder">⠿</span></td>
                    <td class="td-name">{{ row.name }}</td>
                    <td><input class="fld-input" type="text" placeholder="Describe condition…" :value="get(sec.id,row.id,'condition')" @input="set(sec.id,row.id,'condition',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                  </tr>
                  <tr v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid" class="extra-row"
                    draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                    <td class="td-drag"><span class="drag-handle">⠿</span></td>
                    <td><input class="fld-input" type="text" placeholder="Item name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                    <td><input class="fld-input" type="text" placeholder="Describe condition…" :value="ex.condition" @input="setExtraField(sec.id,ex._eid,'condition',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                  </tr>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- CLEANING SUMMARY -->
            <div v-else-if="sec.type === 'cleaning_summary'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Area</th><th class="col-clean">Cleanliness</th><th>Notes</th><th class="col-del"></th></tr></thead>
                <tbody>
                  <tr v-for="row in sec.rows" :key="row.id" v-show="!isHidden(sec.id,row.id)">
                    <td class="td-drag"><span class="drag-handle">⠿</span></td>
                    <td class="td-name">{{ row.name }}</td>
                    <td><select class="fld-select" :value="get(sec.id,row.id,'cleanliness')" @change="set(sec.id,row.id,'cleanliness',$event.target.value)"><option value="">— Select —</option><option v-for="o in cleanlinessOpts" :key="o" :value="o">{{ o }}</option></select></td>
                    <td><input class="fld-input" type="text" placeholder="Notes…" :value="get(sec.id,row.id,'cleanlinessNotes')" @input="set(sec.id,row.id,'cleanlinessNotes',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                  </tr>
                  <tr v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid" class="extra-row"
                    draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                    <td class="td-drag"><span class="drag-handle">⠿</span></td>
                    <td><input class="fld-input" type="text" placeholder="Area name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                    <td><select class="fld-select" :value="ex.cleanliness" @change="setExtraField(sec.id,ex._eid,'cleanliness',$event.target.value)"><option value="">— Select —</option><option v-for="o in cleanlinessOpts" :key="o" :value="o">{{ o }}</option></select></td>
                    <td><input class="fld-input" type="text" placeholder="Notes…" :value="ex.cleanlinessNotes" @input="setExtraField(sec.id,ex._eid,'cleanlinessNotes',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                  </tr>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- SMOKE ALARMS -->
            <div v-else-if="sec.type === 'smoke_alarms'">
              <div v-for="row in sec.rows" :key="row.id" v-show="!isHidden(sec.id,row.id)" class="qa-row">
                <div class="qa-row-header"><p class="qa-question">{{ row.question }}</p><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div>
                <p v-if="row.notes" class="qa-guidance">{{ row.notes }}</p>
                <div class="qa-controls">
                  <div class="yn-group"><label v-for="opt in ['Yes','No','N/A']" :key="opt" class="yn-chip" :class="{'yn-yes':get(sec.id,row.id,'answer')==='Yes'&&opt==='Yes','yn-no':get(sec.id,row.id,'answer')==='No'&&opt==='No','yn-na':get(sec.id,row.id,'answer')==='N/A'&&opt==='N/A'}"><input type="radio" :name="`${sec.id}_${row.id}`" style="display:none" :checked="get(sec.id,row.id,'answer')===opt" @change="set(sec.id,row.id,'answer',opt)" />{{ opt }}</label></div>
                  <input class="fld-input fld-grow" type="text" placeholder="Additional notes…" :value="get(sec.id,row.id,'notes')" @input="set(sec.id,row.id,'notes',$event.target.value)" />
                </div>
              </div>
              <div v-for="ex in getExtra(sec.id)" :key="ex._eid" class="qa-row extra-row">
                <div class="qa-extra-header"><input class="fld-input fld-grow" type="text" placeholder="Question / item…" :value="ex.question" @input="setExtraField(sec.id,ex._eid,'question',$event.target.value)" /><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div>
                <div class="qa-controls"><div class="yn-group"><label v-for="opt in ['Yes','No','N/A']" :key="opt" class="yn-chip" :class="{'yn-yes':ex.answer==='Yes'&&opt==='Yes','yn-no':ex.answer==='No'&&opt==='No','yn-na':ex.answer==='N/A'&&opt==='N/A'}"><input type="radio" :name="`${sec.id}_${ex._eid}`" style="display:none" :checked="ex.answer===opt" @change="setExtraField(sec.id,ex._eid,'answer',opt)" />{{ opt }}</label></div><input class="fld-input fld-grow" type="text" placeholder="Notes…" :value="ex.notes" @input="setExtraField(sec.id,ex._eid,'notes',$event.target.value)" /></div>
              </div>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- FIRE DOOR -->
            <div v-else-if="sec.type === 'fire_door_safety'">
              <div v-for="row in sec.rows" :key="row.id" v-show="!isHidden(sec.id,row.id)" class="qa-row">
                <div class="qa-row-header"><div><div class="qa-location-badge">{{ row.name }}</div><p class="qa-question" style="margin-top:6px">{{ row.question }}</p></div><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div>
                <p v-if="row.notes" class="qa-guidance">{{ row.notes }}</p>
                <div class="qa-controls"><div class="yn-group"><label v-for="opt in ['Yes','No','N/A']" :key="opt" class="yn-chip" :class="{'yn-yes':get(sec.id,row.id,'answer')==='Yes'&&opt==='Yes','yn-no':get(sec.id,row.id,'answer')==='No'&&opt==='No','yn-na':get(sec.id,row.id,'answer')==='N/A'&&opt==='N/A'}"><input type="radio" :name="`${sec.id}_${row.id}`" style="display:none" :checked="get(sec.id,row.id,'answer')===opt" @change="set(sec.id,row.id,'answer',opt)" />{{ opt }}</label></div><input class="fld-input fld-grow" type="text" placeholder="Notes…" :value="get(sec.id,row.id,'notes')" @input="set(sec.id,row.id,'notes',$event.target.value)" /></div>
              </div>
              <div v-for="ex in getExtra(sec.id)" :key="ex._eid" class="qa-row extra-row">
                <div class="qa-extra-header"><input class="fld-input" type="text" placeholder="Location…" style="width:160px" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /><input class="fld-input fld-grow" type="text" placeholder="Question…" :value="ex.question" @input="setExtraField(sec.id,ex._eid,'question',$event.target.value)" /><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div>
                <div class="qa-controls"><div class="yn-group"><label v-for="opt in ['Yes','No','N/A']" :key="opt" class="yn-chip" :class="{'yn-yes':ex.answer==='Yes'&&opt==='Yes','yn-no':ex.answer==='No'&&opt==='No','yn-na':ex.answer==='N/A'&&opt==='N/A'}"><input type="radio" :name="`${sec.id}_${ex._eid}`" style="display:none" :checked="ex.answer===opt" @change="setExtraField(sec.id,ex._eid,'answer',opt)" />{{ opt }}</label></div><input class="fld-input fld-grow" type="text" placeholder="Notes…" :value="ex.notes" @input="setExtraField(sec.id,ex._eid,'notes',$event.target.value)" /></div>
              </div>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- HEALTH & SAFETY -->
            <div v-else-if="sec.type === 'health_safety'">
              <div v-for="row in sec.rows" :key="row.id" v-show="!isHidden(sec.id,row.id)" class="qa-row">
                <div class="qa-row-header"><p class="qa-question">{{ row.question }}</p><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></div>
                <p v-if="row.notes" class="qa-guidance">{{ row.notes }}</p>
                <div class="qa-controls"><div class="yn-group"><label v-for="opt in ['Yes','No','N/A']" :key="opt" class="yn-chip" :class="{'yn-yes':get(sec.id,row.id,'answer')==='Yes'&&opt==='Yes','yn-no':get(sec.id,row.id,'answer')==='No'&&opt==='No','yn-na':get(sec.id,row.id,'answer')==='N/A'&&opt==='N/A'}"><input type="radio" :name="`${sec.id}_${row.id}`" style="display:none" :checked="get(sec.id,row.id,'answer')===opt" @change="set(sec.id,row.id,'answer',opt)" />{{ opt }}</label></div><input class="fld-input fld-grow" type="text" placeholder="Notes…" :value="get(sec.id,row.id,'notes')" @input="set(sec.id,row.id,'notes',$event.target.value)" /></div>
              </div>
              <div v-for="ex in getExtra(sec.id)" :key="ex._eid" class="qa-row extra-row">
                <div class="qa-extra-header"><input class="fld-input fld-grow" type="text" placeholder="Question / item…" :value="ex.question" @input="setExtraField(sec.id,ex._eid,'question',$event.target.value)" /><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></div>
                <div class="qa-controls"><div class="yn-group"><label v-for="opt in ['Yes','No','N/A']" :key="opt" class="yn-chip" :class="{'yn-yes':ex.answer==='Yes'&&opt==='Yes','yn-no':ex.answer==='No'&&opt==='No','yn-na':ex.answer==='N/A'&&opt==='N/A'}"><input type="radio" :name="`${sec.id}_${ex._eid}`" style="display:none" :checked="ex.answer===opt" @change="setExtraField(sec.id,ex._eid,'answer',opt)" />{{ opt }}</label></div><input class="fld-input fld-grow" type="text" placeholder="Notes…" :value="ex.notes" @input="setExtraField(sec.id,ex._eid,'notes',$event.target.value)" /></div>
              </div>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- KEYS -->
            <div v-else-if="sec.type === 'keys'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Key / Access Item</th><th>Description</th><th class="col-del"></th></tr></thead>
                <tbody>
                  <tr v-for="row in sec.rows" :key="row.id" v-show="!isHidden(sec.id,row.id)">
                    <td class="td-drag"><span class="drag-handle">⠿</span></td>
                    <td class="td-name">{{ row.name }}</td>
                    <td><input class="fld-input" type="text" placeholder="e.g. 2× Yale front door key…" :value="get(sec.id,row.id,'description')" @input="set(sec.id,row.id,'description',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                  </tr>
                  <tr v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid" class="extra-row"
                    draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                    <td class="td-drag"><span class="drag-handle">⠿</span></td>
                    <td><input class="fld-input" type="text" placeholder="Key / item name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                    <td><input class="fld-input" type="text" placeholder="Description…" :value="ex.description" @input="setExtraField(sec.id,ex._eid,'description',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                  </tr>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <!-- METERS -->
            <div v-else-if="sec.type === 'meter_readings'">
              <table class="tbl">
                <thead><tr><th class="col-drag"></th><th class="col-item">Meter</th><th>Location &amp; Serial No.</th><th class="col-reading">Reading</th><th class="col-del"></th></tr></thead>
                <tbody>
                  <tr v-for="row in sec.rows" :key="row.id" v-show="!isHidden(sec.id,row.id)">
                    <td class="td-drag"><span class="drag-handle">⠿</span></td>
                    <td class="td-name">{{ row.name }}</td>
                    <td><input class="fld-input" type="text" placeholder="e.g. Understairs cupboard — SN 123456" :value="get(sec.id,row.id,'locationSerial')" @input="set(sec.id,row.id,'locationSerial',$event.target.value)" /></td>
                    <td><input class="fld-input fld-mono" type="text" placeholder="e.g. 12345.6" :value="get(sec.id,row.id,'reading')" @input="set(sec.id,row.id,'reading',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="hideRow(sec.id,row.id)">×</button></td>
                  </tr>
                  <tr v-for="(ex,idx) in getExtra(sec.id)" :key="ex._eid" class="extra-row"
                    draggable="true" @dragstart="onFixedDragStart(sec.id,idx)" @dragover.prevent @drop.prevent="onFixedDrop(sec.id,idx)">
                    <td class="td-drag"><span class="drag-handle">⠿</span></td>
                    <td><input class="fld-input" type="text" placeholder="Meter name…" :value="ex.name" @input="setExtraField(sec.id,ex._eid,'name',$event.target.value)" /></td>
                    <td><input class="fld-input" type="text" placeholder="Location & serial…" :value="ex.locationSerial" @input="setExtraField(sec.id,ex._eid,'locationSerial',$event.target.value)" /></td>
                    <td><input class="fld-input fld-mono" type="text" placeholder="Reading…" :value="ex.reading" @input="setExtraField(sec.id,ex._eid,'reading',$event.target.value)" /></td>
                    <td class="td-del"><button class="del-btn" @click="removeExtraRow(sec.id,ex._eid)">×</button></td>
                  </tr>
                </tbody>
              </table>
              <div class="add-row-bar"><button class="add-row-btn" @click="addExtraRow(sec.id,sec.type)">+ Add line</button></div>
            </div>

            <div v-else class="unknown-type">Unknown section type: {{ sec.type }}</div>
          </div>

          <!-- ═══ ROOMS ═════════════════════════════════════════════ -->
          <div v-for="room in rooms" :key="room.id" :id="`sec-${room.id}`" class="card card-room">
            <div class="card-hd card-hd-room">
              <h2 class="card-title">{{ room.name }}</h2>
              <span class="card-hint">{{ room.sections?.length || 0 }} items</span>
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
              <!-- Label column -->
              <div class="room-row-label">
                <span class="drag-handle drag-handle-room">⠿</span>
                <template v-if="item._type === 'extra'">
                  <input class="fld-input label-input" type="text" placeholder="Item name…"
                    :value="item.label"
                    @input="setRoomExtraField(room.id, item._eid, 'label', $event.target.value)" />
                </template>
                <template v-else>{{ item.label }}</template>
              </div>

              <!-- Fields column -->
              <div class="room-row-right">
                <div class="room-row-fields">
                  <!-- Template item fields -->
                  <template v-if="item._type === 'template'">
                    <div v-if="item.hasDescription" class="room-field-desc">
                      <label class="field-lbl">Description</label>
                      <textarea class="fld-textarea" rows="3" :placeholder="`Describe ${item.label.toLowerCase()}…`"
                        :value="get(room.id,item.id,'description')" @input="set(room.id,item.id,'description',$event.target.value)"></textarea>
                    </div>
                    <div v-if="item.hasCondition" class="room-field-cond">
                      <label class="field-lbl">Condition</label>
                      <textarea class="fld-textarea" rows="3" :placeholder="`Condition of ${item.label.toLowerCase()}…`"
                        :value="get(room.id,item.id,'condition')" @input="set(room.id,item.id,'condition',$event.target.value)"></textarea>
                    </div>
                    <div v-if="item.hasNotes" class="room-field-notes">
                      <label class="field-lbl">Notes</label>
                      <input class="fld-input" type="text" placeholder="Notes…"
                        :value="get(room.id,item.id,'notes')" @input="set(room.id,item.id,'notes',$event.target.value)" />
                    </div>
                  </template>
                  <!-- Extra item fields -->
                  <template v-else>
                    <div class="room-field-desc">
                      <label class="field-lbl">Description</label>
                      <textarea class="fld-textarea" rows="3" placeholder="Describe…"
                        :value="item.description" @input="setRoomExtraField(room.id,item._eid,'description',$event.target.value)"></textarea>
                    </div>
                    <div class="room-field-cond">
                      <label class="field-lbl">Condition</label>
                      <textarea class="fld-textarea" rows="3" placeholder="Condition…"
                        :value="item.condition" @input="setRoomExtraField(room.id,item._eid,'condition',$event.target.value)"></textarea>
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
  </div>
</template>

<style scoped>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
.shell{display:flex;flex-direction:column;height:100vh;overflow:hidden;background:#f1f3f7;font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
.loading-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:16px;background:#f1f3f7;color:#64748b;font-size:14px}
.ring{width:34px;height:34px;border:3px solid #e2e8f0;border-top-color:#6366f1;border-radius:50%;animation:spin 0.7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* Topbar */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:52px;background:#1e293b;border-bottom:1px solid #0f172a;flex-shrink:0;gap:16px;z-index:10}
.topbar-l{display:flex;align-items:center;gap:16px;min-width:0}
.topbar-r{display:flex;align-items:center;gap:12px;flex-shrink:0}
.back-btn{display:flex;align-items:center;gap:5px;padding:5px 12px;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.1);border-radius:5px;color:#94a3b8;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.15s}
.back-btn:hover{background:rgba(255,255,255,0.13);color:#e2e8f0}
.crumbs{display:flex;align-items:center;gap:8px;min-width:0;overflow:hidden}
.crumb-addr{font-size:13px;font-weight:600;color:#f1f5f9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.crumb-dot{color:#334155}.crumb-type{font-size:12px;font-weight:700;color:#818cf8;white-space:nowrap}.crumb-who{font-size:12px;color:#475569;white-space:nowrap}
.prog{display:flex;align-items:center;gap:8px}.prog-track{width:72px;height:3px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden}.prog-fill{height:100%;background:#6366f1;border-radius:2px;transition:width 0.5s}.prog-lbl{font-size:11px;font-weight:700;color:#475569}
.chip{display:flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600}.chip-saving{color:#64748b}.chip-saved{color:#4ade80}.chip-unsaved{color:#fb923c}.spin-icon{animation:spin 0.75s linear infinite}
.photo-btn{display:flex;align-items:center;gap:6px;padding:5px 12px;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.15);border-radius:5px;color:#94a3b8;font-size:12px;font-weight:600;cursor:pointer;transition:all 0.15s;white-space:nowrap}
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
.main{overflow-y:auto;padding:28px 40px 60px;display:flex;flex-direction:column;gap:24px}
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
.extra-row td{background:white}  /* NO extra highlight — same as regular rows */

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
.qa-row-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.qa-extra-header{display:flex;align-items:center;gap:8px}
.qa-location-badge{display:inline-block;padding:2px 8px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:4px;font-size:11px;font-weight:700;color:#0369a1;text-transform:uppercase;letter-spacing:0.4px;width:fit-content}
.qa-question{font-size:13px;font-weight:600;color:#1e293b;line-height:1.4;flex:1}
.qa-guidance{font-size:12px;color:#64748b;line-height:1.5;background:#fffbeb;border-left:3px solid #fbbf24;padding:8px 12px;border-radius:0 4px 4px 0}
.qa-controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap}

/* Room rows */
.room-row{display:grid;grid-template-columns:180px 1fr;border-bottom:1px solid #f1f5f9}
.room-row:last-child{border-bottom:none}
.room-row-label{display:flex;align-items:flex-start;padding:14px 12px;font-size:13px;font-weight:700;color:#374151;border-right:1px solid #f1f5f9;background:#fafbfd;line-height:1.3;gap:6px}
.label-input{font-weight:700;font-size:13px}
.room-row-right{display:flex;flex-direction:column}
.room-row-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px 16px;align-items:start}
.room-field-desc{grid-column:1}.room-field-cond{grid-column:2}.room-field-notes{grid-column:1/-1}
.field-lbl{display:block;margin-bottom:4px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8}

/* Item action bar */
.item-action-bar{display:flex;align-items:center;gap:12px;padding:6px 16px 10px;border-top:1px solid #f8fafc}
.del-item-btn{background:none;border:none;color:#ef4444;font-size:12px;font-weight:600;cursor:pointer;padding:2px 0;margin-left:auto}
.del-item-btn:hover{text-decoration:underline}

/* Sub-items */
.sub-items{display:flex;flex-direction:column;border-top:1px dashed #e5e7eb}
.sub-item{display:flex;align-items:flex-start;gap:8px;padding:10px 16px;background:#f9f8ff;border-bottom:1px dashed #ede9fe}
.sub-item:last-child{border-bottom:none}
.sub-item-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px;flex:1}

/* Sub add bar */
.add-sub-btn{padding:4px 10px;background:none;border:1px dashed #a78bfa;border-radius:5px;font-size:11.5px;font-weight:600;color:#7c3aed;cursor:pointer;transition:all 0.12s}
.add-sub-btn:hover{background:#f5f3ff}

/* Fields */
.fld-input{width:100%;padding:7px 10px;border:1px solid #e5e7eb;border-radius:6px;font-size:13px;color:#1e293b;font-family:inherit;background:white;transition:border-color 0.12s,box-shadow 0.12s}
.fld-input:focus{outline:none;border-color:#6366f1;box-shadow:0 0 0 2.5px rgba(99,102,241,0.14)}
.fld-textarea{width:100%;padding:8px 10px;border:1px solid #e5e7eb;border-radius:6px;font-size:13px;color:#1e293b;font-family:inherit;resize:vertical;min-height:72px;line-height:1.55}
.fld-textarea:focus{outline:none;border-color:#6366f1;box-shadow:0 0 0 2.5px rgba(99,102,241,0.14)}
.fld-select{width:100%;padding:7px 10px;border:1px solid #e5e7eb;border-radius:6px;font-size:13px;color:#1e293b;font-family:inherit;background:white;cursor:pointer}
.fld-select:focus{outline:none;border-color:#6366f1}
.fld-grow{flex:1;min-width:200px}.fld-mono{font-family:'Courier New',monospace;font-weight:700;letter-spacing:1px}

/* Y/N chips */
.yn-group{display:flex;gap:6px;flex-shrink:0}
.yn-chip{padding:6px 13px;border:1.5px solid #e5e7eb;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;user-select:none;color:#94a3b8;background:white;transition:all 0.1s}
.yn-chip:hover{border-color:#cbd5e1;color:#475569}
.yn-yes{background:#f0fdf4!important;border-color:#16a34a!important;color:#166534!important}
.yn-no{background:#fef2f2!important;border-color:#dc2626!important;color:#991b1b!important}
.yn-na{background:#f1f5f9!important;border-color:#94a3b8!important;color:#475569!important}

/* Bottom */
.foot{display:flex;justify-content:space-between;align-items:center;padding:8px 0 0}
.btn-ghost{padding:9px 18px;background:white;border:1px solid #e2e8f0;border-radius:7px;font-size:13px;font-weight:600;color:#475569;cursor:pointer;transition:all 0.15s;font-family:inherit}
.btn-ghost:hover{background:#f8fafc}
.btn-save-lg{padding:10px 28px;background:#6366f1;color:white;border:none;border-radius:7px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;transition:background 0.15s}
.btn-save-lg:hover:not(:disabled){background:#4f46e5}.btn-save-lg:disabled{background:#94a3b8;cursor:not-allowed}

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
</style>
