<script setup>
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from '../services/api'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import FullCalendar from '@fullcalendar/vue3'
import PdfImportModal from '../components/PdfImportModal.vue'

const toast = useToast()
const authStore = useAuthStore()
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'

const router = useRouter()
const route  = useRoute()

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
const selectedDate        = ref('')
const selectedDateDisplay = ref('')  // DD/MM/YYYY for display
const conductDateDisplay  = ref('')  // DD/MM/YYYY for Add Inspection form

function onDateDisplayInput(e) {
  let v = e.target.value.replace(/[^0-9]/g, '')
  if (v.length > 2) v = v.slice(0,2) + '/' + v.slice(2)
  if (v.length > 5) v = v.slice(0,5) + '/' + v.slice(5,9)
  selectedDateDisplay.value = v
  if (v.length === 10) {
    const [dd, mm, yyyy] = v.split('/')
    selectedDate.value = `${yyyy}-${mm}-${dd}`
  } else {
    selectedDate.value = ''
  }
}

function onConductDateInput(e) {
  let v = e.target.value.replace(/[^0-9]/g, '')
  if (v.length > 2) v = v.slice(0,2) + '/' + v.slice(2)
  if (v.length > 5) v = v.slice(0,5) + '/' + v.slice(5,9)
  conductDateDisplay.value = v
  if (v.length === 10) {
    const [dd, mm, yyyy] = v.split('/')
    form.value.conduct_date = `${yyyy}-${mm}-${dd}`
  } else {
    form.value.conduct_date = ''
  }
}

function onConductNativeChange(e) {
  const val = e.target.value // YYYY-MM-DD
  if (!val) return
  const [yyyy, mm, dd] = val.split('-')
  conductDateDisplay.value = `${dd}/${mm}/${yyyy}`
  form.value.conduct_date = val
}
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
  client_ids: [],    // multi-select array
  postcode: '',
  reference: '',     // reference number text search
  statuses: [],      // multi-select array
  clerk_ids: [],     // multi-select array
  month: '',         // 'YYYY-MM' or ''
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
  reference_number: '',
  conduct_date: '',
  time_preference: 'anytime',
  time_hour: '09',
  time_minute: '00',
  source_inspection_id: null,
  include_photos: false,
  create_heads_up: false
})

// ── Lifecycle suggestion state ─────────────────────────────────────────
const propertyHistory     = ref([])
const lifecycleSuggestion = ref(null)   // { sourceId, sourceType, sourceDateStr, label }
const noCheckInFound      = ref(false)  // true when check_out selected but no check_in exists
const historyLoading      = ref(false)

// Watch property + inspection_type — load history and compute suggestion
watch(
  () => [form.value.property_id, form.value.inspection_type],
  async ([propId, iType]) => {
    lifecycleSuggestion.value = null
    noCheckInFound.value = false
    form.value.source_inspection_id = null
    if (!propId) return

    // Standalone types — no lifecycle lookup needed
    if (iType === 'damage_report' || iType === 'midterm' || iType === 'heads_up') return

    historyLoading.value = true
    try {
      const res = await api.getPropertyHistory(propId)
      // Guard: type may have changed while the request was in-flight
      if (form.value.inspection_type !== iType) return
      propertyHistory.value = res.data

      if (iType === 'check_out') {
        // Only look for the most recent Check In (not inventory/check_out)
        const source = res.data.find(h =>
          h.id !== undefined && h.inspection_type === 'check_in'
        )
        if (source) {
          const dateStr = source.conduct_date
            ? new Date(source.conduct_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
            : new Date(source.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
          lifecycleSuggestion.value = {
            sourceId: source.id,
            sourceType: 'check_in',
            sourceDateStr: dateStr,
            label: 'Check In'
          }
          form.value.source_inspection_id = source.id
        } else {
          noCheckInFound.value = true
          // Auto-switch to Damage Report — standalone type used when no Check In exists
          form.value.inspection_type = 'damage_report'
        }
      } else if (iType === 'check_in') {
        // Seed from most recent check_out with report data
        const source = res.data.find(h =>
          h.id !== undefined && h.inspection_type === 'check_out' && h.has_report_data
        )
        if (source) {
          const dateStr = source.conduct_date
            ? new Date(source.conduct_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
            : new Date(source.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
          lifecycleSuggestion.value = {
            sourceId: source.id,
            sourceType: 'check_out',
            sourceDateStr: dateStr,
            label: 'Check Out'
          }
          form.value.source_inspection_id = source.id
        }
      }
    } catch {
      // silent fail
    } finally {
      historyLoading.value = false
    }
  }
)

// ── Create-from-PDF modal ──────────────────────────────────────────────────
// All PDF import state and logic lives in <PdfImportModal>. The parent only
// tracks whether the modal is open so it can v-if the component in/out of DOM.
const showPdfImportModal = ref(false)
function openPdfImportModal() { showPdfImportModal.value = true }

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
    filtered = filtered.filter(i => calendarFilters.value.client_ids.map(Number).includes(Number(i.client_id)))
  if (calendarFilters.value.statuses?.length)
    filtered = filtered.filter(i => calendarFilters.value.statuses.includes(i.status))
  if (calendarFilters.value.clerk_ids?.length)
    filtered = filtered.filter(i => calendarFilters.value.clerk_ids.map(Number).includes(Number(i.inspector_id)))

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
        case 'check_in':      typeShort = 'C/I'; break
        case 'check_out':     typeShort = 'C/O'; break
        case 'inventory':     typeShort = 'INV'; break
        case 'damage_report': typeShort = 'DMG'; break
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
  // Clients must not see inspections in active or processing stage
  if (authStore.isClient) {
    result = result.filter(i => !['active', 'processing'].includes(i.status))
  }
  if (filters.value.client_ids?.length)
    result = result.filter(i => filters.value.client_ids.map(Number).includes(Number(i.client_id)))
  if (filters.value.postcode) {
    const s = filters.value.postcode.toLowerCase()
    result = result.filter(i => i.property_address && i.property_address.toLowerCase().includes(s))
  }
  if (filters.value.reference) {
    const s = filters.value.reference.toLowerCase()
    result = result.filter(i => i.reference_number && i.reference_number.toLowerCase().includes(s))
  }
  if (filters.value.statuses && filters.value.statuses.length)
    result = result.filter(i => filters.value.statuses.includes(i.status))
  if (filters.value.clerk_ids?.length)
    result = result.filter(i => filters.value.clerk_ids.map(Number).includes(Number(i.inspector_id)))
  if (filters.value.month) {
    result = result.filter(i => {
      const d = i.conduct_date || i.created_at
      if (!d) return false
      return d.startsWith(filters.value.month)
    })
  }
  // Sort newest first by conduct_date, falling back to created_at; nulls last
  result.sort((a, b) => {
    const da = a.conduct_date || a.created_at || ''
    const db = b.conduct_date || b.created_at || ''
    if (!da && !db) return 0
    if (!da) return 1
    if (!db) return -1
    return db.localeCompare(da)
  })
  return result
})

const propertySearchQuery = ref('')

const filteredProperties = computed(() => {
  let props = form.value.client_id
    ? properties.value.filter(p => p.client_id === form.value.client_id)
    : properties.value
  if (propertySearchQuery.value.trim()) {
    const q = propertySearchQuery.value.trim().toLowerCase()
    props = props.filter(p => p.address && p.address.toLowerCase().includes(q))
  }
  return props
})

const clerks = computed(() => users.value.filter(u => u.role === 'clerk'))
const typists = computed(() => users.value.filter(u => u.role === 'typist'))
const filteredTemplates = computed(() =>
  form.value.inspection_type === 'damage_report'
    ? templates.value
    : templates.value.filter(t => t.inspection_type === form.value.inspection_type)
)

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
  filters.value = { client_ids: [], postcode: '', reference: '', statuses: [], clerk_ids: [], month: '' }
}

function clearCalendarFilters() {
  calendarFilters.value = { client_ids: [], statuses: [], clerk_ids: [] }
}

function handleEventClick(info) {
  router.push(`/inspections/${info.event.id}`)
}

function openDatePicker() {
  const today = new Date()
  const dd   = String(today.getDate()).padStart(2,'0')
  const mm   = String(today.getMonth()+1).padStart(2,'0')
  const yyyy = today.getFullYear()
  selectedDateDisplay.value = `${dd}/${mm}/${yyyy}`
  selectedDate.value = today.toISOString().split('T')[0]
  showDatePicker.value = true
}

// Called when user picks from native calendar icon
function onNativeDateChange(e) {
  const val = e.target.value // YYYY-MM-DD
  if (!val) return
  const [yyyy, mm, dd] = val.split('-')
  selectedDateDisplay.value = `${dd}/${mm}/${yyyy}`
  selectedDate.value = val
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

// Directive: v-click-outside — closes dropdowns when clicking outside filters-bar
const vClickOutside = {
  mounted(el, binding) {
    el._outsideClick = (e) => { if (!el.contains(e.target)) binding.value(e) }
    document.addEventListener('mousedown', el._outsideClick)
  },
  unmounted(el) { document.removeEventListener('mousedown', el._outsideClick) }
}

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
    const msg = error._friendlyMessage || 'Could not load inspections — please try again.'
    console.error('fetchInspections error:', error)
    toast.error(msg)
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
  propertySearchQuery.value = ''
  conductDateDisplay.value = ''
  form.value = {
    client_id: authStore.isClient ? authStore.user.client_id : null,
    property_id: null,
    inspection_type: 'check_in',
    inspector_id: null,
    template_id: null,
    typist_id: null,
    tenant_email: '',
    reference_number: '',
    conduct_date: '',
    time_preference: 'anytime',
    time_hour: '09',
    time_minute: '00',
    source_inspection_id: null,
    include_photos: false
  }
  lifecycleSuggestion.value = null
  noCheckInFound.value = false
  propertyHistory.value = []
  showModal.value = true
}

function onClientChange() {
  form.value.property_id = null
  propertySearchQuery.value = ''
  lifecycleSuggestion.value = null
  form.value.source_inspection_id = null
}

async function handleSubmit() {
  if (!form.value.property_id) {
    toast.warning('Please select a property')
    return
  }
  if (!authStore.isClient && !form.value.inspector_id) {
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
      reference_number: form.value.reference_number || null,
      conduct_time_preference: timePreference,
      source_inspection_id: form.value.source_inspection_id || null,
      include_photos: form.value.include_photos || false,
      create_heads_up: form.value.create_heads_up || false
    }

    if (form.value.conduct_date) {
      payload.conduct_date = form.value.conduct_date + 'T00:00:00'
    }

    await api.createInspection(payload)

    toast.success(form.value.create_heads_up ? 'Inspection and Heads Up Report created' : 'Inspection created')
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

onMounted(async () => {
  // Pre-apply status filter if navigated from a dashboard workflow card
  const statusParam = route.query.status
  if (statusParam) {
    const valid = ['created', 'assigned', 'active', 'processing', 'review', 'complete']
    const statuses = (Array.isArray(statusParam) ? statusParam : [statusParam])
      .filter(s => valid.includes(s))
    if (statuses.length) filters.value.statuses = statuses
  }

  fetchInspections()

  const doAutoOpen  = route.query.autoOpen === '1'
  const qClientId   = doAutoOpen && route.query.clientId   ? Number(route.query.clientId)   : null
  const qPropertyId = doAutoOpen && route.query.propertyId ? Number(route.query.propertyId) : null

  if (doAutoOpen) {
    // Wait for the data the modal needs before opening it
    await Promise.all([
      fetchProperties(),
      !authStore.isClient ? fetchClients()   : Promise.resolve(),
      !authStore.isClient ? fetchUsers()     : Promise.resolve(),
      fetchTemplates()
    ])
    openModal()
    if (qClientId) {
      form.value.client_id = qClientId
      await nextTick()   // let filteredProperties recompute before setting property
    }
    if (qPropertyId) form.value.property_id = qPropertyId
  } else {
    fetchProperties()
    if (!authStore.isClient) {
      fetchClients()
      fetchUsers()
    }
    fetchTemplates()
  }
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Inspections</h1>
        <p class="page-sub">Manage and track property inspections</p>
      </div>
      <div class="header-actions">
        <button v-if="authStore.isAdmin || authStore.isManager" @click="openPdfImportModal" class="btn-secondary btn-pdf-import">📄 Create from PDF</button>
        <button v-if="authStore.isAdmin || authStore.isManager || authStore.isClient" @click="openModal" class="btn-primary">+ Add Inspection</button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button @click="activeTab = 'list'" class="tab-button" :class="{ active: activeTab === 'list' }">
        List View
      </button>
      <button @click="activeTab = 'calendar'" class="tab-button" :class="{ active: activeTab === 'calendar' }">
        Calendar View
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
          <label>Reference</label>
          <input v-model="filters.reference" type="text" placeholder="Search reference..." class="filter-input" />
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
        <div class="filter-group">
          <label>Month</label>
          <input v-model="filters.month" type="month" class="filter-input" style="min-width:140px" />
        </div>
        <button @click="clearFilters" class="btn-clear-filters">Clear Filters</button>
      </div>


    <!-- Mobile FABs (shown on small screens only via media query) -->
    <button
      v-if="authStore.isAdmin || authStore.isManager"
      class="mobile-fab mobile-fab-pdf"
      @click="openPdfImportModal"
      title="Import from PDF"
    >📄</button>
    <button
      v-if="authStore.isAdmin || authStore.isManager || authStore.isClient"
      class="mobile-fab mobile-fab-add"
      @click="openModal"
      title="Add Inspection"
    >+</button>

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
              <div class="assign-left">
                <div v-if="inspection.inspector_name" class="assign-row">
                  <span class="assign-role">Clerk</span>
                  <span class="assign-name">{{ inspection.inspector_name }}</span>
                </div>
                <div v-if="inspection.typist_name" class="assign-row">
                  <span class="assign-role">Typist</span>
                  <span class="assign-name">{{ inspection.typist_name }}</span>
                </div>
              </div>
              <div v-if="inspection.reference_number" class="assign-row assign-ref">
                <span class="assign-role">Ref</span>
                <span class="assign-name">{{ inspection.reference_number }}</span>
              </div>
            </div>
          </div>

          <div class="card-footer">
            <span class="card-created">Created {{ new Date(inspection.created_at).toLocaleDateString('en-GB') }}</span>
            <button v-if="authStore.isAdmin || authStore.isManager" @click.stop="deleteInspection(inspection.id)" class="btn-delete-sm">✕</button>
          </div>
        </div>
        <div v-if="filteredInspections.length === 0" class="empty-state">
          {{ filters.client_ids.length || filters.postcode || filters.reference || filters.statuses.length || filters.clerk_ids.length
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
            <button class="cal-view-btn cal-goto-btn" @click="openDatePicker">Go to Date</button>
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
                <input
                  v-if="form.client_id"
                  v-model="propertySearchQuery"
                  type="text"
                  placeholder="Filter by address..."
                  class="prop-filter-input"
                  autocomplete="off"
                />
                <select v-model="form.property_id" required :disabled="!form.client_id">
                  <option :value="null" disabled>
                    {{ form.client_id ? 'Select a property...' : 'Select a portfolio first' }}
                  </option>
                  <option v-for="property in filteredProperties" :key="property.id" :value="property.id">
                    {{ property.address }}
                  </option>
                </select>
                <p v-if="form.client_id && filteredProperties.length === 0" class="helper-text">
                  No properties found{{ propertySearchQuery ? ' matching your search' : ' for this portfolio' }}.
                </p>
              </div>

              <!-- Inspection Type -->
              <div class="form-group">
                <label>Inspection Type *</label>
                <select v-model="form.inspection_type" required>
                  <option value="check_in">Check In</option>
                  <option value="check_out">Check Out</option>
                  <option value="midterm">Midterm Inspection</option>
                  <option value="interim">Interim Inspection</option>
                  <option value="inventory">Inventory</option>
                  <option value="damage_report">Damage Report</option>
                  <option value="heads_up">Heads Up Report</option>
                </select>
              </div>

              <!-- Date -->
              <div class="form-group">
                <label>Conduct Date</label>
                <div class="date-input-row">
                  <input
                    :value="conductDateDisplay"
                    type="text"
                    placeholder="DD/MM/YYYY"
                    class="input-field date-text-input"
                    maxlength="10"
                    @input="onConductDateInput"
                  />
                  <label class="date-cal-btn" title="Pick from calendar">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="pointer-events:none;position:relative;z-index:0">
                      <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
                    </svg>
                    <input
                      type="date"
                      :value="form.conduct_date"
                      @change="onConductNativeChange"
                      style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;z-index:1"
                    />
                  </label>
                </div>
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

              <!-- Template (admin/manager only) -->
              <template v-if="!authStore.isClient">
                <div class="form-group" v-if="form.inspection_type === 'midterm'">
                  <label>Template</label>
                  <p class="helper-text">Midterm reports use sections configured in <strong>Settings → Midterm Sections</strong>. No room template required.</p>
                </div>
                <div class="form-group" v-else-if="form.inspection_type === 'heads_up'">
                  <label>Template</label>
                  <p class="helper-text">Heads Up Reports use sections configured in <strong>Settings → Heads-Up Sections</strong>. No room template required.</p>
                </div>
                <div class="form-group" v-else>
                  <label>Template</label>
                  <select v-model="form.template_id">
                    <option :value="null">Use default for this type</option>
                    <option v-for="t in filteredTemplates" :key="t.id" :value="t.id">
                      {{ t.name }}{{ t.is_default ? ' ★ Default' : '' }}
                    </option>
                  </select>
                  <p v-if="filteredTemplates.length === 0" class="helper-text warning">
                    No templates for this type. Create one in Settings → Templates.
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
                    No clerks available. Create clerk users first.
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
              </template>

              <!-- Tenant contact -->
              <div class="form-group">
                <label>Tenant Email(s)</label>
                <input v-model="form.tenant_email" type="text" placeholder="tenant@example.com, tenant2@example.com" />
                <p class="helper-text">💡 Separate multiple addresses with commas</p>
              </div>

              <!-- Heads-Up Report -->
              <div class="form-group">
                <label class="lc-checkbox">
                  <input type="checkbox" v-model="form.create_heads_up" />
                  <span>Create Heads Up Report</span>
                </label>
                <p class="helper-text">Automatically creates a linked Heads-Up Report for this property</p>
              </div>

              <!-- Reference Number -->
              <div class="form-group">
                <label>Reference Number</label>
                <input v-model="form.reference_number" type="text" placeholder="e.g. INS-2024-001" />
                <p class="helper-text">Optional — auto-generated if left blank</p>
              </div>
            </div>

          </div>
          <!-- ── End columns ─────────────────────────────────────────── -->

          <!-- ── Lifecycle suggestion banner (full-width below cols) ─── -->
          <div v-if="historyLoading && form.property_id && !['damage_report','midterm','heads_up'].includes(form.inspection_type)" class="lc-loading">
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

          <!-- ── No Check In found — auto-switched to Damage Report ─── -->
          <div
            v-else-if="noCheckInFound && !historyLoading"
            class="lc-warning-banner lc-info-banner"
          >
            <div class="lc-banner-icon">ℹ️</div>
            <div class="lc-banner-body">
              <strong class="lc-banner-title">No previous Check In found — switched to Damage Report</strong>
              <p class="lc-banner-desc">
                No Check In exists for this property, so the inspection type has been set to
                <strong>Damage Report</strong> automatically. To use a Check Out instead, select it
                manually above, or create a backdated Check In via the
                <strong>Create from PDF</strong> button on the Inspections page.
              </p>
            </div>
          </div>

          <div class="modal-footer">
            <button type="button" @click="showModal = false" class="btn-secondary">Cancel</button>
            <button type="submit" class="btn-primary">Create Inspection</button>
          </div>
        </form>
      </div>
    </div>

    <!-- ══ Create Inspection from PDF Modal ════════════════════════════ -->
    <PdfImportModal
      v-if="showPdfImportModal"
      :clients="clients"
      :properties="properties"
      :templates="templates"
      :is-client="authStore.isClient"
      :user-client-id="authStore.user?.client_id ?? null"
      @close="showPdfImportModal = false"
      @saved="showPdfImportModal = false; fetchInspections()"
    />

    <!-- Date Picker Modal -->
    <div v-if="showDatePicker" class="modal-overlay" @click.self="showDatePicker = false">
      <div class="modal modal-small">
        <div class="modal-header">
          <h2>Go to Date</h2>
          <button @click="showDatePicker = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Select a date</label>
            <div class="date-input-row">
              <input
                v-model="selectedDateDisplay"
                type="text"
                placeholder="DD/MM/YYYY"
                class="input-field date-text-input"
                maxlength="10"
                @input="onDateDisplayInput"
              />
              <label class="date-cal-btn" title="Pick from calendar">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="pointer-events:none;position:relative;z-index:0">
                  <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
                </svg>
                <input
                  type="date"
                  :value="selectedDate"
                  @change="onNativeDateChange"
                  style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;z-index:1"
                />
              </label>
            </div>
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
  height: 36px;
  box-sizing: border-box;
}
/* Normalise month picker height to match other filter controls */
.filter-input[type="month"] {
  height: 36px;
  padding: 0 10px;
  line-height: 36px;
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
  border: 1px solid #e8ecf1;
  border-radius: 12px;
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
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
}

.assign-left {
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
  color: #94a3b8;
  padding-bottom: 6px;
  border-bottom: 1px solid #f1f5f9;
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

.prop-filter-input {
  padding: 7px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 7px 7px 0 0;
  border-bottom: none;
  font-size: 13px;
  font-family: inherit;
  color: #1e293b;
  background: #f8fafc;
  width: 100%;
  box-sizing: border-box;
}
.prop-filter-input:focus {
  outline: none;
  border-color: #6366f1;
  background: #fff;
}
.prop-filter-input + select {
  border-radius: 0 0 7px 7px;
}

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

/* ══════════════════════════════════════
   MOBILE  ≤ 768px
══════════════════════════════════════ */
@media (max-width: 768px) {

  /* FAB replaces the header Add button */
  .page-header .btn-primary,
  .page-header .btn-secondary.btn-pdf-import {
    display: none;
  }

  .mobile-fab {
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


.mobile-fab {
  display: none;
  position: fixed;
  right: 18px;
  width: 52px;
  height: 52px;
  color: white;
  border: none;
  border-radius: 50%;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  z-index: 150;
  align-items: center;
  justify-content: center;
  transition: transform 0.15s;
}
.mobile-fab:hover { transform: scale(1.07); }

.mobile-fab-add {
  bottom: 76px;
  background: #6366f1;
  box-shadow: 0 4px 14px rgba(99,102,241,0.4);
  font-size: 28px;
}

.mobile-fab-pdf {
  bottom: 138px;
  background: #0ea5e9;
  box-shadow: 0 4px 14px rgba(14,165,233,0.35);
  font-size: 20px;
}


/* ── Multi-select dropdown filters ─────────────────────────────────────── */
.filter-group { position: relative; }

.ms-dropdown {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1.5px solid #e2e8f0;
  border-radius: 7px;
  padding: 0 10px;
  height: 36px;
  box-sizing: border-box;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  color: #1e293b;
  min-width: 140px;
  user-select: none;
  white-space: nowrap;
  transition: border-color 0.12s;
}
.ms-dropdown:hover { border-color: #a5b4fc; }
.ms-dropdown.open {
  border-color: #6366f1;
  border-bottom-color: transparent;
  border-radius: 7px 7px 0 0;
}

.ms-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1e293b;
  font-size: 13px;
}
.ms-chevron {
  font-size: 10px;
  color: #94a3b8;
  margin-left: 8px;
  flex-shrink: 0;
  transition: transform 0.15s;
}
.ms-dropdown.open .ms-chevron { transform: rotate(180deg); }

.ms-menu {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 400;
  background: #fff;
  border: 1.5px solid #6366f1;
  border-top: none;
  border-radius: 0 0 7px 7px;
  box-shadow: 0 6px 20px rgba(99,102,241,0.13);
  min-width: 100%;
  padding: 4px 0;
  max-height: 240px;
  overflow-y: auto;
}

.ms-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  cursor: pointer;
  font-size: 13px;
  color: #1e293b;
  white-space: nowrap;
  transition: background 0.08s;
}
.ms-item:hover { background: #f5f3ff; }
.ms-item input[type=checkbox] {
  accent-color: #6366f1;
  cursor: pointer;
  flex-shrink: 0;
  width: 14px;
  height: 14px;
}

.ms-status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ms-clerk-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ms-empty {
  padding: 10px 12px;
  font-size: 12px;
  color: #94a3b8;
  font-style: italic;
}

/* ── FullCalendar event cursor ──────────────────────────────────────────── */
.calendar-container :deep(.fc-event) { cursor: pointer !important; }
.calendar-container :deep(.fc-event *) { cursor: pointer !important; }
.calendar-container :deep(.fc-daygrid-event) { cursor: pointer !important; }
.calendar-container :deep(.fc-timegrid-event) { cursor: pointer !important; }


/* Date input with calendar icon */
.date-input-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.date-text-input {
  flex: 1;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.5px;
}
.date-cal-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1.5px solid #e2e8f0;
  border-radius: 7px;
  background: #f8fafc;
  cursor: pointer;
  flex-shrink: 0;
  color: #64748b;
  transition: border-color 0.12s, background 0.12s;
  overflow: hidden;
}
.date-cal-btn:hover {
  border-color: #6366f1;
  background: #eef2ff;
  color: #6366f1;
}

/* ── Header action buttons ─────────────────────────────────────────────── */
.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.btn-pdf-import {
  font-size: 13px;
  font-weight: 600;
  padding: 9px 16px;
  border-radius: 8px;
  white-space: nowrap;
}

/* ── Warning banner (no check-in found) ────────────────────────────────── */
.lc-warning-banner {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 14px 16px;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: 10px;
}
.lc-warn-title { color: #92400e !important; }
.lc-warn-desc  { color: #78350f !important; }

/* Info variant (blue) — for auto-switch notification */
.lc-info-banner {
  background: #eff6ff;
  border-color: #93c5fd;
}
.lc-info-banner .lc-banner-title { color: #1e40af; }
.lc-info-banner .lc-banner-desc  { color: #1d4ed8; }
</style>
