<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'
import api from '../services/api'
import TemplatePreviewModal from '../components/settings/TemplatePreviewModal.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const toast = useToast()

const inspection = ref(null)
const templates = ref([])
const users = ref([])
const loading = ref(true)

const showEditConductDate = ref(false)
const showEditTemplate = ref(false)
const showEditClerk = ref(false)
const showEditTypist = ref(false)
const showEditKeyLocation = ref(false)
const showEditKeyReturn = ref(false)
const showEditNotes = ref(false)
const showEditTenantEmail = ref(false)
const showEditClientEmail = ref(false)
const showPreview = ref(false)
const showPhotoModal = ref(false)
const photoUploading = ref(false)
const localPhoto = ref(null)

const editForms = ref({
  conduct_date: '',
  time_preference: 'anytime',
  time_hour: '09',
  time_minute: '00',
  template_id: null,
  inspector_id: null,
  typist_id: null,
  key_location: '',
  key_return: '',
  internal_notes: '',
  tenant_email: '',
  client_email_override: ''
})

// Key location options
const keyLocationOptions = [
  'With Agent',
  'With Landlord',
  'With Tenant',
  'At Property',
  'At Concierge',
  'In Key Safe'
]

// Key return options
const keyReturnOptions = [
  'From where collected',
  'To Agent',
  'To Concierge',
  'To Key Safe',
  'Hand to Tenant',
  'Leave Inside Property'
]

// Time options
const timePreferenceOptions = [
  { value: 'anytime', label: 'Anytime' },
  { value: 'am', label: 'AM (Morning)' },
  { value: 'pm', label: 'PM (Afternoon)' },
  { value: 'specific', label: 'Specific Time' }
]

const hourOptions = [
  '09', '10', '11', '12', '13', '14', '15', '16', '17'
]

const minuteOptions = ['00', '15', '30', '45']

const statusSteps = [
  { key: 'created',    label: 'Created',    icon: '📋' },
  { key: 'assigned',   label: 'Assigned',   icon: '👤' },
  { key: 'active',     label: 'Active',     icon: '🔍' },
  { key: 'processing', label: 'Processing', icon: '✍️'  },
  { key: 'review',     label: 'Review',     icon: '👁️'  },
  { key: 'complete',   label: 'Complete',   icon: '✅'  }
]

const currentStepIndex = computed(() => {
  if (!inspection.value) return 0
  return statusSteps.findIndex(s => s.key === inspection.value.status)
})

const canEdit = computed(() => authStore.isAdmin || authStore.isManager)

// Role-based: which statuses can the current user advance to?
// Clerks: can move created→active, active→processing
// Managers/Admins: can move anything forward or back
const canAdvance = computed(() => {
  if (!inspection.value) return false
  if (currentStepIndex.value >= statusSteps.length - 1) return false
  if (authStore.isAdmin || authStore.isManager) return true
  // Clerks can mark as active or processing
  const clerkAllowed = ['assigned', 'active']
  return clerkAllowed.includes(inspection.value.status)
})

const canGoBack = computed(() => {
  if (!inspection.value) return false
  if (currentStepIndex.value === 0) return false
  return authStore.isAdmin || authStore.isManager
})

const nextStep = computed(() => statusSteps[currentStepIndex.value + 1] ?? null)
const prevStep = computed(() => statusSteps[currentStepIndex.value - 1] ?? null)

// Status colour theming
const statusColors = {
  created:    { bg: '#f1f5f9', text: '#475569', dot: '#94a3b8' },
  assigned:   { bg: '#eff6ff', text: '#1d4ed8', dot: '#3b82f6' },
  active:     { bg: '#f0fdf4', text: '#16a34a', dot: '#22c55e' },
  processing: { bg: '#fffbeb', text: '#d97706', dot: '#f59e0b' },
  review:     { bg: '#fdf4ff', text: '#9333ea', dot: '#a855f7' },
  complete:   { bg: '#f0fdf4', text: '#15803d', dot: '#16a34a' }
}

// Get the email to display (override or default client email)
const displayClientEmail = computed(() => {
  if (inspection.value?.client_email_override) {
    return inspection.value.client_email_override
  }
  return inspection.value?.client?.email || 'Not set'
})

// Format time preference for display
const displayTimePreference = computed(() => {
  if (!inspection.value?.conduct_time_preference) return 'Anytime'
  
  const pref = inspection.value.conduct_time_preference
  if (pref === 'anytime') return 'Anytime'
  if (pref === 'am') return 'AM (Morning)'
  if (pref === 'pm') return 'PM (Afternoon)'
  if (pref.startsWith('specific:')) {
    const [, time] = pref.split(':')
    const [hour, minute] = time.split('_')
    return `${hour}:${minute}`
  }
  return 'Anytime'
})

function convertDateToUKFormat(isoDate) {
  if (!isoDate) return ''
  const date = new Date(isoDate)
  const day = String(date.getDate()).padStart(2, '0')
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const year = date.getFullYear()
  return `${day}/${month}/${year}`
}

async function fetchInspection() {
  loading.value = true
  try {
    const response = await api.getInspection(route.params.id)
    inspection.value = response.data
    
    // Initialize edit forms
    if (inspection.value.conduct_date) {
      editForms.value.conduct_date = inspection.value.conduct_date.split('T')[0]
    } else {
      editForms.value.conduct_date = ''
    }
    
    // Parse time preference
    const timePref = inspection.value.conduct_time_preference || 'anytime'
    if (timePref.startsWith('specific:')) {
      editForms.value.time_preference = 'specific'
      const [, time] = timePref.split(':')
      const [hour, minute] = time.split('_')
      editForms.value.time_hour = hour
      editForms.value.time_minute = minute
    } else {
      editForms.value.time_preference = timePref
      editForms.value.time_hour = '09'
      editForms.value.time_minute = '00'
    }
    
    editForms.value.template_id = inspection.value.template_id
    editForms.value.inspector_id = inspection.value.inspector?.id || null
    editForms.value.typist_id = inspection.value.typist?.id || null
    editForms.value.key_location = inspection.value.key_location || ''
    editForms.value.key_return = inspection.value.key_return || ''
    editForms.value.internal_notes = inspection.value.internal_notes || ''
    editForms.value.tenant_email = inspection.value.tenant_email || ''
    editForms.value.client_email_override = inspection.value.client_email_override || inspection.value.client?.email || ''
    // Load property photo
    localPhoto.value = inspection.value.property?.overview_photo || null
  } catch (error) {
    console.error('Failed to fetch inspection:', error)
    toast.error('Failed to load inspection')
    router.push('/inspections')
  } finally {
    loading.value = false
  }
}

async function fetchTemplates() {
  try {
    const response = await api.getTemplates()
    templates.value = response.data
  } catch (error) {
    console.error('Failed to fetch templates:', error)
  }
}

async function fetchUsers() {
  try {
    const response = await api.getUsers()
    users.value = response.data
  } catch (error) {
    console.error('Failed to fetch users:', error)
  }
}

const clerks = computed(() => users.value.filter(u => u.role === 'clerk'))
const typists = computed(() => users.value.filter(u => u.role === 'typist'))

async function updateField(field, value) {
  try {
    await api.updateInspection(inspection.value.id, { [field]: value })
    toast.success('Updated successfully')
    fetchInspection()
    // Close all modals
    showEditConductDate.value = false
    showEditTemplate.value = false
    showEditClerk.value = false
    showEditTypist.value = false
    showEditKeyLocation.value = false
    showEditKeyReturn.value = false
    showEditNotes.value = false
    showEditTenantEmail.value = false
    showEditClientEmail.value = false
  } catch (error) {
    console.error('Failed to update:', error)
    toast.error('Failed to update')
  }
}

async function saveConductDateTime() {
  try {
    const updates = {}
    
    // Save date if provided (now comes from date picker in YYYY-MM-DD format)
    if (editForms.value.conduct_date) {
      updates.conduct_date = editForms.value.conduct_date + 'T00:00:00'
    }
    
    // Build time preference string
    let timePreference = editForms.value.time_preference
    if (timePreference === 'specific') {
      timePreference = `specific:${editForms.value.time_hour}_${editForms.value.time_minute}`
    }
    updates.conduct_time_preference = timePreference
    
    await api.updateInspection(inspection.value.id, updates)
    toast.success('Date and time updated')
    fetchInspection()
    showEditConductDate.value = false
  } catch (error) {
    console.error('Failed to update:', error)
    toast.error('Failed to update date and time')
  }
}

async function changeStatus(newStatus) {
  if (!confirm(`Move inspection to "${statusSteps.find(s => s.key === newStatus)?.label}"?`)) return
  try {
    await api.updateInspection(inspection.value.id, { status: newStatus })
    inspection.value.status = newStatus
    toast.success(`Status updated to ${statusSteps.find(s => s.key === newStatus)?.label}`)
  } catch (error) {
    console.error('Failed to change status:', error)
    toast.error('Failed to update status')
  }
}

async function advanceStatus() {
  if (!nextStep.value) return
  await changeStatus(nextStep.value.key)
}

async function revertStatus() {
  if (!prevStep.value) return
  await changeStatus(prevStep.value.key)
}

function formatDate(dateString) {
  if (!dateString) return 'Not set'
  return convertDateToUKFormat(dateString)
}

// ── Property photo ──────────────────────────────────────────────────
function onPhotoFileChange(e) {
  const file = e.target.files[0]
  if (!file) return
  if (file.size > 8 * 1024 * 1024) { toast.error('Photo must be under 8MB'); return }
  const reader = new FileReader()
  reader.onload = (ev) => { localPhoto.value = ev.target.result }
  reader.readAsDataURL(file)
}

async function savePhoto() {
  if (!inspection.value?.property_id) return
  photoUploading.value = true
  try {
    await api.updateProperty(inspection.value.property_id, { overview_photo: localPhoto.value })
    toast.success('Property photo saved')
    showPhotoModal.value = false
    fetchInspection()
  } catch {
    toast.error('Failed to save photo')
  } finally {
    photoUploading.value = false
  }
}

// ── Preview branding ─────────────────────────────────────────────────
const previewTemplate = computed(() => {
  if (!inspection.value?.template_id) return null
  return templates.value.find(t => t.id === inspection.value.template_id) || null
})

const previewBranding = computed(() => ({
  primaryColor: inspection.value?.client?.primary_color || '#1E3A8A',
  clientName:   inspection.value?.client?.name || 'Client',
  logoText:     (inspection.value?.client?.name || 'CL').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase(),
  logoUrl:      inspection.value?.client?.logo || null,
  photoUrl:     localPhoto.value || inspection.value?.property?.overview_photo || null,
  disclaimer:   inspection.value?.client?.report_disclaimer || null,
}))

onMounted(() => {
  fetchInspection()
  fetchTemplates()
  fetchUsers()
})
</script>

<template>
  <div class="inspection-detail">
    <div v-if="loading" class="loading">Loading inspection...</div>

    <div v-else-if="inspection">
      <!-- Header -->
      <div class="detail-header">
        <button @click="router.push('/inspections')" class="btn-back">
          ← Back to Inspections
        </button>
        <h1>Inspection #{{ inspection.id }}</h1>
      </div>

      <!-- Status + Workflow Action Bar -->
      <div class="workflow-bar">
        <!-- Progress track -->
        <div class="status-track">
          <div
            v-for="(step, index) in statusSteps"
            :key="step.key"
            class="status-step"
            :class="{
              'status-step--completed': index < currentStepIndex,
              'status-step--active': index === currentStepIndex,
              'status-step--pending': index > currentStepIndex
            }"
          >
            <div class="step-bubble">
              <svg v-if="index < currentStepIndex" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              <span v-else class="step-num">{{ index + 1 }}</span>
            </div>
            <span class="step-label">{{ step.label }}</span>
            <div v-if="index < statusSteps.length - 1" class="step-connector" :class="{ 'step-connector--done': index < currentStepIndex }"></div>
          </div>
        </div>

        <!-- Action buttons -->
        <div class="workflow-actions">
          <!-- Current status badge -->
          <div
            class="current-status-badge"
            :style="{
              background: statusColors[inspection.status]?.bg,
              color: statusColors[inspection.status]?.text
            }"
          >
            <div class="status-dot" :style="{ background: statusColors[inspection.status]?.dot }"></div>
            {{ statusSteps.find(s => s.key === inspection.status)?.label }}
          </div>

          <!-- Back button (managers only) -->
          <button
            v-if="canGoBack"
            @click="revertStatus"
            class="btn-status-back"
            :title="`Move back to ${prevStep?.label}`"
          >
            ← {{ prevStep?.label }}
          </button>

          <!-- Advance button -->
          <button
            v-if="canAdvance"
            @click="advanceStatus"
            class="btn-status-advance"
            :style="{ background: statusColors[nextStep?.key]?.dot }"
          >
            Advance to {{ nextStep?.label }} →
          </button>

          <!-- Preview button — always visible when template assigned -->
          <button
            v-if="inspection.template_id && previewTemplate"
            @click="showPreview = true"
            class="btn-preview-report"
          >
            👁 Preview Report
          </button>

          <!-- Edit Report button — visible when Active or Review -->
          <button
            v-if="['active', 'processing', 'review'].includes(inspection.status)"
            @click="router.push(`/inspections/${inspection.id}/report`)"
            class="btn-edit-report"
          >
            ✍️ Edit Report
          </button>

          <!-- Complete state -->
          <div v-if="inspection.status === 'complete'" class="complete-badge">
            ✅ Inspection Complete
          </div>
        </div>
      </div>

      <!-- Main Content Grid -->
      <div class="content-grid">
        
        <!-- Left Column -->
        <div class="left-column">
          
          <!-- Property Overview Photo -->
          <div class="info-card photo-card">
            <div class="card-header" style="padding: 14px 20px;">
              <h3>🏠 Property Overview</h3>
              <button class="btn-edit" @click="showPhotoModal = true">
                {{ localPhoto ? '✏️ Edit' : '+ Add Photo' }}
              </button>
            </div>
            <div class="photo-card-body">
              <img v-if="localPhoto" :src="localPhoto" alt="Property overview" class="property-photo-img" />
              <div v-else class="photo-placeholder">
                <span class="photo-icon">🏠</span>
                <p>No overview photo yet</p>
                <p style="font-size:12px;opacity:0.7;">Appears on the report cover page</p>
              </div>
            </div>
          </div>

          <!-- Conduct Date & Time -->
          <div class="info-card">
            <div class="card-header">
              <h3>📅 Conduct Date & Time</h3>
              <button v-if="canEdit" @click="showEditConductDate = true" class="btn-edit">✏️ Edit</button>
            </div>
            <div class="card-content">
              <p class="date-display">{{ formatDate(inspection.conduct_date) }}</p>
              <p class="time-display">🕐 {{ displayTimePreference }}</p>
            </div>
          </div>

          <!-- Template -->
          <div class="info-card">
            <div class="card-header">
              <h3>📋 Template</h3>
              <button v-if="canEdit" @click="showEditTemplate = true" class="btn-edit">✏️ Edit</button>
            </div>
            <div class="card-content">
              <p>{{ inspection.template_name || 'No template assigned' }}</p>
              <span class="badge">{{ inspection.inspection_type.replace('_', ' ').toUpperCase() }}</span>
            </div>
          </div>

          <!-- Assignments -->
          <div class="info-card">
            <div class="card-header">
              <h3>👥 Assignments</h3>
            </div>
            <div class="card-content">
              <div class="assignment-row">
                <strong>Clerk:</strong>
                <span>{{ inspection.inspector?.name || 'Not assigned' }}</span>
                <button v-if="canEdit" @click="showEditClerk = true" class="btn-edit-inline">✏️</button>
              </div>
              <div class="assignment-row">
                <strong>Typist:</strong>
                <span>{{ inspection.typist?.name || 'Not assigned' }}</span>
                <button v-if="canEdit" @click="showEditTypist = true" class="btn-edit-inline">✏️</button>
              </div>
            </div>
          </div>

          <!-- Key Location & Return -->
          <div class="info-card">
            <div class="card-header">
              <h3>🔑 Key Information</h3>
            </div>
            <div class="card-content">
              <div class="key-section">
                <div class="key-header">
                  <strong>Key Location</strong>
                  <button v-if="canEdit" @click="showEditKeyLocation = true" class="btn-edit-inline">✏️</button>
                </div>
                <p>{{ inspection.key_location || 'Not specified' }}</p>
              </div>
              <div class="key-section">
                <div class="key-header">
                  <strong>Key Return</strong>
                  <button v-if="canEdit" @click="showEditKeyReturn = true" class="btn-edit-inline">✏️</button>
                </div>
                <p>{{ inspection.key_return || 'Not specified' }}</p>
              </div>
            </div>
          </div>

        </div>

        <!-- Right Column -->
        <div class="right-column">
          
          <!-- Client Info -->
          <div class="info-card" v-if="inspection.client">
            <div class="card-header">
              <h3>👤 Client</h3>
            </div>
            <div class="card-content">
              <h4>{{ inspection.client.name }}</h4>
              <p v-if="inspection.client.company" class="company">🏢 {{ inspection.client.company }}</p>
            </div>
          </div>

          <!-- Contact Details -->
          <div class="info-card">
            <div class="card-header">
              <h3>📞 Contacts</h3>
            </div>
            <div class="card-content">
              <div class="contact-row">
                <strong>Email:</strong>
                <span>{{ displayClientEmail }}</span>
                <button v-if="canEdit" @click="showEditClientEmail = true" class="btn-edit-inline">✏️</button>
              </div>
              <div class="contact-row" v-if="inspection.client?.phone">
                <strong>Phone:</strong>
                <a :href="`tel:${inspection.client.phone}`">{{ inspection.client.phone }}</a>
              </div>
              <div class="contact-row">
                <strong>Tenant:</strong>
                <span>{{ inspection.tenant_email || 'Not specified' }}</span>
                <button v-if="canEdit" @click="showEditTenantEmail = true" class="btn-edit-inline">✏️</button>
              </div>
              <div class="contact-row" v-if="inspection.typist?.email">
                <strong>Typist:</strong>
                <a :href="`mailto:${inspection.typist.email}`">{{ inspection.typist.email }}</a>
              </div>
            </div>
          </div>

          <!-- Property Address -->
          <div class="info-card" v-if="inspection.property">
            <div class="card-header">
              <h3>📍 Address</h3>
            </div>
            <div class="card-content">
              <div class="address-container">
                <a 
                  :href="`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(inspection.property.address)}`" 
                  target="_blank"
                  class="map-button"
                  title="View on Google Maps"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                    <circle cx="12" cy="10" r="3"></circle>
                  </svg>
                </a>
                <p class="address-text">{{ inspection.property.address }}</p>
              </div>
            </div>
          </div>

          <!-- Property Details -->
          <div class="info-card" v-if="inspection.property">
            <div class="card-header">
              <h3>🏠 Property Details</h3>
            </div>
            <div class="card-content">
              <div class="detail-row">
                <strong>Type:</strong>
                <span>{{ inspection.property.property_type }}</span>
              </div>
              <div class="detail-row" v-if="inspection.property.bedrooms">
                <strong>Bedrooms:</strong>
                <span>{{ inspection.property.bedrooms }}</span>
              </div>
              <div class="detail-row" v-if="inspection.property.bathrooms">
                <strong>Bathrooms:</strong>
                <span>{{ inspection.property.bathrooms }}</span>
              </div>
              <div class="detail-row" v-if="inspection.property.furnished">
                <strong>Furnished:</strong>
                <span>{{ inspection.property.furnished }}</span>
              </div>
              <div class="detail-row" v-if="inspection.property.parking">
                <strong>Parking:</strong>
                <span>{{ inspection.property.parking }}</span>
              </div>
              <div class="detail-row" v-if="inspection.property.garden">
                <strong>Garden:</strong>
                <span>{{ inspection.property.garden }}</span>
              </div>
            </div>
          </div>

          <!-- Internal Notes -->
          <div class="info-card">
            <div class="card-header">
              <h3>📝 Internal Notes</h3>
              <button v-if="canEdit" @click="showEditNotes = true" class="btn-edit">✏️ Edit</button>
            </div>
            <div class="card-content">
              <p class="notes-text">{{ inspection.internal_notes || 'No notes added yet' }}</p>
            </div>
          </div>

        </div>
      </div>

      <!-- Modals -->
      
      <!-- Edit Conduct Date & Time -->
      <div v-if="showEditConductDate" class="modal-overlay" @click.self="showEditConductDate = false">
        <div class="modal modal-large">
          <div class="modal-header">
            <h2>Edit Conduct Date & Time</h2>
            <button @click="showEditConductDate = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            
            <div class="form-group">
              <label>Date</label>
              <input 
                v-model="editForms.conduct_date" 
                type="date" 
                class="input-field date-picker" 
              />
              <p class="helper-text">Selected: {{ editForms.conduct_date ? convertDateToUKFormat(editForms.conduct_date + 'T00:00:00') : 'No date selected' }}</p>
            </div>

            <div class="form-group">
              <label>Time Preference</label>
              <select v-model="editForms.time_preference" class="input-field">
                <option v-for="option in timePreferenceOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>

            <div v-if="editForms.time_preference === 'specific'" class="time-selection">
              <div class="form-row">
                <div class="form-group">
                  <label>Hour</label>
                  <select v-model="editForms.time_hour" class="input-field">
                    <option v-for="hour in hourOptions" :key="hour" :value="hour">
                      {{ hour }}:00
                    </option>
                  </select>
                </div>

                <div class="form-group">
                  <label>Minute</label>
                  <select v-model="editForms.time_minute" class="input-field">
                    <option v-for="minute in minuteOptions" :key="minute" :value="minute">
                      :{{ minute }}
                    </option>
                  </select>
                </div>
              </div>
              <p class="helper-text">Selected time: {{ editForms.time_hour }}:{{ editForms.time_minute }}</p>
            </div>

          </div>
          <div class="modal-footer">
            <button @click="showEditConductDate = false" class="btn-secondary">Cancel</button>
            <button @click="saveConductDateTime" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Template -->
      <div v-if="showEditTemplate" class="modal-overlay" @click.self="showEditTemplate = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Edit Template</h2>
            <button @click="showEditTemplate = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <select v-model="editForms.template_id" class="input-field">
              <option :value="null">No template</option>
              <option v-for="template in templates" :key="template.id" :value="template.id">
                {{ template.name }}
              </option>
            </select>
          </div>
          <div class="modal-footer">
            <button @click="showEditTemplate = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('template_id', editForms.template_id)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Clerk -->
      <div v-if="showEditClerk" class="modal-overlay" @click.self="showEditClerk = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Assign Clerk</h2>
            <button @click="showEditClerk = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <select v-model="editForms.inspector_id" class="input-field">
              <option :value="null">Not assigned</option>
              <option v-for="clerk in clerks" :key="clerk.id" :value="clerk.id">
                {{ clerk.name }} ({{ clerk.email }})
              </option>
            </select>
            <p class="helper-text" style="margin-top: 12px; font-size: 12px; color: #64748b;">
              ℹ️ Removing clerk assignment will automatically revert status to "Created"
            </p>
          </div>
          <div class="modal-footer">
            <button @click="showEditClerk = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('inspector_id', editForms.inspector_id)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Typist -->
      <div v-if="showEditTypist" class="modal-overlay" @click.self="showEditTypist = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Assign Typist</h2>
            <button @click="showEditTypist = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <select v-model="editForms.typist_id" class="input-field">
              <option :value="null">No typist</option>
              <option v-for="typist in typists" :key="typist.id" :value="typist.id">
                {{ typist.name }} ({{ typist.email }})
              </option>
            </select>
          </div>
          <div class="modal-footer">
            <button @click="showEditTypist = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('typist_id', editForms.typist_id)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Key Location -->
      <div v-if="showEditKeyLocation" class="modal-overlay" @click.self="showEditKeyLocation = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Edit Key Location</h2>
            <button @click="showEditKeyLocation = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <select v-model="editForms.key_location" class="input-field">
              <option value="">Not specified</option>
              <option v-for="option in keyLocationOptions" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
          </div>
          <div class="modal-footer">
            <button @click="showEditKeyLocation = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('key_location', editForms.key_location)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Key Return -->
      <div v-if="showEditKeyReturn" class="modal-overlay" @click.self="showEditKeyReturn = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Edit Key Return</h2>
            <button @click="showEditKeyReturn = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <select v-model="editForms.key_return" class="input-field">
              <option value="">Not specified</option>
              <option v-for="option in keyReturnOptions" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
          </div>
          <div class="modal-footer">
            <button @click="showEditKeyReturn = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('key_return', editForms.key_return)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Tenant Email -->
      <div v-if="showEditTenantEmail" class="modal-overlay" @click.self="showEditTenantEmail = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Edit Tenant Email</h2>
            <button @click="showEditTenantEmail = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <input 
              v-model="editForms.tenant_email" 
              type="text" 
              class="input-field" 
              placeholder="tenant@example.com, tenant2@example.com"
            />
            <p class="helper-text" style="margin-top: 8px;">
              💡 Enter multiple email addresses separated by commas
            </p>
          </div>
          <div class="modal-footer">
            <button @click="showEditTenantEmail = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('tenant_email', editForms.tenant_email)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Client Email -->
      <div v-if="showEditClientEmail" class="modal-overlay" @click.self="showEditClientEmail = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Edit Client Email</h2>
            <button @click="showEditClientEmail = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <input 
              v-model="editForms.client_email_override" 
              type="text" 
              class="input-field" 
              placeholder="client@example.com, manager@example.com"
            />
            <p class="helper-text" style="margin-top: 8px;">
              💡 This overrides the default client email for this inspection only. Enter multiple addresses separated by commas.
            </p>
          </div>
          <div class="modal-footer">
            <button @click="showEditClientEmail = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('client_email_override', editForms.client_email_override)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

      <!-- Edit Notes -->
      <div v-if="showEditNotes" class="modal-overlay" @click.self="showEditNotes = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Edit Internal Notes</h2>
            <button @click="showEditNotes = false" class="btn-close">✕</button>
          </div>
          <div class="modal-body">
            <textarea v-model="editForms.internal_notes" class="input-field" rows="6"></textarea>
          </div>
          <div class="modal-footer">
            <button @click="showEditNotes = false" class="btn-secondary">Cancel</button>
            <button @click="updateField('internal_notes', editForms.internal_notes)" class="btn-primary">Save</button>
          </div>
        </div>
      </div>

    </div>
  </div>

    <!-- ══ PREVIEW MODAL ════════════════════════════════════════════════ -->
    <TemplatePreviewModal
      v-if="showPreview && previewTemplate"
      :template="previewTemplate"
      :branding="previewBranding"
      @close="showPreview = false"
    />

    <!-- ══ PHOTO EDIT MODAL ══════════════════════════════════════════════ -->
    <div v-if="showPhotoModal" class="modal-overlay" @click.self="showPhotoModal = false">
      <div class="photo-modal">
        <div class="modal-header">
          <h2>Property Overview Photo</h2>
          <button @click="showPhotoModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="localPhoto" class="photo-preview">
            <img :src="localPhoto" alt="Property overview" class="photo-preview-img" />
            <button class="photo-remove-btn" @click="localPhoto = null">× Remove photo</button>
          </div>
          <div v-else class="photo-dropzone">
            <span style="font-size:40px;">🏠</span>
            <p>No photo uploaded yet</p>
            <p style="font-size:12px;color:#94a3b8;">Appears on the report cover page</p>
          </div>
          <label class="photo-upload-label">
            {{ localPhoto ? '📷 Replace photo' : '📷 Upload photo' }}
            <input type="file" accept="image/*" style="display:none" @change="onPhotoFileChange" />
          </label>
          <p style="font-size:12px;color:#94a3b8;margin-top:6px;">JPG, PNG, WEBP — max 8MB</p>
        </div>
        <div class="modal-footer">
          <button @click="showPhotoModal = false" class="btn-secondary">Cancel</button>
          <button @click="savePhoto" :disabled="photoUploading || !localPhoto" class="btn-primary">
            {{ photoUploading ? 'Saving…' : 'Save Photo' }}
          </button>
        </div>
      </div>
    </div>

</template>

<style scoped>
.inspection-detail {
  max-width: 1600px;
  margin: 0 auto;
}

.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
  font-size: 18px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 32px;
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

.detail-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
}

/* ─── Workflow / Status Bar ──────────────────────────── */
.workflow-bar {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  margin-bottom: 28px;
  overflow: hidden;
}

/* Progress track */
.status-track {
  display: flex;
  align-items: center;
  padding: 20px 28px 16px;
  gap: 0;
  overflow-x: auto;
}

.status-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  flex: 1;
  min-width: 80px;
}

.step-bubble {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  transition: all 0.2s;
  position: relative;
  z-index: 1;
}

.status-step--completed .step-bubble {
  background: #10b981;
  color: white;
}

.status-step--active .step-bubble {
  background: #6366f1;
  color: white;
  box-shadow: 0 0 0 5px rgba(99, 102, 241, 0.15);
}

.status-step--pending .step-bubble {
  background: #f1f5f9;
  color: #94a3b8;
  border: 2px solid #e5e7eb;
}

.step-num { font-size: 11px; font-weight: 700; }

.step-label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  margin-top: 6px;
  text-align: center;
  white-space: nowrap;
}

.status-step--active .step-label   { color: #6366f1; }
.status-step--completed .step-label { color: #10b981; }

.step-connector {
  position: absolute;
  top: 16px;
  left: calc(50% + 16px);
  right: calc(-50% + 16px);
  height: 2px;
  background: #e5e7eb;
  z-index: 0;
}

.step-connector--done { background: #10b981; }

/* Action row */
.workflow-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 28px;
  border-top: 1px solid #f1f5f9;
  background: #fafafa;
  flex-wrap: wrap;
}

.current-status-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 700;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.btn-status-back {
  padding: 8px 16px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-status-back:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #1e293b;
}

.btn-status-advance {
  padding: 9px 20px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  color: white;
  cursor: pointer;
  transition: filter 0.15s;
  margin-left: auto;
}
.btn-status-advance:hover { filter: brightness(1.1); }

.btn-preview-report {
  padding: 9px 18px;
  background: #0f172a;
  border: 1.5px solid #334155;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-preview-report:hover {
  background: #1e293b;
  color: #e2e8f0;
  border-color: #475569;
}

.btn-edit-report {
  padding: 9px 18px;
  background: white;
  border: 1.5px solid #6366f1;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #6366f1;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-edit-report:hover {
  background: #eff6ff;
  border-color: #4f46e5;
  color: #4f46e5;
}

.complete-badge {
  margin-left: auto;
  font-size: 14px;
  font-weight: 700;
  color: #16a34a;
}

/* Content Grid */
.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.left-column,
.right-column {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Info Cards */
.info-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
  background: #f8fafc;
}

.card-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.btn-edit {
  padding: 6px 12px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-edit:hover {
  background: #4f46e5;
}

.btn-edit-inline {
  padding: 4px 8px;
  background: #e0e7ff;
  color: #4338ca;
  border: none;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-edit-inline:hover {
  background: #c7d2fe;
}

.card-content {
  padding: 24px;
}

/* Photo Card */
.photo-card .card-content {
  padding: 0;
}

.photo-card-body { position: relative; }

.property-photo-img {
  width: 100%;
  height: auto;
  max-height: 280px;
  object-fit: cover;
  display: block;
}

.photo-placeholder {
  height: 200px;
  background: linear-gradient(135deg, #1e3a5f 0%, #1e293b 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: white;
  gap: 6px;
}

.photo-icon {
  font-size: 48px;
}

.photo-placeholder p {
  font-size: 14px;
  font-weight: 600;
}

.photo-modal {
  background: white;
  border-radius: 12px;
  width: 500px;
  max-width: 95vw;
  box-shadow: 0 20px 60px rgba(0,0,0,0.25);
  overflow: hidden;
}

.photo-preview { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
.photo-preview-img { width: 100%; max-height: 260px; object-fit: cover; border-radius: 8px; border: 1px solid #e2e8f0; }
.photo-remove-btn { background: none; border: none; color: #ef4444; font-size: 13px; font-weight: 600; cursor: pointer; text-align: left; }
.photo-remove-btn:hover { text-decoration: underline; }
.photo-dropzone { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px; background: #f8fafc; border: 2px dashed #e2e8f0; border-radius: 8px; text-align: center; margin-bottom: 12px; color: #64748b; font-size: 14px; }
.photo-upload-label { display: inline-block; padding: 9px 18px; background: #6366f1; color: white; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; }
.photo-upload-label:hover { background: #4f46e5; }

/* Date & Time Display */
.date-display {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.time-display {
  font-size: 14px;
  color: #6366f1;
  font-weight: 600;
  background: #eff6ff;
  padding: 6px 12px;
  border-radius: 6px;
  display: inline-block;
}

/* Badge */
.badge {
  display: inline-block;
  padding: 4px 12px;
  background: #e0e7ff;
  color: #4338ca;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 8px;
}

/* Assignment Row */
.assignment-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.assignment-row:last-child {
  border-bottom: none;
}

.assignment-row strong {
  color: #64748b;
  font-size: 14px;
  min-width: 80px;
}

.assignment-row span {
  flex: 1;
  color: #1e293b;
  font-size: 14px;
}

/* Key Section */
.key-section {
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.key-section:last-child {
  border-bottom: none;
}

.key-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.key-header strong {
  color: #64748b;
  font-size: 14px;
}

.key-section p {
  color: #1e293b;
  font-size: 14px;
  line-height: 1.6;
}

/* Company */
.company {
  color: #6366f1;
  font-weight: 600;
  font-size: 14px;
  margin-top: 4px;
}

/* Contact Row */
.contact-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 14px;
}

.contact-row:last-child {
  border-bottom: none;
}

.contact-row strong {
  color: #64748b;
  min-width: 80px;
}

.contact-row span {
  flex: 1;
  color: #1e293b;
  word-break: break-word;
}

.contact-row a {
  color: #6366f1;
  text-decoration: none;
  flex: 1;
}

.contact-row a:hover {
  text-decoration: underline;
}

/* Address Container */
.address-container {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.map-button {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #eff6ff;
  border-radius: 8px;
  color: #2563eb;
  transition: all 0.2s;
  text-decoration: none;
}

.map-button:hover {
  background: #dbeafe;
  transform: scale(1.05);
}

.map-button svg {
  flex-shrink: 0;
}

.address-container .address-text {
  flex: 1;
  margin: 0;
}

/* Address */
.address-text {
  font-size: 16px;
  line-height: 1.6;
  color: #1e293b;
}

/* Detail Row */
.detail-row {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 14px;
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-row strong {
  color: #64748b;
  min-width: 100px;
}

.detail-row span {
  color: #1e293b;
  text-transform: capitalize;
}

/* Notes */
.notes-text {
  font-size: 14px;
  line-height: 1.7;
  color: #475569;
  white-space: pre-wrap;
}

/* Modals */
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
  max-width: 500px;
}

.modal-large {
  max-width: 600px;
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
}

.btn-close {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
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

.input-field {
  width: 100%;
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

select.input-field {
  background: white;
}

textarea.input-field {
  resize: vertical;
}

.date-picker {
  cursor: pointer;
}

.date-picker::-webkit-calendar-picker-indicator {
  cursor: pointer;
  font-size: 18px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.time-selection {
  background: #f8fafc;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.helper-text {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  margin-top: 6px;
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
  cursor: pointer;
  font-weight: 600;
}

.btn-primary {
  padding: 10px 20px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

.btn-primary:hover {
  background: #4f46e5;
}

/* Responsive */
@media (max-width: 1024px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
  
  .workflow-bar {
    overflow-x: auto;
  }
}
</style>
