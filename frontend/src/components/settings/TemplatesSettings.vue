<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../../services/api'
import TemplatePreviewModal from './TemplatePreviewModal.vue'

const router    = useRouter()
const templates = ref([])
const loading   = ref(false)

// Preview
const previewTemplate = ref(null)
const showPreview     = ref(false)

// Create modal
const showCreateModal = ref(false)
const creating        = ref(false)
const createForm      = ref({ name: '', inspection_type: 'check_in' })

async function fetchTemplates() {
  loading.value = true
  try {
    const res = await api.getTemplates()
    templates.value = res.data
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

// ── Create ────────────────────────────────────────────────────────────────────
function openCreateModal() {
  createForm.value = { name: '', inspection_type: 'check_in' }
  showCreateModal.value = true
}

async function handleCreate() {
  if (!createForm.value.name.trim()) { alert('Template name is required'); return }
  creating.value = true
  try {
    const res = await api.createTemplate({
      name:            createForm.value.name.trim(),
      inspection_type: createForm.value.inspection_type,
      content:         '{}',
      is_default:      false,
    })
    showCreateModal.value = false
    // Navigate to the real id returned by the server
    router.push(`/settings/templates/${res.data.id}`)
  } catch (e) {
    console.error(e)
    alert('Failed to create template')
  } finally {
    creating.value = false
  }
}

// ── Edit / preview ────────────────────────────────────────────────────────────
function editTemplate(id) {
  router.push(`/settings/templates/${id}`)
}

async function openPreview(id) {
  try {
    const res = await api.getTemplate(id)
    previewTemplate.value = res.data
    showPreview.value = true
  } catch (e) {
    console.error(e)
    alert('Failed to load template')
  }
}

function closePreview() {
  showPreview.value = false
  previewTemplate.value = null
}

// ── Copy ──────────────────────────────────────────────────────────────────────
async function copyTemplate(template) {
  if (!confirm(`Create a copy of "${template.name}"?`)) return
  try {
    const res = await api.copyTemplate(template.id)
    await fetchTemplates()
    router.push(`/settings/templates/${res.data.id}`)
  } catch (e) {
    console.error(e)
    alert('Failed to copy template')
  }
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function deleteTemplate(template) {
  if (!confirm(`Delete "${template.name}"? This cannot be undone.`)) return
  try {
    await api.deleteTemplate(template.id)
    templates.value = templates.value.filter(t => t.id !== template.id)
  } catch (e) {
    console.error(e)
    alert('Failed to delete template')
  }
}

onMounted(fetchTemplates)
</script>

<template>
  <div class="settings-section">
    <div class="section-header">
      <div>
        <h2>Inspection Templates</h2>
        <p class="section-description">
          Create and manage templates for different inspection types.
        </p>
      </div>
      <button @click="openCreateModal" class="btn-create">➕ Create New Template</button>
    </div>

    <div v-if="loading" class="loading">Loading templates…</div>

    <div v-else-if="templates.length === 0" class="empty-state">
      <span class="empty-icon">📋</span>
      <h3>No templates yet</h3>
      <p>Create your first inspection template to get started</p>
      <button @click="openCreateModal" class="btn-create">➕ Create Template</button>
    </div>

    <div v-else class="templates-grid">
      <div v-for="template in templates" :key="template.id" class="template-card">
        <div class="template-header">
          <div>
            <h3>{{ template.name }}</h3>
            <span class="template-type">{{ template.inspection_type.replace('_', ' ').toUpperCase() }}</span>
          </div>
          <span v-if="template.is_default" class="badge-default">Default</span>
        </div>

        <div class="template-meta">
          <p>📅 {{ new Date(template.created_at).toLocaleDateString('en-GB') }}</p>
          <p v-if="template.sections?.length">
            🏠 {{ template.sections.length }} section{{ template.sections.length !== 1 ? 's' : '' }}
          </p>
        </div>

        <div class="template-actions">
          <button @click="editTemplate(template.id)"   class="btn-action btn-edit">✏️ Edit</button>
          <button @click="openPreview(template.id)"    class="btn-action btn-preview">👁️ Preview</button>
          <button @click="copyTemplate(template)"      class="btn-action btn-copy">📋 Copy</button>
          <button @click="deleteTemplate(template)"    class="btn-action btn-delete">🗑️ Delete</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Create modal -->
  <Teleport to="body">
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>New Template</h2>
          <button @click="showCreateModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Template name *</label>
            <input
              v-model="createForm.name"
              type="text"
              placeholder="e.g. Standard 2 Bed Flat"
              autofocus
              @keyup.enter="handleCreate"
            />
          </div>
          <div class="form-group">
            <label>Inspection type *</label>
            <select v-model="createForm.inspection_type">
              <option value="check_in">Check In</option>
              <option value="check_out">Check Out</option>
              <option value="midterm">Midterm Inspection</option>
              <option value="interim">Interim</option>
              <option value="inventory">Inventory</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showCreateModal = false" class="btn-secondary">Cancel</button>
          <button @click="handleCreate" class="btn-primary" :disabled="creating">
            {{ creating ? 'Creating…' : 'Create & Edit' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Preview modal -->
  <Teleport to="body">
    <TemplatePreviewModal
      v-if="showPreview && previewTemplate"
      :template="previewTemplate"
      @close="closePreview"
    />
  </Teleport>
</template>

<style scoped>
.settings-section { min-height: auto; }

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
  gap: 20px;
}

.settings-section h2 { font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 6px; }
.section-description  { color: #64748b; font-size: 14px; }

.btn-create {
  padding: 10px 20px;
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
.btn-create:hover { background: #4f46e5; }

.loading { text-align: center; padding: 60px; color: #94a3b8; }

.empty-state {
  text-align: center;
  padding: 80px 20px;
}
.empty-icon { font-size: 56px; display: block; margin-bottom: 12px; }
.empty-state h3 { font-size: 18px; font-weight: 600; color: #1e293b; margin-bottom: 6px; }
.empty-state p  { color: #64748b; margin-bottom: 20px; }

.templates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.template-card {
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  padding: 18px;
  background: white;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.template-card:hover { border-color: #c7d2fe; box-shadow: 0 2px 8px rgba(99,102,241,0.08); }

.template-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 10px;
}
.template-header h3 { font-size: 15px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }

.template-type {
  display: inline-block;
  padding: 2px 8px;
  background: #e0e7ff;
  color: #4338ca;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
}

.badge-default {
  padding: 2px 8px;
  background: #dcfce7;
  color: #166534;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
}

.template-meta { font-size: 12px; color: #94a3b8; margin-bottom: 14px; }
.template-meta p { margin-bottom: 2px; }

.template-actions { display: flex; gap: 6px; flex-wrap: wrap; }

.btn-action {
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #e5e7eb;
  background: white;
  color: #374151;
  transition: all 0.15s;
}
.btn-action:hover   { background: #f1f5f9; }
.btn-edit:hover     { background: #e0e7ff; border-color: #a5b4fc; color: #4338ca; }
.btn-preview:hover  { background: #f0fdf4; border-color: #a7f3d0; color: #166534; }
.btn-copy:hover     { background: #fefce8; border-color: #fde68a; color: #854d0e; }
.btn-delete:hover   { background: #fee2e2; border-color: #fca5a5; color: #dc2626; }

/* ── Modal ─────────────────────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; padding: 20px;
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
  padding: 14px 22px; border-top: 1px solid #e5e7eb; background: #f8fafc;
  border-radius: 0 0 12px 12px;
}

.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: #475569; }
.form-group input,
.form-group select {
  width: 100%; padding: 9px 12px;
  border: 1px solid #cbd5e1; border-radius: 7px;
  font-size: 14px; font-family: inherit; box-sizing: border-box;
}
.form-group input:focus,
.form-group select:focus { outline: none; border-color: #6366f1; }

.btn-primary {
  padding: 9px 20px; background: #6366f1; color: white;
  border: none; border-radius: 7px; font-size: 14px; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.btn-primary:hover:not(:disabled) { background: #4f46e5; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  padding: 9px 18px; background: white; color: #64748b;
  border: 1px solid #cbd5e1; border-radius: 7px; font-size: 14px;
  font-weight: 600; cursor: pointer;
}
.btn-secondary:hover { background: #f1f5f9; }
</style>
