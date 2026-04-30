
.form-textarea { min-height: 80px; resize: vertical; font-family: inherit; }
<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

// ── Column definitions (all 9 available types) ────────────────────────────────
const COLUMN_TYPES = [
  { key: 'name',              label: 'Name',                    type: 'text' },
  { key: 'question',          label: 'Question',                type: 'text' },
  { key: 'answer',            label: 'Answer',                  type: 'dropdown',
    options: ['Yes', 'No', 'N/A'] },
  { key: 'cleanliness',       label: 'Cleanliness',             type: 'dropdown',
    options: [
      'Professionally Cleaned',
      'Professionally Cleaned - Receipt Seen',
      'Professionally Cleaned with Omissions',
      'Domestically Cleaned',
      'Domestically Cleaned with Omissions',
      'Not Clean',
    ]},
  { key: 'description',       label: 'Description',             type: 'text' },
  { key: 'condition',         label: 'Condition',               type: 'text' },
  { key: 'additional_notes',  label: 'Additional Notes',        type: 'text' },
  { key: 'location_serial',   label: 'Location & Serial No.',   type: 'text' },
  { key: 'reading',           label: 'Reading',                 type: 'text' },
]

// ── State ─────────────────────────────────────────────────────────────────────
const sections  = ref([])
const loading   = ref(true)
const saving    = ref(false)
const expanded  = ref({})
const dirty     = ref(false)

const newSectionName = ref('')

// Item modal: null | { sectionIndex, itemIndex|null, form: { col_key: value } }
const itemModal = ref(null)

// Column picker: null | sectionIndex
const colPicker = ref(null)

// ── Helpers ───────────────────────────────────────────────────────────────────
function colDef(key) {
  return COLUMN_TYPES.find(c => c.key === key)
}

function emptyItemForm(columns) {
  const form = {}
  columns.forEach(k => { form[k] = '' })
  return form
}

function itemDisplayValue(item, colKey) {
  return item[colKey] ?? '—'
}

function markDirty() { dirty.value = true }

// ── Load / Save ───────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const res = await api.getMidtermSections()
    sections.value = (res.data || []).map(normalise)
    if (sections.value.length > 0) expanded.value[0] = true
  } catch (e) {
    console.error(e); alert('Failed to load midterm sections')
  } finally {
    loading.value = false
  }
}

function normalise(s) {
  return {
    name:    s.name    || '',
    enabled: s.enabled !== false,
    columns: Array.isArray(s.columns) ? s.columns : ['name'],
    items:   Array.isArray(s.items)   ? s.items   : [],
  }
}

async function save() {
  saving.value = true
  try {
    const res = await api.updateMidtermSections(sections.value)
    sections.value = (res.data || []).map(normalise)
    dirty.value = false
  } catch (e) {
    console.error(e); alert('Failed to save')
  } finally {
    saving.value = false
  }
}

// ── Section management ────────────────────────────────────────────────────────
function toggleExpanded(i) {
  expanded.value[i] = !expanded.value[i]
}

function addSection() {
  const name = newSectionName.value.trim()
  if (!name) return
  sections.value.push({ name, enabled: true, columns: ['name'], items: [] })
  expanded.value[sections.value.length - 1] = true
  newSectionName.value = ''
  markDirty()
}

function removeSection(i) {
  if (!confirm(`Remove "${sections.value[i].name}"?`)) return
  sections.value.splice(i, 1)
  const next = {}
  Object.keys(expanded.value).forEach(k => {
    const ki = parseInt(k)
    if (ki < i) next[ki] = expanded.value[k]
    else if (ki > i) next[ki - 1] = expanded.value[k]
  })
  expanded.value = next
  markDirty()
}

function moveSectionUp(i) {
  if (i === 0) return
  ;[sections.value[i - 1], sections.value[i]] = [sections.value[i], sections.value[i - 1]]
  ;[expanded.value[i - 1], expanded.value[i]] = [expanded.value[i], expanded.value[i - 1]]
  markDirty()
}

function moveSectionDown(i) {
  if (i === sections.value.length - 1) return
  ;[sections.value[i], sections.value[i + 1]] = [sections.value[i + 1], sections.value[i]]
  ;[expanded.value[i], expanded.value[i + 1]] = [expanded.value[i + 1], expanded.value[i]]
  markDirty()
}

// ── Column picker ─────────────────────────────────────────────────────────────
function openColPicker(sectionIndex) {
  colPicker.value = sectionIndex
}

function closeColPicker() {
  colPicker.value = null
}

function toggleColumn(sectionIndex, colKey) {
  const cols = sections.value[sectionIndex].columns
  const idx  = cols.indexOf(colKey)
  if (idx === -1) {
    const order = COLUMN_TYPES.map(c => c.key)
    const newCols = [...cols, colKey].sort((a, b) => order.indexOf(a) - order.indexOf(b))
    sections.value[sectionIndex].columns = newCols
  } else {
    if (cols.length === 1) return
    cols.splice(idx, 1)
    sections.value[sectionIndex].items.forEach(item => { delete item[colKey] })
  }
  markDirty()
}

function moveColLeft(sectionIndex, colKey) {
  const cols = sections.value[sectionIndex].columns
  const idx  = cols.indexOf(colKey)
  if (idx <= 0) return
  ;[cols[idx - 1], cols[idx]] = [cols[idx], cols[idx - 1]]
  markDirty()
}

function moveColRight(sectionIndex, colKey) {
  const cols = sections.value[sectionIndex].columns
  const idx  = cols.indexOf(colKey)
  if (idx === -1 || idx === cols.length - 1) return
  ;[cols[idx], cols[idx + 1]] = [cols[idx + 1], cols[idx]]
  markDirty()
}

// ── Item management ───────────────────────────────────────────────────────────
function openAddItem(sectionIndex) {
  itemModal.value = {
    sectionIndex,
    itemIndex: null,
    form: emptyItemForm(sections.value[sectionIndex].columns),
  }
}

function openEditItem(sectionIndex, itemIndex) {
  const item = sections.value[sectionIndex].items[itemIndex]
  const cols = sections.value[sectionIndex].columns
  const form = emptyItemForm(cols)
  cols.forEach(k => { form[k] = item[k] ?? '' })
  itemModal.value = { sectionIndex, itemIndex, form }
}

function closeItemModal() { itemModal.value = null }

function saveItem() {
  const { sectionIndex, itemIndex, form } = itemModal.value
  const firstCol = sections.value[sectionIndex].columns[0]
  if (!form[firstCol]?.trim()) { alert(`${colDef(firstCol).label} is required`); return }
  const cleaned = {}
  sections.value[sectionIndex].columns.forEach(k => { cleaned[k] = form[k] ?? '' })
  if (itemIndex === null) {
    sections.value[sectionIndex].items.push(cleaned)
  } else {
    sections.value[sectionIndex].items[itemIndex] = cleaned
  }
  markDirty()
  closeItemModal()
}

function deleteItem(si, ii) {
  const col = sections.value[si].columns[0]
  const val = sections.value[si].items[ii][col] || 'this item'
  if (!confirm(`Delete "${val}"?`)) return
  sections.value[si].items.splice(ii, 1)
  markDirty()
}

function moveItemUp(si, ii) {
  if (ii === 0) return
  const items = sections.value[si].items
  ;[items[ii - 1], items[ii]] = [items[ii], items[ii - 1]]
  markDirty()
}

function moveItemDown(si, ii) {
  const items = sections.value[si].items
  if (ii === items.length - 1) return
  ;[items[ii], items[ii + 1]] = [items[ii + 1], items[ii]]
  markDirty()
}

onMounted(load)
</script>

<template>
  <div class="fs-wrap">

    <!-- ── Header ─────────────────────────────────────────────────────────── -->
    <div class="fs-header">
      <div>
        <h2 class="fs-title">Midterm Sections</h2>
        <p class="fs-subtitle">
          These sections appear on <strong>Midterm Inspection</strong> reports only.
          Configure columns per section, then add rows (items) for each.
        </p>
      </div>
      <button @click="save" :disabled="saving || !dirty" class="btn-save">
        {{ saving ? 'Saving…' : dirty ? 'Save Changes' : 'Saved ✓' }}
      </button>
    </div>

    <div v-if="loading" class="fs-loading">Loading…</div>

    <div v-else>
      <!-- ── Accordion ───────────────────────────────────────────────────── -->
      <div class="accordion">
        <div
          v-for="(section, sIdx) in sections"
          :key="sIdx"
          class="accordion-item"
          :class="{ 'is-expanded': expanded[sIdx], 'is-disabled': !section.enabled }"
        >
          <!-- Section header -->
          <div class="acc-header" @click="toggleExpanded(sIdx)">
            <span class="chevron">{{ expanded[sIdx] ? '▾' : '▸' }}</span>

            <label class="toggle" @click.stop title="Enable / disable">
              <input type="checkbox" v-model="section.enabled" @change="markDirty" />
              <span class="toggle-track"></span>
            </label>

            <input
              v-model="section.name"
              class="sec-name-input"
              :class="{ muted: !section.enabled }"
              placeholder="Section name"
              @click.stop
              @input="markDirty"
            />

            <div class="sec-pills">
              <span
                v-for="colKey in section.columns"
                :key="colKey"
                class="col-pill"
              >{{ colDef(colKey)?.label }}</span>
            </div>

            <span class="row-count">{{ section.items.length }} row{{ section.items.length !== 1 ? 's' : '' }}</span>

            <div class="sec-actions" @click.stop>
              <button @click="moveSectionUp(sIdx)"   :disabled="sIdx === 0"                    class="btn-icon" title="Up">↑</button>
              <button @click="moveSectionDown(sIdx)" :disabled="sIdx === sections.length - 1"  class="btn-icon" title="Down">↓</button>
              <button @click="removeSection(sIdx)"                                              class="btn-icon danger" title="Remove">✕</button>
            </div>
          </div>

          <!-- Section body -->
          <div v-if="expanded[sIdx]" class="acc-body">

            <!-- Column configurator -->
            <div class="col-config-bar">
              <span class="col-config-label">Columns:</span>

              <!-- Active columns -->
              <div class="active-cols">
                <div
                  v-for="(colKey, cIdx) in section.columns"
                  :key="colKey"
                  class="active-col-chip"
                >
                  <button @click="moveColLeft(sIdx, colKey)"  :disabled="cIdx === 0"                         class="chip-arrow">‹</button>
                  <span class="chip-label">{{ colDef(colKey)?.label }}</span>
                  <button @click="moveColRight(sIdx, colKey)" :disabled="cIdx === section.columns.length - 1" class="chip-arrow">›</button>
                  <button
                    @click="toggleColumn(sIdx, colKey)"
                    class="chip-remove"
                    :disabled="section.columns.length === 1"
                    title="Remove column"
                  >✕</button>
                </div>
              </div>

              <!-- Add column button -->
              <div class="col-add-wrap">
                <button @click.stop="openColPicker(sIdx)" class="btn-add-col">＋ Column</button>
                <div v-if="colPicker === sIdx" class="col-picker-dropdown" @click.stop>
                  <div class="col-picker-title">Add column</div>
                  <label
                    v-for="ct in COLUMN_TYPES"
                    :key="ct.key"
                    class="col-picker-row"
                    :class="{ active: section.columns.includes(ct.key) }"
                    @click="toggleColumn(sIdx, ct.key); if(!section.columns.includes(ct.key)) closeColPicker()"
                  >
                    <span class="col-picker-check">{{ section.columns.includes(ct.key) ? '✓' : '' }}</span>
                    {{ ct.label }}
                    <span v-if="ct.type === 'dropdown'" class="col-picker-badge">dropdown</span>
                  </label>
                  <div class="col-picker-close">
                    <button @click="closeColPicker" class="btn-secondary-sm">Done</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- Items table -->
            <div class="items-table-wrap">
              <table v-if="section.items.length > 0" class="items-table">
                <thead>
                  <tr>
                    <th v-for="colKey in section.columns" :key="colKey">
                      {{ colDef(colKey)?.label }}
                    </th>
                    <th class="col-actions">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(item, iIdx) in section.items" :key="iIdx">
                    <td v-for="colKey in section.columns" :key="colKey" class="item-cell">
                      {{ itemDisplayValue(item, colKey) }}
                    </td>
                    <td class="col-actions">
                      <button @click="moveItemUp(sIdx, iIdx)"   :disabled="iIdx === 0"                         class="btn-icon-sm" title="Up">↑</button>
                      <button @click="moveItemDown(sIdx, iIdx)" :disabled="iIdx === section.items.length - 1"  class="btn-icon-sm" title="Down">↓</button>
                      <button @click="openEditItem(sIdx, iIdx)"                                                class="btn-icon-sm edit" title="Edit">✎</button>
                      <button @click="deleteItem(sIdx, iIdx)"                                                  class="btn-icon-sm danger" title="Delete">✕</button>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="items-empty">No rows yet.</div>
            </div>

            <button @click="openAddItem(sIdx)" class="btn-add-item">＋ Add Row</button>
          </div>
        </div>
      </div>

      <!-- Add section -->
      <div class="add-section-row">
        <input
          v-model="newSectionName"
          class="add-section-input"
          placeholder="New section name, e.g. General Condition"
          @keyup.enter="addSection"
        />
        <button @click="addSection" class="btn-add-section">＋ Add Section</button>
      </div>

      <p class="fs-hint">
        Disabled sections are hidden from midterm reports but not deleted. Changes apply system-wide on save.
      </p>
    </div>
  </div>

  <!-- ── Item add / edit modal ─────────────────────────────────────────────── -->
  <Teleport to="body">
    <div v-if="colPicker !== null" class="picker-backdrop" @click="closeColPicker"></div>

    <div v-if="itemModal" class="modal-overlay" @click.self="closeItemModal">
      <div class="modal">
        <div class="modal-header">
          <h2>{{ itemModal.itemIndex === null ? 'Add Row' : 'Edit Row' }}</h2>
          <button @click="closeItemModal" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div
            v-for="colKey in sections[itemModal.sectionIndex].columns"
            :key="colKey"
            class="form-group"
          >
            <label>{{ colDef(colKey)?.label }}<span v-if="colKey === sections[itemModal.sectionIndex].columns[0]"> *</span></label>

            <select
              v-if="colDef(colKey)?.type === 'dropdown'"
              v-model="itemModal.form[colKey]"
            >
              <option value="">— Select —</option>
              <option v-for="opt in colDef(colKey).options" :key="opt" :value="opt">{{ opt }}</option>
            </select>

            <textarea
              v-else-if="['additional_notes','notes'].includes(colKey)"
              v-model="itemModal.form[colKey]"
              :placeholder="colDef(colKey)?.label"
              class="form-textarea"
              rows="3"
            ></textarea>
            <input
              v-else
              v-model="itemModal.form[colKey]"
              type="text"
              :placeholder="colDef(colKey)?.label"
              :autofocus="colKey === sections[itemModal.sectionIndex].columns[0]"
              @keyup.enter="saveItem"
            />
          </div>
        </div>
        <div class="modal-footer">
          <button @click="closeItemModal" class="btn-secondary">Cancel</button>
          <button @click="saveItem" class="btn-primary">
            {{ itemModal.itemIndex === null ? 'Add Row' : 'Update Row' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.fs-wrap { max-width: 900px; }

/* ── Header ──────────────────────────────────────────────────────────────── */
.fs-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 24px; gap: 20px;
}
.fs-title    { font-size: 20px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.fs-subtitle { font-size: 13px; color: #64748b; line-height: 1.5; }
.fs-loading  { color: #94a3b8; padding: 20px 0; }

.btn-save {
  padding: 10px 22px; background: #6366f1; color: white; border: none;
  border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer;
  white-space: nowrap; flex-shrink: 0; transition: background 0.15s;
}
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { background: #a5b4fc; cursor: default; }

/* ── Accordion ───────────────────────────────────────────────────────────── */
.accordion { border: 1.5px solid #e5e7eb; border-radius: 10px; overflow: visible; margin-bottom: 16px; }
.accordion-item { border-bottom: 1px solid #f1f5f9; position: relative; }
.accordion-item:last-child { border-bottom: none; }
.accordion-item.is-disabled .acc-header { background: #fafafa; }

.acc-header {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; background: white; cursor: pointer;
  user-select: none; transition: background 0.15s;
}
.acc-header:hover { background: #f8fafc; }
.accordion-item.is-expanded > .acc-header { background: #f5f3ff; border-bottom: 1px solid #e0e7ff; }

.chevron { font-size: 13px; color: #94a3b8; width: 14px; flex-shrink: 0; }

/* Toggle */
.toggle { position: relative; flex-shrink: 0; cursor: pointer; }
.toggle input { display: none; }
.toggle-track {
  display: block; width: 34px; height: 18px; background: #d1d5db;
  border-radius: 9px; position: relative; transition: background 0.2s;
}
.toggle-track::after {
  content: ''; position: absolute; top: 2px; left: 2px;
  width: 14px; height: 14px; background: white; border-radius: 50%;
  transition: transform 0.2s; box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.toggle input:checked ~ .toggle-track              { background: #6366f1; }
.toggle input:checked ~ .toggle-track::after       { transform: translateX(16px); }

.sec-name-input {
  flex: 0 0 auto; min-width: 140px; max-width: 220px;
  border: none; background: transparent; font-size: 14px; font-weight: 600;
  color: #1e293b; padding: 3px 6px; border-radius: 4px; font-family: inherit;
}
.sec-name-input:focus { outline: none; background: #f1f5f9; }
.sec-name-input.muted { color: #94a3b8; }

.sec-pills { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; min-width: 0; }
.col-pill {
  padding: 2px 7px; background: #e0e7ff; color: #4338ca;
  border-radius: 8px; font-size: 10px; font-weight: 700; white-space: nowrap;
}

.row-count { font-size: 11px; color: #94a3b8; white-space: nowrap; flex-shrink: 0; }
.sec-actions { display: flex; gap: 4px; flex-shrink: 0; }

/* ── Accordion body ──────────────────────────────────────────────────────── */
.acc-body { padding: 16px; background: #fafafa; border-top: 1px solid #f1f5f9; }

.col-config-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; background: white;
  border: 1.5px solid #e5e7eb; border-radius: 8px;
  margin-bottom: 14px; flex-wrap: wrap;
}
.col-config-label { font-size: 12px; font-weight: 700; color: #94a3b8; white-space: nowrap; }

.active-cols { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }

.active-col-chip {
  display: flex; align-items: center; gap: 2px;
  background: #f1f5f9; border: 1px solid #e2e8f0;
  border-radius: 6px; padding: 3px 6px;
}
.chip-label { font-size: 12px; font-weight: 600; color: #374151; padding: 0 4px; }
.chip-arrow {
  width: 16px; height: 16px; background: none; border: none;
  font-size: 14px; font-weight: 700; color: #94a3b8; cursor: pointer;
  display: flex; align-items: center; justify-content: center; border-radius: 3px;
  line-height: 1; padding: 0;
}
.chip-arrow:hover:not(:disabled) { background: #e2e8f0; color: #374151; }
.chip-arrow:disabled { opacity: 0.3; cursor: not-allowed; }
.chip-remove {
  width: 14px; height: 14px; background: none; border: none;
  font-size: 10px; color: #94a3b8; cursor: pointer; border-radius: 2px;
  display: flex; align-items: center; justify-content: center; padding: 0;
}
.chip-remove:hover:not(:disabled) { background: #fee2e2; color: #dc2626; }
.chip-remove:disabled { opacity: 0.2; cursor: not-allowed; }

.col-add-wrap { position: relative; }
.btn-add-col {
  padding: 5px 10px; background: #f1f5f9; border: 1.5px dashed #cbd5e1;
  border-radius: 6px; font-size: 12px; font-weight: 600; color: #6366f1;
  cursor: pointer; white-space: nowrap; transition: all 0.15s;
}
.btn-add-col:hover { background: #e0e7ff; border-color: #a5b4fc; }

.picker-backdrop { position: fixed; inset: 0; z-index: 999; }

.col-picker-dropdown {
  position: absolute; top: calc(100% + 6px); left: 0;
  background: white; border: 1.5px solid #e5e7eb; border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12); min-width: 220px;
  z-index: 1000; padding: 8px 0;
}
.col-picker-title {
  font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase;
  letter-spacing: 0.5px; padding: 4px 14px 8px;
}
.col-picker-row {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 14px; font-size: 13px; color: #374151; cursor: pointer;
  transition: background 0.1s;
}
.col-picker-row:hover { background: #f8fafc; }
.col-picker-row.active { color: #4338ca; font-weight: 600; }
.col-picker-check { width: 14px; font-size: 12px; color: #6366f1; flex-shrink: 0; }
.col-picker-badge {
  margin-left: auto; font-size: 10px; background: #fef3c7;
  color: #92400e; padding: 1px 5px; border-radius: 4px; font-weight: 600;
}
.col-picker-close { padding: 8px 14px 4px; }

/* ── Items table ─────────────────────────────────────────────────────────── */
.items-table-wrap { overflow-x: auto; margin-bottom: 10px; }
.items-table td { min-width: 80px; }

.items-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
.items-table th {
  text-align: left; padding: 8px 12px;
  background: #f1f5f9; border-bottom: 2px solid #e5e7eb;
  font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;
  letter-spacing: 0.4px; white-space: normal; word-break: break-word;
}
.items-table td {
  padding: 9px 12px; border-bottom: 1px solid #f1f5f9;
  color: #1e293b; vertical-align: middle;
}
.items-table tr:last-child td { border-bottom: none; }
.items-table tr:hover td { background: #fafbff; }
.item-cell { max-width: 280px; white-space: pre-wrap; word-break: break-word; vertical-align: top; }

.col-actions { white-space: nowrap; width: 1%; }
.col-actions .btn-icon-sm { display: inline-flex; }

.items-empty {
  text-align: center; color: #94a3b8; font-size: 13px;
  padding: 20px 0 10px;
}

.btn-add-item {
  width: 100%; padding: 8px; background: white;
  border: 1.5px dashed #cbd5e1; border-radius: 7px;
  font-size: 13px; font-weight: 600; color: #64748b; cursor: pointer;
  transition: all 0.15s; margin-top: 4px;
}
.btn-add-item:hover { border-color: #6366f1; color: #6366f1; background: #f5f3ff; }

/* ── Add section ─────────────────────────────────────────────────────────── */
.add-section-row { display: flex; gap: 10px; margin-bottom: 12px; }
.add-section-input {
  flex: 1; padding: 10px 14px; border: 1.5px solid #e5e7eb;
  border-radius: 8px; font-size: 14px; font-family: inherit;
  transition: border-color 0.15s;
}
.add-section-input:focus { outline: none; border-color: #6366f1; }
.btn-add-section {
  padding: 10px 18px; background: #f1f5f9; color: #374151;
  border: 1.5px solid #e5e7eb; border-radius: 8px; font-size: 14px;
  font-weight: 600; cursor: pointer; white-space: nowrap; transition: all 0.15s;
}
.btn-add-section:hover { background: #e2e8f0; }

.fs-hint { font-size: 12px; color: #94a3b8; line-height: 1.5; }

/* ── Icon buttons ────────────────────────────────────────────────────────── */
.btn-icon {
  width: 28px; height: 28px; background: white; border: 1px solid #e5e7eb;
  border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer;
  display: flex; align-items: center; justify-content: center; color: #374151;
  transition: all 0.15s;
}
.btn-icon:hover:not(:disabled) { background: #f1f5f9; color: #6366f1; border-color: #c7d2fe; }
.btn-icon:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-icon.danger:hover { background: #fee2e2; border-color: #fca5a5; color: #dc2626; }

.btn-icon-sm {
  width: 24px; height: 24px; background: #f8fafc; border: 1px solid #e5e7eb;
  border-radius: 5px; font-size: 11px; font-weight: 700; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; color: #374151;
  transition: all 0.15s; margin-left: 2px;
}
.btn-icon-sm:hover:not(:disabled) { background: #f1f5f9; color: #6366f1; }
.btn-icon-sm:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-icon-sm.edit:hover   { background: #e0e7ff; color: #4338ca; }
.btn-icon-sm.danger:hover { background: #fee2e2; color: #dc2626; }

/* ── Modal ───────────────────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 1001; padding: 20px;
}
.modal {
  background: white; border-radius: 12px; width: 100%; max-width: 460px;
  max-height: 90vh; overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 18px 22px; border-bottom: 1px solid #e5e7eb;
  position: sticky; top: 0; background: white; z-index: 1;
}
.modal-header h2 { font-size: 17px; font-weight: 700; color: #1e293b; }
.btn-close {
  background: none; border: none; font-size: 17px; color: #94a3b8; cursor: pointer;
  width: 28px; height: 28px; border-radius: 4px; display: flex; align-items: center; justify-content: center;
}
.btn-close:hover { background: #f1f5f9; color: #374151; }
.modal-body { padding: 20px 22px; }
.modal-footer {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 22px; border-top: 1px solid #e5e7eb;
  background: #f8fafc; position: sticky; bottom: 0;
}

.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: #475569; }
.form-group input,
.form-group select {
  width: 100%; padding: 9px 12px; border: 1px solid #cbd5e1;
  border-radius: 7px; font-size: 14px; font-family: inherit;
  box-sizing: border-box; transition: border-color 0.15s;
}
.form-group input:focus,
.form-group select:focus { outline: none; border-color: #6366f1; }

.btn-primary {
  padding: 9px 20px; background: #6366f1; color: white; border: none;
  border-radius: 7px; font-size: 14px; font-weight: 600; cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover { background: #4f46e5; }
.btn-secondary {
  padding: 9px 18px; background: white; color: #64748b;
  border: 1px solid #cbd5e1; border-radius: 7px; font-size: 14px;
  font-weight: 600; cursor: pointer;
}
.btn-secondary:hover { background: #f1f5f9; }
.btn-secondary-sm {
  padding: 5px 12px; background: white; color: #64748b;
  border: 1px solid #cbd5e1; border-radius: 6px; font-size: 12px;
  font-weight: 600; cursor: pointer; width: 100%;
}
.btn-secondary-sm:hover { background: #f1f5f9; }
</style>
