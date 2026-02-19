<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../../services/api'
import TemplatePreviewModal from './TemplatePreviewModal.vue'

const router = useRouter()
const templates = ref([])
const loading = ref(true)

// Preview state
const previewTemplate = ref(null)
const showPreview = ref(false)

async function fetchTemplates() {
  loading.value = true
  try {
    const response = await api.getTemplates()
    templates.value = response.data
  } catch (error) {
    console.error('Failed to fetch templates:', error)
  } finally {
    loading.value = false
  }
}

function createNewTemplate() {
  router.push('/settings/templates/new')
}

function editTemplate(id) {
  router.push(`/settings/templates/${id}`)
}

async function openPreview(id) {
  try {
    const response = await api.getTemplate(id)
    previewTemplate.value = response.data
    showPreview.value = true
  } catch (error) {
    console.error('Failed to load template for preview:', error)
    alert('Failed to load template')
  }
}

function closePreview() {
  showPreview.value = false
  previewTemplate.value = null
}

async function copyTemplate(templateId) {
  try {
    const response = await api.getTemplate(templateId)
    const template = response.data

    if (!confirm(`Create a copy of "${template.name}"?`)) return

    const newTemplate = {
      name: `${template.name} (Copy)`,
      inspection_type: template.inspection_type,
      is_default: false,
      content: template.content
    }

    await api.createTemplate(newTemplate)
    await fetchTemplates()
    alert('Template copied successfully!')
  } catch (error) {
    console.error('Copy error:', error)
    alert('Failed to copy template')
  }
}

async function deleteTemplate(id) {
  if (!confirm('Delete this template? This action cannot be undone.')) return

  try {
    await api.deleteTemplate(id)
    alert('Template deleted!')
    fetchTemplates()
  } catch (error) {
    console.error('Failed to delete template:', error)
    alert('Failed to delete template')
  }
}

onMounted(() => {
  fetchTemplates()
})
</script>

<template>
  <div class="settings-section">
    <div class="section-header">
      <div>
        <h2>Inspection Templates</h2>
        <p class="section-description">
          Create and manage templates for different inspection types. Templates define the structure and fields for inspection reports.
        </p>
      </div>
      <button @click="createNewTemplate" class="btn-create">
        ➕ Create New Template
      </button>
    </div>

    <div v-if="loading" class="loading">Loading templates...</div>

    <div v-else-if="templates.length === 0" class="empty-state">
      <span class="empty-icon">📋</span>
      <h3>No templates yet</h3>
      <p>Create your first inspection template to get started</p>
      <button @click="createNewTemplate" class="btn-create-empty">
        ➕ Create Template
      </button>
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
          <p>📅 Created: {{ new Date(template.created_at).toLocaleDateString('en-GB') }}</p>
          <p v-if="template.updated_at !== template.created_at">
            ✏️ Updated: {{ new Date(template.updated_at).toLocaleDateString('en-GB') }}
          </p>
        </div>

        <div class="template-actions">
          <button @click="editTemplate(template.id)" class="btn-action btn-edit">
            ✏️ Edit
          </button>
          <button @click="openPreview(template.id)" class="btn-action btn-preview">
            👁️ Preview
          </button>
          <button @click="copyTemplate(template.id)" class="btn-action btn-copy">
            📋 Copy
          </button>
          <button @click="deleteTemplate(template.id)" class="btn-action btn-delete">
            🗑️ Delete
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Preview Modal — rendered at root level via Teleport to escape stacking contexts -->
  <Teleport to="body">
    <TemplatePreviewModal
      v-if="showPreview && previewTemplate"
      :template="previewTemplate"
      @close="closePreview"
    />
  </Teleport>
</template>

<style scoped>
.settings-section {
  min-height: auto;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
  gap: 20px;
}

.settings-section h2 {
  font-size: 24px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.section-description {
  color: #64748b;
  font-size: 15px;
  line-height: 1.5;
}

.btn-create {
  padding: 12px 24px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}

.btn-create:hover {
  background: #4f46e5;
}

.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
}

.empty-state {
  text-align: center;
  padding: 80px 20px;
}

.empty-icon {
  font-size: 64px;
  display: block;
  margin-bottom: 16px;
}

.empty-state h3 {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.empty-state p {
  color: #64748b;
  margin-bottom: 24px;
}

.btn-create-empty {
  padding: 12px 32px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.btn-create-empty:hover {
  background: #4f46e5;
}

.templates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.template-card {
  background: #f8fafc;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  padding: 24px;
  transition: all 0.2s;
}

.template-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
}

.template-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  gap: 12px;
}

.template-card h3 {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 6px;
}

.template-type {
  display: inline-block;
  padding: 4px 10px;
  background: #dbeafe;
  color: #1e40af;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.badge-default {
  padding: 4px 10px;
  background: #dcfce7;
  color: #166534;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.template-meta {
  margin-bottom: 20px;
}

.template-meta p {
  font-size: 13px;
  color: #64748b;
  margin: 4px 0;
}

.template-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.btn-action {
  padding: 10px 16px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-edit { background: #dbeafe; color: #1e40af; }
.btn-edit:hover { background: #bfdbfe; }

.btn-preview { background: #e0e7ff; color: #3730a3; }
.btn-preview:hover { background: #c7d2fe; }

.btn-copy { background: #ddd6fe; color: #5b21b6; }
.btn-copy:hover { background: #c4b5fd; }

.btn-delete { background: #fee2e2; color: #991b1b; }
.btn-delete:hover { background: #fecaca; }
</style>
