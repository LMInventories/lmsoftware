<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

// ── State ─────────────────────────────────────────────────────────────────────
const sections       = ref([])   // [{ name, enabled, items: [{ name, description, requires_photo, requires_condition }] }]
const loading        = ref(true)
const saving         = ref(false)
const expanded       = ref({})   // { sectionIndex: bool }
const dirty          = ref(false)

// New section form
const newSectionName = ref('')

// Item modal state
const itemModal = ref(null)  // null | { sectionIndex, itemIndex|null, form: {} }

// ── Load / save ───────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const res = await api.getFixedSections()
    // Ensure every section has an items array
    sections.value = (res.data || []).map(s => ({
      name:        s.name || '',
      enabled:     s.enabled !== false,
      items:       Array.isArray(s.items) ? s.items : [],
    }))
    // Expand first section by default
    if (sections.value.length > 0) expanded.value[0] = true
  } catch (e) {
    console.error(e)
    alert('Failed to load fixed sections')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res = await api.updateFixedSections(sections.value)
    sections.value = (res.data || []).map(s => ({
      name:    s.name || '',
      enabled: s.enabled !== false,
      items:   Array.isArray(s.items) ? s.items : [],
    }))
    dirty.value = false
  } catch (e) {
    console.error(e)
    alert('Failed to save')
  } finally {
    saving.value = false
  }
}

function markDirty() { dirty.value = true }

// ── Section management ────────────────────────────────────────────────────────
function toggleExpanded(index) {
  expanded.value[index] = !expanded.value[index]
}

function addSection() {
  const name = newSectionName.value.trim()
  if (!name) return
  sections.value.push({ name, enabled: true, items: [] })
  expanded.value[sections.value.length - 1] = true
  newSectionName.value = ''
  markDirty()
}

function removeSection(index) {
  if (!confirm(`Remove "${sections.value[index].name}"?`)) return
  sections.value.splice(index, 1)
  // Rebuild expanded keys
  const newExpanded = {}
  Object.keys(expanded.value).forEach(k => {
    const ki = parseInt(k)
    if (ki < index) newExpanded[ki] = expanded.value[k]
    else if (ki > index) newExpanded[ki - 1] = expanded.value[k]
  })
  expanded.value = newExpanded
  markDirty()
}

function moveSectionUp(index) {
  if (index === 0) return
  const arr = sections.value
  ;[arr[index - 1], arr[index]] = [arr[index], arr[index - 1]]
  // Swap expanded state
  const tmp = expanded.value[index - 1]
  expanded.value[index - 1] = expanded.value[index]
  expanded.value[index] = tmp
  markDirty()
}

function moveSectionDown(index) {
  if (index === sections.value.length - 1) return
  const arr = sections.value
  ;[arr[index], arr[index + 1]] = [arr[index + 1], arr[index]]
  const tmp = expanded.value[index]
  expanded.value[index] = expanded.value[index + 1]
  expanded.value[index + 1] = tmp
  markDirty()
}

// ── Item management ───────────────────────────────────────────────────────────
function openAddItem(sectionIndex) {
  itemModal.value = {
    sectionIndex,
    itemIndex: null,
    form: { name: '', description: '', requires_photo: true, requires_condition: true },
  }
}

function openEditItem(sectionIndex, itemIndex) {
  const item = sections.value[sectionIndex].items[itemIndex]
  itemModal.value = {
    sectionIndex,
    itemIndex,
    form: { ...item },
  }
}

function closeItemModal() { itemModal.value = null }

function saveItem() {
  const { sectionIndex, itemIndex, form } = itemModal.value
  if (!form.name.trim()) { alert('Item name is required'); return }
  const items = sections.value[sectionIndex].items
  if (itemIndex === null) {
    items.push({ ...form, name: form.name.trim() })
  } else {
    items[itemIndex] = { ...form, name: form.name.trim() }
  }
  markDirty()
  closeItemModal()
}

function deleteItem(sectionIndex, itemIndex) {
  const item = sections.value[sectionIndex].items[itemIndex]
  if (!confirm(`Delete "${item.name}"?`)) return
  sections.value[sectionIndex].items.splice(itemIndex, 1)
  markDirty()
}

function moveItemUp(sectionIndex, itemIndex) {
  if (itemIndex === 0) return
  const items = sections.value[sectionIndex].items
  ;[items[itemIndex - 1], items[itemIndex]] = [items[itemIndex], items[itemIndex - 1]]
  markDirty()
}

function moveItemDown(sectionIndex, itemIndex) {
  const items = sections.value[sectionIndex].items
  if (itemIndex === items.length - 1) return
  ;[items[itemIndex], items[itemIndex + 1]] = [items[itemIndex + 1], items[itemIndex]]
  markDirty()
}

onMounted(load)
</script>

<template>
  <div class="fs-wrap">

    <!-- Header -->
    <div class="fs-header">
      <div>
        <h2 class="fs-title">Fixed Sections</h2>
        <p class="fs-subtitle">
          These sections appear on <strong>every</strong> inspection report regardless of template.
          Edit the items within each section here.
        </p>
      </div>
      <button @click="save" :disabled="saving || !dirty" class="btn-save">
        {{ saving ? 'Saving…' : dirty ? 'Save Changes' : 'Saved' }}
      </button>
    </div>

    <div v-if="loading" class="fs-loading">Loading…</div>

    <div v-else>

      <!-- Section accordion list -->
      <div class="accordion">
        <div
          v-for="(section, sIdx) in sections"
          :key="sIdx"
          class="accordion-item"
          :class="{ expanded: expanded[sIdx], disabled: !section.enabled }"
        >
          <!-- Section header row -->
          <div class="accordion-header" @click="toggleExpanded(sIdx)">

            <!-- Toggle chevron -->
            <span class="chevron">{{ expanded[sIdx] ? '▾' : '▸' }}</span>

            <!-- Enable/disable toggle (stop propagation so it doesn't toggle expand) -->
            <label class="toggle" @click.stop title="Enable / disable">
              <input type="checkbox" v-model="section.enabled" @change="markDirty" />
              <span class="toggle-track"></span>
            </label>

            <!-- Section name (inline edit) -->
            <input
              v-model="section.name"
              class="section-name-input"
              :class="{ muted: !section.enabled }"
              placeholder="Section name"
              @click.stop
              @input="markDirty"
            />

            <span class="item-count">{{ section.items.length }} item{{ section.items.length !== 1 ? 's' : '' }}</span>

            <!-- Reorder + delete -->
            <div class="section-btns" @click.stop>
              <button @click="moveSectionUp(sIdx)"   :disabled="sIdx === 0"                     class="btn-icon" title="Move Up">↑</button>
              <button @click="moveSectionDown(sIdx)" :disabled="sIdx === sections.length - 1"   class="btn-icon" title="Move Down">↓</button>
              <button @click="removeSection(sIdx)"                                               class="btn-icon danger" title="Remove">✕</button>
            </div>
          </div>

          <!-- Expanded: item list -->
          <div v-if="expanded[sIdx]" class="accordion-body">

            <div v-if="section.items.length === 0" class="items-empty">
              No items yet. Add the first one below.
            </div>

            <div class="items-list">
              <div
                v-for="(item, iIdx) in section.items"
                :key="iIdx"
                class="item-row"
              >
                <div class="item-info">
                  <span class="item-name">{{ item.name }}</span>
                  <span v-if="item.description" class="item-desc">{{ item.description }}</span>
                  <div class="item-badges">
                    <span v-if="item.requires_photo"     class="badge photo">📷 Photo</span>
                    <span v-if="item.requires_condition" class="badge cond">✓ Condition</span>
                  </div>
                </div>
                <div class="item-actions">
                  <button @click="moveItemUp(sIdx, iIdx)"   :disabled="iIdx === 0"                         class="btn-icon-sm">↑</button>
                  <button @click="moveItemDown(sIdx, iIdx)" :disabled="iIdx === section.items.length - 1"  class="btn-icon-sm">↓</button>
                  <button @click="openEditItem(sIdx, iIdx)"                                                class="btn-icon-sm edit">✎</button>
                  <button @click="deleteItem(sIdx, iIdx)"                                                  class="btn-icon-sm danger">✕</button>
                </div>
              </div>
            </div>

            <button @click="openAddItem(sIdx)" class="btn-add-item">＋ Add Item</button>
          </div>
        </div>
      </div>

      <!-- Add new section row -->
      <div class="add-section-row">
        <input
          v-model="newSectionName"
          class="add-section-input"
          placeholder="New section name, e.g. Carbon Monoxide Alarms"
          @keyup.enter="addSection"
        />
        <button @click="addSection" class="btn-add-section">＋ Add Section</button>
      </div>

      <p class="fs-hint">
        Disabled sections are hidden from reports but not deleted.
        Changes take effect on all reports once saved.
      </p>
    </div>

  </div>

  <!-- Item add/edit modal -->
  <Teleport to="body">
    <div v-if="itemModal" class="modal-overlay" @click.self="closeItemModal">
      <div class="modal">
        <div class="modal-header">
          <h2>{{ itemModal.itemIndex === null ? 'Add Item' : 'Edit Item' }}</h2>
          <button @click="closeItemModal" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Item name *</label>
            <input
              v-model="itemModal.form.name"
              type="text"
              placeholder="e.g. Smoke Alarm — Hallway"
              autofocus
              @keyup.enter="saveItem"
            />
          </div>
          <div class="form-group">
            <label>Description <span class="optional">(optional)</span></label>
            <textarea v-model="itemModal.form.description" rows="2" placeholder="Optional detail"></textarea>
          </div>
          <div class="form-group-inline">
            <label class="checkbox-label">
              <input type="checkbox" v-model="itemModal.form.requires_photo" />
              <span>Requires Photo</span>
            </label>
            <label class="checkbox-label">
              <input type="checkbox" v-model="itemModal.form.requires_condition" />
              <span>Requires Condition</span>
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="closeItemModal" class="btn-secondary">Cancel</button>
          <button @click="saveItem" class="btn-primary">
            {{ itemModal.itemIndex === null ? 'Add Item' : 'Update Item' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.fs-wrap { max-width: 760px; }

/* ── Header ──────────────────────────────────────────────────────────────── */
.fs-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 24px; gap: 20px;
}
.fs-title    { font-size: 20px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.fs-subtitle { font-size: 13px; color: #64748b; line-height: 1.5; max-width: 500px; }
.fs-loading  { color: #94a3b8; padding: 20px 0; }

.btn-save {
  padding: 10px 22px; background: #6366f1; color: white;
  border: none; border-radius: 8px; font-size: 14px; font-weight: 600;
  cursor: pointer; white-space: nowrap; flex-shrink: 0; transition: background 0.15s;
}
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { background: #a5b4fc; cursor: default; }

/* ── Accordion ───────────────────────────────────────────────────────────── */
.accordion {
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 16px;
}

.accordion-item { border-bottom: 1px solid #f1f5f9; }
.accordion-item:last-child { border-bottom: none; }
.accordion-item.disabled .accordion-header { background: #fafafa; }

.accordion-header {
  display: flex; align-items: center; gap: 10px;
  padding: 13px 16px;
  background: white;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.accordion-header:hover { background: #f8fafc; }
.accordion-item.expanded > .accordion-header { background: #f5f3ff; border-bottom: 1px solid #e0e7ff; }

.chevron { font-size: 13px; color: #94a3b8; width: 14px; flex-shrink: 0; }

/* Toggle */
.toggle { position: relative; flex-shrink: 0; cursor: pointer; }
.toggle input { display: none; }
.toggle-track {
  display: block; width: 34px; height: 18px;
  background: #d1d5db; border-radius: 9px; position: relative;
  transition: background 0.2s;
}
.toggle-track::after {
  content: ''; position: absolute; top: 2px; left: 2px;
  width: 14px; height: 14px; background: white; border-radius: 50%;
  transition: transform 0.2s; box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.toggle input:checked ~ .toggle-track              { background: #6366f1; }
.toggle input:checked ~ .toggle-track::after       { transform: translateX(16px); }

/* Section name input */
.section-name-input {
  flex: 1; border: none; background: transparent;
  font-size: 14px; font-weight: 600; color: #1e293b;
  padding: 3px 6px; border-radius: 4px; font-family: inherit;
  min-width: 0;
}
.section-name-input:focus { outline: none; background: #f1f5f9; }
.section-name-input.muted { color: #94a3b8; }

.item-count { font-size: 11px; color: #94a3b8; white-space: nowrap; flex-shrink: 0; }

.section-btns { display: flex; gap: 4px; flex-shrink: 0; }

.btn-icon {
  width: 28px; height: 28px; background: white; border: 1px solid #e5e7eb;
  border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer;
  display: flex; align-items: center; justify-content: center; color: #374151;
  transition: all 0.15s;
}
.btn-icon:hover:not(:disabled) { background: #f1f5f9; color: #6366f1; border-color: #c7d2fe; }
.btn-icon:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-icon.danger:hover { background: #fee2e2; border-color: #fca5a5; color: #dc2626; }

/* ── Accordion body ──────────────────────────────────────────────────────── */
.accordion-body {
  padding: 14px 16px 16px;
  background: #fafafa;
}

.items-empty { text-align: center; color: #94a3b8; font-size: 13px; padding: 12px 0 8px; }

.items-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }

.item-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 14px; background: white; border: 1px solid #e9ecef;
  border-radius: 7px; transition: border-color 0.15s;
}
.item-row:hover { border-color: #c7d2fe; }

.item-info { flex: 1; min-width: 0; }
.item-name { font-size: 13px; font-weight: 600; color: #1e293b; display: block; margin-bottom: 2px; }
.item-desc { font-size: 11px; color: #64748b; display: block; margin-bottom: 4px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-badges { display: flex; gap: 5px; }
.badge { padding: 1px 6px; border-radius: 6px; font-size: 10px; font-weight: 700; }
.badge.photo { background: #e0e7ff; color: #4338ca; }
.badge.cond  { background: #dcfce7; color: #166534; }

.item-actions { display: flex; gap: 4px; flex-shrink: 0; }

.btn-icon-sm {
  width: 26px; height: 26px; background: #f8fafc; border: 1px solid #e5e7eb;
  border-radius: 5px; font-size: 11px; font-weight: 700; cursor: pointer;
  display: flex; align-items: center; justify-content: center; color: #374151;
  transition: all 0.15s;
}
.btn-icon-sm:hover:not(:disabled) { background: #f1f5f9; color: #6366f1; }
.btn-icon-sm:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-icon-sm.edit:hover   { background: #e0e7ff; color: #4338ca; }
.btn-icon-sm.danger:hover { background: #fee2e2; color: #dc2626; }

.btn-add-item {
  width: 100%; padding: 8px; background: white;
  border: 1.5px dashed #cbd5e1; border-radius: 7px;
  font-size: 13px; font-weight: 600; color: #64748b; cursor: pointer;
  transition: all 0.15s;
}
.btn-add-item:hover { border-color: #6366f1; color: #6366f1; background: #f5f3ff; }

/* ── Add section row ─────────────────────────────────────────────────────── */
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
.btn-add-section:hover { background: #e2e8f0; border-color: #cbd5e1; }

.fs-hint { font-size: 12px; color: #94a3b8; line-height: 1.5; }

/* ── Modal ───────────────────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 2000; padding: 20px;
}
.modal {
  background: white; border-radius: 12px; width: 100%; max-width: 440px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 18px 22px; border-bottom: 1px solid #e5e7eb;
}
.modal-header h2 { font-size: 17px; font-weight: 700; color: #1e293b; }
.btn-close {
  background: none; border: none; font-size: 17px; color: #94a3b8;
  cursor: pointer; width: 28px; height: 28px; border-radius: 4px;
}
.btn-close:hover { background: #f1f5f9; color: #374151; }
.modal-body { padding: 20px 22px; }
.modal-footer {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 22px; border-top: 1px solid #e5e7eb;
  background: #f8fafc; border-radius: 0 0 12px 12px;
}

.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: #475569; }
.form-group input,
.form-group textarea {
  width: 100%; padding: 9px 12px; border: 1px solid #cbd5e1;
  border-radius: 7px; font-size: 14px; font-family: inherit;
  box-sizing: border-box; transition: border-color 0.15s;
}
.form-group input:focus,
.form-group textarea:focus { outline: none; border-color: #6366f1; }
.form-group textarea { resize: vertical; }

.form-group-inline { display: flex; gap: 20px; margin-bottom: 6px; }
.checkbox-label {
  display: flex; align-items: center; gap: 7px;
  font-size: 14px; color: #475569; cursor: pointer;
}
.checkbox-label input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
.optional { font-weight: 400; color: #94a3b8; }

.btn-primary {
  padding: 9px 20px; background: #6366f1; color: white;
  border: none; border-radius: 7px; font-size: 14px; font-weight: 600; cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover { background: #4f46e5; }
.btn-secondary {
  padding: 9px 18px; background: white; color: #64748b;
  border: 1px solid #cbd5e1; border-radius: 7px;
  font-size: 14px; font-weight: 600; cursor: pointer;
}
.btn-secondary:hover { background: #f1f5f9; }
</style>
