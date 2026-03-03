<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'
import { useToast } from '../../composables/useToast'

const toast = useToast()

const loading  = ref(true)
const saving   = ref(false)
const saved    = ref(false)

// ── State ──────────────────────────────────────────────────────────────────
const actions         = ref([])
const responsibilities = ref([])

const newActionName   = ref('')
const newActionColor  = ref('#6366f1')
const newResp         = ref('')

const editingActionId = ref(null)
const editingName     = ref('')
const editingColor    = ref('')

// Preset colour palette
const PALETTE = [
  '#ef4444', '#f97316', '#f59e0b', '#84cc16',
  '#10b981', '#06b6d4', '#3b82f6', '#8b5cf6',
  '#ec4899', '#64748b',
]

// ── Load ───────────────────────────────────────────────────────────────────
onMounted(load)

async function load() {
  loading.value = true
  try {
    const res = await api.getActions()
    actions.value         = res.data.actions         || []
    responsibilities.value = res.data.responsibilities || []
  } catch {
    toast.error('Failed to load actions config')
  } finally {
    loading.value = false
  }
}

// ── Save full config ───────────────────────────────────────────────────────
async function save() {
  saving.value = true
  saved.value  = false
  try {
    await api.saveActions({
      actions:         actions.value,
      responsibilities: responsibilities.value,
    })
    saved.value = true
    setTimeout(() => { saved.value = false }, 2500)
  } catch {
    toast.error('Failed to save — please try again')
  } finally {
    saving.value = false
  }
}

// ── Action CRUD ────────────────────────────────────────────────────────────
function addAction() {
  const name = newActionName.value.trim()
  if (!name) return
  actions.value.push({
    id:    'act_' + Date.now(),
    name,
    color: newActionColor.value,
  })
  newActionName.value  = ''
  newActionColor.value = '#6366f1'
}

function startEdit(act) {
  editingActionId.value = act.id
  editingName.value     = act.name
  editingColor.value    = act.color
}

function commitEdit(act) {
  if (!editingName.value.trim()) { cancelEdit(); return }
  act.name  = editingName.value.trim()
  act.color = editingColor.value
  cancelEdit()
}

function cancelEdit() {
  editingActionId.value = null
  editingName.value     = ''
  editingColor.value    = ''
}

function removeAction(id) {
  actions.value = actions.value.filter(a => a.id !== id)
}

// ── Responsibility CRUD ────────────────────────────────────────────────────
function addResp() {
  const r = newResp.value.trim()
  if (!r || responsibilities.value.includes(r)) return
  responsibilities.value.push(r)
  newResp.value = ''
}

function removeResp(r) {
  responsibilities.value = responsibilities.value.filter(x => x !== r)
}
</script>

<template>
  <div class="actions-page">

    <div class="page-intro">
      <h2>Actions &amp; Liabilities</h2>
      <p>
        Define the action tags that can be assigned to items in Check Out reports,
        and the responsibility parties that can be held liable.
        These appear in the Actions picker on each room item.
      </p>
    </div>

    <div v-if="loading" class="loading-state">Loading…</div>

    <template v-else>
      <div class="two-col">

        <!-- ── LEFT: Action types ───────────────────────────────────────── -->
        <section class="panel">
          <div class="panel-header">
            <h3>Action Types</h3>
            <span class="panel-count">{{ actions.length }}</span>
          </div>
          <p class="panel-desc">
            Each action tag has a name and a colour. The colour appears on the tag
            in the report editor and in the final PDF.
          </p>

          <!-- Existing actions -->
          <div class="action-list">
            <div
              v-for="act in actions"
              :key="act.id"
              class="action-row"
            >
              <template v-if="editingActionId === act.id">
                <!-- Editing state -->
                <div class="edit-swatch-wrap">
                  <input type="color" class="color-input" v-model="editingColor" />
                </div>
                <input
                  class="edit-name-input"
                  type="text"
                  v-model="editingName"
                  @keydown.enter="commitEdit(act)"
                  @keydown.esc="cancelEdit"
                  autofocus
                />
                <div class="action-row-btns">
                  <button class="btn-save-inline" @click="commitEdit(act)">✓</button>
                  <button class="btn-cancel-inline" @click="cancelEdit">✕</button>
                </div>
              </template>

              <template v-else>
                <!-- View state -->
                <div class="action-swatch" :style="{ background: act.color }"></div>
                <span class="action-name">{{ act.name }}</span>
                <div class="action-row-btns">
                  <button class="btn-icon-edit" @click="startEdit(act)" title="Edit">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button class="btn-icon-del" @click="removeAction(act.id)" title="Remove">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                  </button>
                </div>
              </template>
            </div>

            <div v-if="!actions.length" class="empty-hint">No action types yet — add one below.</div>
          </div>

          <!-- Colour palette quick-pick -->
          <div class="palette-row">
            <span class="palette-lbl">Quick colour:</span>
            <button
              v-for="c in PALETTE"
              :key="c"
              class="palette-dot"
              :style="{ background: c }"
              :class="{ selected: newActionColor === c }"
              @click="newActionColor = c"
            ></button>
            <input type="color" class="color-input-sm" v-model="newActionColor" title="Custom colour" />
          </div>

          <!-- Add action -->
          <div class="add-row">
            <input
              class="add-name-input"
              type="text"
              placeholder="New action name…"
              v-model="newActionName"
              @keydown.enter="addAction"
              maxlength="60"
            />
            <button class="btn-add-action" @click="addAction" :disabled="!newActionName.trim()">
              + Add
            </button>
          </div>
        </section>

        <!-- ── RIGHT: Responsibilities ──────────────────────────────────── -->
        <section class="panel">
          <div class="panel-header">
            <h3>Responsibility Parties</h3>
            <span class="panel-count">{{ responsibilities.length }}</span>
          </div>
          <p class="panel-desc">
            When assigning an action to a Check Out item, a responsibility party
            is selected to indicate who is liable (e.g. Tenant, Landlord/Agent).
          </p>

          <div class="resp-list">
            <div
              v-for="r in responsibilities"
              :key="r"
              class="resp-row"
            >
              <div class="resp-pill">{{ r }}</div>
              <button class="btn-icon-del" @click="removeResp(r)" title="Remove">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
              </button>
            </div>
            <div v-if="!responsibilities.length" class="empty-hint">No parties yet — add one below.</div>
          </div>

          <div class="add-row">
            <input
              class="add-name-input"
              type="text"
              placeholder="New party name…"
              v-model="newResp"
              @keydown.enter="addResp"
              maxlength="60"
            />
            <button class="btn-add-action" @click="addResp" :disabled="!newResp.trim()">
              + Add
            </button>
          </div>

          <!-- Preview: what typist will see -->
          <div class="preview-block">
            <div class="preview-title">Preview — Actions picker in report:</div>
            <div class="preview-inner">
              <div class="preview-tags">
                <span
                  v-for="act in actions.slice(0, 4)"
                  :key="act.id"
                  class="preview-tag"
                  :style="{ background: act.color + '22', color: act.color, borderColor: act.color + '66' }"
                >{{ act.name }}</span>
                <span v-if="!actions.length" class="preview-empty">No actions configured</span>
              </div>
              <div class="preview-resp-row">
                <span class="preview-resp-lbl">Responsibility:</span>
                <select class="preview-resp-select" disabled>
                  <option v-for="r in responsibilities" :key="r">{{ r }}</option>
                  <option v-if="!responsibilities.length" disabled>None configured</option>
                </select>
              </div>
            </div>
          </div>
        </section>

      </div>

      <!-- Save bar -->
      <div class="save-bar">
        <span v-if="saved" class="saved-msg">✓ Saved</span>
        <button class="btn-save" @click="save" :disabled="saving">
          {{ saving ? 'Saving…' : 'Save Changes' }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.actions-page { max-width: 1100px; }

.page-intro {
  margin-bottom: 28px;
}
.page-intro h2 {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 6px;
}
.page-intro p {
  color: #64748b;
  font-size: 14px;
  line-height: 1.6;
}

.loading-state {
  padding: 40px;
  text-align: center;
  color: #94a3b8;
}

/* Two-column layout */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-bottom: 28px;
}
@media (max-width: 800px) {
  .two-col { grid-template-columns: 1fr; }
}

/* Panel */
.panel {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 24px;
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.panel-header h3 {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
}
.panel-count {
  background: #e0e7ff;
  color: #4f46e5;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  padding: 1px 8px;
}
.panel-desc {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
  margin-bottom: 20px;
}

/* Action list */
.action-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
  min-height: 40px;
}
.action-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px 12px;
}
.action-swatch {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  flex-shrink: 0;
}
.action-name {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}
.action-row-btns {
  display: flex;
  gap: 4px;
}

/* Edit mode */
.edit-swatch-wrap { flex-shrink: 0; }
.color-input {
  width: 36px;
  height: 28px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
  padding: 2px;
}
.edit-name-input {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid #6366f1;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
}
.btn-save-inline {
  background: #dcfce7;
  color: #16a34a;
  border: 1px solid #bbf7d0;
  border-radius: 5px;
  width: 28px;
  height: 28px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 700;
}
.btn-cancel-inline {
  background: #fee2e2;
  color: #dc2626;
  border: 1px solid #fecaca;
  border-radius: 5px;
  width: 28px;
  height: 28px;
  font-size: 14px;
  cursor: pointer;
}

/* Icon buttons */
.btn-icon-edit,
.btn-icon-del {
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.btn-icon-edit:hover { background: #eff6ff; color: #3b82f6; }
.btn-icon-del:hover  { background: #fff1f2; color: #ef4444; }

/* Palette */
.palette-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.palette-lbl {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  white-space: nowrap;
}
.palette-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  flex-shrink: 0;
  transition: transform 0.1s;
}
.palette-dot:hover  { transform: scale(1.2); }
.palette-dot.selected { border-color: #1e293b; transform: scale(1.15); }
.color-input-sm {
  width: 28px;
  height: 22px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  cursor: pointer;
  padding: 1px;
}

/* Add row */
.add-row {
  display: flex;
  gap: 8px;
}
.add-name-input {
  flex: 1;
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  background: white;
}
.add-name-input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
}
.btn-add-action {
  padding: 9px 18px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}
.btn-add-action:hover:not(:disabled) { background: #4f46e5; }
.btn-add-action:disabled { background: #c7d2fe; cursor: not-allowed; }

/* Empty hint */
.empty-hint {
  font-size: 13px;
  color: #94a3b8;
  font-style: italic;
  padding: 8px 0;
}

/* Responsibilities */
.resp-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
  min-height: 40px;
}
.resp-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px 12px;
}
.resp-pill {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

/* Preview */
.preview-block {
  margin-top: 24px;
  padding: 16px;
  background: white;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
}
.preview-title {
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}
.preview-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.preview-tag {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid;
}
.preview-empty {
  font-size: 12px;
  color: #cbd5e1;
  font-style: italic;
}
.preview-resp-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.preview-resp-lbl {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}
.preview-resp-select {
  flex: 1;
  padding: 5px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  background: #f8fafc;
  color: #94a3b8;
}

/* Save bar */
.save-bar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 16px;
}
.saved-msg {
  font-size: 14px;
  font-weight: 600;
  color: #16a34a;
}
.btn-save {
  padding: 12px 32px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { background: #a5b4fc; cursor: not-allowed; }
</style>
