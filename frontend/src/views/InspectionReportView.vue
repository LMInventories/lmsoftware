<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../services/api'

const route  = useRoute()
const router = useRouter()

// ── Core state ────────────────────────────────────────────────────────────────
const inspection     = ref(null)
const template       = ref(null)     // from GET /api/templates/:id  → .sections[].items[]
const fixedSections  = ref([])       // from GET /api/fixed-sections → columns + items
const loading        = ref(true)
const saving         = ref(false)
const unsaved        = ref(false)
const savedTime      = ref(null)
const activeId       = ref(null)
const reportData     = ref({})       // clerk-entered values, persisted as JSON

// Column type definitions — same 9 types as FixedSectionsSettings
const COL = {
  name:             { label: 'Name',                  dropdown: false },
  question:         { label: 'Question',              dropdown: false },
  answer:           { label: 'Answer',                dropdown: true,
                      options: ['Yes', 'No', 'N/A'] },
  cleanliness:      { label: 'Cleanliness',           dropdown: true,
                      options: ['Professionally Cleaned',
                                'Professionally Cleaned - Receipt Seen',
                                'Professionally Cleaned with Omissions',
                                'Domestically Cleaned',
                                'Domestically Cleaned with Omissions',
                                'Not Clean'] },
  description:      { label: 'Description',           dropdown: false },
  condition:        { label: 'Condition',              dropdown: false },
  additional_notes: { label: 'Additional Notes',      dropdown: false },
  location_serial:  { label: 'Location & Serial No.', dropdown: false },
  reading:          { label: 'Reading',               dropdown: false },
}

// ── Derived lists ─────────────────────────────────────────────────────────────
const enabledFixed = computed(() =>
  fixedSections.value.filter(s => s.enabled !== false)
)

const roomSections = computed(() =>
  (template.value?.sections || [])
    .filter(s => s.section_type === 'room')
    .sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0))
)

// Stable slug for fixed section keys (no spaces/special chars in reportData keys)
function fsKey(name) {
  return 'fs__' + name.replace(/[^a-zA-Z0-9]/g, '_')
}

// Combined nav list
const allSections = computed(() => [
  ...enabledFixed.value.map(s  => ({ navId: fsKey(s.name),  name: s.name,  _type: 'fixed' })),
  ...roomSections.value.map(r  => ({ navId: String(r.id),   name: r.name,  _type: 'room'  })),
])

// ── Load ──────────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const [iRes, fsRes] = await Promise.all([
      api.getInspection(route.params.id),
      api.getFixedSections(),
    ])
    inspection.value    = iRes.data
    fixedSections.value = fsRes.data || []

    if (inspection.value.template_id) {
      const tRes = await api.getTemplate(inspection.value.template_id)
      template.value = tRes.data
    }

    if (inspection.value.report_data) {
      try { reportData.value = JSON.parse(inspection.value.report_data) }
      catch { reportData.value = {} }
    }
  } catch (e) {
    console.error('Load failed', e)
    alert('Failed to load report')
    router.push('/inspections')
  } finally {
    loading.value = false
    await nextTick()
    if (allSections.value[0]) activeId.value = allSections.value[0].navId
  }
}

// ── Save ──────────────────────────────────────────────────────────────────────
async function save() {
  if (saving.value) return
  saving.value = true
  try {
    await api.saveInspectionReport(inspection.value.id, {
      report_data: JSON.stringify(reportData.value)
    })
    unsaved.value   = false
    savedTime.value = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    console.error('Save failed', e)
    alert('Failed to save — please try again')
  } finally {
    saving.value = false
  }
}

// Auto-save on tab close / navigation
onBeforeUnmount(() => { if (unsaved.value) save() })

// ── Fixed-section data helpers ────────────────────────────────────────────────
// Template rows: stored at reportData[key][rowIdx][colKey]
function getFsVal(sectionName, rowIdx, colKey) {
  return reportData.value[fsKey(sectionName)]?.[String(rowIdx)]?.[colKey] ?? ''
}
function setFsVal(sectionName, rowIdx, colKey, value) {
  const k = fsKey(sectionName)
  if (!reportData.value[k]) reportData.value[k] = {}
  if (!reportData.value[k][String(rowIdx)]) reportData.value[k][String(rowIdx)] = {}
  reportData.value[k][String(rowIdx)][colKey] = value
  unsaved.value = true
}

// Clerk-added extra rows per fixed section
function getFsExtra(sectionName) {
  return reportData.value[fsKey(sectionName)]?._extra ?? []
}
function addFsRow(section) {
  const k = fsKey(section.name)
  if (!reportData.value[k]) reportData.value[k] = {}
  if (!reportData.value[k]._extra) reportData.value[k]._extra = []
  const blank = { _eid: `ex_${Date.now()}` }
  section.columns.forEach(c => { blank[c] = '' })
  reportData.value[k]._extra.push(blank)
  unsaved.value = true
}
function setFsExtraVal(sectionName, eid, colKey, value) {
  const row = reportData.value[fsKey(sectionName)]?._extra?.find(r => r._eid === eid)
  if (row) { row[colKey] = value; unsaved.value = true }
}
function removeFsRow(sectionName, eid) {
  const k = fsKey(sectionName)
  if (!reportData.value[k]?._extra) return
  reportData.value[k]._extra = reportData.value[k]._extra.filter(r => r._eid !== eid)
  unsaved.value = true
}

// ── Room data helpers ─────────────────────────────────────────────────────────
function getRoomVal(roomId, itemId, field) {
  return reportData.value[String(roomId)]?.[String(itemId)]?.[field] ?? ''
}
function setRoomVal(roomId, itemId, field, value) {
  const r = String(roomId), i = String(itemId)
  if (!reportData.value[r]) reportData.value[r] = {}
  if (!reportData.value[r][i]) reportData.value[r][i] = {}
  reportData.value[r][i][field] = value
  unsaved.value = true
}

// Clerk-added extra items in a room
function getRoomExtra(roomId) {
  return reportData.value[String(roomId)]?._extra ?? []
}
function addRoomItem(roomId) {
  const r = String(roomId)
  if (!reportData.value[r]) reportData.value[r] = {}
  if (!reportData.value[r]._extra) reportData.value[r]._extra = []
  reportData.value[r]._extra.push({ _eid: `rex_${Date.now()}`, label: '', condition: '', description: '' })
  unsaved.value = true
}
function setRoomExtraVal(roomId, eid, field, value) {
  const row = reportData.value[String(roomId)]?._extra?.find(r => r._eid === eid)
  if (row) { row[field] = value; unsaved.value = true }
}
function removeRoomItem(roomId, eid) {
  const r = String(roomId)
  if (!reportData.value[r]?._extra) return
  reportData.value[r]._extra = reportData.value[r]._extra.filter(x => x._eid !== eid)
  unsaved.value = true
}

// ── Sidebar / scroll ──────────────────────────────────────────────────────────
function scrollTo(navId) {
  activeId.value = navId
  document.getElementById(`sec-${navId}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function onScroll(e) {
  const top = e.target.scrollTop
  for (let i = allSections.value.length - 1; i >= 0; i--) {
    const el = document.getElementById(`sec-${allSections.value[i].navId}`)
    if (el && el.offsetTop - top <= 160) { activeId.value = allSections.value[i].navId; break }
  }
}

function sectionDone(navId) {
  return Object.keys(reportData.value[navId] || {}).filter(k => !k.startsWith('_')).length > 0
}

onMounted(load)
</script>

<template>
  <div class="rp">

    <!-- ── Header ─────────────────────────────────────────────────────────── -->
    <header class="rp-header">
      <div class="rp-header-left">
        <button class="btn-back" @click="router.push(`/inspections/${route.params.id}`)">← Back</button>
        <div v-if="inspection" class="rp-title-block">
          <span class="rp-type">{{ (inspection.inspection_type || '').replace(/_/g,' ').toUpperCase() }}</span>
          <span class="rp-addr">{{ inspection.property_address || '' }}</span>
        </div>
      </div>
      <div class="rp-header-right">
        <span v-if="saving"        class="chip chip-saving">Saving…</span>
        <span v-else-if="unsaved"  class="chip chip-unsaved">● Unsaved</span>
        <span v-else-if="savedTime" class="chip chip-saved">✓ {{ savedTime }}</span>
        <button class="btn-save" :disabled="saving || !unsaved" @click="save">Save</button>
      </div>
    </header>

    <!-- ── Loading ────────────────────────────────────────────────────────── -->
    <div v-if="loading" class="rp-loading">Loading report…</div>

    <div v-else class="rp-body">

      <!-- ── Sidebar ──────────────────────────────────────────────────────── -->
      <nav class="rp-nav">
        <div v-if="enabledFixed.length" class="nav-group">
          <p class="nav-label">Fixed Sections</p>
          <button
            v-for="s in enabledFixed" :key="fsKey(s.name)"
            class="nav-btn" :class="{ active: activeId === fsKey(s.name) }"
            @click="scrollTo(fsKey(s.name))"
          >
            <span class="dot" :class="{ done: sectionDone(fsKey(s.name)) }"></span>
            {{ s.name }}
          </button>
        </div>

        <div v-if="roomSections.length" class="nav-group">
          <p class="nav-label">Rooms</p>
          <button
            v-for="r in roomSections" :key="r.id"
            class="nav-btn" :class="{ active: activeId === String(r.id) }"
            @click="scrollTo(String(r.id))"
          >
            <span class="dot" :class="{ done: sectionDone(String(r.id)) }"></span>
            {{ r.name }}
          </button>
        </div>

        <div v-if="!template && !loading" class="nav-warn">
          ⚠️ No template assigned — go back to the inspection overview and assign one first.
        </div>
      </nav>

      <!-- ── Main scroll area ──────────────────────────────────────────────── -->
      <main class="rp-main" @scroll="onScroll">

        <!-- No template state -->
        <div v-if="!template" class="empty-state">
          <div class="empty-icon">📋</div>
          <h3>No template assigned</h3>
          <p>Assign a template from the inspection overview first.</p>
          <button class="btn-ghost" @click="router.push(`/inspections/${route.params.id}`)">← Back to Overview</button>
        </div>

        <template v-else>

          <!-- ══ FIXED SECTIONS ════════════════════════════════════════════ -->
          <section
            v-for="fs in enabledFixed"
            :key="fsKey(fs.name)"
            :id="`sec-${fsKey(fs.name)}`"
            class="card"
          >
            <div class="card-head">
              <h2>{{ fs.name }}</h2>
            </div>

            <div class="card-body">
              <div class="fs-table-wrap">
                <table class="fs-table">
                  <thead>
                    <tr>
                      <th v-for="col in fs.columns" :key="col">{{ COL[col]?.label || col }}</th>
                      <th class="th-del"></th>
                    </tr>
                  </thead>
                  <tbody>
                    <!-- Template-seeded rows (pre-filled name/values from settings) -->
                    <tr v-for="(item, idx) in (fs.items || [])" :key="idx">
                      <td v-for="col in fs.columns" :key="col">
                        <select
                          v-if="COL[col]?.dropdown"
                          :value="getFsVal(fs.name, idx, col) || item[col] || ''"
                          @change="setFsVal(fs.name, idx, col, $event.target.value)"
                          class="cell-sel"
                        >
                          <option value="">— select —</option>
                          <option v-for="opt in COL[col].options" :key="opt" :value="opt">{{ opt }}</option>
                        </select>
                        <input
                          v-else
                          :value="getFsVal(fs.name, idx, col) !== '' ? getFsVal(fs.name, idx, col) : (item[col] || '')"
                          @input="setFsVal(fs.name, idx, col, $event.target.value)"
                          class="cell-inp"
                          :placeholder="COL[col]?.label"
                        />
                      </td>
                      <td class="th-del"><!-- template rows locked --></td>
                    </tr>

                    <!-- Clerk-added extra rows -->
                    <tr
                      v-for="extra in getFsExtra(fs.name)"
                      :key="extra._eid"
                      class="tr-extra"
                    >
                      <td v-for="col in fs.columns" :key="col">
                        <select
                          v-if="COL[col]?.dropdown"
                          :value="extra[col] || ''"
                          @change="setFsExtraVal(fs.name, extra._eid, col, $event.target.value)"
                          class="cell-sel"
                        >
                          <option value="">— select —</option>
                          <option v-for="opt in COL[col].options" :key="opt" :value="opt">{{ opt }}</option>
                        </select>
                        <input
                          v-else
                          :value="extra[col] || ''"
                          @input="setFsExtraVal(fs.name, extra._eid, col, $event.target.value)"
                          class="cell-inp"
                          :placeholder="COL[col]?.label"
                        />
                      </td>
                      <td class="th-del">
                        <button @click="removeFsRow(fs.name, extra._eid)" class="btn-del">✕</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <button @click="addFsRow(fs)" class="btn-add-row">＋ Add Row</button>
            </div>
          </section>

          <!-- ══ ROOM SECTIONS ════════════════════════════════════════════ -->
          <section
            v-for="room in roomSections"
            :key="room.id"
            :id="`sec-${room.id}`"
            class="card"
          >
            <div class="card-head">
              <h2>{{ room.name }}</h2>
            </div>

            <div class="card-body">

              <!-- Template items -->
              <div
                v-for="item in (room.items || [])"
                :key="item.id"
                class="room-item"
              >
                <div class="room-item-name">{{ item.name }}</div>
                <div class="room-fields">
                  <div class="field" v-if="item.requires_condition !== false">
                    <label>Condition</label>
                    <input
                      :value="getRoomVal(room.id, item.id, 'condition')"
                      @input="setRoomVal(room.id, item.id, 'condition', $event.target.value)"
                      class="field-inp"
                      placeholder="e.g. Good, Fair, Poor…"
                    />
                  </div>
                  <div class="field">
                    <label>Description / Notes</label>
                    <textarea
                      :value="getRoomVal(room.id, item.id, 'description')"
                      @input="setRoomVal(room.id, item.id, 'description', $event.target.value)"
                      class="field-ta"
                      placeholder="Additional notes…"
                      rows="2"
                    ></textarea>
                  </div>
                </div>
              </div>

              <!-- Clerk-added extra items -->
              <div
                v-for="extra in getRoomExtra(room.id)"
                :key="extra._eid"
                class="room-item room-item-extra"
              >
                <div class="room-item-name-row">
                  <input
                    :value="extra.label"
                    @input="setRoomExtraVal(room.id, extra._eid, 'label', $event.target.value)"
                    class="extra-name-inp"
                    placeholder="Item name…"
                  />
                  <button @click="removeRoomItem(room.id, extra._eid)" class="btn-del">✕</button>
                </div>
                <div class="room-fields">
                  <div class="field">
                    <label>Condition</label>
                    <input
                      :value="extra.condition"
                      @input="setRoomExtraVal(room.id, extra._eid, 'condition', $event.target.value)"
                      class="field-inp"
                      placeholder="e.g. Good, Fair, Poor…"
                    />
                  </div>
                  <div class="field">
                    <label>Description / Notes</label>
                    <textarea
                      :value="extra.description"
                      @input="setRoomExtraVal(room.id, extra._eid, 'description', $event.target.value)"
                      class="field-ta"
                      rows="2"
                    ></textarea>
                  </div>
                </div>
              </div>

              <button @click="addRoomItem(room.id)" class="btn-add-row">＋ Add Item</button>
            </div>
          </section>

        </template>
      </main>
    </div>
  </div>
</template>

<style scoped>
/* ── Shell ───────────────────────────────────────────────────────────────── */
.rp { display: flex; flex-direction: column; height: 100vh; overflow: hidden; background: #f8fafc; }

/* ── Header ──────────────────────────────────────────────────────────────── */
.rp-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 20px; background: white; border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0; gap: 12px;
}
.rp-header-left  { display: flex; align-items: center; gap: 14px; }
.rp-header-right { display: flex; align-items: center; gap: 10px; }

.btn-back {
  padding: 6px 12px; background: white; border: 1px solid #e5e7eb;
  border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer;
  color: #374151; white-space: nowrap;
}
.btn-back:hover { background: #f1f5f9; }

.rp-title-block { display: flex; flex-direction: column; gap: 1px; }
.rp-type { font-size: 12px; font-weight: 700; color: #6366f1; }
.rp-addr { font-size: 13px; color: #64748b; }

.chip { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
.chip-saving  { background: #fef3c7; color: #92400e; }
.chip-unsaved { background: #fee2e2; color: #dc2626; }
.chip-saved   { background: #dcfce7; color: #166534; }

.btn-save {
  padding: 7px 18px; background: #6366f1; color: white; border: none;
  border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer;
  transition: background 0.15s;
}
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { opacity: 0.45; cursor: default; }

.rp-loading {
  flex: 1; display: flex; align-items: center; justify-content: center;
  color: #94a3b8; font-size: 15px;
}

/* ── Body ────────────────────────────────────────────────────────────────── */
.rp-body { display: flex; flex: 1; overflow: hidden; }

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
.rp-nav {
  width: 210px; flex-shrink: 0;
  background: white; border-right: 1px solid #e5e7eb;
  overflow-y: auto; padding: 14px 8px;
}
.nav-group   { margin-bottom: 18px; }
.nav-label   { font-size: 10px; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.6px; color: #94a3b8; padding: 0 8px; margin-bottom: 4px; }
.nav-btn     { display: flex; align-items: center; gap: 8px; width: 100%;
                padding: 7px 10px; background: transparent; border: none;
                border-radius: 7px; font-size: 12px; font-weight: 500; color: #475569;
                cursor: pointer; text-align: left; transition: all 0.15s; }
.nav-btn:hover  { background: #f1f5f9; color: #1e293b; }
.nav-btn.active { background: #e0e7ff; color: #4338ca; font-weight: 700; }

.dot { width: 8px; height: 8px; border-radius: 50%; background: #e2e8f0; flex-shrink: 0; }
.dot.done { background: #6366f1; }

.nav-warn { padding: 12px 8px; font-size: 12px; color: #f59e0b; line-height: 1.5; }

/* ── Main scroll ─────────────────────────────────────────────────────────── */
.rp-main {
  flex: 1; overflow-y: auto; padding: 20px 24px;
  display: flex; flex-direction: column; gap: 18px;
}

/* ── Empty state ─────────────────────────────────────────────────────────── */
.empty-state { text-align: center; padding: 80px 20px; color: #64748b; }
.empty-icon  { font-size: 52px; margin-bottom: 12px; }
.empty-state h3 { font-size: 18px; font-weight: 600; color: #1e293b; margin-bottom: 8px; }
.btn-ghost {
  margin-top: 16px; padding: 8px 18px; background: white;
  border: 1px solid #e5e7eb; border-radius: 8px; font-size: 13px;
  font-weight: 600; color: #374151; cursor: pointer;
}

/* ── Cards ───────────────────────────────────────────────────────────────── */
.card { background: white; border-radius: 10px; border: 1px solid #e5e7eb; overflow: hidden; }

.card-head {
  padding: 12px 18px; background: #6366f1;
}
.card-head h2 {
  font-size: 13px; font-weight: 700; color: white;
  text-transform: uppercase; letter-spacing: 0.6px; margin: 0;
}

.card-body { padding: 14px 18px; }

/* ── Fixed section table ─────────────────────────────────────────────────── */
.fs-table-wrap { overflow-x: auto; margin-bottom: 10px; }

.fs-table { width: 100%; border-collapse: collapse; font-size: 13px; }

.fs-table th {
  padding: 7px 10px; background: #f8fafc; border-bottom: 2px solid #e5e7eb;
  text-align: left; font-size: 10px; font-weight: 700;
  color: #64748b; text-transform: uppercase; letter-spacing: 0.4px; white-space: nowrap;
}
.fs-table td {
  padding: 5px 5px; border-bottom: 1px solid #f1f5f9; vertical-align: middle;
}
.fs-table tr:last-child td { border-bottom: none; }
.fs-table tr.tr-extra td   { background: #fafbff; }

.th-del { width: 28px; text-align: center; }

.cell-inp {
  width: 100%; padding: 5px 7px; border: 1px solid transparent;
  border-radius: 5px; font-size: 13px; font-family: inherit;
  background: transparent; box-sizing: border-box; transition: all 0.12s;
}
.cell-inp:hover  { border-color: #e2e8f0; }
.cell-inp:focus  { outline: none; border-color: #6366f1; background: white; }

.cell-sel {
  width: 100%; padding: 5px 7px; border: 1px solid #e2e8f0;
  border-radius: 5px; font-size: 13px; font-family: inherit;
  background: white; cursor: pointer; box-sizing: border-box;
}
.cell-sel:focus { outline: none; border-color: #6366f1; }

.btn-del {
  width: 22px; height: 22px; background: none; border: none;
  font-size: 11px; color: #94a3b8; cursor: pointer; border-radius: 3px;
  display: inline-flex; align-items: center; justify-content: center;
}
.btn-del:hover { background: #fee2e2; color: #dc2626; }

.btn-add-row {
  padding: 7px 14px; background: white; border: 1.5px dashed #cbd5e1;
  border-radius: 7px; font-size: 13px; font-weight: 600; color: #64748b;
  cursor: pointer; transition: all 0.15s; margin-top: 2px;
}
.btn-add-row:hover { border-color: #6366f1; color: #6366f1; background: #f5f3ff; }

/* ── Room items ──────────────────────────────────────────────────────────── */
.room-item {
  border: 1px solid #f1f5f9; border-radius: 8px;
  margin-bottom: 8px; overflow: hidden;
}
.room-item:hover { border-color: #e0e7ff; }
.room-item.room-item-extra { border-color: #e0e7ff; }

.room-item-name {
  padding: 8px 13px; background: #f8fafc; border-bottom: 1px solid #f1f5f9;
  font-size: 13px; font-weight: 600; color: #1e293b;
}

.room-item-name-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 10px 6px 13px; background: #f0f4ff; border-bottom: 1px solid #e0e7ff;
}
.extra-name-inp {
  flex: 1; border: none; background: transparent; font-size: 13px;
  font-weight: 600; color: #1e293b; font-family: inherit; padding: 2px 4px; border-radius: 3px;
}
.extra-name-inp:focus { outline: none; background: white; }

.room-fields {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 10px 13px;
}
@media (max-width: 640px) { .room-fields { grid-template-columns: 1fr; } }

.field label {
  display: block; font-size: 10px; font-weight: 700; color: #94a3b8;
  text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 4px;
}
.field-inp {
  width: 100%; padding: 6px 9px; border: 1px solid #e5e7eb;
  border-radius: 6px; font-size: 13px; font-family: inherit;
  box-sizing: border-box; transition: border-color 0.12s;
}
.field-inp:focus { outline: none; border-color: #6366f1; }

.field-ta {
  width: 100%; padding: 6px 9px; border: 1px solid #e5e7eb;
  border-radius: 6px; font-size: 13px; font-family: inherit;
  box-sizing: border-box; resize: vertical; transition: border-color 0.12s;
}
.field-ta:focus { outline: none; border-color: #6366f1; }
</style>
