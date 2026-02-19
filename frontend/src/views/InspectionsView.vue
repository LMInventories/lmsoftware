<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'
import { useToast } from '../composables/useToast'
import FullCalendar from '@fullcalendar/vue3'

const toast = useToast()
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'

const router = useRouter()

const activeTab = ref('list') // 'list' or 'calendar'
const calendarView = ref('dayGridMonth') // 'dayGridMonth', 'timeGridWeek', 'timeGridDay'
const calendarRef = ref(null) // Reference to FullCalendar component
const selectedDate = ref('') // For date picker
const showDatePicker = ref(false) // Toggle date picker modal
const inspections = ref([])
const properties = ref([])
const clients = ref([])
const users = ref([])
const templates = ref([])
const loading = ref(true)
const showModal = ref(false)

// Filters
const filters = ref({
  client_id: null,
  postcode: '',
  status: null,
  clerk_id: null
})

// Calendar filters
const calendarFilters = ref({
  client_id: null,
  status: null,
  clerk_id: null
})

const form = ref({
  client_id: null,
  property_id: null,
  inspection_type: 'check_in',
  template_id: null,
  inspector_id: null,
  typist_id: null,
  tenant_email: '',
  conduct_date: '',
  time_preference: 'anytime',
  time_hour: '09',
  time_minute: '00'
})

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

const statusColors = {
  created: '#94a3b8',
  assigned: '#3b82f6',
  active: '#10b981',
  processing: '#f59e0b',
  review: '#8b5cf6',
  complete: '#10b981'
}

const statusOptions = [
  { value: null, label: 'All Statuses' },
  { value: 'created', label: 'Created' },
  { value: 'assigned', label: 'Assigned' },
  { value: 'active', label: 'Active' },
  { value: 'processing', label: 'Processing' },
  { value: 'review', label: 'Review' },
  { value: 'complete', label: 'Complete' }
]

// FullCalendar plugins and options
const calendarOptions = computed(() => ({
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin],
  initialView: calendarView.value,
  firstDay: 1, // Start week on Monday
  headerToolbar: {
    left: 'prev,next today',
    center: 'title',
    right: 'dayGridMonth,timeGridWeek,timeGridDay'
  },
  events: calendarEvents.value,
  eventClick: handleEventClick,
  height: 'auto',
  slotMinTime: '09:00:00',
  slotMaxTime: '18:00:00',
  allDaySlot: true,
  nowIndicator: true,
  eventTimeFormat: {
    hour: '2-digit',
    minute: '2-digit',
    meridiem: false,
    hour12: false
  }
}))

// Convert inspections to calendar events
const calendarEvents = computed(() => {
  let filtered = [...inspections.value]
  
  // Apply calendar filters
  if (calendarFilters.value.client_id) {
    filtered = filtered.filter(i => i.client_id === calendarFilters.value.client_id)
  }
  
  if (calendarFilters.value.status) {
    filtered = filtered.filter(i => i.status === calendarFilters.value.status)
  }
  
  if (calendarFilters.value.clerk_id) {
    filtered = filtered.filter(i => i.inspector_id === calendarFilters.value.clerk_id)
  }
  
  return filtered
    .filter(i => i.conduct_date) // Only show inspections with dates
    .map(inspection => {
      let eventTime = null
      
      // Parse time preference
      if (inspection.conduct_time_preference) {
        const pref = inspection.conduct_time_preference
        if (pref.startsWith('specific:')) {
          const [, time] = pref.split(':')
          const [hour, minute] = time.split('_')
          eventTime = `${hour}:${minute}:00`
        }
      }
      
      const eventDate = inspection.conduct_date.split('T')[0]
      
      // Extract postcode from address (last part)
      let postcode = ''
      if (inspection.property_address) {
        const addressParts = inspection.property_address.split(',').map(p => p.trim())
        postcode = addressParts[addressParts.length - 1] || ''
      }
      
      // Format inspection type (e.g., "Check In" -> "C/I", "Check Out" -> "C/O")
      let typeShort = ''
      switch(inspection.inspection_type) {
        case 'check_in':
          typeShort = 'C/I'
          break
        case 'check_out':
          typeShort = 'C/O'
          break
        case 'inventory':
          typeShort = 'INV'
          break
        case 'mid_term':
          typeShort = 'M/T'
          break
        default:
          typeShort = inspection.inspection_type.substring(0, 3).toUpperCase()
      }
      
      // Create compact title
      const title = `${typeShort} - ${postcode}`
      
      // Get clerk color
      const assignedClerk = users.value.find(u => u.id === inspection.inspector_id)
      const clerkColor = assignedClerk?.color || '#6366f1'
      
      return {
        id: inspection.id,
        title: title,
        start: eventTime ? `${eventDate}T${eventTime}` : eventDate,
        allDay: !eventTime,
        backgroundColor: clerkColor,
        borderColor: clerkColor,
        extendedProps: {
          inspectionType: inspection.inspection_type,
          clerkName: inspection.inspector_name,
          clientName: inspection.client_name,
          status: inspection.status,
          fullAddress: inspection.property_address
        }
      }
    })
})

// Filtered inspections for list view
const filteredInspections = computed(() => {
  let result = [...inspections.value]
  
  // Filter by client
  if (filters.value.client_id) {
    result = result.filter(i => i.client_id === filters.value.client_id)
  }
  
  // Filter by postcode
  if (filters.value.postcode) {
    const searchPostcode = filters.value.postcode.toLowerCase()
    result = result.filter(i => 
      i.property_address && i.property_address.toLowerCase().includes(searchPostcode)
    )
  }
  
  // Filter by status
  if (filters.value.status) {
    result = result.filter(i => i.status === filters.value.status)
  }
  
  // Filter by clerk
  if (filters.value.clerk_id) {
    result = result.filter(i => i.inspector_id === filters.value.clerk_id)
  }
  
  return result
})

// Filter properties by selected client
const filteredProperties = computed(() => {
  if (!form.value.client_id) {
    return properties.value
  }
  return properties.value.filter(p => p.client_id === form.value.client_id)
})

// Filter users by role
const clerks = computed(() => {
  return users.value.filter(u => u.role === 'clerk')
})

const typists = computed(() => {
  return users.value.filter(u => u.role === 'typist')
})

const filteredTemplates = computed(() => {
  return templates.value.filter(t => t.inspection_type === form.value.inspection_type)
})

function convertDateToUKFormat(isoDate) {
  if (!isoDate) return ''
  const date = new Date(isoDate)
  const day = String(date.getDate()).padStart(2, '0')
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const year = date.getFullYear()
  return `${day}/${month}/${year}`
}

function clearFilters() {
  filters.value = {
    client_id: null,
    postcode: '',
    status: null,
    clerk_id: null
  }
}

function clearCalendarFilters() {
  calendarFilters.value = {
    client_id: null,
    status: null,
    clerk_id: null
  }
}

function handleEventClick(info) {
  const inspectionId = info.event.id
  router.push(`/inspections/${inspectionId}`)
}

// Open date picker
function openDatePicker() {
  // Set to today's date initially
  const today = new Date()
  selectedDate.value = today.toISOString().split('T')[0]
  showDatePicker.value = true
}

// Go to selected date in day view
function goToDate() {
  if (selectedDate.value && calendarRef.value) {
    const calendarApi = calendarRef.value.getApi()
    calendarApi.changeView('timeGridDay', selectedDate.value)
    showDatePicker.value = false
  }
}

async function fetchTemplates() {
  try {
    const res = await api.getTemplates()
    templates.value = res.data
  } catch (e) {
    console.error('Failed to fetch templates:', e)
  }
}

async function fetchInspections() {
  loading.value = true
  try {
    const response = await api.getInspections()
    inspections.value = response.data
  } catch (error) {
    console.error('Failed to fetch inspections:', error)
    toast.error('Failed to load inspections')
  } finally {
    loading.value = false
  }
}

async function fetchProperties() {
  try {
    const response = await api.getProperties()
    properties.value = response.data
  } catch (error) {
    console.error('Failed to fetch properties:', error)
  }
}

async function fetchClients() {
  try {
    const response = await api.getClients()
    clients.value = response.data
  } catch (error) {
    console.error('Failed to fetch clients:', error)
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

function openModal() {
  form.value = {
    client_id: null,
    property_id: null,
    inspection_type: 'check_in',
    inspector_id: null,
    template_id: null,
    typist_id: null,
    tenant_email: '',
    conduct_date: '',
    time_preference: 'anytime',
    time_hour: '09',
    time_minute: '00'
  }
  showModal.value = true
}

// Reset property selection when client changes
function onClientChange() {
  form.value.property_id = null
}

async function handleSubmit() {
  if (!form.value.property_id) {
    toast.warning('Please select a property')
    return
  }

  if (!form.value.inspector_id) {
    toast.warning('Please assign a clerk')
    return
  }

  try {
    let timePreference = form.value.time_preference
    if (timePreference === 'specific') {
      timePreference = `specific:${form.value.time_hour}_${form.value.time_minute}`
    }

    const payload = {
      property_id: form.value.property_id,
      inspection_type: form.value.inspection_type,
      inspector_id: form.value.inspector_id,
      typist_id: form.value.typist_id,
      template_id: form.value.template_id || null,
      tenant_email: form.value.tenant_email,
      conduct_time_preference: timePreference
    }

    if (form.value.conduct_date) {
      payload.conduct_date = form.value.conduct_date + 'T00:00:00'
    }

    await api.createInspection(payload)
    toast.success('Inspection created')
    showModal.value = false
    fetchInspections()
  } catch (error) {
    console.error('Failed to create inspection:', error)
    toast.error('Failed to create inspection')
  }
}

async function deleteInspection(id) {
  if (!confirm('Delete this inspection?')) return

  try {
    await api.deleteInspection(id)
    toast.success('Inspection deleted')
    fetchInspections()
  } catch (error) {
    console.error('Failed to delete inspection:', error)
    toast.error('Failed to delete inspection')
  }
}

function viewInspection(id) {
  router.push(`/inspections/${id}`)
}

onMounted(() => {
  fetchInspections()
  fetchProperties()
  fetchClients()
  fetchUsers()
  fetchTemplates()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>📋 Inspections</h1>
      <button @click="openModal" class="btn-primary">➕ New Inspection</button>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button 
        @click="activeTab = 'list'" 
        class="tab-button"
        :class="{ active: activeTab === 'list' }"
      >
        📄 List View
      </button>
      <button 
        @click="activeTab = 'calendar'" 
        class="tab-button"
        :class="{ active: activeTab === 'calendar' }"
      >
        📅 Calendar View
      </button>
    </div>

    <!-- List View -->
    <div v-if="activeTab === 'list'">
      
      <!-- Filters -->
      <div class="filters-bar">
        <div class="filter-group">
          <label>Client</label>
          <select v-model="filters.client_id" class="filter-select">
            <option :value="null">All Clients</option>
            <option v-for="client in clients" :key="client.id" :value="client.id">
              {{ client.name }}
            </option>
          </select>
        </div>

        <div class="filter-group">
          <label>Postcode</label>
          <input 
            v-model="filters.postcode" 
            type="text" 
            placeholder="Search postcode..."
            class="filter-input"
          />
        </div>

        <div class="filter-group">
          <label>Workflow Stage</label>
          <select v-model="filters.status" class="filter-select">
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>

        <div class="filter-group">
          <label>Clerk</label>
          <select v-model="filters.clerk_id" class="filter-select">
            <option :value="null">All Clerks</option>
            <option v-for="clerk in clerks" :key="clerk.id" :value="clerk.id">
              {{ clerk.name }}
            </option>
          </select>
        </div>

        <button @click="clearFilters" class="btn-clear-filters">Clear Filters</button>
      </div>

      <div v-if="loading" class="loading">Loading...</div>

      <div v-else class="inspections-list">
        <div v-for="inspection in filteredInspections" :key="inspection.id" class="inspection-card">
          <div class="inspection-header">
            <div>
              <h3>{{ inspection.property_address }}</h3>
              <p class="inspection-type">{{ inspection.inspection_type.replace('_', ' ').toUpperCase() }}</p>
            </div>
            <span 
              class="status-badge" 
              :style="{ backgroundColor: statusColors[inspection.status] }"
            >
              {{ inspection.status }}
            </span>
          </div>

          <div class="inspection-details">
            <p v-if="inspection.client_name">🏢 {{ inspection.client_name }}</p>
            <p v-if="inspection.inspector_name">👤 Clerk: {{ inspection.inspector_name }}</p>
            <p v-if="inspection.conduct_date">📅 Conduct: {{ new Date(inspection.conduct_date).toLocaleDateString('en-GB') }}</p>
            <p>🕐 Created: {{ new Date(inspection.created_at).toLocaleDateString('en-GB') }}</p>
          </div>

          <div class="inspection-actions">
            <button @click="viewInspection(inspection.id)" class="btn-view">View Details</button>
            <button @click="deleteInspection(inspection.id)" class="btn-delete">Delete</button>
          </div>
        </div>

        <div v-if="filteredInspections.length === 0" class="empty-state">
          {{ filters.client_id || filters.postcode || filters.status || filters.clerk_id 
            ? 'No inspections match your filters.' 
            : 'No inspections yet. Create your first inspection!' }}
        </div>
      </div>
    </div>

    <!-- Calendar View -->
    <div v-if="activeTab === 'calendar'" class="calendar-view">
      
      <!-- Calendar Filters -->
      <div class="filters-bar calendar-filters">
        <div class="filter-group">
          <label>Client</label>
          <select v-model="calendarFilters.client_id" class="filter-select">
            <option :value="null">All Clients</option>
            <option v-for="client in clients" :key="client.id" :value="client.id">
              {{ client.name }}
            </option>
          </select>
        </div>

        <div class="filter-group">
          <label>Workflow Stage</label>
          <select v-model="calendarFilters.status" class="filter-select">
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>

        <div class="filter-group">
          <label>Clerk</label>
          <select v-model="calendarFilters.clerk_id" class="filter-select">
            <option :value="null">All Clerks</option>
            <option v-for="clerk in clerks" :key="clerk.id" :value="clerk.id">
              {{ clerk.name }}
            </option>
          </select>
        </div>

        <button @click="clearCalendarFilters" class="btn-clear-filters">Clear Filters</button>
        <button @click="openDatePicker" class="btn-date-picker">📅 Go to Date</button>
      </div>

      <div v-if="loading" class="loading">Loading calendar...</div>

      <!-- Calendar Component -->
      <div v-else class="calendar-container">
        <FullCalendar ref="calendarRef" :options="calendarOptions" />
      </div>

      <!-- Legend -->
      <div class="calendar-legend">
        <h4>Clerk Legend:</h4>
        <div class="legend-items">
          <div v-for="clerk in clerks" :key="clerk.id" class="legend-item">
            <span class="legend-color" :style="{ background: clerk.color }"></span>
            <span>{{ clerk.name }}</span>
          </div>
          <div v-if="clerks.length === 0" class="empty-legend">
            No clerks assigned yet
          </div>
        </div>
      </div>
    </div>

    <!-- Create Inspection Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal modal-large">
        <div class="modal-header">
          <h2>New Inspection</h2>
          <button @click="showModal = false" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleSubmit" class="modal-body">
          
          <!-- Client Selection -->
          <div class="form-group">
            <label>Client *</label>
            <select v-model="form.client_id" @change="onClientChange" required>
              <option :value="null" disabled>Select a client...</option>
              <option v-for="client in clients" :key="client.id" :value="client.id">
                {{ client.name }} {{ client.company ? `(${client.company})` : '' }}
              </option>
            </select>
          </div>

          <!-- Property Selection (filtered by client) -->
          <div class="form-group">
            <label>Property *</label>
            <select v-model="form.property_id" required :disabled="!form.client_id">
              <option :value="null" disabled>
                {{ form.client_id ? 'Select a property...' : 'Please select a client first' }}
              </option>
              <option v-for="property in filteredProperties" :key="property.id" :value="property.id">
                {{ property.address }}
              </option>
            </select>
            <p v-if="form.client_id && filteredProperties.length === 0" class="helper-text">
              No properties found for this client. Please add a property first.
            </p>
          </div>

          <!-- Inspection Type -->
          <div class="form-group">
            <label>Inspection Type *</label>
            <select v-model="form.inspection_type" required>
              <option value="check_in">Check In</option>
              <option value="check_out">Check Out</option>
              <option value="inventory">Inventory</option>
              <option value="mid_term">Mid Term</option>
            </select>
          </div>

          <!-- Conduct Date & Time -->
          <div class="form-section">
            <h3 class="section-title">📅 Conduct Date & Time (Optional)</h3>
            
            <div class="form-group">
              <label>Date</label>
              <input 
                v-model="form.conduct_date" 
                type="date" 
                class="input-field date-picker-input" 
              />
              <p class="helper-text">Selected: {{ form.conduct_date ? convertDateToUKFormat(form.conduct_date + 'T00:00:00') : 'No date selected' }}</p>
            </div>

            <div class="form-group">
              <label>Time Preference</label>
              <select v-model="form.time_preference" class="input-field">
                <option v-for="option in timePreferenceOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>

            <div v-if="form.time_preference === 'specific'" class="time-selection">
              <div class="form-row">
                <div class="form-group">
                  <label>Hour</label>
                  <select v-model="form.time_hour" class="input-field">
                    <option v-for="hour in hourOptions" :key="hour" :value="hour">
                      {{ hour }}:00
                    </option>
                  </select>
                </div>

                <div class="form-group">
                  <label>Minute</label>
                  <select v-model="form.time_minute" class="input-field">
                    <option v-for="minute in minuteOptions" :key="minute" :value="minute">
                      :{{ minute }}
                    </option>
                  </select>
                </div>
              </div>
              <p class="helper-text">Selected time: {{ form.time_hour }}:{{ form.time_minute }}</p>
            </div>
          </div>

          <!-- Template Assignment -->
          <div class="form-section">
            <h3 class="section-title">📋 Report Template</h3>
            <div class="form-group">
              <label>Template</label>
              <select v-model="form.template_id" class="input-field">
                <option :value="null">— Use default for {{ form.inspection_type.replace('_', ' ') }} —</option>
                <option v-for="t in filteredTemplates" :key="t.id" :value="t.id">
                  {{ t.name }}{{ t.is_default ? ' ★ Default' : '' }}
                </option>
              </select>
              <p v-if="filteredTemplates.length === 0" class="helper-text warning">
                ⚠️ No templates found for this inspection type. Create one in Settings → Templates.
              </p>
              <p v-else class="helper-text">
                {{ filteredTemplates.length }} template{{ filteredTemplates.length !== 1 ? 's' : '' }} available for this type.
                Leave blank to use the default.
              </p>
            </div>
          </div>

          <!-- Assign Clerk -->
          <div class="form-group">
            <label>Assign Clerk (Inspector) *</label>
            <select v-model="form.inspector_id" required>
              <option :value="null" disabled>Select a clerk...</option>
              <option v-for="clerk in clerks" :key="clerk.id" :value="clerk.id">
                {{ clerk.name }} ({{ clerk.email }})
              </option>
            </select>
            <p v-if="clerks.length === 0" class="helper-text warning">
              ⚠️ No clerks available. Please create clerk users first.
            </p>
          </div>

          <!-- Assign Typist -->
          <div class="form-group">
            <label>Assign Typist (Optional)</label>
            <select v-model="form.typist_id">
              <option :value="null">None (assign later at Processing stage)</option>
              <option v-for="typist in typists" :key="typist.id" :value="typist.id">
                {{ typist.name }} ({{ typist.email }})
              </option>
            </select>
            <p class="helper-text">
              Typists handle the "Processing" stage. You can assign them now or later.
            </p>
          </div>

          <!-- Tenant Email -->
          <div class="form-group">
            <label>Tenant Email(s)</label>
            <input 
              v-model="form.tenant_email" 
              type="text" 
              placeholder="tenant@example.com, tenant2@example.com"
            />
            <p class="helper-text">
              💡 Enter tenant email addresses separated by commas
            </p>
          </div>

          <div class="modal-footer">
            <button type="button" @click="showModal = false" class="btn-secondary">Cancel</button>
            <button type="submit" class="btn-primary">Create Inspection</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Date Picker Modal -->
    <div v-if="showDatePicker" class="modal-overlay" @click.self="showDatePicker = false">
      <div class="modal modal-small">
        <div class="modal-header">
          <h2>Go to Date</h2>
          <button @click="showDatePicker = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Select a date to view in Day view</label>
            <input 
              v-model="selectedDate" 
              type="date" 
              class="input-field date-picker-input" 
            />
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showDatePicker = false" class="btn-secondary">Cancel</button>
          <button @click="goToDate" class="btn-primary">Go to Date</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1400px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
}

.page-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
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
}

.btn-primary:hover {
  background: #4f46e5;
}

/* Tabs */
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  border-bottom: 2px solid #e5e7eb;
}

.tab-button {
  padding: 12px 24px;
  background: none;
  border: none;
  border-bottom: 3px solid transparent;
  font-size: 15px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: -2px;
}

.tab-button:hover {
  color: #1e293b;
}

.tab-button.active {
  color: #6366f1;
  border-bottom-color: #6366f1;
}

/* Filters */
.filters-bar {
  display: flex;
  gap: 16px;
  padding: 20px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  margin-bottom: 24px;
  flex-wrap: wrap;
  align-items: flex-end;
}

.calendar-filters {
  margin-bottom: 16px;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-width: 180px;
}

.filter-group label {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}

.filter-select,
.filter-input {
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  background: white;
}

.filter-select:focus,
.filter-input:focus {
  outline: none;
  border-color: #6366f1;
}

.btn-clear-filters {
  padding: 8px 16px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  align-self: flex-end;
}

.btn-clear-filters:hover {
  background: #e2e8f0;
}

.btn-date-picker {
  padding: 8px 16px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  align-self: flex-end;
  white-space: nowrap;
}

.btn-date-picker:hover {
  background: #4f46e5;
}

.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
}

.inspections-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.inspection-card {
  background: white;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.inspection-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.inspection-header h3 {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.inspection-type {
  font-size: 13px;
  color: #64748b;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status-badge {
  padding: 6px 14px;
  color: white;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.inspection-details {
  margin-bottom: 16px;
}

.inspection-details p {
  font-size: 14px;
  color: #64748b;
  margin: 6px 0;
}

.inspection-actions {
  display: flex;
  gap: 12px;
}

.btn-view {
  padding: 10px 20px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-view:hover {
  background: #4f46e5;
}

.btn-delete {
  padding: 10px 20px;
  background: #fee2e2;
  color: #991b1b;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-delete:hover {
  background: #fecaca;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
}

/* Calendar View */
.calendar-view {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  padding: 24px;
}

.calendar-container {
  margin-bottom: 24px;
}

/* FullCalendar Custom Styles */
:deep(.fc) {
  font-family: inherit;
}

:deep(.fc-toolbar-title) {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
}

:deep(.fc-button) {
  background: #6366f1;
  border-color: #6366f1;
  text-transform: capitalize;
  font-weight: 600;
}

:deep(.fc-button:hover) {
  background: #4f46e5;
  border-color: #4f46e5;
}

:deep(.fc-button-active) {
  background: #4338ca !important;
  border-color: #4338ca !important;
}

:deep(.fc-event) {
  cursor: pointer;
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 13px;
  font-weight: 600;
}

:deep(.fc-event:hover) {
  opacity: 0.85;
}

:deep(.fc-daygrid-event) {
  white-space: normal;
}

:deep(.fc-col-header-cell) {
  background: #f8fafc;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  font-size: 12px;
  letter-spacing: 0.5px;
}

:deep(.fc-day-today) {
  background: #eff6ff !important;
}

/* Calendar Legend */
.calendar-legend {
  padding: 20px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.calendar-legend h4 {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 12px;
}

.legend-items {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #475569;
}

.legend-color {
  width: 16px;
  height: 16px;
  border-radius: 4px;
}

.empty-legend {
  color: #94a3b8;
  font-style: italic;
}

/* Modal styles */
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

.modal-large {
  max-width: 700px;
}

.modal-small {
  max-width: 400px;
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

.form-section {
  padding: 20px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  margin-bottom: 20px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 16px;
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

.form-group select,
.form-group input,
.input-field {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  background: white;
}

.form-group select:focus,
.form-group input:focus,
.input-field:focus {
  outline: none;
  border-color: #6366f1;
}

.form-group select:disabled {
  background: #f1f5f9;
  color: #94a3b8;
  cursor: not-allowed;
}

.date-picker-input {
  cursor: pointer;
  font-size: 16px;
}

.date-picker-input::-webkit-calendar-picker-indicator {
  cursor: pointer;
  font-size: 20px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.time-selection {
  background: #fff;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.helper-text {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.helper-text.warning {
  color: #f59e0b;
  font-weight: 600;
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
  font-size: 14px;
}

.btn-secondary:hover {
  background: #f1f5f9;
}
</style>
