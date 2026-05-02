<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
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
  conduct_date: '',
  time_preference: 'anytime',
  time_hour: '09',
  time_minute: '00',
  source_inspection_id: null,
  include_photos: false
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
    if (iType === 'damage_report' || iType === 'midterm') return

    historyLoading.value = true
    try {
      const res = await api.getPropertyHistory(propId)
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

// ── Create-from-PDF modal state ────────────────────────────────────────
const showPdfImportModal   = ref(false)
const pdfImportStep        = ref(1)  // 1=select property, 2=upload+parse, 3=review
const pdfImportForm        = ref({
  client_id:       null,
  property_id:     null,
  conduct_date:    '',
  conductDateDisplay: '',
  template_id:     null,
  suppress_emails: true,   // default ON — backdated reports don't need client emails
})
const pdfImportFile        = ref(null)
const pdfImportFileName    = ref('')
const pdfImportParsed      = ref(null)   // { rooms, fixedSections }
const pdfImportError       = ref('')
const pdfImportSaving      = ref(false)
const pdfImportParsing     = ref(false)

function openPdfImportModal() {
  pdfImportStep.value = 1
  pdfImportForm.value = {
    client_id: authStore.isClient ? authStore.user.client_id : null,
    property_id: null,
    conduct_date: '',
    conductDateDisplay: '',
    template_id: null,
    suppress_emails: true,
  }
  pdfImportFile.value = null
  pdfImportFileName.value = ''
  pdfImportParsed.value = null
  pdfImportError.value = ''
  pdfImportSaving.value = false
  pdfImportParsing.value = false
  showPdfImportModal.value = true
}

function onPdfImportClientChange() {
  pdfImportForm.value.property_id = null
}

const filteredPdfProperties = computed(() => {
  if (!pdfImportForm.value.client_id) return properties.value
  return properties.value.filter(p => p.client_id === pdfImportForm.value.client_id)
})

const filteredPdfTemplates = computed(() => templates.value.filter(t => t.inspection_type === 'check_in'))

function onPdfImportConductDateInput(e) {
  let v = e.target.value.replace(/[^0-9]/g, '')
  if (v.length > 2) v = v.slice(0,2) + '/' + v.slice(2)
  if (v.length > 5) v = v.slice(0,5) + '/' + v.slice(5,9)
  pdfImportForm.value.conductDateDisplay = v
  if (v.length === 10) {
    const [dd, mm, yyyy] = v.split('/')
    pdfImportForm.value.conduct_date = `${yyyy}-${mm}-${dd}`
  } else {
    pdfImportForm.value.conduct_date = ''
  }
}

function onPdfImportNativeDateChange(e) {
  const val = e.target.value
  if (!val) return
  const [yyyy, mm, dd] = val.split('-')
  pdfImportForm.value.conductDateDisplay = `${dd}/${mm}/${yyyy}`
  pdfImportForm.value.conduct_date = val
}

function onPdfImportFileSelected(e) {
  const file = e.target?.files?.[0] || e.dataTransfer?.files?.[0]
  if (!file) return
  if (file.type !== 'application/pdf') { toast.error('Please choose a PDF file'); return }
  pdfImportFile.value = file
  pdfImportFileName.value = file.name
}

// ── Cloud PDF pickers ────────────────────────────────────────────────────────

const DROPBOX_KEY     = import.meta.env.VITE_DROPBOX_APP_KEY    || ''
const GDRIVE_CLIENT   = import.meta.env.VITE_GOOGLE_CLIENT_ID   || ''
const GDRIVE_API_KEY  = import.meta.env.VITE_GOOGLE_API_KEY     || ''

function _loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return }
    const s = document.createElement('script')
    s.src = src; s.onload = resolve; s.onerror = reject
    document.head.appendChild(s)
  })
}

function _setPdfFile(file) {
  pdfImportFile.value     = file
  pdfImportFileName.value = file.name
  pdfImportError.value    = ''
}

async function openDropboxPicker() {
  if (!DROPBOX_KEY) { toast.error('Dropbox is not configured'); return }
  try {
    await _loadScript('https://www.dropbox.com/static/api/2/dropins.js')
    window.Dropbox.choose({
      appKey:     DROPBOX_KEY,
      linkType:   'direct',
      multiselect: false,
      extensions: ['.pdf'],
      success: async (files) => {
        const url = files[0].link
        try {
          const resp = await fetch(url)
          if (!resp.ok) throw new Error('Download failed')
          const blob = await resp.blob()
          const file = new File([blob], files[0].name, { type: 'application/pdf' })
          _setPdfFile(file)
          toast.success('PDF loaded from Dropbox')
        } catch (e) {
          toast.error('Failed to download from Dropbox: ' + e.message)
        }
      },
      cancel: () => {},
    })
  } catch (e) {
    toast.error('Could not load Dropbox picker')
    console.error(e)
  }
}

let _gdriveToken = null

async function _ensureGdriveToken() {
  if (_gdriveToken) return _gdriveToken
  await _loadScript('https://accounts.google.com/gsi/client')
  return new Promise((resolve, reject) => {
    const client = google.accounts.oauth2.initTokenClient({
      client_id: GDRIVE_CLIENT,
      scope: 'https://www.googleapis.com/auth/drive.readonly',
      callback: (resp) => {
        if (resp.error) { reject(new Error(resp.error)); return }
        _gdriveToken = resp.access_token
        resolve(_gdriveToken)
      },
    })
    client.requestAccessToken({ prompt: 'consent' })
  })
}

async function openGoogleDrivePicker() {
  if (!GDRIVE_CLIENT || !GDRIVE_API_KEY) { toast.error('Google Drive is not configured'); return }
  try {
    const [token] = await Promise.all([
      _ensureGdriveToken(),
      _loadScript('https://apis.google.com/js/api.js'),
    ])
    await new Promise((resolve) => gapi.load('picker', resolve))

    const picker = new google.picker.PickerBuilder()
      .addView(google.picker.ViewId.DOCS)
      .setMimeTypes('application/pdf')
      .setOAuthToken(token)
      .setDeveloperKey(GDRIVE_API_KEY)
      .setCallback(async (data) => {
        if (data.action !== google.picker.Action.PICKED) return
        const fileId   = data.docs[0].id
        const fileName = data.docs[0].name
        try {
          const resp = await fetch(
            `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media`,
            { headers: { Authorization: `Bearer ${token}` } }
          )
          if (!resp.ok) throw new Error('Drive download failed')
          const blob = await resp.blob()
          const file = new File([blob], fileName.endsWith('.pdf') ? fileName : fileName + '.pdf', { type: 'application/pdf' })
          _setPdfFile(file)
          toast.success('PDF loaded from Google Drive')
        } catch (e) {
          toast.error('Failed to download from Drive: ' + e.message)
        }
      })
      .build()
    picker.setVisible(true)
  } catch (e) {
    toast.error('Could not open Google Drive picker')
    console.error(e)
  }
}

// ── End cloud pickers ─────────────────────────────────────────────────────────

async function runPdfImportParse() {
  if (!pdfImportFile.value) { toast.warning('Please select a PDF file'); return }
  pdfImportParsing.value = true
  pdfImportError.value = ''
  try {
    // POST the PDF — returns a job_id immediately (background thread does the work)
    const startRes = await api.pdfImport(pdfImportFile.value)
    const jobId = startRes.data.job_id
    if (!jobId) throw new Error('No job ID returned from server')

    // Poll every 2 seconds until done
    const MAX_POLLS = 150  // 5 minutes max
    for (let i = 0; i < MAX_POLLS; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const statusRes = await api.pdfImportStatus(jobId)
      const { status, result, error } = statusRes.data

      if (status === 'done') {
        pdfImportParsed.value = result
        pdfImportParsed.value._fileName = pdfImportFileName.value
        pdfImportStep.value = 3
        return
      }
      if (status === 'error') throw new Error(error || 'AI parsing failed')
      if (status === 'not_found') throw new Error('Job expired — please try again')
      // status === 'processing' — keep polling
    }
    throw new Error('Timed out waiting for AI — please try again')

  } catch (e) {
    console.error('PDF parse error:', e)
    pdfImportError.value = 'AI parsing failed: ' + (e.message || 'unknown error')
  } finally {
    pdfImportParsing.value = false
  }
}

async function savePdfImportInspection() {
  if (!pdfImportForm.value.property_id) { toast.warning('Please select a property'); return }
  pdfImportSaving.value = true
  try {
    const payload = {
      property_id:          pdfImportForm.value.property_id,
      inspection_type:      'check_in',
      template_id:          pdfImportForm.value.template_id || null,
      status:               'complete',
      source_inspection_id: null,
      // SUPPRESS sentinel tells the backend not to send client emails for this inspection
      client_email_override: pdfImportForm.value.suppress_emails ? 'SUPPRESS' : undefined,
    }
    if (pdfImportForm.value.conduct_date) {
      payload.conduct_date = pdfImportForm.value.conduct_date + 'T00:00:00'
    }
    const createRes = await api.createInspection(payload)
    const newId = createRes.data?.id || createRes.data?.inspection?.id

    if (pdfImportParsed.value && newId) {
      await api.applyPdfImport(newId, pdfImportParsed.value)
    }

    toast.success('Backdated Check In created successfully')
    showPdfImportModal.value = false
    fetchInspections()
  } catch (e) {
    console.error('Save PDF inspection error:', e)
    toast.error('Failed to save inspection')
  } finally {
    pdfImportSaving.value = false
  }
}

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
  conductDateDisplay.value = ''
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
  noCheckInFound.value = false
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
  // Pre-apply status filter if navigated from a dashboard workflow card
  const statusParam = route.query.status
  if (statusParam) {
    const valid = ['created', 'assigned', 'active', 'processing', 'review', 'complete']
    const statuses = (Array.isArray(statusParam) ? statusParam : [statusParam])
      .filter(s => valid.includes(s))
    if (statuses.length) filters.value.statuses = statuses
  }

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
                  <option value="midterm">Midterm Inspection</option>
                  <option value="interim">Interim Inspection</option>
                  <option value="inventory">Inventory</option>
                  <option value="damage_report">Damage Report</option>
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
          <div v-if="historyLoading && form.property_id && form.inspection_type !== 'damage_report'" class="lc-loading">
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
    <div v-if="showPdfImportModal" class="modal-overlay" @click.self="showPdfImportModal = false">
      <div class="modal modal-wide">
        <div class="modal-header">
          <h2>Create Inspection from PDF</h2>
          <button @click="showPdfImportModal = false" class="btn-close">✕</button>
        </div>

        <!-- Step indicators -->
        <div class="pdf-steps">
          <div class="pdf-step" :class="{ active: pdfImportStep >= 1, done: pdfImportStep > 1 }">
            <span class="pdf-step-num">1</span><span class="pdf-step-label">Property</span>
          </div>
          <div class="pdf-step-line"></div>
          <div class="pdf-step" :class="{ active: pdfImportStep >= 2, done: pdfImportStep > 2 }">
            <span class="pdf-step-num">2</span><span class="pdf-step-label">Upload PDF</span>
          </div>
          <div class="pdf-step-line"></div>
          <div class="pdf-step" :class="{ active: pdfImportStep >= 3 }">
            <span class="pdf-step-num">3</span><span class="pdf-step-label">Review &amp; Save</span>
          </div>
        </div>

        <div class="modal-body">

          <!-- Step 1: Select property + clerk + date -->
          <div v-if="pdfImportStep === 1">
            <div class="modal-cols">
              <div class="modal-col">
                <div class="col-section-title">Property Details</div>
                <div v-if="!authStore.isClient" class="form-group">
                  <label>Portfolio *</label>
                  <select v-model="pdfImportForm.client_id" @change="onPdfImportClientChange">
                    <option :value="null" disabled>Select a portfolio...</option>
                    <option v-for="client in clients" :key="client.id" :value="client.id">{{ client.name }}</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Property *</label>
                  <select v-model="pdfImportForm.property_id" :disabled="!pdfImportForm.client_id">
                    <option :value="null" disabled>{{ pdfImportForm.client_id ? 'Select a property...' : 'Select a portfolio first' }}</option>
                    <option v-for="p in filteredPdfProperties" :key="p.id" :value="p.id">{{ p.address }}</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Original Inspection Date</label>
                  <div class="date-input-row">
                    <input :value="pdfImportForm.conductDateDisplay" type="text" placeholder="DD/MM/YYYY" class="input-field date-text-input" maxlength="10" @input="onPdfImportConductDateInput" />
                    <label class="date-cal-btn" title="Pick from calendar">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="pointer-events:none;position:relative;z-index:0"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                      <input type="date" :value="pdfImportForm.conduct_date" @change="onPdfImportNativeDateChange" style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;z-index:1" />
                    </label>
                  </div>
                  <p class="helper-text">Set the original check-in date from the PDF</p>
                </div>
              </div>
              <div class="modal-col">
                <div class="col-section-title">Options</div>
                <div class="form-group">
                  <label>Template</label>
                  <select v-model="pdfImportForm.template_id">
                    <option :value="null">Use default check-in template</option>
                    <option v-for="t in filteredPdfTemplates" :key="t.id" :value="t.id">{{ t.name }}{{ t.is_default ? ' ★' : '' }}</option>
                  </select>
                </div>
                <div class="pdf-suppress-row">
                  <label class="pdf-suppress-label">
                    <input type="checkbox" v-model="pdfImportForm.suppress_emails" />
                    <span>Disable client email notifications</span>
                  </label>
                  <p class="pdf-suppress-hint">Prevents the system sending a completed report email for this backdated inspection.</p>
                </div>
                <div class="pdf-step1-info">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  <span>The inspection will be created as a completed Check In backdated to the date you enter. You can then start a Check Out against it.</span>
                </div>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" @click="showPdfImportModal = false" class="btn-secondary">Cancel</button>
              <button type="button" @click="pdfImportStep = 2" :disabled="!pdfImportForm.property_id" class="btn-primary">Next: Upload PDF →</button>
            </div>
          </div>

          <!-- Step 2: Upload PDF + parse -->
          <div v-if="pdfImportStep === 2">
            <p class="pdf-step2-intro">Upload the original Check In or Inventory PDF. Claude will extract all rooms, items, descriptions and conditions automatically.</p>
            <label
              class="pdf-dropzone"
              :class="{ 'pdf-dropzone-has': pdfImportFileName }"
              @dragover.prevent
              @drop.prevent="onPdfImportFileSelected"
            >
              <template v-if="!pdfImportFileName">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <span class="pdf-dz-title">Drop PDF here or <u>browse</u></span>
                <span class="pdf-dz-hint">Supports Check In and Inventory reports in PDF format</span>
              </template>
              <template v-else>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span class="pdf-dz-filename">{{ pdfImportFileName }}</span>
                <span class="pdf-dz-hint">Click to change</span>
              </template>
              <input type="file" accept="application/pdf" style="display:none" @change="onPdfImportFileSelected" />
            </label>

            <!-- Cloud pickers -->
            <div class="pdf-cloud-row">
              <span class="pdf-cloud-or">or import from</span>
              <button type="button" class="btn-cloud btn-cloud-gdrive" @click="openGoogleDrivePicker">
                <svg width="18" height="18" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
                  <path d="M6.6 66.85l3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3L27.5 53H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
                  <path d="M43.65 25L29.9 1.2C28.55 2 27.4 3.1 26.6 4.5L1.2 48.5A9.06 9.06 0 000 53h27.5z" fill="#00ac47"/>
                  <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8L73.55 76.8z" fill="#ea4335"/>
                  <path d="M43.65 25L57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>
                  <path d="M59.8 53H27.5L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.4 4.5-1.2z" fill="#2684fc"/>
                  <path d="M73.4 26.5L60.7 4.5C59.9 3.1 58.75 2 57.4 1.2L43.65 25 59.8 53h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/>
                </svg>
                Google Drive
              </button>
              <button type="button" class="btn-cloud btn-cloud-dropbox" @click="openDropboxPicker">
                <svg width="18" height="18" viewBox="0 0 215 205" xmlns="http://www.w3.org/2000/svg" fill="#0061FF">
                  <path d="M67.5 0L0 43.8l47.7 38.2L67.5 71l19.8 11L107.5 71l19.8 11 19.8-11 47.7-38.2L127.5 0 107.5 22.5zM107.5 82L87.7 71 47.7 97.8 0 63.8l67.5 43.8 40-27L127.5 108l40-27.2L215 63.8l-47.7 34L127.5 71zM67.5 108.8L0 152.5 67.5 196 107.5 171l40 25L215 152.5l-67.5-43.7-40 27-40-27z"/>
                </svg>
                Dropbox
              </button>
            </div>

            <div v-if="pdfImportError" class="pdf-error">{{ pdfImportError }}</div>
            <div v-if="pdfImportParsing" class="pdf-parsing-status">
              <span class="lc-spinner"></span> Analysing PDF with AI — this may take 30–60 seconds…
            </div>
            <div class="modal-footer">
              <button type="button" @click="pdfImportStep = 1" class="btn-secondary" :disabled="pdfImportParsing">← Back</button>
              <button type="button" @click="runPdfImportParse" :disabled="!pdfImportFileName || pdfImportParsing" class="btn-primary">
                {{ pdfImportParsing ? 'Analysing…' : 'Analyse PDF →' }}
              </button>
            </div>
          </div>

          <!-- Step 3: Review & Save -->
          <div v-if="pdfImportStep === 3 && pdfImportParsed">
            <div class="pdf-review-summary">
              <div class="pdf-review-stat">
                <span class="pdf-review-num">{{ pdfImportParsed.rooms?.length || 0 }}</span>
                <span class="pdf-review-lbl">Rooms found</span>
              </div>
              <div class="pdf-review-stat">
                <span class="pdf-review-num">{{ pdfImportParsed.rooms?.reduce((n, r) => n + (r.items?.length || 0), 0) || 0 }}</span>
                <span class="pdf-review-lbl">Items extracted</span>
              </div>
              <div class="pdf-review-stat">
                <span class="pdf-review-num">{{ Object.keys(pdfImportParsed.fixedSections || {}).length }}</span>
                <span class="pdf-review-lbl">Fixed sections</span>
              </div>
            </div>
            <div class="pdf-review-rooms">
              <div v-for="room in (pdfImportParsed.rooms || [])" :key="room.name" class="pdf-review-room">
                <div class="pdf-review-room-name">{{ room.name }}</div>
                <div class="pdf-review-items">{{ room.items?.length || 0 }} items</div>
              </div>
            </div>
            <p class="pdf-review-note">✓ Review looks correct? Click Save to create the backdated Check In with this data.</p>
            <div class="modal-footer">
              <button type="button" @click="pdfImportStep = 2" class="btn-secondary" :disabled="pdfImportSaving">← Re-upload</button>
              <button type="button" @click="savePdfImportInspection" :disabled="pdfImportSaving" class="btn-primary">
                {{ pdfImportSaving ? 'Saving…' : 'Save Backdated Check In' }}
              </button>
            </div>
          </div>

        </div>
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

/* ── Create from PDF modal steps ────────────────────────────────────────── */
.pdf-steps {
  display: flex;
  align-items: center;
  padding: 16px 24px 0;
  gap: 0;
}
.pdf-step {
  display: flex;
  align-items: center;
  gap: 7px;
  opacity: 0.4;
  transition: opacity 0.2s;
}
.pdf-step.active { opacity: 1; }
.pdf-step-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.2s, color 0.2s;
}
.pdf-step.active .pdf-step-num { background: #6366f1; color: #fff; }
.pdf-step.done .pdf-step-num   { background: #10b981; color: #fff; }
.pdf-step-label { font-size: 12px; font-weight: 600; color: #64748b; white-space: nowrap; }
.pdf-step.active .pdf-step-label { color: #1e293b; }
.pdf-step-line {
  flex: 1;
  height: 2px;
  background: #e2e8f0;
  margin: 0 8px;
  min-width: 20px;
}

/* Step 1 info box */
.pdf-step1-info {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  background: #eef2ff;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  color: #4338ca;
  line-height: 1.5;
  margin-top: 4px;
}
.pdf-step1-info svg { flex-shrink: 0; margin-top: 1px; }

/* Step 2 intro */
.pdf-step2-intro {
  font-size: 13px;
  color: #64748b;
  margin: 0 0 16px;
  line-height: 1.5;
}

/* PDF dropzone (large) */
.pdf-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 40px 24px;
  cursor: pointer;
  transition: all 0.15s;
  background: #f8fafc;
  text-align: center;
  color: #64748b;
  min-height: 160px;
}
.pdf-dropzone:hover, .pdf-dropzone-has {
  border-color: #6366f1;
  background: #eef2ff;
}
.pdf-dz-title  { font-size: 15px; font-weight: 600; color: #475569; }
.pdf-dz-hint   { font-size: 12px; color: #94a3b8; }
.pdf-dz-filename { font-size: 14px; font-weight: 700; color: #4338ca; }

.pdf-cloud-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.pdf-cloud-or {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
}
.btn-cloud {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 14px;
  border-radius: 8px;
  border: 1.5px solid #e2e8f0;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.btn-cloud:hover {
  border-color: #6366f1;
  background: #f5f3ff;
}

.pdf-error {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  margin-top: 10px;
}

.pdf-parsing-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #6366f1;
  padding: 12px 0 4px;
  font-weight: 600;
}

/* Step 3 review */
.pdf-review-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}
.pdf-review-stat {
  flex: 1;
  background: #f1f5f9;
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}
.pdf-review-num {
  display: block;
  font-size: 28px;
  font-weight: 800;
  color: #6366f1;
  line-height: 1;
  margin-bottom: 4px;
}
.pdf-review-lbl { font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }
.pdf-review-rooms {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
  max-height: 200px;
  overflow-y: auto;
  margin-bottom: 12px;
}
.pdf-review-room {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  padding: 8px 10px;
}
.pdf-review-room-name { font-size: 12px; font-weight: 700; color: #1e293b; margin-bottom: 2px; }
.pdf-review-items     { font-size: 11px; color: #94a3b8; }
.pdf-review-note      { font-size: 12px; color: #16a34a; font-weight: 600; margin: 0; }

/* Email suppress toggle */
.pdf-suppress-row {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  padding: 10px 12px;
}
.pdf-suppress-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #92400e;
  cursor: pointer;
}
.pdf-suppress-label input[type="checkbox"] {
  accent-color: #f59e0b;
  width: 15px;
  height: 15px;
  cursor: pointer;
  flex-shrink: 0;
}
.pdf-suppress-hint {
  font-size: 11px;
  color: #b45309;
  margin: 5px 0 0 23px;
  line-height: 1.4;
}
</style>