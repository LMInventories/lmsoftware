<script setup>
import { ref, onMounted, computed, watch } from 'vue'
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
const calendarView = ref('dayGridMonth')
const calendarRef = ref(null)
const selectedDate = ref('')
const showDatePicker = ref(false)
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
  time_minute: '00',
  source_inspection_id: null,
  include_photos: false
})

// ── Lifecycle suggestion state ─────────────────────────────────────────
const propertyHistory    = ref([])
const lifecycleSuggestion = ref(null)  // { sourceId, sourceType, sourceDateStr, label }
const historyLoading     = ref(false)

// Watch property + inspection_type — load history and compute suggestion
watch(
  () => [form.value.property_id, form.value.inspection_type],
  async ([propId, iType]) => {
    lifecycleSuggestion.value = null
    form.value.source_inspection_id = null
    if (!propId) return

    historyLoading.value = true
    try {
      const res = await api.getPropertyHistory(propId)
      propertyHistory.value = res.data

      // Determine what type of prior report can seed this new inspection
      const seedableTypes = iType === 'check_out'
        ? ['check_in', 'inventory']
        : iType === 'check_in'
          ? ['check_out']
          : []

      // For check_out: find any check_in/inventory, prefer ones with report data
      // For check_in: find any check_out with report data
      const source = res.data.find(h =>
        h.id !== undefined &&
        seedableTypes.includes(h.inspection_type) &&
        (iType === 'check_out' ? true : h.has_report_data)
      )

      if (source) {
        const typeLabel = { check_in: 'Check In', check_out: 'Check Out', inventory: 'Inventory' }[source.inspection_type] || source.inspection_type
        const dateStr = source.conduct_date
          ? new Date(source.conduct_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
          : new Date(source.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })

        lifecycleSuggestion.value = {
          sourceId: source.id,
          sourceType: source.inspection_type,
          sourceDateStr: dateStr,
          label: typeLabel
        }
        // Pre-select it
        form.value.source_inspection_id = source.id
      }
    } catch {
      // silent fail
    } finally {
      historyLoading.value = false
    }
  }
)

// Time options
const timePreferenceOptions = [
  { value: 'anytime', label: 'Anytime' },
  { value: 'am', label: 'AM (Morning)' },
  { value: 'pm', label: 'PM (Afternoon)' },
  { value: 'specific', label: 'Specific Time' }
]

const hourOptions = ['09', '10', '11', '12', '13', '14', '15', '16', '17']
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

// FullCalendar options
const calendarOptions = computed(() => ({
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin],
  initialView: calendarView.value,
  firstDay: 1,
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

const calendarEvents = computed(() => {
  let filtered = [...inspections.value]

  if (calendarFilters.value.client_id)
    filtered = filtered.filter(i => i.client_id === calendarFilters.value.client_id)
  if (calendarFilters.value.status)
    filtered = filtered.filter(i => i.status === calendarFilters.value.status)
  if (calendarFilters.value.clerk_id)
    filtered = filtered.filter(i => i.inspector_id === calendarFilters.value.clerk_id)

  return filtered
    .filter(i => i.conduct_date)
    .map(inspection => {
      let eventTime = null
      if (inspection.conduct_time_preference) {
        const pref = inspection.conduct_time_preference
        if (pref.startsWith('specific:')) {
          const [, time] = pref.split(':')
          const [hour, minute] = time.split('_')
          eventTime = `${hour}:${minute}:00`
        }
      }
      const eventDate = inspection.conduct_date.split('T')[0]
      let postcode = ''
      if (inspection.property_address) {
        const parts = inspection.property_address.split(',').map(p => p.trim())
        postcode = parts[parts.length - 1] || ''
      }
      let typeShort = ''
      switch (inspection.inspection_type) {
        case 'check_in':  typeShort = 'C/I'; break
        case 'check_out': typeShort = 'C/O'; break
        case 'inventory': typeShort = 'INV'; break
        default: typeShort = inspection.inspection_type.substring(0, 3).toUpperCase()
      }
      const title = `${typeShort} - ${postcode}`
      const assignedClerk = users.value.find(u => u.id === inspection.inspector_id)
      const clerkColor = assignedClerk?.color || '#6366f1'
      return {
        id: inspection.id,
        title,
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

const filteredInspections = computed(() => {
  let result = [...inspections.value]
  if (filters.value.client_id)
    result = result.filter(i => i.client_id === filters.value.client_id)
  if (filters.value.postcode) {
    const s = filters.value.postcode.toLowerCase()
    result = result.filter(i => i.property_address && i.property_address.toLowerCase().includes(s))
  }
  if (filters.value.status)
    result = result.filter(i => i.status === filters.value.status)
  if (filters.value.clerk_id)
    result = result.filter(i => i.inspector_id === filters.value.clerk_id)
  return result
})

const filteredProperties = computed(() => {
  if (!form.value.client_id) return properties.value
  return properties.value.filter(p => p.client_id === form.value.client_id)
})

const clerks = computed(() => users.value.filter(u => u.role === 'clerk'))
const typists = computed(() => users.value.filter(u => u.role === 'typist'))
const filteredTemplates = computed(() => templates.value.filter(t => t.inspection_type === form.value.inspection_type))

function convertDateToUKFormat(isoDate) {
  if (!isoDate) return ''
  const date = new Date(isoDate)
  const day = String(date.getDate()).padStart(2, '0')
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const year = date.getFullYear()
  return `${day}/${month}/${year}`
}

function clearFilters() {
  filters.value = { client_id: null, postcode: '', status: null, clerk_id: null }
}

function clearCalendarFilters() {
  calendarFilters.value = { client_id: null, status: null, clerk_id: null }
}

function handleEventClick(info) {
  router.push(`/inspections/${info.event.id}`)
}

function openDatePicker() {
  selectedDate.value = new Date().toISOString().split('T')[0]
  showDatePicker.value = true
}

function goToDate() {
  if (selectedDate.value && calendarRef.value) {
    calendarRef.value.getApi().changeView('timeGridDay', selectedDate.value)
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
    time_minute: '00',
    source_inspection_id: null,
  include_photos: false
  }
  lifecycleSuggestion.value = null
  propertyHistory.value = []
  showModal.value = true
}

function onClientChange() {
  form.value.property_id = null
  lifecycleSuggestion.value = null
  form.value.source_inspection_id = null
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
      conduct_time_preference: timePreference,
      source_inspection_id: form.value.source_inspection_id || null,
      include_photos: form.value.include_photos || false
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
      <button @click="activeTab = 'list'" class="tab-button" :class="{ active: activeTab === 'list' }">
        📄 List View
      </button>
      <button @click="activeTab = 'calendar'" class="tab-button" :class="{ active: activeTab === 'calendar' }">
        📅 Calendar View
      </button>
    </div>

    <!-- List View -->
    <div v-if="activeTab === 'list'">
      <div class="filters-bar">
        <div class="filter-group">
          <label>Client</label>
          <select v-model="filters.client_id" class="filter-select">
            <option :value="null">All Clients</option>
            <option v-for="client in clients" :key="client.id" :value="client.id">{{ client.name }}</option>
          </select>
        </div>
        <div class="filter-group">
          <label>Postcode</label>
          <input v-model="filters.postcode" type="text" placeholder="Search postcode..." class="filter-input" />
        </div>
        <div class="filter-group">
          <label>Workflow Stage</label>
          <select v-model="filters.status" class="filter-select">
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="filter-group">
          <label>Clerk</label>
          <select v-model="filters.clerk_id" class="filter-select">
            <option :value="null">All Clerks</option>
            <option v-for="clerk in clerks" :key="clerk.id" :value="clerk.id">{{ clerk.name }}</option>
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
            <span class="status-badge" :style="{ backgroundColor: statusColors[inspection.status] }">
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
      <div class="filters-bar calendar-filters">
        <div class="filter-group">
          <label>Client</label>
          <select v-model="calendarFilters.client_id" class="filter-select">
            <option :value="null">All Clients</option>
            <option v-for="client in clients" :key="client.id" :value="client.id">{{ client.name }}</option>
          </select>
        </div>
        <div class="filter-group">
          <label>Workflow Stage</label>
          <select v-model="calendarFilters.status" class="filter-select">
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="filter-group">
          <label>Clerk</label>
          <select v-model="calendarFilters.clerk_id" class="filter-select">
            <option :value="null">All Clerks</option>
            <option v-for="clerk in clerks" :key="clerk.id" :value="clerk.id">{{ clerk.name }}</option>
          </select>
        </div>
        <button @click="clearCalendarFilters" class="btn-clear-filters">Clear Filters</button>
        <button @click="openDatePicker" class="btn-date-picker">📅 Go to Date</button>
      </div>

      <div v-if="loading" class="loading">Loading calendar...</div>

      <div v-else class="calendar-container">
        <FullCalendar ref="calendarRef" :options="calendarOptions" />
      </div>

      <div class="calendar-legend">
        <h4>Clerk Legend:</h4>
        <div class="legend-items">
          <div v-for="clerk in clerks" :key="clerk.id" class="legend-item">
            <span class="legend-color" :style="{ background: clerk.color }"></span>
            <span>{{ clerk.name }}</span>
          </div>
          <div v-if="clerks.length === 0" class="empty-legend">No clerks assigned yet</div>
        </div>
      </div>
    </div>

    <!-- ══ Create Inspection Modal ══════════════════════════════════════ -->
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

          <!-- Property Selection -->
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
              No properties found for this client.
            </p>
          </div>

          <!-- Inspection Type -->
          <div class="form-group">
            <label>Inspection Type *</label>
            <select v-model="form.inspection_type" required>
              <option value="check_in">Check In</option>
              <option value="check_out">Check Out</option>
              <option value="interim">Interim Inspection</option>
              <option value="inventory">Inventory</option>
            </select>
          </div>

          <!-- ── Lifecycle suggestion banner ───────────────────────────── -->
          <div v-if="historyLoading" class="lc-loading">
            <span class="lc-spinner"></span> Checking property history…
          </div>

          <div v-else-if="lifecycleSuggestion" class="lc-banner">
            <div class="lc-banner-icon">🔗</div>
            <div class="lc-banner-body">
              <strong class="lc-banner-title">
                Completed {{ lifecycleSuggestion.label }} found for this property
              </strong>
              <p class="lc-banner-desc">
                Pre-fill this {{ form.inspection_type === 'check_out' ? 'Check Out' : 'Check In' }}
                with conditions from the
                {{ lifecycleSuggestion.label }} ({{ lifecycleSuggestion.sourceDateStr }}).
                You'll only need to note what changed.
              </p>
              <label class="lc-checkbox">
                <input
                  type="checkbox"
                  :checked="form.source_inspection_id === lifecycleSuggestion.sourceId"
                  @change="form.source_inspection_id = $event.target.checked ? lifecycleSuggestion.sourceId : null"
                />
                <span>
                  Work from {{ lifecycleSuggestion.label }} report
                  <span class="lc-date-chip">{{ lifecycleSuggestion.sourceDateStr }}</span>
                </span>
              </label>
              <label class="lc-checkbox" v-if="form.source_inspection_id">
                <input
                  type="checkbox"
                  v-model="form.include_photos"
                />
                <span>
                  Include photos from {{ lifecycleSuggestion.label }}
                  <span class="lc-photo-hint">Room item photos will carry through to the new report</span>
                </span>
              </label>
            </div>
          </div>
          <!-- ────────────────────────────────────────────────────────── -->

          <!-- Conduct Date -->
          <div class="form-group">
            <label>Conduct Date</label>
            <input v-model="form.conduct_date" type="date" class="input-field date-picker" />
          </div>

          <!-- Time Preference -->
          <div class="form-group">
            <label>Time Preference</label>
            <select v-model="form.time_preference">
              <option v-for="opt in timePreferenceOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <div v-if="form.time_preference === 'specific'" class="time-row">
              <select v-model="form.time_hour" class="time-select">
                <option v-for="h in hourOptions" :key="h" :value="h">{{ h }}</option>
              </select>
              <span>:</span>
              <select v-model="form.time_minute" class="time-select">
                <option v-for="m in minuteOptions" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
          </div>

          <!-- Template -->
          <div class="form-group">
            <label>Template</label>
            <select v-model="form.template_id">
              <option :value="null">Use default template for this type</option>
              <option v-for="t in filteredTemplates" :key="t.id" :value="t.id">
                {{ t.name }}{{ t.is_default ? ' ★ Default' : '' }}
              </option>
            </select>
            <p v-if="filteredTemplates.length === 0" class="helper-text warning">
              ⚠️ No templates for this inspection type. Create one in Settings → Templates.
            </p>
            <p v-else class="helper-text">
              {{ filteredTemplates.length }} template{{ filteredTemplates.length !== 1 ? 's' : '' }} available. Leave blank to use the default.
            </p>
          </div>

          <!-- Clerk -->
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

          <!-- Typist -->
          <div class="form-group">
            <label>Assign Typist (Optional)</label>
            <select v-model="form.typist_id">
              <option :value="null">None (assign later at Processing stage)</option>
              <option v-for="typist in typists" :key="typist.id" :value="typist.id">
                {{ typist.name }} ({{ typist.email }})
              </option>
            </select>
            <p class="helper-text">Typists handle the "Processing" stage. You can assign them now or later.</p>
          </div>

          <!-- Tenant Email -->
          <div class="form-group">
            <label>Tenant Email(s)</label>
            <input v-model="form.tenant_email" type="text" placeholder="tenant@example.com, tenant2@example.com" />
            <p class="helper-text">💡 Enter tenant email addresses separated by commas</p>
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
            <input v-model="selectedDate" type="date" class="input-field date-picker-input" />
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
  transition: background 0.15s;
}
.btn-primary:hover { background: #4f46e5; }

.btn-secondary {
  padding: 10px 20px;
  background: white;
  color: #475569;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}
.btn-secondary:hover { background: #f8fafc; }

.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  border-bottom: 2px solid #e2e8f0;
}

.tab-button {
  padding: 10px 20px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}
.tab-button:hover { color: #1e293b; }
.tab-button.active { color: #6366f1; border-bottom-color: #6366f1; }

/* Filters */
.filters-bar {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 160px;
}

.filter-group label {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.filter-select,
.filter-input {
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 14px;
  background: white;
  color: #1e293b;
  font-family: inherit;
}

.btn-clear-filters,
.btn-date-picker {
  padding: 8px 16px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  align-self: flex-end;
}
.btn-clear-filters:hover, .btn-date-picker:hover { background: #e2e8f0; }

/* Inspections list */
.inspections-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.inspection-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
  transition: box-shadow 0.15s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.inspection-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }

.inspection-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.inspection-header h3 {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.3;
}

.inspection-type {
  font-size: 11px;
  font-weight: 700;
  color: #6366f1;
  margin-top: 3px;
}

.status-badge {
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 700;
  color: white;
  white-space: nowrap;
  flex-shrink: 0;
}

.inspection-details {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 16px;
}
.inspection-details p { font-size: 13px; color: #64748b; }

.inspection-actions {
  display: flex;
  gap: 10px;
}

.btn-view {
  flex: 1;
  padding: 8px 16px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.btn-view:hover { background: #4f46e5; }

.btn-delete {
  padding: 8px 16px;
  background: none;
  color: #ef4444;
  border: 1px solid #fca5a5;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.btn-delete:hover { background: #fef2f2; }

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 60px 20px;
  color: #94a3b8;
  font-size: 15px;
}

.loading {
  text-align: center;
  padding: 60px;
  color: #94a3b8;
  font-size: 15px;
}

/* Calendar */
.calendar-view { margin-top: 8px; }
.calendar-filters { background: #f8fafc; padding: 16px; border-radius: 8px; border: 1px solid #e2e8f0; }
.calendar-container { margin-top: 16px; }

.calendar-legend {
  margin-top: 20px;
  padding: 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.calendar-legend h4 { font-size: 13px; font-weight: 700; color: #475569; margin-bottom: 10px; }
.legend-items { display: flex; flex-wrap: wrap; gap: 12px; }
.legend-item { display: flex; align-items: center; gap: 7px; font-size: 13px; color: #475569; }
.legend-color { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
.empty-legend { font-size: 13px; color: #94a3b8; font-style: italic; }

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 20px;
}

.modal {
  background: white;
  border-radius: 12px;
  width: 560px;
  max-width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0,0,0,0.2);
}

.modal-large { width: 680px; }
.modal-small { width: 400px; }

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid #f1f5f9;
  position: sticky;
  top: 0;
  background: white;
  z-index: 1;
}
.modal-header h2 { font-size: 17px; font-weight: 700; color: #0f172a; }

.btn-close {
  background: none;
  border: none;
  font-size: 18px;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  line-height: 1;
}
.btn-close:hover { background: #f1f5f9; color: #475569; }

.modal-body {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 8px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 13px;
  font-weight: 700;
  color: #374151;
}

.form-group select,
.form-group input {
  padding: 9px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  font-size: 14px;
  font-family: inherit;
  color: #1e293b;
  background: white;
  width: 100%;
  transition: border-color 0.15s;
}
.form-group select:focus,
.form-group input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99,102,241,0.08);
}
.form-group select:disabled { background: #f8fafc; color: #94a3b8; cursor: not-allowed; }

.input-field { padding: 9px 12px; border: 1px solid #e2e8f0; border-radius: 7px; font-size: 14px; font-family: inherit; width: 100%; }

.helper-text { font-size: 12px; color: #64748b; }
.helper-text.warning { color: #f59e0b; font-weight: 600; }

.time-row { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.time-select { width: 80px; padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; }

.date-picker { cursor: pointer; }
.date-picker-input { width: 100%; }

/* ── Lifecycle banner ──────────────────────────────────────────────── */
.lc-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.lc-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #e2e8f0;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin { to { transform: rotate(360deg); } }

.lc-banner {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 14px 16px;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  border-radius: 10px;
}

.lc-banner-icon {
  font-size: 20px;
  flex-shrink: 0;
  margin-top: 1px;
}

.lc-banner-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.lc-banner-title {
  font-size: 13px;
  font-weight: 700;
  color: #3730a3;
}

.lc-banner-desc {
  font-size: 12px;
  color: #4338ca;
  line-height: 1.5;
}

.lc-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  margin-top: 2px;
}

.lc-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: #6366f1;
  cursor: pointer;
  flex-shrink: 0;
}

.lc-photo-hint{display:block;font-size:11px;color:#94a3b8;margin-top:2px}
.lc-date-chip {
  display: inline-block;
  padding: 1px 8px;
  background: #ddd6fe;
  color: #4c1d95;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  margin-left: 4px;
}
</style>
