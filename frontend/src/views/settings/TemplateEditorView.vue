<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../services/api'

const route  = useRoute()
const router = useRouter()

// Auto-focus directive for inline rename input
const vFocus = { mounted: (el) => el.focus() }

const template = ref(null)
const loading  = ref(true)
const saving   = ref(false)

// ── Modal state ───────────────────────────────────────────────────────────────
const showAddSectionModal  = ref(false)  // step 1: empty or from preset?
const showPresetPicker     = ref(false)  // step 2: pick + rename presets
const showSavePresetModal  = ref(null)   // section object being saved
const showAddItemModal     = ref(null)   // section id
const showEditItemModal    = ref(null)   // item object

// ── Inline section rename ─────────────────────────────────────────────────────
// renamingSection: { id, name } — the section currently being renamed inline
const renamingSection = ref(null)

function startRenameSection(section) {
  renamingSection.value = { id: section.id, name: section.name }
}

async function commitRenameSection(section) {
  if (!renamingSection.value || renamingSection.value.id !== section.id) return
  const newName = renamingSection.value.name.trim()
  if (!newName) { renamingSection.value = null; return }
  if (newName === section.name) { renamingSection.value = null; return }
  try {
    await api.updateSection(section.id, { name: newName })
    section.name = newName
  } catch (err) {
    console.error(err)
    alert('Failed to rename section')
  } finally {
    renamingSection.value = null
  }
}

function cancelRenameSection() {
  renamingSection.value = null
}

// ── Preset picker state ───────────────────────────────────────────────────────
const presets         = ref([])
const presetsLoading  = ref(false)
const presetSearch    = ref('')
// selectedPresets: [{ preset, customName }]
const selectedPresets = ref([])
const addingFromPreset = ref(false)

// ── Forms ─────────────────────────────────────────────────────────────────────
const newSectionName = ref('')

const savePresetForm = ref({ name: '', description: '' })

const newItemForm = ref({
  name: '', description: '', requires_photo: true, requires_condition: true
})
const editItemForm = ref({
  id: null, name: '', description: '', requires_photo: true, requires_condition: true
})

// ── Computed ──────────────────────────────────────────────────────────────────
const roomSections = computed(() =>
  template.value?.sections?.filter(s => s.section_type === 'room') ?? []
)
const fixedSections = computed(() =>
  template.value?.sections?.filter(s => s.section_type === 'fixed') ?? []
)

const filteredPresets = computed(() => {
  const q = presetSearch.value.toLowerCase().trim()
  if (!q) return presets.value
  return presets.value.filter(p => p.name.toLowerCase().includes(q))
})

// ── Template ──────────────────────────────────────────────────────────────────
async function fetchTemplate() {
  loading.value = true
  try {
    const res = await api.getTemplate(route.params.id)
    template.value = res.data
  } catch (err) {
    console.error(err)
    alert('Failed to load template')
    localStorage.setItem('settings_tab', 'templates'); router.push('/settings')
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

// ── Add Section — step 1 ──────────────────────────────────────────────────────
function openAddSectionModal() {
  newSectionName.value = ''
  showAddSectionModal.value = true
}

async function handleAddBlankSection() {
  if (!newSectionName.value.trim()) { alert('Section name is required'); return }
  try {
    const res = await api.addSection(template.value.id, {
      name: newSectionName.value.trim(),
      section_type: 'room',
    })
    template.value.sections.push(res.data)
    showAddSectionModal.value = false
  } catch (err) {
    console.error(err)
    alert('Failed to add section')
  }
}

// ── Add Section — step 2: preset picker ──────────────────────────────────────
async function openPresetPicker() {
  showAddSectionModal.value = false
  showPresetPicker.value = true
  selectedPresets.value = []
  presetSearch.value = ''
  presetsLoading.value = true
  try {
    const res = await api.getSectionPresets()
    presets.value = res.data
  } catch (err) {
    console.error(err)
    alert('Failed to load presets')
  } finally {
    presetsLoading.value = false
  }
}

function isPresetSelected(preset) {
  return selectedPresets.value.some(s => s.preset.id === preset.id)
}

function togglePreset(preset) {
  const idx = selectedPresets.value.findIndex(s => s.preset.id === preset.id)
  if (idx === -1) {
    selectedPresets.value.push({ preset, customName: preset.name })
  } else {
    selectedPresets.value.splice(idx, 1)
  }
}

async function handleAddFromPresets() {
  if (selectedPresets.value.length === 0) return
  addingFromPreset.value = true
  try {
    for (const { preset, customName } of selectedPresets.value) {
      const res = await api.addPresetToTemplate(preset.id, template.value.id, {
        name: customName.trim() || preset.name,
      })
      template.value.sections.push(res.data)
    }
    showPresetPicker.value = false
  } catch (err) {
    console.error(err)
    alert('Failed to add sections from presets')
  } finally {
    addingFromPreset.value = false
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
    alert(`"${savePresetForm.value.name}" saved to presets!`)
  } catch (err) {
    console.error(err)
    alert('Failed to save preset')
  }
}

// ── Section actions ───────────────────────────────────────────────────────────
async function duplicateSection(section) {
  if (!confirm(`Duplicate "${section.name}"?`)) return
  try {
    const res = await api.duplicateSection(section.id)
    template.value.sections.push(res.data)
    fetchTemplate()
  } catch (err) { console.error(err); alert('Failed to duplicate section') }
}

async function deleteSection(section) {
  if (section.is_required) { alert('Cannot delete required sections'); return }
  if (!confirm(`Delete "${section.name}"? This will remove all its items.`)) return
  try {
    await api.deleteSection(section.id)
    template.value.sections = template.value.sections.filter(s => s.id !== section.id)
  } catch (err) { console.error(err); alert('Failed to delete section') }
}

async function moveSectionUp(section) {
  try { await api.reorderSection(section.id, 'up'); fetchTemplate() } catch (err) { console.error(err) }
}
async function moveSectionDown(section) {
  try { await api.reorderSection(section.id, 'down'); fetchTemplate() } catch (err) { console.error(err) }
}

// ── Item actions ──────────────────────────────────────────────────────────────
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
  } catch (err) { console.error(err); alert('Failed to add item') }
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
  } catch (err) { console.error(err); alert('Failed to update item') }
}

async function duplicateItem(item, section) {
  try {
    const res = await api.duplicateItem(item.id)
    section.items.push(res.data)
  } catch (err) { console.error(err); alert('Failed to duplicate item') }
}

async function deleteItem(item, section) {
  if (!confirm(`Delete "${item.name}"?`)) return
  try {
    await api.deleteItem(item.id)
    section.items = section.items.filter(i => i.id !== item.id)
  } catch (err) { console.error(err); alert('Failed to delete item') }
}

async function moveItemUp(item) {
  try { await api.reorderItem(item.id, 'up'); fetchTemplate() } catch (err) { console.error(err) }
}
async function moveItemDown(item) {
  try { await api.reorderItem(item.id, 'down'); fetchTemplate() } catch (err) { console.error(err) }
}

// Drag-to-reorder state
const dragSectionIdx = ref(null)
const dragItemKey    = ref(null)

function onSectionDragStart(e, index) {
  dragSectionIdx.value = index
  e.dataTransfer.effectAllowed = 'move'
}
function onSectionDragOver(e, index) {
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
}
async function onSectionDrop(e, toIndex) {
  e.preventDefault()
  const fromIndex = dragSectionIdx.value
  if (fromIndex === null || fromIndex === toIndex) { dragSectionIdx.value = null; return }
  const section = roomSections.value[fromIndex]
  const steps = toIndex - fromIndex
  const dir = steps > 0 ? 'down' : 'up'
  const count = Math.abs(steps)
  for (let i = 0; i < count; i++) {
    await api.reorderSection(section.id, dir)
  }
  dragSectionIdx.value = null
  fetchTemplate()
}
function onSectionDragEnd() { dragSectionIdx.value = null }

function onItemDragStart(e, sectionId, itemIdx) {
  dragItemKey.value = `${sectionId}:${itemIdx}`
  e.dataTransfer.effectAllowed = 'move'
}
async function onItemDrop(e, section, toIdx) {
  e.preventDefault()
  if (!dragItemKey.value) return
  const [sid, fromIdxStr] = dragItemKey.value.split(':')
  const fromIdx = parseInt(fromIdxStr)
  if (String(section.id) !== sid || fromIdx === toIdx) { dragItemKey.value = null; return }
  const item = section.items[fromIdx]
  const steps = toIdx - fromIdx
  const dir = steps > 0 ? 'down' : 'up'
  const count = Math.abs(steps)
  for (let i = 0; i < count; i++) {
    await api.reorderItem(item.id, dir)
  }
  dragItemKey.value = null
  fetchTemplate()
}
function onItemDragEnd() { dragItemKey.value = null }

onMounted(fetchTemplate)
</script>

<template>
  <div class="template-editor">

    <!-- ── Header ──────────────────────────────────────────────────────────── -->
    <div class="page-header">
      <div class="header-left">
        <button @click="localStorage.setItem('settings_tab', 'templates'); router.push('/settings')" class="btn-back">← Back</button>
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
      <button @click="openAddSectionModal" class="btn-primary">＋ Add Section</button>
    </div>

    <div v-if="loading" class="loading">Loading template…</div>

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
        <h3 class="group-title">🏠 Room Sections</h3>
        <p class="group-description">Customise these sections for different property types.</p>

        <div class="sections-list">
          <div
            v-for="(section, index) in roomSections"
            :key="section.id"
            class="section-card"
            :class="{ 'drag-over': dragSectionIdx !== null && dragSectionIdx !== index }"
            @dragover="onSectionDragOver($event, index)"
            @drop="onSectionDrop($event, index)"
          >

            <div class="section-header">
              <!-- Inline rename: click the name to edit, blur/enter to save, Escape to cancel -->
              <template v-if="renamingSection && renamingSection.id === section.id">
                <input
                  class="section-name-input"
                  v-model="renamingSection.name"
                  @blur="commitRenameSection(section)"
                  @keyup.enter="commitRenameSection(section)"
                  @keyup.escape="cancelRenameSection"
                  v-focus
                />
              </template>
              <span
                v-else
                class="section-name section-name-editable"
                @click="startRenameSection(section)"
                title="Click to rename"
              >{{ section.name }} ✎</span>
              <div class="section-actions">
                <span
                  class="drag-handle"
                  draggable="true"
                  @dragstart="onSectionDragStart($event, index)"
                  @dragend="onSectionDragEnd"
                  title="Drag to reorder"
                >::</span>
                <button @click="openSavePresetModal(section)" class="btn-icon preset-btn" title="Save as Preset">💾</button>
                <button @click="duplicateSection(section)" class="btn-icon" title="Duplicate">⧉</button>
                <button @click="deleteSection(section)"   class="btn-icon danger" title="Delete">✕</button>
              </div>
            </div>

            <div class="item-count-label">{{ (section.items || []).length }} item{{ (section.items || []).length !== 1 ? 's' : '' }}</div>

            <div class="items-list">
              <div
                v-for="(item, itemIndex) in section.items"
                :key="item.id"
                class="item-row"
                @dragover.prevent
                @drop="onItemDrop($event, section, itemIndex)"
              >
                <div class="item-info">
                  <span class="item-name">{{ item.name }}</span>
                  <div class="item-meta">
                    <span v-if="item.requires_photo"     class="meta-badge photo">📷 Photo</span>
                    <span v-if="item.requires_condition" class="meta-badge cond">✓ Condition</span>
                  </div>
                </div>
                <div class="item-actions">
                  <span
                    class="drag-handle drag-handle-sm"
                    draggable="true"
                    @dragstart="onItemDragStart($event, section.id, itemIndex)"
                    @dragend="onItemDragEnd"
                    title="Drag to reorder"
                  >::</span>
                  <button @click="openEditItemModal(item)"                                                        class="btn-icon-sm" title="Edit">✎</button>
                  <button @click="duplicateItem(item, section)"                                                   class="btn-icon-sm" title="Duplicate">⧉</button>
                  <button @click="deleteItem(item, section)"                                                      class="btn-icon-sm danger" title="Delete">✕</button>
                </div>
              </div>
              <button @click="openAddItemModal(section.id)" class="btn-add-item">＋ Add Item</button>
            </div>
          </div>

          <div v-if="roomSections.length === 0" class="empty-sections">
            <p>No room sections yet.</p>
            <button @click="openAddSectionModal" class="btn-primary" style="margin-top:12px">＋ Add Section</button>
          </div>
        </div>
      </div>

    </div>


    <!-- ═══════════════════════════════════════════════════════════════════════
         MODAL: Add Section — choose Empty or From Preset
    ═══════════════════════════════════════════════════════════════════════════ -->
    <div v-if="showAddSectionModal" class="modal-overlay" @click.self="showAddSectionModal = false">
      <div class="modal modal-narrow">
        <div class="modal-header">
          <h2>Add Section</h2>
          <button @click="showAddSectionModal = false" class="btn-close">✕</button>
        </div>

        <div class="modal-body">
          <!-- Empty section -->
          <div class="add-section-option" @click="() => {}">
            <div class="option-label">Empty section</div>
            <div class="option-row">
              <input
                v-model="newSectionName"
                type="text"
                placeholder="e.g. Balcony / Terrace"
                class="option-input"
                @keyup.enter="handleAddBlankSection"
              />
              <button @click="handleAddBlankSection" class="btn-primary btn-sm">Add</button>
            </div>
          </div>

          <div class="option-divider">or</div>

          <!-- From preset -->
          <div class="add-section-option preset-option" @click="openPresetPicker">
            <div class="option-label">From a saved preset</div>
            <div class="option-hint">Choose one or more saved rooms to add with items pre-filled</div>
            <button class="btn-library" style="margin-top:10px" @click.stop="openPresetPicker">
              Browse Presets →
            </button>
          </div>
        </div>
      </div>
    </div>


    <!-- ═══════════════════════════════════════════════════════════════════════
         MODAL: Preset Picker — multi-select + rename
    ═══════════════════════════════════════════════════════════════════════════ -->
    <div v-if="showPresetPicker" class="modal-overlay" @click.self="showPresetPicker = false">
      <div class="modal modal-wide">
        <div class="modal-header">
          <div>
            <h2>Add from Presets</h2>
            <p class="modal-subtitle">Select one or more saved rooms to add to this template.</p>
          </div>
          <button @click="showPresetPicker = false" class="btn-close">✕</button>
        </div>

        <div class="modal-body">

          <!-- Search -->
          <input
            v-model="presetSearch"
            type="text"
            placeholder="Search presets…"
            class="preset-search"
          />

          <!-- Loading -->
          <div v-if="presetsLoading" class="picker-empty">Loading presets…</div>

          <!-- No presets at all -->
          <div v-else-if="presets.length === 0" class="picker-empty">
            <div style="font-size:36px;margin-bottom:8px">📭</div>
            <p>No presets saved yet.</p>
            <p class="picker-empty-hint">Use the 💾 button on any room section to save it as a preset.</p>
          </div>

          <!-- No search match -->
          <div v-else-if="filteredPresets.length === 0" class="picker-empty">
            No presets matching "{{ presetSearch }}"
          </div>

          <!-- Preset list -->
          <div v-else class="picker-list">
            <div
              v-for="preset in filteredPresets"
              :key="preset.id"
              class="picker-row"
              :class="{ selected: isPresetSelected(preset) }"
              @click="togglePreset(preset)"
            >
              <!-- Checkbox -->
              <div class="picker-check">
                <div class="check-box" :class="{ checked: isPresetSelected(preset) }">
                  <span v-if="isPresetSelected(preset)">✓</span>
                </div>
              </div>

              <!-- Preset info -->
              <div class="picker-info">
                <div class="picker-name">{{ preset.name }}</div>
                <div class="picker-meta">{{ preset.item_count }} item{{ preset.item_count !== 1 ? 's' : '' }}
                  <span v-if="preset.description" class="picker-desc"> · {{ preset.description }}</span>
                </div>
                <div class="picker-items-preview">
                  <span v-for="(item, i) in (preset.items || []).slice(0, 4)" :key="i" class="preview-chip">
                    {{ item.name }}
                  </span>
                  <span v-if="(preset.items || []).length > 4" class="preview-chip more">
                    +{{ preset.items.length - 4 }} more
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- Rename selected presets -->
          <div v-if="selectedPresets.length > 0" class="rename-panel">
            <div class="rename-panel-title">
              {{ selectedPresets.length }} section{{ selectedPresets.length !== 1 ? 's' : '' }} selected — rename if needed:
            </div>
            <div
              v-for="(sel, i) in selectedPresets"
              :key="sel.preset.id"
              class="rename-row"
            >
              <span class="rename-original">{{ sel.preset.name }}</span>
              <span class="rename-arrow">→</span>
              <input
                v-model="selectedPresets[i].customName"
                type="text"
                class="rename-input"
                :placeholder="sel.preset.name"
              />
            </div>
          </div>

        </div>

        <div class="modal-footer">
          <button @click="showPresetPicker = false" class="btn-secondary">Cancel</button>
          <button
            @click="handleAddFromPresets"
            class="btn-primary"
            :disabled="selectedPresets.length === 0 || addingFromPreset"
          >
            <span v-if="addingFromPreset">Adding…</span>
            <span v-else>Add {{ selectedPresets.length > 0 ? selectedPresets.length : '' }} Section{{ selectedPresets.length !== 1 ? 's' : '' }}</span>
          </button>
        </div>
      </div>
    </div>


    <!-- ═══════════════════════════════════════════════════════════════════════
         MODAL: Save section as preset
    ═══════════════════════════════════════════════════════════════════════════ -->
    <div v-if="showSavePresetModal" class="modal-overlay" @click.self="showSavePresetModal = null">
      <div class="modal modal-narrow">
        <div class="modal-header">
          <h2>💾 Save as Preset</h2>
          <button @click="showSavePresetModal = null" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <p class="save-info">
            Save <strong>{{ showSavePresetModal.name }}</strong> and its
            {{ (showSavePresetModal.items || []).length }} item(s) as a reusable preset.
          </p>
          <div class="form-group">
            <label>Preset name *</label>
            <input v-model="savePresetForm.name" type="text" placeholder="e.g. Standard Bedroom" autofocus />
          </div>
          <div class="form-group">
            <label>Notes <span class="optional">(optional)</span></label>
            <input v-model="savePresetForm.description" type="text" placeholder="e.g. Double room with en-suite" />
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showSavePresetModal = null" class="btn-secondary">Cancel</button>
          <button @click="handleSaveAsPreset" class="btn-primary">Save Preset</button>
        </div>
      </div>
    </div>


    <!-- ═══════════════════════════════════════════════════════════════════════
         MODAL: Add Item
    ═══════════════════════════════════════════════════════════════════════════ -->
    <div v-if="showAddItemModal" class="modal-overlay" @click.self="showAddItemModal = null">
      <div class="modal modal-narrow">
        <div class="modal-header">
          <h2>Add Item</h2>
          <button @click="showAddItemModal = null" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Item name *</label>
            <input v-model="newItemForm.name" type="text" placeholder="e.g. Door, Frame, Threshold & Furniture" autofocus />
          </div>
          <div class="form-group">
            <label>Description</label>
            <textarea v-model="newItemForm.description" rows="2" placeholder="Optional"></textarea>
          </div>
          <div class="form-group-inline">
            <label class="checkbox-label"><input type="checkbox" v-model="newItemForm.requires_photo" /><span>Requires Photo</span></label>
            <label class="checkbox-label"><input type="checkbox" v-model="newItemForm.requires_condition" /><span>Requires Condition</span></label>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showAddItemModal = null" class="btn-secondary">Cancel</button>
          <button @click="handleAddItem" class="btn-primary">Add Item</button>
        </div>
      </div>
    </div>


    <!-- ═══════════════════════════════════════════════════════════════════════
         MODAL: Edit Item
    ═══════════════════════════════════════════════════════════════════════════ -->
    <div v-if="showEditItemModal" class="modal-overlay" @click.self="showEditItemModal = null">
      <div class="modal modal-narrow">
        <div class="modal-header">
          <h2>Edit Item</h2>
          <button @click="showEditItemModal = null" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Item name *</label>
            <input v-model="editItemForm.name" type="text" />
          </div>
          <div class="form-group">
            <label>Description</label>
            <textarea v-model="editItemForm.description" rows="2"></textarea>
          </div>
          <div class="form-group-inline">
            <label class="checkbox-label"><input type="checkbox" v-model="editItemForm.requires_photo" /><span>Requires Photo</span></label>
            <label class="checkbox-label"><input type="checkbox" v-model="editItemForm.requires_condition" /><span>Requires Condition</span></label>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showEditItemModal = null" class="btn-secondary">Cancel</button>
          <button @click="handleUpdateItem" class="btn-primary">Update Item</button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.template-editor { max-width: 1400px; }

/* ── Header ──────────────────────────────────────────────────────────────── */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
}
.header-left { display: flex; align-items: center; gap: 20px; }

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

/* ── Buttons ─────────────────────────────────────────────────────────────── */
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
.btn-primary:hover:not(:disabled) { background: #4f46e5; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-sm { padding: 8px 14px; font-size: 13px; }

.btn-library {
  padding: 9px 18px;
  background: white;
  color: #374151;
  border: 1.5px solid #d1d5db;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  display: inline-block;
}
.btn-library:hover { background: #f8fafc; border-color: #6366f1; color: #6366f1; }

.btn-secondary {
  padding: 9px 18px;
  background: white;
  color: #64748b;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-secondary:hover { background: #f1f5f9; }

/* ── Loading / empty ─────────────────────────────────────────────────────── */
.loading { text-align: center; padding: 60px 20px; color: #94a3b8; font-size: 15px; }

.empty-sections {
  text-align: center;
  padding: 48px 20px;
  border: 2px dashed #e5e7eb;
  border-radius: 10px;
  color: #94a3b8;
}

/* ── Editor layout ───────────────────────────────────────────────────────── */
.editor-container { display: flex; flex-direction: column; gap: 40px; }

.sections-group {
  background: white;
  padding: 28px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
}

.group-title { font-size: 17px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.group-note  { font-size: 13px; font-weight: 500; color: #94a3b8; }
.group-description { color: #64748b; font-size: 13px; margin-bottom: 20px; }

.sections-list { display: flex; flex-direction: column; gap: 12px; }

/* ── Section cards ───────────────────────────────────────────────────────── */
.section-card {
  background: #f8fafc;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px 18px;
  transition: border-color 0.15s;
}
.section-card:hover  { border-color: #c7d2fe; }
.section-card.fixed  { background: #fffbeb; border-color: #fcd34d; }

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.section-name-editable {
  cursor: pointer;
  border-radius: 4px;
  padding: 2px 4px;
  transition: background 0.15s;
}
.section-name-editable:hover {
  background: rgba(99, 102, 241, 0.08);
  color: #6366f1;
}
.section-name-input {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  border: 2px solid #6366f1;
  border-radius: 6px;
  padding: 3px 8px;
  outline: none;
  flex: 1;
  min-width: 0;
  background: white;
}
.section-name { font-size: 15px; font-weight: 700; color: #1e293b; }

.section-badge {
  padding: 3px 10px;
  background: #fbbf24;
  color: #78350f;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
}

.section-actions { display: flex; gap: 6px; }

.item-count-label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 10px;
}

/* ── Icon buttons ────────────────────────────────────────────────────────── */
.drag-handle {
  cursor: grab;
  font-size: 14px;
  font-weight: 900;
  color: #94a3b8;
  padding: 4px 6px;
  border-radius: 4px;
  letter-spacing: -1px;
  user-select: none;
  flex-shrink: 0;
  line-height: 1;
  transition: color 0.12s, background 0.12s;
}
.drag-handle:hover { color: #6366f1; background: #f1f5f9; }
.drag-handle:active { cursor: grabbing; }
.drag-handle-sm { font-size: 12px; padding: 2px 4px; }
.section-card.drag-over { border-color: #6366f1; background: #fafafe; }

.btn-icon {
  width: 30px; height: 30px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  color: #374151;
  transition: all 0.15s;
}
.btn-icon:hover:not(:disabled) { background: #f1f5f9; border-color: #c7d2fe; color: #6366f1; }
.btn-icon:disabled { opacity: 0.35; cursor: not-allowed; }
.btn-icon.danger:hover { background: #fee2e2; border-color: #fecaca; color: #dc2626; }
.btn-icon.preset-btn:hover { background: #ecfdf5 !important; border-color: #6ee7b7 !important; color: #059669 !important; }

/* ── Items ───────────────────────────────────────────────────────────────── */
.items-list { display: flex; flex-direction: column; gap: 6px; }

.item-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px;
  background: white;
  border-radius: 7px;
  border: 1px solid #e9ecef;
  transition: border-color 0.15s;
}
.item-row:hover { border-color: #c7d2fe; }

.item-info { flex: 1; }
.item-name { font-size: 13px; font-weight: 600; color: #1e293b; display: block; margin-bottom: 3px; }
.item-meta { display: flex; gap: 6px; }
.meta-badge { padding: 1px 7px; border-radius: 8px; font-size: 10px; font-weight: 700; }
.meta-badge.photo { background: #e0e7ff; color: #4338ca; }
.meta-badge.cond  { background: #dcfce7; color: #166534; }

.item-actions { display: flex; gap: 4px; }

.btn-icon-sm {
  width: 26px; height: 26px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 5px;
  font-size: 12px; font-weight: 700;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
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
  font-size: 13px; font-weight: 600; color: #64748b;
  cursor: pointer;
  margin-top: 6px;
  transition: all 0.15s;
}
.btn-add-item:hover { border-color: #6366f1; color: #6366f1; background: #f5f3ff; }

/* ── Modal shared ────────────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center;
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
  display: flex; flex-direction: column;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.modal-narrow { max-width: 460px; }
.modal-wide   { max-width: 680px; }

.modal-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}
.modal-header h2 { font-size: 18px; font-weight: 700; color: #1e293b; }
.modal-subtitle { font-size: 13px; color: #64748b; margin-top: 2px; }

.btn-close {
  background: none; border: none;
  font-size: 18px; color: #94a3b8; cursor: pointer;
  width: 28px; height: 28px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 4px; flex-shrink: 0;
}
.btn-close:hover { background: #f1f5f9; color: #374151; }

.modal-body { padding: 20px 24px; overflow-y: auto; flex: 1; }

.modal-footer {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid #e5e7eb;
  background: #f8fafc;
  flex-shrink: 0;
}

/* ── Add Section modal ───────────────────────────────────────────────────── */
.add-section-option {
  padding: 16px;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  margin-bottom: 4px;
}

.option-label { font-size: 14px; font-weight: 700; color: #1e293b; margin-bottom: 10px; }

.option-row { display: flex; gap: 8px; }

.option-input {
  flex: 1;
  padding: 9px 13px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 14px;
  font-family: inherit;
}
.option-input:focus { outline: none; border-color: #6366f1; }

.option-hint { font-size: 13px; color: #64748b; }

.preset-option { cursor: default; }

.option-divider {
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 10px 0;
}

/* ── Preset picker modal ─────────────────────────────────────────────────── */
.preset-search {
  width: 100%;
  padding: 9px 13px;
  border: 1.5px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  box-sizing: border-box;
  margin-bottom: 14px;
  transition: border-color 0.15s;
}
.preset-search:focus { outline: none; border-color: #6366f1; }

.picker-empty {
  text-align: center;
  padding: 32px 20px;
  color: #94a3b8;
  font-size: 14px;
}
.picker-empty-hint { font-size: 12px; margin-top: 6px; }

.picker-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }

.picker-row {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 14px;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
}
.picker-row:hover    { border-color: #a5b4fc; background: #fafafa; }
.picker-row.selected { border-color: #6366f1; background: #f5f3ff; }

.picker-check { padding-top: 1px; flex-shrink: 0; }

.check-box {
  width: 18px; height: 18px;
  border: 2px solid #d1d5db;
  border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700;
  transition: all 0.15s;
}
.check-box.checked { background: #6366f1; border-color: #6366f1; color: white; }

.picker-info { flex: 1; min-width: 0; }
.picker-name { font-size: 14px; font-weight: 700; color: #1e293b; margin-bottom: 2px; }
.picker-meta { font-size: 12px; color: #94a3b8; margin-bottom: 6px; }
.picker-desc { color: #64748b; }

.picker-items-preview { display: flex; flex-wrap: wrap; gap: 4px; }

.preview-chip {
  padding: 2px 8px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 11px;
  color: #475569;
}
.preview-chip.more { color: #94a3b8; font-style: italic; }

/* ── Rename panel ────────────────────────────────────────────────────────── */
.rename-panel {
  margin-top: 16px;
  padding: 16px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 10px;
}

.rename-panel-title {
  font-size: 13px;
  font-weight: 700;
  color: #166534;
  margin-bottom: 12px;
}

.rename-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.rename-row:last-child { margin-bottom: 0; }

.rename-original {
  font-size: 13px;
  color: #64748b;
  min-width: 120px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rename-arrow { color: #94a3b8; font-size: 14px; flex-shrink: 0; }

.rename-input {
  flex: 1;
  padding: 7px 11px;
  border: 1px solid #a7f3d0;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  background: white;
}
.rename-input:focus { outline: none; border-color: #059669; }

/* ── Save preset modal ───────────────────────────────────────────────────── */
.save-info {
  font-size: 13px; color: #475569;
  margin-bottom: 18px;
  padding: 10px 14px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 7px;
  line-height: 1.5;
}

/* ── Shared form styles ──────────────────────────────────────────────────── */
.form-group { margin-bottom: 18px; }
.form-group label {
  display: block; margin-bottom: 6px;
  font-weight: 600; color: #475569; font-size: 13px;
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
.form-group textarea:focus  { outline: none; border-color: #6366f1; }
.form-group textarea        { resize: vertical; }

.form-group-inline { display: flex; gap: 20px; margin-bottom: 18px; }
.checkbox-label {
  display: flex; align-items: center; gap: 7px;
  font-size: 14px; color: #475569; cursor: pointer;
}
.checkbox-label input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }

.optional { font-weight: 400; color: #94a3b8; }
</style>
