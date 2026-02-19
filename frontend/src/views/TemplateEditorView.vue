<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../services/api'
import { useToast } from '../composables/useToast'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const loading = ref(true)
const saving = ref(false)

// Template metadata
const templateName = ref('')
const inspectionType = ref('check_in')
const isDefault = ref(false)

// Cleanliness dropdown options
const cleanlinessOptions = [
  'Professionally Cleaned',
  'Professionally Cleaned - Receipt Seen',
  'Professionally Cleaned with Omissions',
  'Domestically Cleaned',
  'Domestically Cleaned with Omissions',
  'Not Clean'
]

// Fixed sections with actual form fields
const fixedSections = ref([
  {
    id: 'condition_summary',
    name: 'Condition Summary',
    enabled: true,
    type: 'condition_summary',
    rows: [
      { id: 1, name: '', condition: '' },
      { id: 2, name: '', condition: '' },
      { id: 3, name: '', condition: '' }
    ]
  },
  {
    id: 'cleaning_summary',
    name: 'Cleaning Summary',
    enabled: true,
    type: 'cleaning_summary',
    rows: [
      { id: 1, name: '', cleanliness: '', cleanlinessNotes: '' },
      { id: 2, name: '', cleanliness: '', cleanlinessNotes: '' },
      { id: 3, name: '', cleanliness: '', cleanlinessNotes: '' }
    ]
  },
  {
    id: 'smoke_alarms',
    name: 'Smoke & Carbon Monoxide Alarms',
    enabled: true,
    type: 'smoke_alarms',
    rows: [
      { id: 1, question: '', answer: '', notes: '' },
      { id: 2, question: '', answer: '', notes: '' },
      { id: 3, question: '', answer: '', notes: '' },
      { id: 4, question: '', answer: '', notes: '' },
      { id: 5, question: '', answer: '', notes: '' }
    ]
  },
  {
    id: 'fire_door_safety',
    name: 'Fire Door Safety',
    enabled: true,
    type: 'fire_door_safety',
    rows: [
      { id: 1, name: '', question: '', answer: '', notes: '' },
      { id: 2, name: '', question: '', answer: '', notes: '' },
      { id: 3, name: '', question: '', answer: '', notes: '' }
    ]
  },
  {
    id: 'health_safety',
    name: 'Health & Safety',
    enabled: true,
    type: 'health_safety',
    rows: [
      { id: 1, question: '', answer: '', notes: '' },
      { id: 2, question: '', answer: '', notes: '' },
      { id: 3, question: '', answer: '', notes: '' },
      { id: 4, question: '', answer: '', notes: '' },
      { id: 5, question: '', answer: '', notes: '' },
      { id: 6, question: '', answer: '', notes: '' },
      { id: 7, question: '', answer: '', notes: '' }
    ]
  },
  {
    id: 'keys',
    name: 'Keys & Access',
    enabled: true,
    type: 'keys',
    rows: [
      { id: 1, name: '', description: '' },
      { id: 2, name: '', description: '' },
      { id: 3, name: '', description: '' },
      { id: 4, name: '', description: '' },
      { id: 5, name: '', description: '' },
      { id: 6, name: '', description: '' },
      { id: 7, name: '', description: '' }
    ]
  },
  {
    id: 'meter_readings',
    name: 'Utility Meter Readings',
    enabled: true,
    type: 'meter_readings',
    rows: [
      { id: 1, name: '', locationSerial: '', reading: '' },
      { id: 2, name: '', locationSerial: '', reading: '' },
      { id: 3, name: '', locationSerial: '', reading: '' }
    ]
  }
])

// Rooms - dynamic, can add/remove/reorder
const rooms = ref([
  {
    id: 'entrance_hall',
    name: 'Entrance Hall',
    enabled: true,
    sections: [
      { id: 'walls', label: 'Walls', hasDescription: true, hasCondition: true },
      { id: 'ceiling', label: 'Ceiling', hasDescription: true, hasCondition: true },
      { id: 'floor', label: 'Floor/Flooring', hasDescription: true, hasCondition: true },
      { id: 'doors', label: 'Doors', hasDescription: true, hasCondition: true },
      { id: 'windows', label: 'Windows', hasDescription: true, hasCondition: true },
      { id: 'lighting', label: 'Lighting', hasDescription: true, hasCondition: true },
      { id: 'sockets', label: 'Sockets/Switches', hasDescription: true, hasCondition: true },
      { id: 'heating', label: 'Heating', hasDescription: true, hasCondition: true },
      { id: 'furniture', label: 'Furniture/Fixtures', hasDescription: true, hasCondition: true }
    ]
  },
  {
    id: 'living_room',
    name: 'Living Room',
    enabled: true,
    sections: [
      { id: 'walls', label: 'Walls', hasDescription: true, hasCondition: true },
      { id: 'ceiling', label: 'Ceiling', hasDescription: true, hasCondition: true },
      { id: 'floor', label: 'Floor/Flooring', hasDescription: true, hasCondition: true },
      { id: 'doors', label: 'Doors', hasDescription: true, hasCondition: true },
      { id: 'windows', label: 'Windows', hasDescription: true, hasCondition: true },
      { id: 'curtains', label: 'Curtains/Blinds', hasDescription: true, hasCondition: true },
      { id: 'lighting', label: 'Lighting', hasDescription: true, hasCondition: true },
      { id: 'sockets', label: 'Sockets/Switches', hasDescription: true, hasCondition: true },
      { id: 'heating', label: 'Heating', hasDescription: true, hasCondition: true },
      { id: 'furniture', label: 'Furniture/Fixtures', hasDescription: true, hasCondition: true }
    ]
  },
  {
    id: 'kitchen',
    name: 'Kitchen',
    enabled: true,
    sections: [
      { id: 'walls', label: 'Walls/Tiles', hasDescription: true, hasCondition: true },
      { id: 'ceiling', label: 'Ceiling', hasDescription: true, hasCondition: true },
      { id: 'floor', label: 'Floor/Flooring', hasDescription: true, hasCondition: true },
      { id: 'doors', label: 'Doors', hasDescription: true, hasCondition: true },
      { id: 'windows', label: 'Windows', hasDescription: true, hasCondition: true },
      { id: 'lighting', label: 'Lighting', hasDescription: true, hasCondition: true },
      { id: 'sockets', label: 'Sockets/Switches', hasDescription: true, hasCondition: true },
      { id: 'heating', label: 'Heating', hasDescription: true, hasCondition: true },
      { id: 'kitchen_units', label: 'Kitchen Units', hasDescription: true, hasCondition: true },
      { id: 'worktops', label: 'Worktops', hasDescription: true, hasCondition: true },
      { id: 'sink', label: 'Sink & Taps', hasDescription: true, hasCondition: true },
      { id: 'cooker', label: 'Cooker/Hob', hasDescription: true, hasCondition: true },
      { id: 'oven', label: 'Oven', hasDescription: true, hasCondition: true },
      { id: 'extractor', label: 'Extractor Hood', hasDescription: true, hasCondition: true },
      { id: 'fridge', label: 'Fridge/Freezer', hasDescription: true, hasCondition: true },
      { id: 'dishwasher', label: 'Dishwasher', hasDescription: true, hasCondition: true },
      { id: 'washing_machine', label: 'Washing Machine', hasDescription: true, hasCondition: true }
    ]
  },
  {
    id: 'bathroom',
    name: 'Bathroom',
    enabled: true,
    sections: [
      { id: 'walls', label: 'Walls/Tiles', hasDescription: true, hasCondition: true },
      { id: 'ceiling', label: 'Ceiling', hasDescription: true, hasCondition: true },
      { id: 'floor', label: 'Floor/Flooring', hasDescription: true, hasCondition: true },
      { id: 'doors', label: 'Doors', hasDescription: true, hasCondition: true },
      { id: 'windows', label: 'Windows', hasDescription: true, hasCondition: true },
      { id: 'lighting', label: 'Lighting', hasDescription: true, hasCondition: true },
      { id: 'sockets', label: 'Sockets/Switches', hasDescription: true, hasCondition: true },
      { id: 'heating', label: 'Heating/Towel Rail', hasDescription: true, hasCondition: true },
      { id: 'bath', label: 'Bath', hasDescription: true, hasCondition: true },
      { id: 'shower', label: 'Shower/Shower Screen', hasDescription: true, hasCondition: true },
      { id: 'toilet', label: 'Toilet', hasDescription: true, hasCondition: true },
      { id: 'basin', label: 'Basin & Taps', hasDescription: true, hasCondition: true },
      { id: 'mirror', label: 'Mirror/Cabinet', hasDescription: true, hasCondition: true },
      { id: 'extractor', label: 'Extractor Fan', hasDescription: true, hasCondition: true }
    ]
  },
  {
    id: 'bedroom_1',
    name: 'Bedroom 1',
    enabled: true,
    sections: [
      { id: 'walls', label: 'Walls', hasDescription: true, hasCondition: true },
      { id: 'ceiling', label: 'Ceiling', hasDescription: true, hasCondition: true },
      { id: 'floor', label: 'Floor/Flooring', hasDescription: true, hasCondition: true },
      { id: 'doors', label: 'Doors', hasDescription: true, hasCondition: true },
      { id: 'windows', label: 'Windows', hasDescription: true, hasCondition: true },
      { id: 'curtains', label: 'Curtains/Blinds', hasDescription: true, hasCondition: true },
      { id: 'lighting', label: 'Lighting', hasDescription: true, hasCondition: true },
      { id: 'sockets', label: 'Sockets/Switches', hasDescription: true, hasCondition: true },
      { id: 'heating', label: 'Heating', hasDescription: true, hasCondition: true },
      { id: 'wardrobe', label: 'Wardrobe/Storage', hasDescription: true, hasCondition: true },
      { id: 'furniture', label: 'Furniture/Fixtures', hasDescription: true, hasCondition: true }
    ]
  },
  {
    id: 'bedroom_2',
    name: 'Bedroom 2',
    enabled: true,
    sections: [
      { id: 'walls', label: 'Walls', hasDescription: true, hasCondition: true },
      { id: 'ceiling', label: 'Ceiling', hasDescription: true, hasCondition: true },
      { id: 'floor', label: 'Floor/Flooring', hasDescription: true, hasCondition: true },
      { id: 'doors', label: 'Doors', hasDescription: true, hasCondition: true },
      { id: 'windows', label: 'Windows', hasDescription: true, hasCondition: true },
      { id: 'curtains', label: 'Curtains/Blinds', hasDescription: true, hasCondition: true },
      { id: 'lighting', label: 'Lighting', hasDescription: true, hasCondition: true },
      { id: 'sockets', label: 'Sockets/Switches', hasDescription: true, hasCondition: true },
      { id: 'heating', label: 'Heating', hasDescription: true, hasCondition: true },
      { id: 'wardrobe', label: 'Wardrobe/Storage', hasDescription: true, hasCondition: true },
      { id: 'furniture', label: 'Furniture/Fixtures', hasDescription: true, hasCondition: true }
    ]
  }
])

const isEditMode = computed(() => route.params.id !== undefined)

// Dummy photo handler
function handlePhotoClick(section, item = null) {
  // Placeholder for future photo functionality
  console.log('Photo button clicked for:', section, item)
  toast.info('Photo capture will be available in the mobile app')
}

// Load template if editing
async function loadTemplate() {
  if (!isEditMode.value) {
    loading.value = false
    return
  }

  try {
    const response = await api.getTemplate(route.params.id)
    const template = response.data
    
    templateName.value = template.name
    inspectionType.value = template.inspection_type
    isDefault.value = template.is_default
    
    // Parse content
    const content = JSON.parse(template.content)
    if (content.fixedSections) fixedSections.value = content.fixedSections
    if (content.rooms) rooms.value = content.rooms
  } catch (error) {
    console.error('Failed to load template:', error)
    toast.error('Failed to load template')
  } finally {
    loading.value = false
  }
}

// Save template
async function saveTemplate() {
  if (!templateName.value.trim()) {
    toast.warning('Please enter a template name')
    return
  }

  saving.value = true

  const templateData = {
    name: templateName.value,
    inspection_type: inspectionType.value,
    is_default: isDefault.value,
    content: JSON.stringify({
      fixedSections: fixedSections.value,
      rooms: rooms.value
    })
  }

  try {
    if (isEditMode.value) {
      await api.updateTemplate(route.params.id, templateData)
      toast.success('Template saved')
    } else {
      await api.createTemplate(templateData)
      toast.success('Template created')
    }
    router.push('/settings')
  } catch (error) {
    console.error('Failed to save template:', error)
    toast.error('Failed to save template')
  } finally {
    saving.value = false
  }
}

// Fixed section row management
function addRowToSection(sectionIndex) {
  const section = fixedSections.value[sectionIndex]
  const newId = section.rows.length > 0 ? Math.max(...section.rows.map(r => r.id)) + 1 : 1
  
  let newRow = { id: newId }
  
  if (section.type === 'condition_summary') {
    newRow = { id: newId, name: '', condition: '' }
  } else if (section.type === 'cleaning_summary') {
    newRow = { id: newId, name: '', cleanliness: '', cleanlinessNotes: '' }
  } else if (section.type === 'smoke_alarms') {
    newRow = { id: newId, question: '', answer: '', notes: '' }
  } else if (section.type === 'fire_door_safety') {
    newRow = { id: newId, name: '', question: '', answer: '', notes: '' }
  } else if (section.type === 'health_safety') {
    newRow = { id: newId, question: '', answer: '', notes: '' }
  } else if (section.type === 'keys') {
    newRow = { id: newId, name: '', description: '' }
  } else if (section.type === 'meter_readings') {
    newRow = { id: newId, name: '', locationSerial: '', reading: '' }
  }
  
  section.rows.push(newRow)
}

function deleteRowFromSection(sectionIndex, rowIndex) {
  if (!confirm('Delete this row?')) return
  fixedSections.value[sectionIndex].rows.splice(rowIndex, 1)
}

// Room management functions
function addRoom() {
  const roomNumber = rooms.value.length + 1
  rooms.value.push({
    id: `room_${Date.now()}`,
    name: `Room ${roomNumber}`,
    enabled: true,
    sections: [
      { id: 'walls', label: 'Walls', hasDescription: true, hasCondition: true },
      { id: 'ceiling', label: 'Ceiling', hasDescription: true, hasCondition: true },
      { id: 'floor', label: 'Floor/Flooring', hasDescription: true, hasCondition: true }
    ]
  })
}

function copyRoom(index) {
  const original = rooms.value[index]
  const copy = JSON.parse(JSON.stringify(original))
  copy.id = `room_${Date.now()}`
  copy.name = `${original.name} (Copy)`
  rooms.value.splice(index + 1, 0, copy)
}

function deleteRoom(index) {
  if (!confirm('Delete this room?')) return
  rooms.value.splice(index, 1)
}

function moveRoomUp(index) {
  if (index === 0) return
  const room = rooms.value.splice(index, 1)[0]
  rooms.value.splice(index - 1, 0, room)
}

function moveRoomDown(index) {
  if (index === rooms.value.length - 1) return
  const room = rooms.value.splice(index, 1)[0]
  rooms.value.splice(index + 1, 0, room)
}

// Section management within rooms
function addSectionToRoom(roomIndex) {
  rooms.value[roomIndex].sections.push({
    id: `section_${Date.now()}`,
    label: 'New Section',
    hasDescription: true,
    hasCondition: true
  })
}

function deleteSectionFromRoom(roomIndex, sectionIndex) {
  if (!confirm('Delete this section?')) return
  rooms.value[roomIndex].sections.splice(sectionIndex, 1)
}

function moveSectionUp(roomIndex, sectionIndex) {
  if (sectionIndex === 0) return
  const section = rooms.value[roomIndex].sections.splice(sectionIndex, 1)[0]
  rooms.value[roomIndex].sections.splice(sectionIndex - 1, 0, section)
}

function moveSectionDown(roomIndex, sectionIndex) {
  const room = rooms.value[roomIndex]
  if (sectionIndex === room.sections.length - 1) return
  const section = room.sections.splice(sectionIndex, 1)[0]
  room.sections.splice(sectionIndex + 1, 0, section)
}

onMounted(() => {
  loadTemplate()
})
</script>

<template>
  <div class="page">
    <div class="editor-header">
      <div class="header-left">
        <button @click="router.push('/settings')" class="btn-back">
          ← Back to Settings
        </button>
        <h1>{{ isEditMode ? 'Edit Template' : 'Create New Template' }}</h1>
      </div>
      <div class="header-actions">
        <button @click="saveTemplate" :disabled="saving" class="btn-save">
          {{ saving ? 'Saving...' : '💾 Save Template' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">Loading template...</div>

    <div v-else class="editor-container">
      <!-- Template Metadata -->
      <div class="editor-section metadata-section">
        <h2>Template Information</h2>
        <div class="form-grid">
          <div class="form-group">
            <label>Template Name *</label>
            <input 
              v-model="templateName" 
              type="text" 
              class="input-field" 
              placeholder="e.g. Standard Check-In Template"
            />
          </div>
          
          <div class="form-group">
            <label>Inspection Type *</label>
            <select v-model="inspectionType" class="input-field">
              <option value="check_in">Check In</option>
              <option value="check_out">Check Out</option>
              <option value="interim">Interim Inspection</option>
              <option value="inventory">Inventory Only</option>
            </select>
          </div>
          
          <div class="form-group checkbox-group">
            <label>
              <input type="checkbox" v-model="isDefault" />
              <span>Set as default template for this inspection type</span>
            </label>
          </div>
        </div>
      </div>

      <!-- Fixed Sections -->
      <div class="editor-section">
        <h2>Report Sections</h2>
        <p class="section-description">Configure the standard sections that appear in every inspection report</p>
        
        <div class="fixed-sections-list">
          <!-- Condition Summary -->
          <div class="fixed-section-card">
            <div class="fixed-section-header">
              <label class="section-toggle">
                <input type="checkbox" v-model="fixedSections[0].enabled" />
                <span class="section-name">Condition Summary</span>
              </label>
              <button @click="addRowToSection(0)" class="btn-add-row">➕ Add Row</button>
            </div>
            <div v-if="fixedSections[0].enabled" class="section-table-container">
              <table class="section-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Condition</th>
                    <th style="width: 80px;">Photo</th>
                    <th style="width: 60px;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in fixedSections[0].rows" :key="row.id">
                    <td>
                      <input v-model="row.name" type="text" class="table-input" placeholder="Name" />
                    </td>
                    <td>
                      <input v-model="row.condition" type="text" class="table-input" placeholder="Condition" />
                    </td>
                    <td>
                      <button @click="handlePhotoClick('condition_summary', row)" class="btn-photo">📷 Photo</button>
                    </td>
                    <td>
                      <button @click="deleteRowFromSection(0, rowIndex)" class="btn-delete-row">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Cleaning Summary -->
          <div class="fixed-section-card">
            <div class="fixed-section-header">
              <label class="section-toggle">
                <input type="checkbox" v-model="fixedSections[1].enabled" />
                <span class="section-name">Cleaning Summary</span>
              </label>
              <button @click="addRowToSection(1)" class="btn-add-row">➕ Add Row</button>
            </div>
            <div v-if="fixedSections[1].enabled" class="section-table-container">
              <table class="section-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Cleanliness</th>
                    <th>Cleanliness Notes</th>
                    <th style="width: 80px;">Photo</th>
                    <th style="width: 60px;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in fixedSections[1].rows" :key="row.id">
                    <td>
                      <input v-model="row.name" type="text" class="table-input" placeholder="Name" />
                    </td>
                    <td>
                      <select v-model="row.cleanliness" class="table-select">
                        <option value="">Select...</option>
                        <option v-for="option in cleanlinessOptions" :key="option" :value="option">
                          {{ option }}
                        </option>
                      </select>
                    </td>
                    <td>
                      <input v-model="row.cleanlinessNotes" type="text" class="table-input" placeholder="Notes" />
                    </td>
                    <td>
                      <button @click="handlePhotoClick('cleaning_summary', row)" class="btn-photo">📷 Photo</button>
                    </td>
                    <td>
                      <button @click="deleteRowFromSection(1, rowIndex)" class="btn-delete-row">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Smoke & Carbon Alarms -->
          <div class="fixed-section-card">
            <div class="fixed-section-header">
              <label class="section-toggle">
                <input type="checkbox" v-model="fixedSections[2].enabled" />
                <span class="section-name">Smoke & Carbon Monoxide Alarms</span>
              </label>
              <button @click="addRowToSection(2)" class="btn-add-row">➕ Add Row</button>
            </div>
            <div v-if="fixedSections[2].enabled" class="section-table-container">
              <table class="section-table">
                <thead>
                  <tr>
                    <th>Question</th>
                    <th style="width: 200px;">Answer</th>
                    <th>Additional Notes</th>
                    <th style="width: 80px;">Photo</th>
                    <th style="width: 60px;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in fixedSections[2].rows" :key="row.id">
                    <td>
                      <input v-model="row.question" type="text" class="table-input" placeholder="Question" />
                    </td>
                    <td>
                      <div class="answer-checkboxes">
                        <label><input type="radio" :name="'smoke_' + row.id" :value="'Yes'" v-model="row.answer" /> Yes</label>
                        <label><input type="radio" :name="'smoke_' + row.id" :value="'No'" v-model="row.answer" /> No</label>
                        <label><input type="radio" :name="'smoke_' + row.id" :value="'N/A'" v-model="row.answer" /> N/A</label>
                      </div>
                    </td>
                    <td>
                      <input v-model="row.notes" type="text" class="table-input" placeholder="Notes" />
                    </td>
                    <td>
                      <button @click="handlePhotoClick('smoke_alarms', row)" class="btn-photo">📷 Photo</button>
                    </td>
                    <td>
                      <button @click="deleteRowFromSection(2, rowIndex)" class="btn-delete-row">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Fire Door Safety -->
          <div class="fixed-section-card">
            <div class="fixed-section-header">
              <label class="section-toggle">
                <input type="checkbox" v-model="fixedSections[3].enabled" />
                <span class="section-name">Fire Door Safety</span>
              </label>
              <button @click="addRowToSection(3)" class="btn-add-row">➕ Add Row</button>
            </div>
            <div v-if="fixedSections[3].enabled" class="section-table-container">
              <table class="section-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Question</th>
                    <th style="width: 200px;">Answer</th>
                    <th>Additional Notes</th>
                    <th style="width: 80px;">Photo</th>
                    <th style="width: 60px;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in fixedSections[3].rows" :key="row.id">
                    <td>
                      <input v-model="row.name" type="text" class="table-input" placeholder="Name" />
                    </td>
                    <td>
                      <input v-model="row.question" type="text" class="table-input" placeholder="Question" />
                    </td>
                    <td>
                      <div class="answer-checkboxes">
                        <label><input type="radio" :name="'fire_' + row.id" :value="'Yes'" v-model="row.answer" /> Yes</label>
                        <label><input type="radio" :name="'fire_' + row.id" :value="'No'" v-model="row.answer" /> No</label>
                        <label><input type="radio" :name="'fire_' + row.id" :value="'N/A'" v-model="row.answer" /> N/A</label>
                      </div>
                    </td>
                    <td>
                      <input v-model="row.notes" type="text" class="table-input" placeholder="Notes" />
                    </td>
                    <td>
                      <button @click="handlePhotoClick('fire_door_safety', row)" class="btn-photo">📷 Photo</button>
                    </td>
                    <td>
                      <button @click="deleteRowFromSection(3, rowIndex)" class="btn-delete-row">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Health & Safety -->
          <div class="fixed-section-card">
            <div class="fixed-section-header">
              <label class="section-toggle">
                <input type="checkbox" v-model="fixedSections[4].enabled" />
                <span class="section-name">Health & Safety</span>
              </label>
              <button @click="addRowToSection(4)" class="btn-add-row">➕ Add Row</button>
            </div>
            <div v-if="fixedSections[4].enabled" class="section-table-container">
              <table class="section-table">
                <thead>
                  <tr>
                    <th>Question</th>
                    <th style="width: 200px;">Answer</th>
                    <th>Additional Notes</th>
                    <th style="width: 80px;">Photo</th>
                    <th style="width: 60px;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in fixedSections[4].rows" :key="row.id">
                    <td>
                      <input v-model="row.question" type="text" class="table-input" placeholder="Question" />
                    </td>
                    <td>
                      <div class="answer-checkboxes">
                        <label><input type="radio" :name="'health_' + row.id" :value="'Yes'" v-model="row.answer" /> Yes</label>
                        <label><input type="radio" :name="'health_' + row.id" :value="'No'" v-model="row.answer" /> No</label>
                        <label><input type="radio" :name="'health_' + row.id" :value="'N/A'" v-model="row.answer" /> N/A</label>
                      </div>
                    </td>
                    <td>
                      <input v-model="row.notes" type="text" class="table-input" placeholder="Notes" />
                    </td>
                    <td>
                      <button @click="handlePhotoClick('health_safety', row)" class="btn-photo">📷 Photo</button>
                    </td>
                    <td>
                      <button @click="deleteRowFromSection(4, rowIndex)" class="btn-delete-row">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Keys & Access -->
          <div class="fixed-section-card">
            <div class="fixed-section-header">
              <label class="section-toggle">
                <input type="checkbox" v-model="fixedSections[5].enabled" />
                <span class="section-name">Keys & Access</span>
              </label>
              <button @click="addRowToSection(5)" class="btn-add-row">➕ Add Row</button>
            </div>
            <div v-if="fixedSections[5].enabled" class="section-table-container">
              <table class="section-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Description</th>
                    <th style="width: 80px;">Photo</th>
                    <th style="width: 60px;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in fixedSections[5].rows" :key="row.id">
                    <td>
                      <input v-model="row.name" type="text" class="table-input" placeholder="Name" />
                    </td>
                    <td>
                      <input v-model="row.description" type="text" class="table-input" placeholder="Description" />
                    </td>
                    <td>
                      <button @click="handlePhotoClick('keys', row)" class="btn-photo">📷 Photo</button>
                    </td>
                    <td>
                      <button @click="deleteRowFromSection(5, rowIndex)" class="btn-delete-row">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Utility Meter Readings -->
          <div class="fixed-section-card">
            <div class="fixed-section-header">
              <label class="section-toggle">
                <input type="checkbox" v-model="fixedSections[6].enabled" />
                <span class="section-name">Utility Meter Readings</span>
              </label>
              <button @click="addRowToSection(6)" class="btn-add-row">➕ Add Row</button>
            </div>
            <div v-if="fixedSections[6].enabled" class="section-table-container">
              <table class="section-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Location & Serial Number</th>
                    <th>Reading</th>
                    <th style="width: 80px;">Photo</th>
                    <th style="width: 60px;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in fixedSections[6].rows" :key="row.id">
                    <td>
                      <input v-model="row.name" type="text" class="table-input" placeholder="Name" />
                    </td>
                    <td>
                      <input v-model="row.locationSerial" type="text" class="table-input" placeholder="Location & Serial Number" />
                    </td>
                    <td>
                      <input v-model="row.reading" type="text" class="table-input" placeholder="Reading" />
                    </td>
                    <td>
                      <button @click="handlePhotoClick('meter_readings', row)" class="btn-photo">📷 Photo</button>
                    </td>
                    <td>
                      <button @click="deleteRowFromSection(6, rowIndex)" class="btn-delete-row">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- Rooms -->
      <div class="editor-section">
        <div class="section-header-with-action">
          <div>
            <h2>Rooms</h2>
            <p class="section-description">Add, edit, and organize rooms for the inspection</p>
          </div>
          <button @click="addRoom" class="btn-add">
            ➕ Add Room
          </button>
        </div>

        <div class="rooms-list">
          <div v-for="(room, roomIndex) in rooms" :key="room.id" class="room-card">
            <div class="room-header">
              <div class="room-title-section">
                <label class="room-toggle">
                  <input type="checkbox" v-model="room.enabled" />
                </label>
                <input 
                  v-model="room.name" 
                  type="text" 
                  class="room-name-input"
                  placeholder="Room name"
                />
              </div>
              <div class="room-actions">
                <button 
                  @click="moveRoomUp(roomIndex)" 
                  :disabled="roomIndex === 0"
                  class="btn-icon"
                  title="Move up"
                >
                  ↑
                </button>
                <button 
                  @click="moveRoomDown(roomIndex)" 
                  :disabled="roomIndex === rooms.length - 1"
                  class="btn-icon"
                  title="Move down"
                >
                  ↓
                </button>
                <button 
                  @click="copyRoom(roomIndex)" 
                  class="btn-icon"
                  title="Copy room"
                >
                  📋
                </button>
                <button 
                  @click="deleteRoom(roomIndex)" 
                  class="btn-icon btn-delete"
                  title="Delete room"
                >
                  🗑️
                </button>
              </div>
            </div>

            <div v-if="room.enabled" class="room-sections">
              <div class="room-sections-header">
                <h4>Sections</h4>
                <button @click="addSectionToRoom(roomIndex)" class="btn-add-small">
                  ➕ Add Section
                </button>
              </div>

              <div class="sections-table">
                <div class="table-header">
                  <div class="col-section">Section Name</div>
                  <div class="col-checkbox">Description</div>
                  <div class="col-checkbox">Condition</div>
                  <div class="col-photo">Photo</div>
                  <div class="col-actions">Actions</div>
                </div>

                <div 
                  v-for="(section, sectionIndex) in room.sections" 
                  :key="section.id"
                  class="table-row"
                >
                  <div class="col-section">
                    <input 
                      v-model="section.label" 
                      type="text" 
                      class="section-label-input"
                      placeholder="Section name"
                    />
                  </div>
                  <div class="col-checkbox">
                    <input type="checkbox" v-model="section.hasDescription" />
                  </div>
                  <div class="col-checkbox">
                    <input type="checkbox" v-model="section.hasCondition" />
                  </div>
                  <div class="col-photo">
                    <button @click="handlePhotoClick('room_section', section)" class="btn-photo-small">📷</button>
                  </div>
                  <div class="col-actions">
                    <button 
                      @click="moveSectionUp(roomIndex, sectionIndex)" 
                      :disabled="sectionIndex === 0"
                      class="btn-icon-small"
                      title="Move up"
                    >
                      ↑
                    </button>
                    <button 
                      @click="moveSectionDown(roomIndex, sectionIndex)" 
                      :disabled="sectionIndex === room.sections.length - 1"
                      class="btn-icon-small"
                      title="Move down"
                    >
                      ↓
                    </button>
                    <button 
                      @click="deleteSectionFromRoom(roomIndex, sectionIndex)" 
                      class="btn-icon-small btn-delete"
                      title="Delete"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Save Button Bottom -->
      <div class="editor-footer">
        <button @click="router.push('/settings')" class="btn-cancel">
          Cancel
        </button>
        <button @click="saveTemplate" :disabled="saving" class="btn-save-large">
          {{ saving ? 'Saving...' : '💾 Save Template' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1600px;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
  gap: 20px;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.btn-back {
  padding: 8px 16px;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  width: fit-content;
}

.btn-back:hover {
  background: #e2e8f0;
}

.editor-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
}

.btn-save {
  padding: 12px 24px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.btn-save:hover:not(:disabled) {
  background: #4f46e5;
}

.btn-save:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
  font-size: 16px;
}

.editor-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.editor-section {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  padding: 32px;
}

.editor-section h2 {
  font-size: 24px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.section-description {
  color: #64748b;
  font-size: 14px;
  margin-bottom: 24px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-weight: 600;
  color: #475569;
  font-size: 14px;
}

.input-field {
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
}

.input-field:focus {
  outline: none;
  border-color: #6366f1;
}

.checkbox-group {
  grid-column: 1 / -1;
}

.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.checkbox-group input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
}

/* Fixed Sections Styles */
.fixed-sections-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.fixed-section-card {
  background: #f8fafc;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
}

.fixed-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-toggle {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
}

.section-toggle input[type="checkbox"] {
  width: 20px;
  height: 20px;
  cursor: pointer;
}

.section-name {
  font-weight: 600;
  color: #1e293b;
  font-size: 16px;
}

.btn-add-row {
  padding: 6px 14px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-add-row:hover {
  background: #4f46e5;
}

.section-table-container {
  background: white;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}

.section-table {
  width: 100%;
  border-collapse: collapse;
}

.section-table thead {
  background: #f1f5f9;
}

.section-table th {
  padding: 12px;
  text-align: left;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  border-bottom: 2px solid #e5e7eb;
}

.section-table td {
  padding: 8px;
  border-bottom: 1px solid #e5e7eb;
}

.table-input,
.table-select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 14px;
  font-family: inherit;
}

.table-input:focus,
.table-select:focus {
  outline: none;
  border-color: #6366f1;
}

.answer-checkboxes {
  display: flex;
  gap: 12px;
  align-items: center;
}

.answer-checkboxes label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
  white-space: nowrap;
}

.answer-checkboxes input[type="radio"] {
  cursor: pointer;
}

.btn-photo {
  width: 100%;
  padding: 6px 8px;
  background: #dbeafe;
  color: #1e40af;
  border: 1px solid #93c5fd;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.btn-photo:hover {
  background: #bfdbfe;
}

.btn-delete-row {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fee2e2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  margin: 0 auto;
}

.btn-delete-row:hover {
  background: #fecaca;
}

/* Room Styles */
.section-header-with-action {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.btn-add {
  padding: 10px 20px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.btn-add:hover {
  background: #4f46e5;
}

.rooms-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.room-card {
  background: #f8fafc;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
}

.room-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  gap: 16px;
}

.room-title-section {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.room-toggle input[type="checkbox"] {
  width: 20px;
  height: 20px;
  cursor: pointer;
}

.room-name-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 16px;
  font-weight: 600;
  font-family: inherit;
}

.room-name-input:focus {
  outline: none;
  border-color: #6366f1;
}

.room-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-icon:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.btn-icon:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-icon.btn-delete {
  background: #fee2e2;
  border-color: #fecaca;
}

.btn-icon.btn-delete:hover {
  background: #fecaca;
}

.room-sections {
  background: white;
  border-radius: 8px;
  padding: 20px;
}

.room-sections-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.room-sections-header h4 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.btn-add-small {
  padding: 6px 14px;
  background: #e0e7ff;
  color: #3730a3;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-add-small:hover {
  background: #c7d2fe;
}

.sections-table {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}

.table-header,
.table-row {
  display: grid;
  grid-template-columns: 2fr 100px 100px 80px 110px;
  gap: 1px;
  background: white;
  align-items: center;
}

.table-header {
  font-weight: 600;
  font-size: 12px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.table-header > div {
  padding: 12px;
  background: #f8fafc;
}

.table-row > div {
  padding: 12px;
}

.col-section {
  padding: 8px 12px;
}

.col-checkbox {
  display: flex;
  justify-content: center;
  align-items: center;
}

.col-checkbox input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
}

.col-photo {
  display: flex;
  justify-content: center;
  align-items: center;
}

.btn-photo-small {
  padding: 4px 10px;
  background: #dbeafe;
  color: #1e40af;
  border: 1px solid #93c5fd;
  border-radius: 4px;
  font-size: 16px;
  cursor: pointer;
}

.btn-photo-small:hover {
  background: #bfdbfe;
}

.col-actions {
  display: flex;
  gap: 4px;
  justify-content: center;
}

.section-label-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 14px;
  font-family: inherit;
}

.section-label-input:focus {
  outline: none;
  border-color: #6366f1;
}

.btn-icon-small {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-icon-small:hover:not(:disabled) {
  background: #e2e8f0;
}

.btn-icon-small:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-icon-small.btn-delete {
  background: #fee2e2;
  border-color: #fecaca;
}

.btn-icon-small.btn-delete:hover {
  background: #fecaca;
}

.editor-footer {
  display: flex;
  justify-content: flex-end;
  gap: 16px;
  padding: 24px 0;
}

.btn-cancel {
  padding: 12px 32px;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.btn-cancel:hover {
  background: #e2e8f0;
}

.btn-save-large {
  padding: 12px 32px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.btn-save-large:hover:not(:disabled) {
  background: #4f46e5;
}

.btn-save-large:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  
  .table-header,
  .table-row {
    grid-template-columns: 1fr 60px 60px 60px 70px;
    font-size: 12px;
  }
  
  .table-header {
    font-size: 10px;
  }
  
  .section-table-container {
    overflow-x: scroll;
  }
}
</style>
