<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import api from '../../services/api'

const router = useRouter()
const authStore = useAuthStore()

const templates = ref([])
const loading = ref(true)
const showCreateModal = ref(false)

const createForm = ref({
  name: '',
  description: '',
  inspection_type: 'check_in'
})

async function fetchTemplates() {
  loading.value = true
  try {
    const response = await api.getTemplates()
    templates.value = response.data
  } catch (error) {
    console.error('Failed to fetch templates:', error)
    alert('Failed to load templates')
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  createForm.value = {
    name: '',
    description: '',
    inspection_type: 'check_in'
  }
  showCreateModal.value = true
}

function closeCreateModal() {
  showCreateModal.value = false
}

async function handleCreate() {
  if (!createForm.value.name.trim()) {
    alert('Template name is required')
    return
  }

  try {
    const response = await api.createTemplate(createForm.value)
    alert('Template created successfully!')
    closeCreateModal()
    router.push(`/settings/templates/${response.data.id}`)
  } catch (error) {
    console.error('Failed to create template:', error)
    alert('Failed to create template')
  }
}

async function duplicateTemplate(template) {
  if (!confirm(`Duplicate "${template.name}"?`)) return

  try {
    const response = await api.duplicateTemplate(template.id)
    alert('Template duplicated successfully!')
    router.push(`/settings/templates/${response.data.id}`)
  } catch (error) {
    console.error('Failed to duplicate template:', error)
    alert('Failed to duplicate template')
  }
}

async function deleteTemplate(template) {
  if (!confirm(`Are you sure you want to delete "${template.name}"? This action cannot be undone.`)) return

  try {
    await api.deleteTemplate(template.id)
    alert('Template deleted successfully!')
    fetchTemplates()
  } catch (error) {
    console.error('Failed to delete template:', error)
    alert('Failed to delete template')
  }
}

function editTemplate(template) {
  router.push(`/settings/templates/${template.id}`)
}

function getTypeColor(type) {
  return type === 'check_in' ? '#10b981' : '#f59e0b'
}

onMounted(() => {
  fetchTemplates()
})
</script>

<template>
  <div class="templates-page">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h2>Inspection Templates</h2>
        <p class="subtitle">Manage templates for check-in and check-out inspections</p>
      </div>
      <button @click="openCreateModal" class="btn-primary">
        ➕ New Template
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading">Loading templates...</div>

    <!-- Templates Grid -->
    <div v-else-if="templates.length > 0" class="templates-grid">
      <div 
        v-for="template in templates" 
        :key="template.id"
        class="template-card"
        @click="editTemplate(template)"
      >
        <div class="card-header">
          <h3>{{ template.name }}</h3>
          <span 
            class="type-badge" 
            :style="{ backgroundColor: getTypeColor(template.inspection_type) }"
          >
            {{ template.inspection_type.replace('_', ' ').toUpperCase() }}
          </span>
        </div>

        <p v-if="template.description" class="card-description">
          {{ template.description }}
        </p>

        <div class="card-footer">
          <span class="created-date">
            Created {{ new Date(template.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) }}
          </span>

          <div class="card-actions" @click.stop>
            <button @click="duplicateTemplate(template)" class="btn-action" title="Duplicate">
              📋
            </button>
            <button @click="deleteTemplate(template)" class="btn-action danger" title="Delete">
              🗑️
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="empty-state">
      <div class="empty-icon">📄</div>
      <h3>No templates yet</h3>
      <p>Create your first inspection template to get started</p>
      <button @click="openCreateModal" class="btn-primary">Create Template</button>
    </div>

    <!-- Create Modal -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal">
        <div class="modal-header">
          <h2>Create New Template</h2>
          <button @click="closeCreateModal" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleCreate" class="modal-body">
          <div class="form-group">
            <label for="name">Template Name *</label>
            <input
              id="name"
              v-model="createForm.name"
              type="text"
              required
              placeholder="e.g., Standard 2 Bed 2 Bath"
            />
          </div>

          <div class="form-group">
            <label for="description">Description</label>
            <textarea
              id="description"
              v-model="createForm.description"
              rows="3"
              placeholder="Optional description of this template"
            ></textarea>
          </div>

          <div class="form-group">
            <label for="inspection_type">Inspection Type *</label>
            <select id="inspection_type" v-model="createForm.inspection_type" required>
              <option value="check_in">Check In</option>
              <option value="check_out">Check Out</option>
            </select>
          </div>

          <div class="modal-footer">
            <button type="button" @click="closeCreateModal" class="btn-secondary">Cancel</button>
            <button type="submit" class="btn-primary">Create Template</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.templates-page {
  max-width: 1400px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
}

.page-header h2 {
  font-size: 28px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.subtitle {
  color: #64748b;
  font-size: 14px;
}

.btn-primary {
  padding: 12px 24px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: #4f46e5;
}

.loading {
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
  font-size: 16px;
}

.templates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 24px;
}

.template-card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  cursor: pointer;
  transition: all 0.2s;
  border: 2px solid transparent;
}

.template-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
  border-color: #6366f1;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.card-header h3 {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  flex: 1;
}

.type-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  color: white;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-description {
  color: #64748b;
  font-size: 14px;
  margin-bottom: 16px;
  line-height: 1.5;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
}

.created-date {
  font-size: 12px;
  color: #94a3b8;
}

.card-actions {
  display: flex;
  gap: 8px;
}

.btn-action {
  width: 32px;
  height: 32px;
  background: #f1f5f9;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-action:hover {
  background: #e2e8f0;
}

.btn-action.danger:hover {
  background: #fee2e2;
}

.empty-state {
  background: white;
  padding: 80px 40px;
  border-radius: 12px;
  text-align: center;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 20px;
}

.empty-state h3 {
  font-size: 24px;
  color: #1e293b;
  margin-bottom: 8px;
}

.empty-state p {
  color: #64748b;
  margin-bottom: 24px;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal {
  background: white;
  border-radius: 12px;
  width: 100%;
  max-width: 600px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
}

.btn-close {
  background: none;
  border: none;
  font-size: 24px;
  color: #64748b;
  cursor: pointer;
  padding: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.btn-close:hover {
  background: #f1f5f9;
}

.modal-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #475569;
  font-size: 14px;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  transition: border-color 0.2s;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #6366f1;
}

.form-group textarea {
  resize: vertical;
  font-family: inherit;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 24px;
  border-top: 1px solid #e5e7eb;
  background: #f8fafc;
}

.btn-secondary {
  padding: 10px 20px;
  background: white;
  color: #64748b;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: #f1f5f9;
}
</style>
