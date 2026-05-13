<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../../services/api'

const presets     = ref([])
const loading     = ref(true)
const saving      = ref(false)
const selected    = ref(null)   // index into presets[]
const dirty       = ref(false)

// New preset form
const showCreate      = ref(false)
const createName      = ref('')
const createLoading   = ref(false)

// ── Load ──────────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const res = await api.getSectionPresets()
    presets.value = (res.data || []).map(normalise)
    if (presets.value.length > 0) selected.value = 0
  } catch (e) {
    console.error(e)
    alert('Failed to load room presets')
  } finally {
    loading.value = false
  }
}

function normalise(p) {
  return {
    id:          p.id,
    name:        p.name || '',
    description: p.description || '',
    items:       (p.items || []).map(item => ({
      name:               item.name || '',
      requires_condition: item.requires_condition !== false,
      requires_photo:     item.requires_photo !== false,
    })),
  }
}

// ── Selected preset ───────────────────────────────────────────────────────────
const current = computed(() =>
  selected.value !== null ? presets.value[selected.value] : null
)

function selectPreset(i) {
  if (dirty.value && !confirm('You have unsaved changes. Discard them?')) return
  selected.value = i
  dirty.value = false
}

// ── Item editing ──────────────────────────────────────────────────────────────
function addItem() {
  current.value.items.push({ name: '', requires_condition: true, requires_photo: true })
  dirty.value = true
}

function removeItem(i) {
  current.value.items.splice(i, 1)
  dirty.value = true
}

function moveUp(i) {
  if (i === 0) return
  const arr = current.value.items
  ;[arr[i - 1], arr[i]] = [arr[i], arr[i - 1]]
  dirty.value = true
}

function moveDown(i) {
  const arr = current.value.items
  if (i >= arr.length - 1) return
  ;[arr[i], arr[i + 1]] = [arr[i + 1], arr[i]]
  dirty.value = true
}

// ── Save ──────────────────────────────────────────────────────────────────────
async function save() {
  if (!current.value) return
  saving.value = true
  try {
    const payload = {
      name:  current.value.name.trim(),
      items: current.value.items.map((item, idx) => ({
        name:               item.name.trim(),
        description:        '',
        requires_condition: item.requires_condition,
        requires_photo:     item.requires_photo,
        order_index:        idx,
      })).filter(item => item.name),
    }
    await api.updateSectionPreset(current.value.id, payload)
    dirty.value = false
  } catch (e) {
    console.error(e)
    alert('Failed to save preset')
  } finally {
    saving.value = false
  }
}

// ── Create ────────────────────────────────────────────────────────────────────
async function handleCreate() {
  const name = createName.value.trim()
  if (!name) return
  createLoading.value = true
  try {
    const res = await api.createSectionPreset({ name, category: 'room', items: [] })
    presets.value.push(normalise(res.data))
    selected.value = presets.value.length - 1
    dirty.value = false
    showCreate.value = false
    createName.value = ''
  } catch (e) {
    console.error(e)
    alert('Failed to create preset')
  } finally {
    createLoading.value = false
  }
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function deletePreset(i) {
  const p = presets.value[i]
  if (!confirm(`Delete preset "${p.name}"? This cannot be undone.`)) return
  try {
    await api.deleteSectionPreset(p.id)
    presets.value.splice(i, 1)
    if (selected.value >= presets.value.length) selected.value = presets.value.length - 1
    dirty.value = false
  } catch (e) {
    console.error(e)
    alert('Failed to delete preset')
  }
}

onMounted(load)
</script>

<template>
  <div class="settings-section">
    <div class="section-header">
      <div>
        <h2>Room Presets</h2>
        <p class="section-description">
          Define reusable room templates (items/questions) for Midterm reports.
          Presets are picked from the Add Room picker inside the Edit Report view.
        </p>
      </div>
      <button class="btn-create" @click="showCreate = true">+ New Preset</button>
    </div>

    <div v-if="loading" class="loading">Loading presets…</div>

    <div v-else-if="presets.length === 0" class="empty-state">
      <span class="empty-icon">🏠</span>
      <h3>No room presets yet</h3>
      <p>Create your first preset to use when adding rooms to a Midterm report.</p>
      <button class="btn-create" @click="showCreate = true">+ New Preset</button>
    </div>

    <div v-else class="editor-layout">

      <!-- Left: preset list -->
      <div class="preset-list">
        <div
          v-for="(p, i) in presets"
          :key="p.id"
          class="preset-item"
          :class="{ active: selected === i }"
          @click="selectPreset(i)"
        >
          <div class="preset-item-body">
            <div class="preset-item-name">{{ p.name }}</div>
            <div class="preset-item-meta">{{ p.items.length }} item{{ p.items.length !== 1 ? 's' : '' }}</div>
          </div>
          <button class="preset-delete" @click.stop="deletePreset(i)" title="Delete preset">✕</button>
        </div>
      </div>

      <!-- Right: item editor -->
      <div v-if="current" class="preset-editor">

        <!-- Preset name -->
        <div class="editor-name-row">
          <div class="form-group" style="flex:1">
            <label>Preset name</label>
            <input
              v-model="current.name"
              type="text"
              placeholder="e.g. Midterm Bedroom"
              @input="dirty = true"
            />
          </div>
          <div class="editor-actions">
            <button
              class="btn-save-preset"
              :disabled="saving || !dirty"
              @click="save"
            >
              {{ saving ? 'Saving…' : 'Save' }}
            </button>
          </div>
        </div>

        <!-- Items table -->
        <div class="items-table-wrap">
          <table class="items-table">
            <thead>
              <tr>
                <th class="col-order"></th>
                <th>Item / Question</th>
                <th class="col-tog" title="Condition field">Cond.</th>
                <th class="col-tog" title="Photo field">Photo</th>
                <th class="col-del"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, i) in current.items" :key="i">
                <td class="col-order">
                  <div class="order-btns">
                    <button class="ord-btn" @click="moveUp(i)" :disabled="i === 0">▲</button>
                    <button class="ord-btn" @click="moveDown(i)" :disabled="i === current.items.length - 1">▼</button>
                  </div>
                </td>
                <td>
                  <input
                    v-model="item.name"
                    type="text"
                    class="item-name-input"
                    placeholder="e.g. Damage to walls?"
                    @input="dirty = true"
                  />
                </td>
                <td class="col-tog">
                  <input type="checkbox" v-model="item.requires_condition" @change="dirty = true" />
                </td>
                <td class="col-tog">
                  <input type="checkbox" v-model="item.requires_photo" @change="dirty = true" />
                </td>
                <td class="col-del">
                  <button class="del-item-btn" @click="removeItem(i)">✕</button>
                </td>
              </tr>
              <tr v-if="current.items.length === 0">
                <td colspan="5" class="empty-items">No items yet — add one below.</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="add-item-bar">
          <button class="btn-add-item" @click="addItem">+ Add Item</button>
        </div>

        <div v-if="dirty" class="dirty-banner">
          <span>Unsaved changes</span>
          <button class="btn-save-preset" :disabled="saving" @click="save">
            {{ saving ? 'Saving…' : 'Save Changes' }}
          </button>
        </div>

      </div>
    </div>
  </div>

  <!-- Create modal -->
  <Teleport to="body">
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <div class="modal-header">
          <h2>New Room Preset</h2>
          <button class="btn-close" @click="showCreate = false">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Preset name *</label>
            <input
              v-model="createName"
              type="text"
              placeholder="e.g. Midterm Bedroom"
              autofocus
              @keyup.enter="handleCreate"
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" @click="showCreate = false">Cancel</button>
          <button class="btn-primary" :disabled="createLoading || !createName.trim()" @click="handleCreate">
            {{ createLoading ? 'Creating…' : 'Create' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.settings-section { min-height: auto; }

.section-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 28px; gap: 20px;
}
.settings-section h2 { font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 6px; }
.section-description { color: #64748b; font-size: 14px; }

.btn-create {
  padding: 10px 20px; background: #6366f1; color: white; border: none;
  border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer;
  white-space: nowrap; transition: background 0.15s;
}
.btn-create:hover { background: #4f46e5; }

.loading { text-align: center; padding: 60px; color: #94a3b8; }

.empty-state { text-align: center; padding: 80px 20px; }
.empty-icon { font-size: 56px; display: block; margin-bottom: 12px; }
.empty-state h3 { font-size: 18px; font-weight: 600; color: #1e293b; margin-bottom: 6px; }
.empty-state p { color: #64748b; margin-bottom: 20px; }

/* ── Two-panel layout ────────────────────────────────────────────────── */
.editor-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 20px;
  align-items: start;
}

/* Left panel */
.preset-list {
  background: white;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
}

.preset-item {
  display: flex; align-items: center;
  padding: 12px 14px;
  cursor: pointer;
  border-bottom: 1px solid #f1f5f9;
  transition: background 0.12s;
}
.preset-item:last-child { border-bottom: none; }
.preset-item:hover { background: #f8fafc; }
.preset-item.active { background: #eef2ff; border-left: 3px solid #6366f1; padding-left: 11px; }

.preset-item-body { flex: 1; min-width: 0; }
.preset-item-name { font-size: 13px; font-weight: 600; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.preset-item-meta { font-size: 11px; color: #94a3b8; margin-top: 2px; }

.preset-delete {
  background: none; border: none; color: #cbd5e1; font-size: 13px;
  cursor: pointer; padding: 2px 4px; border-radius: 4px; line-height: 1;
  flex-shrink: 0;
}
.preset-delete:hover { background: #fee2e2; color: #dc2626; }

/* Right panel */
.preset-editor {
  background: white;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.editor-name-row {
  display: flex; gap: 12px; align-items: flex-end;
}
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: 12px; font-weight: 600; color: #475569; }
.form-group input {
  padding: 8px 11px; border: 1px solid #cbd5e1; border-radius: 7px;
  font-size: 14px; font-family: inherit;
}
.form-group input:focus { outline: none; border-color: #6366f1; }

.editor-actions { flex-shrink: 0; padding-bottom: 1px; }

/* Items table */
.items-table-wrap { overflow-x: auto; }
.items-table { width: 100%; border-collapse: collapse; }
.items-table th {
  padding: 8px 10px; text-align: left; font-size: 11px; font-weight: 700;
  color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;
  border-bottom: 1.5px solid #e5e7eb; background: #f8fafc;
}
.items-table td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
.items-table tr:last-child td { border-bottom: none; }

.col-order { width: 48px; }
.col-tog   { width: 52px; text-align: center; }
.col-del   { width: 36px; }

.order-btns { display: flex; flex-direction: column; gap: 1px; }
.ord-btn {
  background: none; border: 1px solid #e5e7eb; border-radius: 3px;
  font-size: 9px; color: #94a3b8; cursor: pointer; padding: 1px 4px; line-height: 1;
}
.ord-btn:hover:not(:disabled) { background: #f1f5f9; color: #475569; }
.ord-btn:disabled { opacity: 0.3; cursor: not-allowed; }

.item-name-input {
  width: 100%; padding: 6px 9px; border: 1px solid #e5e7eb; border-radius: 6px;
  font-size: 13px; font-family: inherit; box-sizing: border-box;
}
.item-name-input:focus { outline: none; border-color: #6366f1; }

.col-tog input[type="checkbox"] { cursor: pointer; }

.del-item-btn {
  background: none; border: none; color: #cbd5e1; font-size: 14px;
  cursor: pointer; padding: 2px 6px; border-radius: 4px;
}
.del-item-btn:hover { background: #fee2e2; color: #dc2626; }

.empty-items { text-align: center; color: #94a3b8; font-size: 13px; padding: 20px; }

.add-item-bar { padding-top: 4px; }
.btn-add-item {
  background: none; border: 1.5px dashed #c7d2fe; border-radius: 7px;
  color: #6366f1; font-size: 13px; font-weight: 600; padding: 7px 18px;
  cursor: pointer; transition: all 0.15s;
}
.btn-add-item:hover { background: #e0e7ff; border-color: #818cf8; }

.btn-save-preset {
  padding: 8px 20px; background: #6366f1; color: white; border: none;
  border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer;
  transition: background 0.15s; white-space: nowrap;
}
.btn-save-preset:hover:not(:disabled) { background: #4f46e5; }
.btn-save-preset:disabled { opacity: 0.5; cursor: not-allowed; }

.dirty-banner {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; background: #fefce8; border: 1px solid #fde68a;
  border-radius: 8px; font-size: 13px; color: #92400e;
}

/* ── Modal ───────────────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px;
}
.modal { background: white; border-radius: 12px; width: 100%; max-width: 400px; box-shadow: 0 20px 60px rgba(0,0,0,0.15); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #e5e7eb; }
.modal-header h2 { font-size: 16px; font-weight: 700; color: #1e293b; }
.btn-close { background: none; border: none; font-size: 17px; color: #94a3b8; cursor: pointer; width: 28px; height: 28px; border-radius: 4px; }
.btn-close:hover { background: #f1f5f9; color: #374151; }
.modal-body { padding: 18px 20px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid #e5e7eb; background: #f8fafc; border-radius: 0 0 12px 12px; }
.btn-primary { padding: 8px 18px; background: #6366f1; color: white; border: none; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #4f46e5; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { padding: 8px 16px; background: white; color: #64748b; border: 1px solid #cbd5e1; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn-secondary:hover { background: #f1f5f9; }
</style>
