<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import FullCalendar from '@fullcalendar/vue3'

const toast = useToast()
const authStore = useAuthStore()
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'

const router = useRouter()

const activeTab = ref(localStorage.getItem('inspections_view') || 'list')
const calendarView = ref('dayGridMonth')
watch(activeTab, val => {
  localStorage.setItem('inspections_view', val)
  if (val === 'calendar') {
    // Give FullCalendar time to mount before reading title
    setTimeout(() => {
      if (calendarRef.value) calendarTitle.value = calendarRef.value.getApi().view.title
    }, 100)
  }
})
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
  client_ids: [],  // multi-select array
  postcode: '',
  statuses: [],    // multi-select array
  clerk_ids: [],   // multi-select array
})

// Calendar filters
const calendarFilters = ref({
  client_ids: [],  // multi-select array
  statuses: [],    // multi-select array
  clerk_ids: []    // multi-select array
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

// ── PDF import state (for Check Out with no linked Check In) ─────────
const pdfFile     = ref(null)
const pdfFileName = ref('')

function onPdfSelected(e) {
  const file = e.target?.files?.[0] || e.dataTransfer?.files?.[0]
  if (!file) return
  if (file.type !== 'application/pdf') { toast.error('Please choose a PDF file'); return }
  pdfFile.value     = file
  pdfFileName.value = file.name
}

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
    pdfFile.value     = null
    pdfFileName.value = ''
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
  headerToolbar: false,
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

  if (calendarFilters.value.client_ids?.length)
    filtered = filtered.filter(i => calendarFilters.value.client_ids.includes(i.client_id))
  if (calendarFilters.value.status)
    filtered = filtered.filter(i => i.status === calendarFilters.value.status)
  if (calendarFilters.value.clerk_ids?.length)
    filtered = filtered.filter(i => calendarFilters.value.clerk_ids.includes(i.inspector_id))

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
  if (filters.value.client_ids?.length)
    result = result.filter(i => filters.value.client_ids.includes(i.client_id))
  if (filters.value.postcode) {
    const s = filters.value.postcode.toLowerCase()
    result = result.filter(i => i.property_address && i.property_address.toLowerCase().includes(s))
  }
  if (filters.value.statuses && filters.value.statuses.length)
    result = result.filter(i => filters.value.statuses.includes(i.status))
  if (filters.value.clerk_ids?.length)
    result = result.filter(i => filters.value.clerk_ids.includes(i.inspector_id))
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

function toggleClientFilter(val, isCalendar = false) {
  const arr = isCalendar ? calendarFilters.value.client_ids : filters.value.client_ids
  const i = arr.indexOf(val)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(val)
}

function toggleClerkFilter(val, isCalendar = false) {
  const arr = isCalendar ? calendarFilters.value.clerk_ids : filters.value.clerk_ids
  const i = arr.indexOf(val)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(val)
}

function toggleStatus(val) {
  const i = filters.value.statuses.indexOf(val)
  if (i >= 0) filters.value.statuses.splice(i, 1)
  else filters.value.statuses.push(val)
}

function toggleCalStatus(val) {
  const i = calendarFilters.value.statuses.indexOf(val)
  if (i >= 0) calendarFilters.value.statuses.splice(i, 1)
  else calendarFilters.value.statuses.push(val)
}

function filterLabel(arr, options, emptyLabel) {
  if (!arr.length) return emptyLabel
  if (arr.length === 1) return options.find(o => o.value === arr[0])?.label || arr[0]
  return `${arr.length} selected`
}
function clientFilterLabel(ids, isCalendar) {
  const arr = isCalendar ? calendarFilters.value.client_ids : filters.value.client_ids
  if (!arr.length) return 'All Clients'
  if (arr.length === 1) return clients.value.find(c => c.id === arr[0])?.name || 'Client'
  return `${arr.length} clients`
}
function clerkFilterLabel(ids, isCalendar) {
  const arr = isCalendar ? calendarFilters.value.clerk_ids : filters.value.clerk_ids
  if (!arr.length) return 'All Clerks'
  if (arr.length === 1) return users.value.find(u => u.id === arr[0])?.name || 'Clerk'
  return `${arr.length} clerks`
}

function clearFilters() {
  filters.value = { client_ids: [], postcode: '', statuses: [], clerk_ids: [] }
}

function clearCalendarFilters() {
  calendarFilters.value = { client_ids: [], statuses: [], clerk_ids: [] }
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

const calendarViews = [
  { value: 'dayGridMonth', label: 'Month' },
  { value: 'timeGridWeek', label: 'Week' },
  { value: 'timeGridDay',  label: 'Day' },
]

const calendarTitle = ref('')
// Dropdown open state for custom multi-select dropdowns
const openDropdown = ref(null) // 'status' | 'client' | 'clerk' | 'cal_status' | 'cal_client' | 'cal_clerk'
function toggleDropdown(name) {
  openDropdown.value = openDropdown.value === name ? null : name
}
function closeDropdowns() { openDropdown.value = null }

function switchCalView(view) {
  calendarView.value = view
  if (calendarRef.value) {
    calendarRef.value.getApi().changeView(view)
    calendarTitle.value = calendarRef.value.getApi().view.title
  }
}

function calNav(action) {
  if (!calendarRef.value) return
  const api = calendarRef.value.getApi()
  if (action === 'prev')  api.prev()
  if (action === 'next')  api.next()
  if (action === 'today') api.today()
  calendarTitle.value = api.view.title
}

// Update title after calendar mounts
function onCalendarMounted() {
  if (calendarRef.value) {
    calendarTitle.value = calendarRef.value.getApi().view.title
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
    client_id: authStore.isClient ? authStore.user.client_id : null,
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
  pdfFile.value     = null
  pdfFileName.value = ''
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

    const createRes = await api.createInspection(payload)
    const newId = createRes.data?.id || createRes.data?.inspection?.id

    // If a PDF was uploaded for a check_out with no linked source, process it now
    if (pdfFile.value && form.value.inspection_type === 'check_out' && newId) {
      toast.info('Analysing PDF — please wait…')
      try {
        const base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader()
          reader.onload  = e => resolve(e.target.result.split(',')[1])
          reader.onerror = reject
          reader.readAsDataURL(pdfFile.value)
        })

        // ── Step 1: Ask Claude to parse the PDF into structured data ──────
        // We don't have the template here (it was just assigned by the backend),
        // so we extract raw structure and let the backend map it to template IDs.
        const prompt = `You are parsing a UK property inspection report PDF (inventory or check-in) to extract structured data for a Check Out report system.

Extract ALL rooms and items. For each item extract:
- label: the item name exactly as written
- description: the physical description of the item
- condition: the condition recorded at check-in (NOT the check-out column if present)

The PDF format is typically: [Ref] [Item Name] [Description] [Condition at Check In] [Condition at Check Out]
Only extract the Check In condition — ignore the Check Out column.

Also extract fixed sections: keys, meter readings, schedule of condition, cleaning summary, smoke alarms.

Return ONLY valid JSON — no markdown, no explanation:
{
  "rooms": [
    {
      "name": "Lounge",
      "items": [
        { "label": "Door, Frame, Threshold & Furniture", "description": "White painted panel door with chrome effect fitment", "condition": "Appears in good condition" }
      ]
    }
  ],
  "fixedSections": {
    "condition_summary": [{ "name": "General Cleanliness", "condition": "Appears in good condition" }],
    "cleaning_summary": [{ "name": "General Cleanliness", "cleanliness": "Professionally Cleaned", "cleanlinessNotes": "" }],
    "keys": [{ "name": "Front Door", "description": "2x Yale key, 1x deadlock key" }],
    "meter_readings": [{ "name": "Gas Meter", "locationSerial": "Under stairs", "reading": "12345.6" }],
    "smoke_alarms": [{ "question": "Smoke alarm present and tested?", "answer": "Yes", "notes": "Audible alarm noted" }]
  }
}`

        const aiResponse = await api.claudeProxy({
            model: 'claude-sonnet-4-6',
            max_tokens: 8000,
            messages: [{
              role: 'user',
              content: [
                { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: base64 } },
                { type: 'text', text: prompt }
              ]
            }]
          })

        // api.claudeProxy uses axios — throws on non-2xx, data is already parsed
        const aiData  = aiResponse.data
        const rawText = (aiData.content || []).map(b => b.text || '').join('')
        const clean   = rawText.replace(/```json[\s\S]*?```|```[\s\S]*?```/g, s => s.replace(/```json|```/g, '')).trim()
        const parsed  = JSON.parse(clean)

        // ── Step 2: Send parsed data to backend to map against template ───
        // The backend knows the inspection's assigned template and maps
        // room/item names to real template IDs, storing as _importedSource.
        parsed._fileName = pdfFileName.value
        const importRes = await api.applyPdfImport(newId, parsed)

        const { room_count, item_count } = importRes.data
        toast.success(`PDF imported: ${room_count} rooms, ${item_count} items loaded as Check In reference`)

      } catch (pdfErr) {
        console.error('PDF import error:', pdfErr)
        toast.warning('Inspection created — PDF analysis failed. You can re-import from the report screen.')
      }
    } else {
      toast.success('Inspection created')
    }

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
  if (!authStore.isClient) {
    fetchClients()
    fetchUsers()
  }
  fetchTemplates()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Inspections</h1>
        <p class="page-sub">Manage and track property inspections</p>
      </div>
      <button v-if="authStore.isAdmin || authStore.isManager || authStore.isClient" @click="openModal" class="btn-primary">+ Add Inspection</button>
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
      <div class="filters-bar" v-click-outside="closeDropdowns">
        <div v-if="authStore.isAdmin || authStore.isManager" class="filter-group">
          <label>Client</label>
          <div class="ms-dropdown" :class="{ open: openDropdown === 'client' }" @click="toggleDropdown('client')">
            <span class="ms-label">{{ clientFilterLabel(filters.client_ids) }}</span>
            <span class="ms-chevron">▾</span>
          </div>
          <div v-show="openDropdown === 'client'" class="ms-menu">
            <label v-for="client in clients" :key="client.id" class="ms-item" @click.stop>
              <input type="checkbox" :checked="filters.client_ids.includes(client.id)" @change="toggleClientFilter(client.id)" />
              <span>{{ client.name }}</span>
            </label>
            <div v-if="!clients.length" class="ms-empty">No clients</div>
          </div>
        </div>
        <div class="filter-group">
          <label>Postcode</label>
          <input v-model="filters.postcode" type="text" placeholder="Search postcode..." class="filter-input" />
        </div>
        <div class="filter-group">
          <label>Workflow Stage</label>
          <div class="ms-dropdown" :class="{ open: openDropdown === 'status' }" @click="toggleDropdown('status')">
            <span class="ms-label">{{ filterLabel(filters.statuses, statusOptions, 'All Stages') }}</span>
            <span class="ms-chevron">▾</span>
          </div>
          <div v-show="openDropdown === 'status'" class="ms-menu">
            <label v-for="option in statusOptions.filter(o => o.value)" :key="option.value" class="ms-item" @click.stop>
              <input type="checkbox" :checked="filters.statuses.includes(option.value)" @change="toggleStatus(option.value)" />
              <span class="ms-status-dot" :style="{ background: statusColors[option.value] }"></span>
              <span>{{ option.label }}</span>
            </label>
          </div>
        </div>
        <div v-if="authStore.isAdmin || authStore.isManager" class="filter-group">
          <label>Clerk</label>
          <div class="ms-dropdown" :class="{ open: openDropdown === 'clerk' }" @click="toggleDropdown('clerk')">
            <span class="ms-label">{{ clerkFilterLabel(filters.clerk_ids) }}</span>
            <span class="ms-chevron">▾</span>
          </div>
          <div v-show="openDropdown === 'clerk'" class="ms-menu">
            <label v-for="clerk in clerks" :key="clerk.id" class="ms-item" @click.stop>
              <input type="checkbox" :checked="filters.clerk_ids.includes(clerk.id)" @change="toggleClerkFilter(clerk.id)" />
              <span class="ms-clerk-dot" :style="{ background: clerk.color }"></span>
              <span>{{ clerk.name }}</span>
            </label>
            <div v-if="!clerks.length" class="ms-empty">No clerks</div>
          </div>
        </div>
        <button @click="clearFilters" class="btn-clear-filters">Clear Filters</button>
      </div>

      
    <!-- Mobile FAB -->
    <button class="mobile-fab-add" @click="openCreateModal" style="display:none">+</button>

    <div v-if="loading" class="loading">Loading...</div>

      <div v-else class="inspections-list">
        <div v-for="inspection in filteredInspections" :key="inspection.id" class="inspection-card" @click="viewInspection(inspection.id)">
          <!-- Date banner -->
          <div class="card-date-banner" v-if="inspection.conduct_date">
            <div class="card-date-day">{{ new Date(inspection.conduct_date).toLocaleDateString('en-GB',{day:'2-digit'}) }}</div>
            <div class="card-date-rest">
              <span class="card-date-month">{{ new Date(inspection.conduct_date).toLocaleDateString('en-GB',{month:'short',year:'numeric'}) }}</span>
            </div>
          </div>
          <div class="card-date-banner card-date-unset" v-else>
            <div class="card-date-day">—</div>
            <div class="card-date-rest"><span class="card-date-month">No date set</span></div>
          </div>

          <div class="card-body">
            <div class="card-top">
              <div class="card-type-badge">{{ inspection.inspection_type.replace(/_/g,' ').toUpperCase() }}</div>
              <span class="status-badge" :style="{ backgroundColor: statusColors[inspection.status] }">{{ inspection.status }}</span>
            </div>
            <h3 class="card-address">{{ inspection.property_address }}</h3>
            <div v-if="inspection.client_name" class="card-client">{{ inspection.client_name }}</div>

            <div class="card-assignments">
              <div v-if="inspection.inspector_name" class="assign-row">
                <span class="assign-role">Clerk</span>
                <span class="assign-name">{{ inspection.inspector_name }}</span>
              </div>
              <div v-if="inspection.typist_name" class="assign-row">
                <span class="assign-role">Typist</span>
                <span class="assign-name">{{ inspection.typist_name }}</span>
              </div>
            </div>
          </div>

          <div class="card-footer">
            <span class="card-created">Created {{ new Date(inspection.created_at).toLocaleDateString('en-GB') }}</span>
            <button @click.stop="deleteInspection(inspection.id)" class="btn-delete-sm">✕</button>
          </div>
        </div>
        <div v-if="filteredInspections.length === 0" class="empty-state">
          {{ filters.client_ids.length || filters.postcode || filters.statuses.length || filters.clerk_ids.length
            ? 'No inspections match your filters.'
            : 'No inspections yet. Create your first inspection!' }}
        </div>
      </div>
    </div>

    <!-- Calendar View -->
    <div v-if="activeTab === 'calendar'" class="calendar-view">
      <div class="filters-bar calendar-filters" v-click-outside="closeDropdowns">
        <div v-if="authStore.isAdmin || authStore.isManager" class="filter-group">
          <label>Client</label>
          <div class="ms-dropdown" :class="{ open: openDropdown === 'cal_client' }" @click="toggleDropdown('cal_client')">
            <span class="ms-label">{{ clientFilterLabel(calendarFilters.client_ids, true) }}</span>
            <span class="ms-chevron">▾</span>
          </div>
          <div v-show="openDropdown === 'cal_client'" class="ms-menu">
            <label v-for="client in clients" :key="client.id" class="ms-item" @click.stop>
              <input type="checkbox" :checked="calendarFilters.client_ids.includes(client.id)" @change="toggleClientFilter(client.id, true)" />
              <span>{{ client.name }}</span>
            </label>
          </div>
        </div>
        <div class="filter-group">
          <label>Workflow Stage</label>
          <div class="ms-dropdown" :class="{ open: openDropdown === 'cal_status' }" @click="toggleDropdown('cal_status')">
            <span class="ms-label">{{ filterLabel(calendarFilters.statuses, statusOptions, 'All Stages') }}</span>
            <span class="ms-chevron">▾</span>
          </div>
          <div v-show="openDropdown === 'cal_status'" class="ms-menu">
            <label v-for="option in statusOptions.filter(o => o.value)" :key="option.value" class="ms-item" @click.stop>
              <input type="checkbox" :checked="calendarFilters.statuses.includes(option.value)" @change="toggleCalStatus(option.value)" />
              <span class="ms-status-dot" :style="{ background: statusColors[option.value] }"></span>
              <span>{{ option.label }}</span>
            </label>
          </div>
        </div>
        <div v-if="authStore.isAdmin || authStore.isManager" class="filter-group">
          <label>Clerk</label>
          <div class="ms-dropdown" :class="{ open: openDropdown === 'cal_clerk' }" @click="toggleDropdown('cal_clerk')">
            <span class="ms-label">{{ clerkFilterLabel(calendarFilters.clerk_ids, true) }}</span>
            <span class="ms-chevron">▾</span>
          </div>
          <div v-show="openDropdown === 'cal_clerk'" class="ms-menu">
            <label v-for="clerk in clerks" :key="clerk.id" class="ms-item" @click.stop>
              <input type="checkbox" :checked="calendarFilters.clerk_ids.includes(clerk.id)" @change="toggleClerkFilter(clerk.id, true)" />
              <span class="ms-clerk-dot" :style="{ background: clerk.color }"></span>
              <span>{{ clerk.name }}</span>
            </label>
          </div>
        </div>
        <button @click="clearCalendarFilters" class="btn-clear-filters">Clear Filters</button>
      </div>

      <div v-if="loading" class="loading">Loading calendar...</div>

      <div v-else class="calendar-container">
        <div class="calendar-toolbar">
          <div class="cal-toolbar-left">
            <button class="cal-nav-btn" @click="calNav('prev')">‹</button>
            <button class="cal-nav-btn" @click="calNav('next')">›</button>
            <button class="cal-nav-btn cal-today-btn" @click="calNav('today')">Today</button>
            <span class="cal-title">{{ calendarTitle }}</span>
          </div>
          <div class="cal-view-btns">
            <button
              v-for="v in calendarViews" :key="v.value"
              class="cal-view-btn" :class="{ active: calendarView === v.value }"
              @click="switchCalView(v.value)">{{ v.label }}</button>
            <button class="cal-view-btn cal-goto-btn" @click="openDatePicker">📅 Go to Date</button>
          </div>
        </div>
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
      <div class="modal modal-wide">
        <div class="modal-header">
          <h2>New Inspection</h2>
          <button @click="showModal = false" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleSubmit" class="modal-body">

          <!-- ── 2-column grid ────────────────────────────────────────── -->
          <div class="modal-cols">

            <!-- ── Column 1: Location & Scheduling ───────────────────── -->
            <div class="modal-col">
              <div class="col-section-title">Location &amp; Scheduling</div>

              <!-- Portfolio — hidden for client role (auto-filled) -->
              <div v-if="!authStore.isClient" class="form-group">
                <label>Portfolio *</label>
                <select v-model="form.client_id" @change="onClientChange" required>
                  <option :value="null" disabled>Select a portfolio...</option>
                  <option v-for="client in clients" :key="client.id" :value="client.id">
                    {{ client.name }} {{ client.company ? `(${client.company})` : '' }}
                  </option>
                </select>
              </div>

              <!-- Property -->
              <div class="form-group">
                <label>Property *</label>
                <select v-model="form.property_id" required :disabled="!form.client_id">
                  <option :value="null" disabled>
                    {{ form.client_id ? 'Select a property...' : 'Select a portfolio first' }}
                  </option>
                  <option v-for="property in filteredProperties" :key="property.id" :value="property.id">
                    {{ property.address }}
                  </option>
                </select>
                <p v-if="form.client_id && filteredProperties.length === 0" class="helper-text">
                  No properties found for this portfolio.
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

              <!-- Date -->
              <div class="form-group">
                <label>Conduct Date</label>
                <input v-model="form.conduct_date" type="date" class="input-field date-picker" />
              </div>

              <!-- Time -->
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
            </div>

            <!-- ── Column 2: Assignment & Contact ────────────────────── -->
            <div class="modal-col">
              <div class="col-section-title">Assignment &amp; Contact</div>

              <!-- Template -->
              <div class="form-group">
                <label>Template</label>
                <select v-model="form.template_id">
                  <option :value="null">Use default for this type</option>
                  <option v-for="t in filteredTemplates" :key="t.id" :value="t.id">
                    {{ t.name }}{{ t.is_default ? ' ★ Default' : '' }}
                  </option>
                </select>
                <p v-if="filteredTemplates.length === 0" class="helper-text warning">
                  ⚠️ No templates for this type. Create one in Settings → Templates.
                </p>
                <p v-else class="helper-text">
                  {{ filteredTemplates.length }} template{{ filteredTemplates.length !== 1 ? 's' : '' }} available.
                </p>
              </div>

              <!-- Clerk -->
              <div class="form-group">
                <label>Clerk (Inspector) *</label>
                <select v-model="form.inspector_id" required>
                  <option :value="null" disabled>Select a clerk...</option>
                  <option v-for="clerk in clerks" :key="clerk.id" :value="clerk.id">
                    {{ clerk.name }} ({{ clerk.email }})
                  </option>
                </select>
                <p v-if="clerks.length === 0" class="helper-text warning">
                  ⚠️ No clerks available. Create clerk users first.
                </p>
              </div>

              <!-- Typist -->
              <div class="form-group">
                <label>Typist (Optional)</label>
                <select v-model="form.typist_id">
                  <option :value="null">None — assign later</option>
                  <option v-for="typist in typists" :key="typist.id" :value="typist.id">
                    {{ typist.name }} ({{ typist.email }})
                  </option>
                </select>
                <p class="helper-text">Can be assigned at the Processing stage.</p>
              </div>

              <!-- Tenant contact -->
              <div class="form-group">
                <label>Tenant Email(s)</label>
                <input v-model="form.tenant_email" type="text" placeholder="tenant@example.com, tenant2@example.com" />
                <p class="helper-text">💡 Separate multiple addresses with commas</p>
              </div>
            </div>

          </div>
          <!-- ── End columns ─────────────────────────────────────────── -->

          <!-- ── Lifecycle suggestion banner (full-width below cols) ─── -->
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
                <input type="checkbox" v-model="form.include_photos" />
                <span>
                  Include photos from {{ lifecycleSuggestion.label }}
                  <span class="lc-photo-hint">Room item photos will carry through to the new report</span>
                </span>
              </label>
            </div>
          </div>

          <!-- ── PDF import for Check Out with no linked Check In ──── -->
          <div
            v-if="form.inspection_type === 'check_out' && !historyLoading && !lifecycleSuggestion"
            class="pdf-import-section"
          >
            <div class="pdf-import-header">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <span>No previous Check In found for this property</span>
            </div>
            <p class="pdf-import-hint">
              Upload a Check In or Inventory PDF from another system to use as the reference for this Check Out.
              The report's room layout, descriptions, and conditions will be extracted automatically.
            </p>
            <label
              class="pdf-dropzone-sm"
              :class="{ 'pdf-dropzone-sm-has': pdfFileName }"
              @dragover.prevent
              @drop.prevent="onPdfSelected"
            >
              <template v-if="!pdfFileName">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <span>Drop PDF here or <u>browse</u></span>
                <span class="pdf-dz-sm-hint">Optional — can also import from the report screen</span>
              </template>
              <template v-else>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span class="pdf-dz-sm-name">{{ pdfFileName }}</span>
                <span class="pdf-dz-sm-hint">Click to change</span>
              </template>
              <input type="file" accept="application/pdf" style="display:none" @change="onPdfSelected" />
            </label>
            <p v-if="pdfFileName" class="pdf-import-notice">
              ✓ PDF will be analysed by AI when you create the inspection
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
  align-items: flex-start;
  margin-bottom: 24px;
}
.page-title { font-size: 22px; font-weight: 700; color: #1e293b; margin: 0 0 4px; }
.page-sub   { font-size: 13px; color: #94a3b8; margin: 0; }

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

/* Multi-select status pills */
.filter-group-multi { min-width: 200px; }
.multi-status-pills { display: flex; flex-wrap: wrap; gap: 5px; padding-top: 2px; }
.status-pill {
  padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 700;
  border: 1.5px solid #e2e8f0; background: #f8fafc; color: #64748b;
  cursor: pointer; transition: all 0.12s; white-space: nowrap;
}
.status-pill:hover { border-color: #cbd5e1; color: #1e293b; }
.status-pill-active { color: #fff !important; border-color: transparent !important; }

/* Calendar toolbar */
.calendar-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px; gap: 10px; flex-wrap: wrap;
}
.cal-toolbar-left { display: flex; align-items: center; gap: 4px; }
.cal-nav-btn {
  padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 600;
  border: 1.5px solid #e2e8f0; background: #fff; color: #64748b; cursor: pointer;
  transition: all 0.12s; line-height: 1;
}
.cal-nav-btn:hover { background: #f1f5f9; border-color: #c7d2fe; color: #1e293b; }
.cal-today-btn { font-size: 12px; padding: 6px 14px; }
.cal-title { font-size: 15px; font-weight: 700; color: #1e293b; margin-left: 8px; white-space: nowrap; }
.cal-view-btns { display: flex; gap: 4px; flex-wrap: wrap; }
.cal-view-btn {
  padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600;
  border: 1.5px solid #e2e8f0; background: #fff; color: #64748b; cursor: pointer;
  transition: all 0.12s;
}
.cal-view-btn:hover { background: #f1f5f9; border-color: #c7d2fe; color: #1e293b; }
.cal-view-btn.active { background: #6366f1; border-color: #6366f1; color: #fff; }
.cal-goto-btn { border-color: #c7d2fe; color: #6366f1; }
.cal-goto-btn:hover { background: #eef2ff; }
/* Client pill active colour */
.status-pill-client { background: #0f172a !important; }

/* btn-primary uniform style */
.btn-primary {
  background: #6366f1; color: #fff; border: none;
  padding: 9px 18px; border-radius: 8px;
  font-size: 13px; font-weight: 700; cursor: pointer; transition: background 0.12s;
  white-space: nowrap;
}
.btn-primary:hover { background: #4f46e5; }

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
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.inspection-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
  transition: box-shadow 0.15s, transform 0.12s;
  cursor: pointer;
  display: flex;
  flex-direction: column;
}
.inspection-card:hover {
  box-shadow: 0 4px 14px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

/* Date banner */
.card-date-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #1e3a5f 0%, #1e293b 100%);
  color: white;
}
.card-date-unset { background: #f1f5f9; }
.card-date-unset .card-date-day { color: #94a3b8; }
.card-date-unset .card-date-month { color: #94a3b8; }

.card-date-day {
  font-size: 26px;
  font-weight: 800;
  line-height: 1;
  color: white;
  min-width: 32px;
}
.card-date-rest { display: flex; flex-direction: column; gap: 1px; }
.card-date-month { font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.75); text-transform: uppercase; letter-spacing: 0.4px; }

.card-body { padding: 12px 14px 8px; flex: 1; }

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 7px;
}

.card-type-badge {
  font-size: 10px;
  font-weight: 700;
  background: #eef2ff;
  color: #6366f1;
  padding: 2px 8px;
  border-radius: 5px;
  letter-spacing: 0.3px;
}

.status-badge {
  padding: 2px 9px;
  border-radius: 20px;
  font-size: 10px;
  font-weight: 700;
  color: white;
  white-space: nowrap;
  flex-shrink: 0;
}

.card-address {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.35;
  margin-bottom: 3px;
}

.card-client {
  font-size: 11px;
  color: #6366f1;
  font-weight: 600;
  margin-bottom: 8px;
}

.card-assignments {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.assign-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.assign-role {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  min-width: 38px;
}

.assign-name {
  font-size: 12px;
  color: #475569;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border-top: 1px solid #f1f5f9;
  background: #fafbfc;
}

.card-created { font-size: 10px; color: #cbd5e1; }

.btn-delete-sm {
  background: none;
  border: none;
  color: #fca5a5;
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1;
}
.btn-delete-sm:hover { background: #fef2f2; color: #ef4444; }

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

.modal-wide { width: 820px; }

/* 2-column modal layout */
.modal-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 28px;
}

.modal-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.col-section-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: #6366f1;
  padding-bottom: 6px;
  border-bottom: 2px solid #e0e7ff;
  margin-bottom: 2px;
}

@media (max-width: 700px) {
  .modal-cols { grid-template-columns: 1fr; }
  .modal-wide { width: 100%; }
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

/* ── PDF import section in create modal ───────────────────────────── */
.pdf-import-section {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.pdf-import-header {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}
.pdf-import-hint {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  margin: 0;
}
.pdf-dropzone-sm {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.15s;
  background: white;
  text-align: center;
  font-size: 13px;
  color: #64748b;
}
.pdf-dropzone-sm:hover,
.pdf-dropzone-sm-has {
  border-color: #6366f1;
  background: #f5f3ff;
  color: #4338ca;
}
.pdf-dz-sm-hint {
  font-size: 11px;
  color: #94a3b8;
}
.pdf-dz-sm-name {
  font-weight: 600;
  color: #4338ca;
}
.pdf-import-notice {
  font-size: 12px;
  color: #16a34a;
  font-weight: 600;
  margin: 0;
}


/* ══════════════════════════════════════
   MOBILE  ≤ 768px
══════════════════════════════════════ */
@media (max-width: 768px) {

  /* FAB replaces the header Add button */
  .page-header .btn-primary {
    display: none;
  }

  .mobile-fab-add {
    display: flex !important;
  }

  /* Filters: stack vertically, full-width inputs */
  .filters-bar {
    flex-direction: column;
    gap: 8px;
    padding: 10px 12px;
  }

  .filter-group {
    min-width: 100%;
  }

  /* Single-column card grid */
  .inspections-grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  /* Tab bar: horizontal scroll, no wrap */
  .view-tabs {
    overflow-x: auto;
    flex-wrap: nowrap;
    gap: 4px;
    padding-bottom: 4px;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }
  .view-tabs::-webkit-scrollbar { display: none; }
  .tab-btn {
    white-space: nowrap;
    flex-shrink: 0;
    padding: 7px 12px;
    font-size: 12px;
  }

  /* Date banner: compact */
  .date-number { font-size: 18px !important; }
  .date-month, .date-day { font-size: 9px !important; }
  .date-banner { padding: 6px 8px !important; }

  /* Card body: slightly more padding for touch */
  .inspection-card .card-body {
    padding: 10px 12px !important;
  }

  /* Modal → full-height bottom sheet */
  .modal-overlay {
    align-items: flex-end;
    padding: 0;
  }
  .modal {
    border-radius: 20px 20px 0 0;
    max-width: 100%;
    max-height: 94vh;
  }
  .modal-cols {
    grid-template-columns: 1fr !important;
  }

  /* Status workflow buttons: 2 per row */
  .workflow-actions {
    flex-wrap: wrap;
  }
  .workflow-actions .btn-action {
    flex: 1 1 calc(50% - 6px);
    min-width: 0;
    font-size: 11px;
    padding: 9px 6px;
  }
}


.mobile-fab-add {
  display: none;
  position: fixed;
  bottom: 76px;
  right: 18px;
  width: 52px;
  height: 52px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 50%;
  font-size: 26px;
  line-height: 1;
  box-shadow: 0 4px 14px rgba(99,102,241,0.4);
  cursor: pointer;
  z-index: 150;
  align-items: center;
  justify-content: center;
  transition: transform 0.15s;
}
.mobile-fab-add:hover { transform: scale(1.07); }

</style>