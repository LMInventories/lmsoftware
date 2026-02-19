<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../services/api'

const route = useRoute()
const router = useRouter()

const template = ref(null)
const loading = ref(true)
const saving = ref(false)

const showAddSectionModal = ref(false)
const showAddItemModal = ref(null) // stores section id
const showEditItemModal = ref(null) // stores item object

const newSectionForm = ref({
  name: '',
  section_type: 'room'
})

const newItemForm = ref({
  name: '',
  description: '',
  requires_photo: true,
  requires_condition: true
})

const editItemForm = ref({
  id: null,
  name: '',
  description: '',
  requires_photo: true,
  requires_condition: true
})

const roomSections = computed(() => {
  if (!template.value?.sections) return []
  return template.value.sections.filter(s => s.section_type === 'room')
})

const fixedSections = computed(() => {
  if (!template.value?.sections) return []
  return template.value.sections.filter(s => s.section_type === 'fixed')
})

async function fetchTemplate() {
  loading.value = true
  try {
    const response = await api.getTemplate(route.params.id)
    template.value = response.data
  } catch (error) {
    console.error('Failed to fetch template:', error)
    alert('Failed to load template')
    router.push('/settings/templates')
  } finally {
    loading.value = false
  }
}

async function updateTemplateName() {
  if (!template.value.name.trim()) {
    alert('Template name is required')
    return
  }

  saving.value = true
  try {
    await api.updateTemplate(template.value.id, {
      name: template.value.name,
      description: template.value.description
    })
    alert('Template updated!')
  } catch (error) {
    console.error('Failed to update template:', error)
    alert('Failed to update template')
  } finally {
    saving.value = false
  }
}

// ============= SECTIONS =============

function openAddSectionModal() {
  newSectionForm.value = {
    name: '',
    section_type: 'room'
  }
  showAddSectionModal.value = true
}

async function handleAddSection() {
  if (!newSectionForm.value.name.trim()) {
    alert('Section name is required')
    return
  }

  try {
    const response = await api.addSection(template.value.id, newSectionForm.value)
    template.value.sections.push(response.data)
    showAddSectionModal.value = false
    alert('Section added!')
  } catch (error) {
    console.error('Failed to add section:', error)
    alert('Failed to add section')
  }
}

async function duplicateSection(section) {
  if (!confirm(`Duplicate "${section.name}"?`)) return

  try {
    const response = await api.duplicateSection(section.id)
    template.value.sections.push(response.data)
    alert('Section duplicated!')
    fetchTemplate() // Refresh to get proper order
  } catch (error) {
    console.error('Failed to duplicate section:', error)
    alert('Failed to duplicate section')
  }
}

async function deleteSection(section) {
  if (section.is_required) {
    alert('Cannot delete required sections')
    return
  }

  if (!confirm(`Delete "${section.name}"? This will remove all items in this section.`)) return

  try {
    await api.deleteSection(section.id)
    template.value.sections = template.value.sections.filter(s => s.id !== section.id)
    alert('Section deleted!')
  } catch (error) {
    console.error('Failed to delete section:', error)
    alert('Failed to delete section')
  }
}

async function moveSectionUp(section) {
  try {
    await api.reorderSection(section.id, 'up')
    fetchTemplate()
  } catch (error) {
    console.error('Failed to move section:', error)
  }
}

async function moveSectionDown(section) {
  try {
    await api.reorderSection(section.id, 'down')
    fetchTemplate()
  } catch (error) {
    console.error('Failed to move section:', error)
  }
}

// ============= ITEMS =============

function openAddItemModal(sectionId) {
  newItemForm.value = {
    name: '',
    description: '',
    requires_photo: true,
    requires_condition: true
  }
  showAddItemModal.value = sectionId
}

async function handleAddItem() {
  if (!newItemForm.value.name.trim()) {
    alert('Item name is required')
    return
  }

  try {
    const response = await api.addItem(showAddItemModal.value, newItemForm.value)
    
    // Add item to correct section
    const section = template.value.sections.find(s => s.id === showAddItemModal.value)
    if (section) {
      if (!section.items) section.items = []
      section.items.push(response.data)
    }
    
    showAddItemModal.value = null
    alert('Item added!')
  } catch (error) {
    console.error('Failed to add item:', error)
    alert('Failed to add item')
  }
}

function openEditItemModal(item) {
  editItemForm.value = {
    id: item.id,
    name: item.name,
    description: item.description,
    requires_photo: item.requires_photo,
    requires_condition: item.requires_condition
  }
  showEditItemModal.value = item
}

async function handleUpdateItem() {
  if (!editItemForm.value.name.trim()) {
    alert('Item name is required')
    return
  }

  try {
    await api.updateItem(editItemForm.value.id, {
      name: editItemForm.value.name,
      description: editItemForm.value.description,
      requires_photo: editItemForm.value.requires_photo,
      requires_condition: editItemForm.value.requires_condition
    })
    
    // Update in local state
    Object.assign(showEditItemModal.value, editItemForm.value)
    
    showEditItemModal.value = null
    alert('Item updated!')
  } catch (error) {
    console.error('Failed to update item:', error)
    alert('Failed to update item')
  }
}

async function duplicateItem(item, section) {
  try {
    const response = await api.duplicateItem(item.id)
    section.items.push(response.data)
    alert('Item duplicated!')
  } catch (error) {
    console.error('Failed to duplicate item:', error)
    alert('Failed to duplicate item')
  }
}

async function deleteItem(item, section) {
  if (!confirm(`Delete "${item.name}"?`)) return

  try {
    await api.deleteItem(item.id)
    section.items = section.items.filter(i => i.id !== item.id)
    alert('Item deleted!')
  } catch (error) {
    console.error('Failed to delete item:', error)
    alert('Failed to delete item')
  }
}

async function moveItemUp(item, section) {
  try {
    await api.reorderItem(item.id, 'up')
    fetchTemplate()
  } catch (error) {
    console.error('Failed to move item:', error)
  }
}

async function moveItemDown(item, section) {
  try {
    await api.reorderItem(item.id, 'down')
    fetchTemplate()
  } catch (error) {
    console.error('Failed to move item:', error)
  }
}

onMounted(() => {
  fetchTemplate()
})
</script>

<template>
  <div class="template-editor">
    <!-- Header -->
    <div class="page-header">
      <div class="header-left">
        <button @click="router.push('/settings/templates')" class="btn-back">
          ← Back
        </button>
        <div v-if="!loading">
          <input 
            v-model="template.name" 
            @blur="updateTemplateName"
            class="template-name-input"
            placeholder="Template Name"
          />
          <p class="subtitle">{{ template.inspection_type.replace('_', ' ').toUpperCase() }}</p>
        </div>
      </div>
      <button @click="openAddSectionModal" class="btn-primary">
        ➕ Add Section
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading">Loading template...</div>

    <!-- Template Editor -->
    <div v-else class="editor-container">
      
      <!-- Fixed Sections -->
      <div class="sections-group">
        <h3 class="group-title">📄 Fixed Sections (Required)</h3>
        <p class="group-description">These sections appear on every inspection report</p>
        
        <div class="sections-list">
          <div v-for="section in fixedSections" :key="section.id" class="section-card fixed">
            <div class="section-header">
              <span class="section-name">{{ section.name }}</span>
              <span class="section-badge">Required</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Room Sections -->
      <div class="sections-group">
        <h3 class="group-title">🏠 Room Sections</h3>
        <p class="group-description">Customize these sections for different property types</p>
        
        <div class="sections-list">
          <div v-for="(section, index) in roomSections" :key="section.id" class="section-card">
            
            <!-- Section Header -->
            <div class="section-header">
              <span class="section-name">{{ section.name }}</span>
              
              <div class="section-actions">
                <button @click="moveSectionUp(section)" :disabled="index === 0" class="btn-icon" title="Move Up">
                  ⬆️
                </button>
                <button @click="moveSectionDown(section)" :disabled="index === roomSections.length - 1" class="btn-icon" title="Move Down">
                  ⬇️
                </button>
                <button @click="duplicateSection(section)" class="btn-icon" title="Duplicate">
                  📋
                </button>
                <button @click="deleteSection(section)" class="btn-icon danger" title="Delete">
                  🗑️
                </button>
              </div>
            </div>

            <!-- Items List -->
            <div class="items-list">
              <div v-for="(item, itemIndex) in section.items" :key="item.id" class="item-row">
                <div class="item-info">
                  <span class="item-name">{{ item.name }}</span>
                  <div class="item-meta">
                    <span v-if="item.requires_photo" class="meta-badge">📷 Photo</span>
                    <span v-if="item.requires_condition" class="meta-badge">✅ Condition</span>
                  </div>
                </div>
                
                <div class="item-actions">
                  <button @click="moveItemUp(item, section)" :disabled="itemIndex === 0" class="btn-icon-sm" title="Up">
                    ⬆️
                  </button>
                  <button @click="moveItemDown(item, section)" :disabled="itemIndex === section.items.length - 1" class="btn-icon-sm" title="Down">
                    ⬇️
                  </button>
                  <button @click="openEditItemModal(item)" class="btn-icon-sm" title="Edit">
                    ✏️
                  </button>
                  <button @click="duplicateItem(item, section)" class="btn-icon-sm" title="Duplicate">
                    📋
                  </button>
                  <button @click="deleteItem(item, section)" class="btn-icon-sm danger" title="Delete">
                    🗑️
                  </button>
                </div>
              </div>

              <!-- Add Item Button -->
              <button @click="openAddItemModal(section.id)" class="btn-add-item">
                ➕ Add Item
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Section Modal -->
    <div v-if="showAddSectionModal" class="modal-overlay" @click.self="showAddSectionModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>Add New Section</h2>
          <button @click="showAddSectionModal = false" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleAddSection" class="modal-body">
          <div class="form-group">
            <label for="section-name">Section Name *</label>
            <input
              id="section-name"
              v-model="newSectionForm.name"
              type="text"
              required
              placeholder="e.g., Master Bedroom"
            />
          </div>

          <div class="modal-footer">
            <button type="button" @click="showAddSectionModal = false" class="btn-secondary">Cancel</button>
            <button type="submit" class="btn-primary">Add Section</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Add Item Modal -->
    <div v-if="showAddItemModal" class="modal-overlay" @click.self="showAddItemModal = null">
      <div class="modal">
        <div class="modal-header">
          <h2>Add New Item</h2>
          <button @click="showAddItemModal = null" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleAddItem" class="modal-body">
          <div class="form-group">
            <label for="item-name">Item Name *</label>
            <input
              id="item-name"
              v-model="newItemForm.name"
              type="text"
              required
              placeholder="e.g., Door, Frame, Threshold & Furniture"
            />
          </div>

          <div class="form-group">
            <label for="item-description">Description</label>
            <textarea
              id="item-description"
              v-model="newItemForm.description"
              rows="2"
              placeholder="Optional description"
            ></textarea>
          </div>

          <div class="form-group-inline">
            <label class="checkbox-label">
              <input type="checkbox" v-model="newItemForm.requires_photo" />
              <span>Requires Photo</span>
            </label>
            <label class="checkbox-label">
              <input type="checkbox" v-model="newItemForm.requires_condition" />
              <span>Requires Condition</span>
            </label>
          </div>

          <div class="modal-footer">
            <button type="button" @click="showAddItemModal = null" class="btn-secondary">Cancel</button>
            <button type="submit" class="btn-primary">Add Item</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Edit Item Modal -->
    <div v-if="showEditItemModal" class="modal-overlay" @click.self="showEditItemModal = null">
      <div class="modal">
        <div class="modal-header">
          <h2>Edit Item</h2>
          <button @click="showEditItemModal = null" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleUpdateItem" class="modal-body">
          <div class="form-group">
            <label for="edit-item-name">Item Name *</label>
            <input
              id="edit-item-name"
              v-model="editItemForm.name"
              type="text"
              required
            />
          </div>

          <div class="form-group">
            <label for="edit-item-description">Description</label>
            <textarea
              id="edit-item-description"
              v-model="editItemForm.description"
              rows="2"
            ></textarea>
          </div>

          <div class="form-group-inline">
            <label class="checkbox-label">
              <input type="checkbox" v-model="editItemForm.requires_photo" />
              <span>Requires Photo</span>
            </label>
            <label class="checkbox-label">
              <input type="checkbox" v-model="editItemForm.requires_condition" />
              <span>Requires Condition</span>
            </label>
          </div>

          <div class="modal-footer">
            <button type="button" @click="showEditItemModal = null" class="btn-secondary">Cancel</button>
            <button type="submit" class="btn-primary">Update Item</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.template-editor {
  max-width: 1400px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
}

.btn-back {
  padding: 10px 16px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-back:hover {
  background: #f8fafc;
}

.template-name-input {
  font-size: 28px;
  font-weight: 600;
  color: #1e293b;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 4px 8px;
  margin-bottom: 4px;
  transition: border-color 0.2s;
}

.template-name-input:hover {
  border-bottom-color: #e5e7eb;
}

.template-name-input:focus {
  outline: none;
  border-bottom-color: #6366f1;
}

.subtitle {
  color: #64748b;
  font-size: 14px;
  text-transform: uppercase;
  font-weight: 600;
  letter-spacing: 0.5px;
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
}

.editor-container {
  display: flex;
  flex-direction: column;
  gap: 48px;
}

.sections-group {
  background: white;
  padding: 32px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.group-title {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.group-description {
  color: #64748b;
  font-size: 14px;
  margin-bottom: 24px;
}

.sections-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-card {
  background: #f8fafc;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
  transition: all 0.2s;
}

.section-card:hover {
  border-color: #cbd5e1;
}

.section-card.fixed {
  background: #fef3c7;
  border-color: #fcd34d;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-name {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
}

.section-badge {
  padding: 4px 12px;
  background: #fbbf24;
  color: #78350f;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 700;
}

.section-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 36px;
  height: 36px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.btn-icon:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-icon.danger:hover {
  background: #fee2e2;
  border-color: #fecaca;
}

.items-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: white;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  transition: all 0.2s;
}

.item-row:hover {
  border-color: #cbd5e1;
}

.item-info {
  flex: 1;
}

.item-name {
  font-size: 14px;
  font-weight: 500;
  color: #1e293b;
  display: block;
  margin-bottom: 4px;
}

.item-meta {
  display: flex;
  gap: 8px;
}

.meta-badge {
  padding: 2px 8px;
  background: #e0e7ff;
  color: #4338ca;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
}

.item-actions {
  display: flex;
  gap: 4px;
}

.btn-icon-sm {
  width: 28px;
  height: 28px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon-sm:hover:not(:disabled) {
  background: #f1f5f9;
}

.btn-icon-sm:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-icon-sm.danger:hover {
  background: #fee2e2;
}

.btn-add-item {
  width: 100%;
  padding: 10px;
  background: white;
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
  margin-top: 8px;
}

.btn-add-item:hover {
  background: #f8fafc;
  border-color: #6366f1;
  color: #6366f1;
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
.form-group textarea {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  transition: border-color 0.2s;
}

.form-group input:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #6366f1;
}

.form-group textarea {
  resize: vertical;
  font-family: inherit;
}

.form-group-inline {
  display: flex;
  gap: 24px;
  margin-bottom: 20px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #475569;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
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
