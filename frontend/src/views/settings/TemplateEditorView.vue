<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../services/api'

const route  = useRoute()
const router = useRouter()

const template = ref(null)
const loading  = ref(true)
const saving   = ref(false)

// ── Modal visibility ─────────────────────────────────────────────────────────
const showAddSectionModal   = ref(false)    // "add blank section" modal
const showLibraryModal      = ref(false)    // section library browser
const showSavePresetModal   = ref(null)     // section object to save as preset
const showAddItemModal      = ref(null)     // section id
const showEditItemModal     = ref(null)     // item object

// ── Section Library state ────────────────────────────────────────────────────
const presets        = ref([])
const presetsLoading = ref(false)
const librarySearch  = ref('')
const addingPresetId = ref(null)  // tracks which preset is being added (spinner)

// ── Forms ────────────────────────────────────────────────────────────────────
const newSectionForm = ref({ name: '', section_type: 'room' })

const savePresetForm = ref({ name: '', description: '' })

const newItemForm = ref({
  name: '', description: '', requires_photo: true, requires_condition: true
})

const editItemForm = ref({
  id: null, name: '', description: '', requires_photo: true, requires_condition: true
})

// ── Computed ─────────────────────────────────────────────────────────────────
const roomSections = computed(() =>
  template.value?.sections?.filter(s => s.section_type === 'room') ?? []
)

const fixedSections = computed(() =>
  template.value?.sections?.filter(s => s.section_type === 'fixed') ?? []
)

const filteredPresets = computed(() => {
  const q = librarySearch.value.toLowerCase().trim()
  if (!q) return presets.value
  return presets.value.filter(p =>
    p.name.toLowerCase().includes(q) ||
    (p.description || '').toLowerCase().includes(q)
  )
})

// ── Template ─────────────────────────────────────────────────────────────────
async function fetchTemplate() {
  loading.value = true
  try {
    const res = await api.getTemplate(route.params.id)
    template.value = res.data
  } catch (err) {
    console.error(err)
    alert('Failed to load template')
    router.push('/settings/templates')
  } finally {
    loading.value = false
  }
}

async function updateTemplateName() {
  if (!template.value.name.trim()) return
  saving.value = true
  try {
    await api.updateTemplate(template.value.id, {
      name: template.value.name,
      description: template.value.description,
    })
  } catch (err) {
    console.error(err)
    alert('Failed to update template name')
  } finally {
    saving.value = false
  }
}

// ── Sections ─────────────────────────────────────────────────────────────────
function openAddSectionModal() {
  newSectionForm.value = { name: '', section_type: 'room' }
  showAddSectionModal.value = true
}

async function handleAddSection() {
  if (!newSectionForm.value.name.trim()) { alert('Section name is required'); return }
  try {
    const res = await api.addSection(template.value.id, newSectionForm.value)
    template.value.sections.push(res.data)
    showAddSectionModal.value = false
  } catch (err) {
    console.error(err)
    alert('Failed to add section')
  }
}

async function duplicateSection(section) {
  if (!confirm(`Duplicate "${section.name}"?`)) return
  try {
    const res = await api.duplicateSection(section.id)
    template.value.sections.push(res.data)
    fetchTemplate()
  } catch (err) {
    console.error(err)
    alert('Failed to duplicate section')
  }
}

async function deleteSection(section) {
  if (section.is_required) { alert('Cannot delete required sections'); return }
  if (!confirm(`Delete "${section.name}"? This will remove all items in this section.`)) return
  try {
    await api.deleteSection(section.id)
    template.value.sections = template.value.sections.filter(s => s.id !== section.id)
  } catch (err) {
    console.error(err)
    alert('Failed to delete section')
  }
}

async function moveSectionUp(section) {
  try { await api.reorderSection(section.id, 'up'); fetchTemplate() } catch (err) { console.error(err) }
}

async function moveSectionDown(section) {
  try { await api.reorderSection(section.id, 'down'); fetchTemplate() } catch (err) { console.error(err) }
}

// ── Section Library ───────────────────────────────────────────────────────────
async function openLibraryModal() {
  showLibraryModal.value = true
  presetsLoading.value = true
  try {
    const res = await api.getSectionPresets()
    presets.value = res.data
  } catch (err) {
    console.error(err)
    alert('Failed to load section library')
  } finally {
    presetsLoading.value = false
  }
}

async function addPresetToTemplate(preset) {
  addingPresetId.value = preset.id
  try {
    const res = await api.addPresetToTemplate(preset.id, template.value.id)
    template.value.sections.push(res.data)
    showLibraryModal.value = false
  } catch (err) {
    console.error(err)
    alert('Failed to add section from library')
  } finally {
    addingPresetId.value = null
  }
}

async function deletePreset(preset) {
  if (!confirm(`Remove "${preset.name}" from your library? This won't affect existing templates.`)) return
  try {
    await api.deleteSectionPreset(preset.id)
    presets.value = presets.value.filter(p => p.id !== preset.id)
  } catch (err) {
    console.error(err)
    alert('Failed to delete preset')
  }
}

// ── Save section as preset ────────────────────────────────────────────────────
function openSavePresetModal(section) {
  savePresetForm.value = { name: section.name, description: '' }
  showSavePresetModal.value = section
}

async function handleSaveAsPreset() {
  const section = showSavePresetModal.value
  if (!savePresetForm.value.name.trim()) { alert('Name is required'); return }
  try {
    await api.saveSectionAsPreset(section.id, {
      name:        savePresetForm.value.name.trim(),
      description: savePresetForm.value.description,
    })
    showSavePresetModal.value = null
    alert(`"${savePresetForm.value.name}" saved to your section library!`)
  } catch (err) {
    console.error(err)
    alert('Failed to save to library')
  }
}

// ── Items ─────────────────────────────────────────────────────────────────────
function openAddItemModal(sectionId) {
  newItemForm.value = { name: '', description: '', requires_photo: true, requires_condition: true }
  showAddItemModal.value = sectionId
}

async function handleAddItem() {
  if (!newItemForm.value.name.trim()) { alert('Item name is required'); return }
  try {
    const res = await api.addItem(showAddItemModal.value, newItemForm.value)
    const section = template.value.sections.find(s => s.id === showAddItemModal.value)
    if (section) {
      if (!section.items) section.items = []
      section.items.push(res.data)
    }
    showAddItemModal.value = null
  } catch (err) {
    console.error(err)
    alert('Failed to add item')
  }
}

function openEditItemModal(item) {
  editItemForm.value = { ...item }
  showEditItemModal.value = item
}

async function handleUpdateItem() {
  if (!editItemForm.value.name.trim()) { alert('Item name is required'); return }
  try {
    await api.updateItem(editItemForm.value.id, {
      name:               editItemForm.value.name,
      description:        editItemForm.value.description,
      requires_photo:     editItemForm.value.requires_photo,
      requires_condition: editItemForm.value.requires_condition,
    })
    Object.assign(showEditItemModal.value, editItemForm.value)
    showEditItemModal.value = null
  } catch (err) {
    console.error(err)
    alert('Failed to update item')
  }
}

async function duplicateItem(item, section) {
  try {
    const res = await api.duplicateItem(item.id)
    section.items.push(res.data)
  } catch (err) {
    console.error(err)
    alert('Failed to duplicate item')
  }
}

async function deleteItem(item, section) {
  if (!confirm(`Delete "${item.name}"?`)) return
  try {
    await api.deleteItem(item.id)
    section.items = section.items.filter(i => i.id !== item.id)
  } catch (err) {
    console.error(err)
    alert('Failed to delete item')
  }
}

async function moveItemUp(item) {
  try { await api.reorderItem(item.id, 'up'); fetchTemplate() } catch (err) { console.error(err) }
}

async function moveItemDown(item) {
  try { await api.reorderItem(item.id, 'down'); fetchTemplate() } catch (err) { console.error(err) }
}

onMounted(fetchTemplate)
</script>

<template>
  <div class="template-editor">

    <!-- ── Header ──────────────────────────────────────────────────────────── -->
    <div class="page-header">
      <div class="header-left">
        <button @click="router.push('/settings/templates')" class="btn-back">← Back</button>
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
      <div class="header-actions">
        <button @click="openLibraryModal" class="btn-library">
          📚 Section Library
        </button>
        <button @click="openAddSectionModal" class="btn-primary">
          ＋ Add Section
        </button>
      </div>
    </div>

    <!-- ── Loading ─────────────────────────────────────────────────────────── -->
    <div v-if="loading" class="loading">Loading template...</div>

    <!-- ── Editor ──────────────────────────────────────────────────────────── -->
    <div v-else class="editor-container">

      <!-- Fixed Sections -->
      <div class="sections-group">
        <h3 class="group-title">📄 Fixed Sections <span class="group-note">(Required)</span></h3>
        <p class="group-description">These sections appear on every inspection report and cannot be removed.</p>
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
        <div class="group-header-row">
          <div>
            <h3 class="group-title">🏠 Room Sections</h3>
            <p class="group-description">Customise these sections for different property types.</p>
          </div>
        </div>

        <div class="sections-list">
          <div v-for="(section, index) in roomSections" :key="section.id" class="section-card">

            <!-- Section header -->
            <div class="section-header">
              <span class="section-name">{{ section.name }}</span>
              <div class="section-actions">
                <button @click="moveSectionUp(section)"   :disabled="index === 0"                     class="btn-icon" title="Move Up">↑</button>
                <button @click="moveSectionDown(section)" :disabled="index === roomSections.length - 1" class="btn-icon" title="Move Down">↓</button>
                <button @click="openSavePresetModal(section)" class="btn-icon save-preset-btn" title="Save to Library">
                  💾
                </button>
                <button @click="duplicateSection(section)" class="btn-icon" title="Duplicate">⧉</button>
                <button @click="deleteSection(section)"    class="btn-icon danger" title="Delete">✕</button>
              </div>
            </div>

            <!-- Item count summary -->
            <div class="item-count-bar">
              <span class="item-count-label">{{ (section.items || []).length }} item{{ (section.items || []).length !== 1 ? 's' : '' }}</span>
            </div>

            <!-- Items -->
            <div class="items-list">
              <div v-for="(item, itemIndex) in section.items" :key="item.id" class="item-row">
                <div class="item-info">
                  <span class="item-name">{{ item.name }}</span>
                  <div class="item-meta">
                    <span v-if="item.requires_photo"     class="meta-badge photo">📷 Photo</span>
                    <span v-if="item.requires_condition" class="meta-badge cond">✓ Condition</span>
                  </div>
                </div>
                <div class="item-actions">
                  <button @click="moveItemUp(item)"              :disabled="itemIndex === 0"                    class="btn-icon-sm" title="Up">↑</button>
                  <button @click="moveItemDown(item)"            :disabled="itemIndex === (section.items.length - 1)" class="btn-icon-sm" title="Down">↓</button>
                  <button @click="openEditItemModal(item)"                                                       class="btn-icon-sm" title="Edit">✎</button>
                  <button @click="duplicateItem(item, section)"                                                  class="btn-icon-sm" title="Duplicate">⧉</button>
                  <button @click="deleteItem(item, section)"                                                     class="btn-icon-sm danger" title="Delete">✕</button>
                </div>
              </div>

              <button @click="openAddItemModal(section.id)" class="btn-add-item">
                ＋ Add Item
              </button>
            </div>
          </div>

          <!-- Empty state -->
          <div v-if="roomSections.length === 0" class="empty-sections">
            <p>No room sections yet.</p>
            <div class="empty-actions">
              <button @click="openAddSectionModal" class="btn-primary-sm">＋ Add blank section</button>
              <span class="or-divider">or</span>
              <button @click="openLibraryModal" class="btn-library-sm">📚 Add from library</button>
            </div>
          </div>
        </div>
      </div>

    </div><!-- /editor-container -->


    <!-- ═══════════════════════════════════════════════════════════════════════
         MODALS
    ═══════════════════════════════════════════════════════════════════════════ -->

    <!-- ── Add blank section ─────────────────────────────────────────────── -->
    <div v-if="showAddSectionModal" class="modal-overlay" @click.self="showAddSectionModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>Add New Section</h2>
          <button @click="showAddSectionModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Section Name *</label>
            <input v-model="newSectionForm.name" type="text" placeholder="e.g. Master Bedroom" autofocus />
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showAddSectionModal = false" class="btn-secondary">Cancel</button>
          <button @click="handleAddSection" class="btn-primary">Add Section</button>
        </div>
      </div>
    </div>

    <!-- ── Section Library browser ──────────────────────────────────────── -->
    <div v-if="showLibraryModal" class="modal-overlay" @click.self="showLibraryModal = false">
      <div class="modal modal-wide">
        <div class="modal-header">
          <div class="modal-title-group">
            <h2>📚 Section Library</h2>
            <p class="modal-subtitle">Saved sections with all their items — click to add to this template.</p>
          </div>
          <button @click="showLibraryModal = false" class="btn-close">✕</button>
        </div>

        <div class="modal-body">
          <!-- Search -->
          <div class="library-search-wrap">
            <input
              v-model="librarySearch"
              type="text"
              placeholder="Search sections…"
              class="library-search"
            />
          </div>

          <!-- Loading -->
          <div v-if="presetsLoading" class="library-loading">Loading library…</div>

          <!-- Empty -->
          <div v-else-if="filteredPresets.length === 0" class="library-empty">
            <div class="library-empty-icon">📭</div>
            <p v-if="librarySearch">No sections matching "{{ librarySearch }}"</p>
            <p v-else>Your library is empty. Save a section using the 💾 button on any room section.</p>
          </div>

          <!-- Preset grid -->
          <div v-else class="preset-grid">
            <div
              v-for="preset in filteredPresets"
              :key="preset.id"
              class="preset-card"
            >
              <div class="preset-card-body">
                <div class="preset-name">{{ preset.name }}</div>
                <div class="preset-meta">{{ preset.item_count }} item{{ preset.item_count !== 1 ? 's' : '' }}</div>
                <div v-if="preset.description" class="preset-desc">{{ preset.description }}</div>
                <ul v-if="preset.items.length" class="preset-items-preview">
                  <li v-for="(item, i) in preset.items.slice(0, 5)" :key="i">{{ item.name }}</li>
                  <li v-if="preset.items.length > 5" class="preview-more">+{{ preset.items.length - 5 }} more…</li>
                </ul>
              </div>
              <div class="preset-card-footer">
                <button
                  @click="addPresetToTemplate(preset)"
                  class="btn-add-preset"
                  :disabled="addingPresetId === preset.id"
                >
                  <span v-if="addingPresetId === preset.id">Adding…</span>
                  <span v-else>＋ Add to Template</span>
                </button>
                <button @click="deletePreset(preset)" class="btn-delete-preset" title="Remove from library">✕</button>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button @click="showLibraryModal = false" class="btn-secondary">Close</button>
        </div>
      </div>
    </div>

    <!-- ── Save section as preset ────────────────────────────────────────── -->
    <div v-if="showSavePresetModal" class="modal-overlay" @click.self="showSavePresetModal = null">
      <div class="modal">
        <div class="modal-header">
          <h2>💾 Save to Library</h2>
          <button @click="showSavePresetModal = null" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <p class="save-preset-info">
            Save <strong>{{ showSavePresetModal.name }}</strong> and its
            {{ (showSavePresetModal.items || []).length }} item(s) as a reusable preset
            you can add to any template.
          </p>
          <div class="form-group">
            <label>Preset Name *</label>
            <input v-model="savePresetForm.name" type="text" placeholder="e.g. Standard Bedroom" autofocus />
          </div>
          <div class="form-group">
            <label>Notes <span class="optional">(optional)</span></label>
            <input v-model="savePresetForm.description" type="text" placeholder="e.g. Use for double rooms with en-suite" />
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showSavePresetModal = null" class="btn-secondary">Cancel</button>
          <button @click="handleSaveAsPreset" class="btn-primary">Save to Library</button>
        </div>
      </div>
    </div>

    <!-- ── Add Item ───────────────────────────────────────────────────────── -->
    <div v-if="showAddItemModal" class="modal-overlay" @click.self="showAddItemModal = null">
      <div class="modal">
        <div class="modal-header">
          <h2>Add Item</h2>
          <button @click="showAddItemModal = null" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Item Name *</label>
            <input v-model="newItemForm.name" type="text" placeholder="e.g. Door, Frame, Threshold & Furniture" autofocus />
          </div>
          <div class="form-group">
            <label>Description</label>
            <textarea v-model="newItemForm.description" rows="2" placeholder="Optional description"></textarea>
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
        </div>
        <div class="modal-footer">
          <button @click="showAddItemModal = null" class="btn-secondary">Cancel</button>
          <button @click="handleAddItem" class="btn-primary">Add Item</button>
        </div>
      </div>
    </div>

    <!-- ── Edit Item ──────────────────────────────────────────────────────── -->
    <div v-if="showEditItemModal" class="modal-overlay" @click.self="showEditItemModal = null">
      <div class="modal">
        <div class="modal-header">
          <h2>Edit Item</h2>
          <button @click="showEditItemModal = null" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Item Name *</label>
            <input v-model="editItemForm.name" type="text" />
          </div>
          <div class="form-group">
            <label>Description</label>
            <textarea v-model="editItemForm.description" rows="2"></textarea>
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
        </div>
        <div class="modal-footer">
          <button @click="showEditItemModal = null" class="btn-secondary">Cancel</button>
          <button @click="handleUpdateItem" class="btn-primary">Update Item</button>
        </div>
      </div>
    </div>

  </div><!-- /template-editor -->
</template>

<style scoped>
.template-editor { max-width: 1400px; }

/* ── Header ─────────────────────────────────────────────────────────────── */
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
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.btn-back {
  padding: 8px 14px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-back:hover { background: #f8fafc; }

.template-name-input {
  font-size: 26px;
  font-weight: 600;
  color: #1e293b;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 4px 8px;
  transition: border-color 0.2s;
}
.template-name-input:hover { border-bottom-color: #e5e7eb; }
.template-name-input:focus { outline: none; border-bottom-color: #6366f1; }

.subtitle {
  color: #64748b;
  font-size: 12px;
  text-transform: uppercase;
  font-weight: 700;
  letter-spacing: 0.6px;
  padding-left: 8px;
}

.btn-primary {
  padding: 10px 20px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover { background: #4f46e5; }

.btn-library {
  padding: 10px 20px;
  background: white;
  color: #374151;
  border: 1.5px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-library:hover {
  background: #f8fafc;
  border-color: #6366f1;
  color: #6366f1;
}

/* ── Loading ─────────────────────────────────────────────────────────────── */
.loading {
  text-align: center;
  padding: 60px 20px;
  color: #94a3b8;
  font-size: 15px;
}

/* ── Editor layout ───────────────────────────────────────────────────────── */
.editor-container {
  display: flex;
  flex-direction: column;
  gap: 40px;
}

.sections-group {
  background: white;
  padding: 28px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
}

.group-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 4px;
}

.group-title {
  font-size: 17px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}
.group-note {
  font-size: 13px;
  font-weight: 500;
  color: #94a3b8;
}
.group-description {
  color: #64748b;
  font-size: 13px;
  margin-bottom: 20px;
}

/* ── Section cards ───────────────────────────────────────────────────────── */
.sections-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-card {
  background: #f8fafc;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px 18px;
  transition: border-color 0.15s;
}
.section-card:hover { border-color: #c7d2fe; }
.section-card.fixed { background: #fffbeb; border-color: #fcd34d; }

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.section-name {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.section-badge {
  padding: 3px 10px;
  background: #fbbf24;
  color: #78350f;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
}

.section-actions {
  display: flex;
  gap: 6px;
}

.item-count-bar {
  margin-bottom: 10px;
}
.item-count-label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ── Icon buttons ────────────────────────────────────────────────────────── */
.btn-icon {
  width: 30px;
  height: 30px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  color: #374151;
}
.btn-icon:hover:not(:disabled) { background: #f1f5f9; border-color: #c7d2fe; color: #6366f1; }
.btn-icon:disabled { opacity: 0.35; cursor: not-allowed; }
.btn-icon.danger:hover { background: #fee2e2; border-color: #fecaca; color: #dc2626; }
.save-preset-btn:hover { background: #ecfdf5 !important; border-color: #6ee7b7 !important; color: #059669 !important; }

/* ── Items ───────────────────────────────────────────────────────────────── */
.items-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: white;
  border-radius: 7px;
  border: 1px solid #e9ecef;
  transition: border-color 0.15s;
}
.item-row:hover { border-color: #c7d2fe; }

.item-info { flex: 1; }
.item-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  display: block;
  margin-bottom: 3px;
}

.item-meta { display: flex; gap: 6px; }
.meta-badge {
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
}
.meta-badge.photo { background: #e0e7ff; color: #4338ca; }
.meta-badge.cond  { background: #dcfce7; color: #166534; }

.item-actions { display: flex; gap: 4px; }

.btn-icon-sm {
  width: 26px;
  height: 26px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #374151;
  transition: all 0.15s;
}
.btn-icon-sm:hover:not(:disabled) { background: #f1f5f9; color: #6366f1; }
.btn-icon-sm:disabled { opacity: 0.35; cursor: not-allowed; }
.btn-icon-sm.danger:hover { background: #fee2e2; color: #dc2626; }

.btn-add-item {
  width: 100%;
  padding: 9px;
  background: white;
  border: 1.5px dashed #cbd5e1;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  margin-top: 6px;
  transition: all 0.15s;
}
.btn-add-item:hover { border-color: #6366f1; color: #6366f1; background: #f5f3ff; }

/* ── Empty state ─────────────────────────────────────────────────────────── */
.empty-sections {
  text-align: center;
  padding: 48px 20px;
  border: 2px dashed #e5e7eb;
  border-radius: 10px;
  color: #94a3b8;
}
.empty-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 16px;
}
.btn-primary-sm {
  padding: 8px 16px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.btn-library-sm {
  padding: 8px 16px;
  background: white;
  color: #374151;
  border: 1.5px solid #d1d5db;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.or-divider { font-size: 12px; color: #94a3b8; }

/* ── Modals ──────────────────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
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
  max-width: 520px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}

.modal-wide { max-width: 820px; }

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}
.modal-header h2 { font-size: 18px; font-weight: 700; color: #1e293b; }
.modal-title-group { display: flex; flex-direction: column; gap: 3px; }
.modal-subtitle { font-size: 13px; color: #64748b; }

.btn-close {
  background: none;
  border: none;
  font-size: 18px;
  color: #94a3b8;
  cursor: pointer;
  padding: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  flex-shrink: 0;
}
.btn-close:hover { background: #f1f5f9; color: #374151; }

.modal-body {
  padding: 20px 24px;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid #e5e7eb;
  background: #f8fafc;
  flex-shrink: 0;
}

.form-group { margin-bottom: 18px; }
.form-group label {
  display: block;
  margin-bottom: 6px;
  font-weight: 600;
  color: #475569;
  font-size: 13px;
}
.form-group input,
.form-group textarea {
  width: 100%;
  padding: 9px 13px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 14px;
  font-family: inherit;
  box-sizing: border-box;
  transition: border-color 0.15s;
}
.form-group input:focus,
.form-group textarea:focus { outline: none; border-color: #6366f1; }
.form-group textarea { resize: vertical; }

.form-group-inline { display: flex; gap: 20px; margin-bottom: 18px; }
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  color: #475569;
  cursor: pointer;
}
.checkbox-label input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }

.optional { font-weight: 400; color: #94a3b8; }

.btn-secondary {
  padding: 9px 18px;
  background: white;
  color: #64748b;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-secondary:hover { background: #f1f5f9; }

/* ── Library modal ───────────────────────────────────────────────────────── */
.library-search-wrap { margin-bottom: 16px; }
.library-search {
  width: 100%;
  padding: 9px 13px;
  border: 1.5px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  box-sizing: border-box;
  transition: border-color 0.15s;
}
.library-search:focus { outline: none; border-color: #6366f1; }

.library-loading,
.library-empty {
  text-align: center;
  padding: 40px 20px;
  color: #94a3b8;
}
.library-empty-icon { font-size: 40px; margin-bottom: 10px; }

.preset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.preset-card {
  background: #f8fafc;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.preset-card:hover { border-color: #a5b4fc; box-shadow: 0 2px 8px rgba(99,102,241,0.08); }

.preset-card-body { padding: 14px 16px; flex: 1; }
.preset-name { font-size: 14px; font-weight: 700; color: #1e293b; margin-bottom: 3px; }
.preset-meta { font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 6px; }
.preset-desc { font-size: 12px; color: #64748b; margin-bottom: 8px; }

.preset-items-preview {
  list-style: none;
  padding: 0;
  margin: 0;
}
.preset-items-preview li {
  font-size: 11px;
  color: #475569;
  padding: 2px 0;
  border-bottom: 1px solid #f1f5f9;
}
.preview-more { color: #94a3b8; font-style: italic; border-bottom: none !important; }

.preset-card-footer {
  display: flex;
  gap: 6px;
  padding: 10px 12px;
  border-top: 1px solid #e9ecef;
  background: white;
}

.btn-add-preset {
  flex: 1;
  padding: 8px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-add-preset:hover:not(:disabled) { background: #4f46e5; }
.btn-add-preset:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-delete-preset {
  padding: 8px 10px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  font-size: 12px;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-delete-preset:hover { background: #fee2e2; color: #dc2626; border-color: #fecaca; }

/* ── Save preset modal ───────────────────────────────────────────────────── */
.save-preset-info {
  font-size: 13px;
  color: #475569;
  margin-bottom: 18px;
  padding: 10px 14px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 7px;
  line-height: 1.5;
}
</style>
