<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Network } from '@capacitor/network'
import api from '../services/api'
import {
  getAllInspections,
  saveInspection,
  getReportData,
  deleteInspection,
} from '../services/offline'
import { syncAll } from '../services/sync'

const router = useRouter()

const localInspections = ref([])
const fetching         = ref(false)
const syncing          = ref(false)
const isOnline         = ref(true)
const syncMessage      = ref('')
const fetchError       = ref('')

// Track which user is logged in for "my inspections" filtering
// Seed from localStorage immediately so role-gated UI (FAB etc.) renders on first paint,
// even before the async getCurrentUser() call completes or when offline.
const currentUser = ref(
  (() => { try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null } })()
)
const isAdminOrManager = computed(() =>
  currentUser.value?.role === 'admin' || currentUser.value?.role === 'manager'
)
const isAdmin = computed(() => currentUser.value?.role === 'admin')

// Speed-dial FAB open/close
const fabExpanded = ref(false)
function closeFab() { fabExpanded.value = false }

onMounted(async () => {
  await checkNetwork()
  await loadLocal()
  try {
    const res = await api.getCurrentUser()
    currentUser.value = res.data
  } catch { /* offline, fine */ }
})

async function checkNetwork() {
  const status = await Network.getStatus()
  isOnline.value = status.connected
  Network.addListener('networkStatusChange', s => { isOnline.value = s.connected })
}

async function loadLocal() {
  localInspections.value = await getAllInspections()
}

// ── Fetch assigned inspections from server ────────────────────────────
async function fetchInspections() {
  if (!isOnline.value) {
    fetchError.value = 'No internet connection'
    return
  }
  fetching.value   = true
  fetchError.value = ''

  try {
    const res  = await api.getInspections()
    const all  = res.data || []

    // Admin/manager see all; clerks and typists see only their own
    const role  = currentUser.value?.role
    const isAM  = role === 'admin' || role === 'manager'
    const mine  = (isAM || !currentUser.value)
      ? all
      : all.filter(i =>
          i.inspector_id === currentUser.value.id ||
          i.typist_id    === currentUser.value.id
        )

    // Save each to local DB
    for (const insp of mine) {
      await saveInspection(insp)
    }

    await loadLocal()
  } catch (err) {
    fetchError.value = `Fetch failed: ${err.message}`
  } finally {
    fetching.value = false
  }
}

// ── Sync all dirty inspections ────────────────────────────────────────
async function syncAllInspections() {
  if (!isOnline.value) { syncMessage.value = 'No connection — sync when back online'; return }
  syncing.value    = true
  syncMessage.value = 'Syncing…'

  const results = await syncAll((step, msg) => { syncMessage.value = msg })

  const ok   = results.filter(r => r.success).length
  const fail = results.filter(r => !r.success).length
  syncMessage.value = fail === 0
    ? `✓ ${ok} inspection(s) synced`
    : `${ok} synced, ${fail} failed`

  await loadLocal()
  syncing.value = false
  setTimeout(() => { syncMessage.value = '' }, 4000)
}

// ── Remove inspection from device ─────────────────────────────────────
async function removeLocal(id) {
  if (!confirm('Remove this inspection from device?')) return
  await deleteInspection(id)
  await loadLocal()
}

// ── Computed ──────────────────────────────────────────────────────────
const dirtyCount = computed(() => localInspections.value.filter(i => i._is_dirty).length)

// ─────────────────────────────────────────────────────────────────────
// CREATE PROPERTY SHEET  (admin only)
// ─────────────────────────────────────────────────────────────────────
const showPropertySheet   = ref(false)
const creatingProp        = ref(false)
const propError           = ref('')
const propSheetLoading    = ref(false)
const propClients         = ref([])

const propForm = ref({
  client_id:         null,
  address:           '',
  property_type:     '',
  bedrooms:          '',
  bathrooms:         '',
  furnished:         '',
  detachment_type:   '',
  elevation:         '',
  parking:           false,
  garden:            false,
  elevator:          false,
  meter_electricity: '',
  meter_gas:         '',
  meter_heat:        '',
  meter_water:       '',
  notes:             '',
})

const PROPERTY_TYPES    = ['House', 'Flat', 'Studio', 'Bungalow', 'Maisonette', 'Cottage', 'Commercial', 'Other']
const FURNISHED_OPTS    = ['Furnished', 'Part Furnished', 'Unfurnished']
const DETACHMENT_OPTS   = ['Terraced', 'End Terrace', 'Semi-Detached', 'Detached', 'Purpose Built']
const ELEVATION_OPTS    = ['Ground Floor', '1st Floor', '2nd Floor', '3rd Floor', '4th Floor', '5th Floor+', 'Top Floor', 'Penthouse']

async function openPropertySheet() {
  propForm.value = {
    client_id: null, address: '', property_type: '', bedrooms: '', bathrooms: '',
    furnished: '', detachment_type: '', elevation: '',
    parking: false, garden: false, elevator: false,
    meter_electricity: '', meter_gas: '', meter_heat: '', meter_water: '',
    notes: '',
  }
  propError.value       = ''
  showPropertySheet.value = true
  propSheetLoading.value  = true
  closeFab()
  try {
    const res = await api.getClients()
    propClients.value = res.data || []
  } catch {
    propError.value = 'Failed to load clients — check connection'
  } finally {
    propSheetLoading.value = false
  }
}

async function submitProperty() {
  if (!propForm.value.client_id) { propError.value = 'Please select a client'; return }
  if (!propForm.value.address.trim()) { propError.value = 'Address is required'; return }
  creatingProp.value = true
  propError.value    = ''
  const payload = {
    client_id:         propForm.value.client_id,
    address:           propForm.value.address.trim(),
    property_type:     propForm.value.property_type     || null,
    bedrooms:          propForm.value.bedrooms !== ''   ? Number(propForm.value.bedrooms)   : null,
    bathrooms:         propForm.value.bathrooms !== ''  ? Number(propForm.value.bathrooms)  : null,
    furnished:         propForm.value.furnished         || null,
    detachment_type:   propForm.value.detachment_type   || null,
    elevation:         propForm.value.elevation         || null,
    parking:           propForm.value.parking,
    garden:            propForm.value.garden,
    elevator:          propForm.value.elevator,
    meter_electricity: propForm.value.meter_electricity || null,
    meter_gas:         propForm.value.meter_gas         || null,
    meter_heat:        propForm.value.meter_heat        || null,
    meter_water:       propForm.value.meter_water       || null,
    notes:             propForm.value.notes             || null,
  }
  try {
    await api.createProperty(payload)
    showPropertySheet.value = false
    // Refresh property list for any open create-inspection sheet
    if (createProperties.value.length) {
      const res = await api.getProperties()
      createProperties.value = res.data || []
    }
  } catch (e) {
    propError.value = e.response?.data?.error || 'Failed to create property'
  } finally {
    creatingProp.value = false
  }
}

// ─────────────────────────────────────────────────────────────────────
// CREATE INSPECTION SHEET  (admin / manager only)
// ─────────────────────────────────────────────────────────────────────
const showCreateSheet   = ref(false)
const creating          = ref(false)
const createError       = ref('')
const createLoading     = ref(false)   // loading properties/templates/users

// Form state
const createForm = ref({
  property_id:          null,
  inspection_type:      'check_in',
  template_id:          null,
  conduct_date:         '',
  inspector_id:         null,
  source_inspection_id: null,
  include_photos:       false,
  tenant_email:         '',
  key_location:         '',
  internal_notes:       '',
})

// Data lists loaded when sheet opens
const createProperties    = ref([])
const createTemplates     = ref([])
const createClerks        = ref([])
const createPropertySearch = ref('')
const createLifecycle     = ref(null)   // { sourceId, label, dateStr }
const historyLoading      = ref(false)

const KEY_LOCATION_OPTS = [
  'With Agent', 'With Landlord', 'With Tenant',
  'At Property', 'At Concierge', 'In Key Safe',
]

const INSPECTION_TYPES = [
  { value: 'check_in',      label: 'Check In' },
  { value: 'check_out',     label: 'Check Out' },
  { value: 'inventory',     label: 'Inventory' },
  { value: 'damage_report', label: 'Damage Report' },
]

const filteredCreateProperties = computed(() => {
  const q = createPropertySearch.value.toLowerCase().trim()
  if (!q) return createProperties.value
  return createProperties.value.filter(p =>
    p.address?.toLowerCase().includes(q)
  )
})

const filteredCreateTemplates = computed(() =>
  createTemplates.value.filter(t => t.inspection_type === createForm.value.inspection_type)
)

const selectedPropertyLabel = computed(() => {
  const p = createProperties.value.find(p => p.id === createForm.value.property_id)
  return p?.address || null
})

async function openCreateSheet() {
  closeFab()
  // Reset form
  createForm.value = {
    property_id:          null,
    inspection_type:      'check_in',
    template_id:          null,
    conduct_date:         '',
    inspector_id:         null,
    source_inspection_id: null,
    include_photos:       false,
    tenant_email:         '',
    key_location:         '',
    internal_notes:       '',
  }
  createPropertySearch.value = ''
  createLifecycle.value      = null
  createError.value          = ''
  showCreateSheet.value      = true
  createLoading.value        = true

  try {
    const [pRes, tRes, uRes] = await Promise.all([
      api.getProperties(),
      api.getTemplates(),
      api.getUsers(),
    ])
    createProperties.value = pRes.data  || []
    createTemplates.value  = tRes.data  || []
    createClerks.value     = (uRes.data || []).filter(u => u.role === 'clerk')
  } catch {
    createError.value = 'Failed to load properties / templates — check connection'
  } finally {
    createLoading.value = false
  }
}

function selectCreateProperty(propId) {
  createForm.value.property_id          = propId
  createForm.value.source_inspection_id = null
  createLifecycle.value                 = null
  createPropertySearch.value            = ''
  loadCreateLifecycle()
}

async function loadCreateLifecycle() {
  const { property_id, inspection_type } = createForm.value
  if (!property_id) return
  historyLoading.value = true
  try {
    const res = await api.getPropertyHistory(property_id)
    const history = res.data || []

    if (inspection_type === 'check_out') {
      const src = history.find(h => h.inspection_type === 'check_in')
      if (src) {
        createLifecycle.value = _lifecycleEntry(src, 'Check In')
        createForm.value.source_inspection_id = src.id
      }
    } else if (inspection_type === 'check_in') {
      const src = history.find(h => h.inspection_type === 'check_out' && h.has_report_data)
      if (src) {
        createLifecycle.value = _lifecycleEntry(src, 'Check Out')
        createForm.value.source_inspection_id = src.id
      }
    }
  } catch { /* offline — silently skip */ }
  historyLoading.value = false
}

function _lifecycleEntry(src, label) {
  const d = src.conduct_date || src.created_at
  const dateStr = d
    ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    : ''
  return { sourceId: src.id, label, dateStr }
}

// When type changes, reset template + lifecycle suggestion
watch(() => createForm.value.inspection_type, () => {
  createForm.value.template_id          = null
  createForm.value.source_inspection_id = null
  createLifecycle.value                 = null
  loadCreateLifecycle()
})

async function submitCreate() {
  if (!createForm.value.property_id) {
    createError.value = 'Please select a property'
    return
  }
  creating.value    = true
  createError.value = ''

  const payload = {
    property_id:          createForm.value.property_id,
    inspection_type:      createForm.value.inspection_type,
    template_id:          createForm.value.template_id  || null,
    conduct_date:         createForm.value.conduct_date || null,
    inspector_id:         createForm.value.inspector_id || null,
    source_inspection_id: createForm.value.source_inspection_id || null,
    include_photos:       createForm.value.include_photos || false,
    tenant_email:         createForm.value.tenant_email  || null,
    key_location:         createForm.value.key_location  || null,
    internal_notes:       createForm.value.internal_notes || null,
  }

  try {
    const res    = await api.createInspection(payload)
    const detail = res.data

    // Normalise detail response → flat format expected by the home list
    const flat = {
      ...detail,
      property_address: detail.property?.address || null,
      client_name:      detail.client?.name      || null,
      inspector_name:   detail.inspector?.name   || null,
      typist_name:      detail.typist?.name      || null,
    }
    await saveInspection(flat)
    await loadLocal()
    showCreateSheet.value = false
    router.push(`/mobile/inspection/${detail.id}`)
  } catch (e) {
    createError.value = e.response?.data?.error || 'Failed to create inspection — check connection'
  } finally {
    creating.value = false
  }
}

const typeLabel = (t) => ({
  check_in:  'Check In',
  check_out: 'Check Out',
  interim:   'Interim',
  inventory: 'Inventory',
}[t] || t)

const statusColour = (s) => ({
  scheduled:  '#3b82f6',
  active:     '#8b5cf6',
  processing: '#f59e0b',
  review:     '#06b6d4',
  complete:   '#22c55e',
}[s] || '#94a3b8')

function fmtDate(d) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}
</script>

<template>
  <div class="mh-shell">

    <!-- Header -->
    <header class="mh-header">
      <div class="mh-header-top">
        <h1 class="mh-title">My Inspections</h1>
        <div class="mh-online-pill" :class="isOnline ? 'online' : 'offline'">
          <span class="mh-online-dot"></span>
          {{ isOnline ? 'Online' : 'Offline' }}
        </div>
      </div>

      <div class="mh-actions">
        <button
          class="mh-btn mh-btn-fetch"
          :disabled="fetching || !isOnline"
          @click="fetchInspections"
        >
          <svg v-if="!fetching" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <svg v-else class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          {{ fetching ? 'Fetching…' : 'Fetch Inspections' }}
        </button>

        <button
          v-if="dirtyCount > 0"
          class="mh-btn mh-btn-sync"
          :disabled="syncing || !isOnline"
          @click="syncAllInspections"
        >
          <svg v-if="!syncing" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          <svg v-else class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          Sync {{ dirtyCount }} unsaved
        </button>
      </div>

      <p v-if="fetchError" class="mh-error">{{ fetchError }}</p>
      <p v-if="syncMessage" class="mh-sync-msg">{{ syncMessage }}</p>
    </header>

    <!-- Speed-dial FAB (admin / manager) -->
    <div v-if="isAdminOrManager" class="mh-fab-wrap">

      <!-- Backdrop: tap outside to close -->
      <div v-if="fabExpanded" class="mh-fab-backdrop" @click="closeFab"></div>

      <!-- Expanded action items -->
      <transition name="fab-actions">
        <div v-if="fabExpanded" class="mh-fab-actions">

          <!-- Create Property (admin only) -->
          <div v-if="isAdmin" class="mh-fab-action-row">
            <span class="mh-fab-action-label">Create Property</span>
            <button class="mh-fab-action-btn mh-fab-btn-property" @click="openPropertySheet">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
            </button>
          </div>

          <!-- Create Inspection -->
          <div class="mh-fab-action-row">
            <span class="mh-fab-action-label">Create Inspection</span>
            <button class="mh-fab-action-btn mh-fab-btn-inspection" @click="openCreateSheet">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
            </button>
          </div>

        </div>
      </transition>

      <!-- Main FAB toggle -->
      <button class="mh-fab" :class="{ 'mh-fab--open': fabExpanded }" @click="fabExpanded = !fabExpanded">
        <svg class="mh-fab-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      </button>

    </div>

    <!-- List -->
    <div class="mh-list">
      <div v-if="localInspections.length === 0" class="mh-empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="1"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
        <p>No inspections on device</p>
        <p class="mh-empty-hint">Tap "Fetch Inspections" to download your assigned work</p>
      </div>

      <div
        v-for="insp in localInspections"
        :key="insp.id"
        class="mh-card"
        @click="router.push(`/mobile/inspection/${insp.id}`)"
      >
        <div class="mh-card-top">
          <div class="mh-card-type-wrap">
            <span class="mh-card-type" :style="{ background: statusColour(insp.status) }">
              {{ typeLabel(insp.inspection_type) }}
            </span>
            <span v-if="insp._is_dirty" class="mh-dirty-badge">● Unsynced</span>
          </div>
          <button class="mh-remove-btn" @click.stop="removeLocal(insp.id)" title="Remove from device">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
          </button>
        </div>
        <p class="mh-card-addr">{{ insp.property_address }}</p>
        <div class="mh-card-meta">
          <span>{{ fmtDate(insp.conduct_date) }}</span>
          <span v-if="insp.inspector_name">· {{ insp.inspector_name }}</span>
          <span class="mh-card-status" :style="{ color: statusColour(insp.status) }">
            · {{ insp.status }}
          </span>
        </div>
      </div>
    </div>

  </div>

  <!-- ══ CREATE PROPERTY SHEET ═════════════════════════════════════════ -->
  <div v-if="showPropertySheet" class="mh-overlay" @click.self="showPropertySheet = false">
    <div class="mh-sheet">

      <div class="mh-sheet-header">
        <h2 class="mh-sheet-title">New Property</h2>
        <button class="mh-sheet-close" @click="showPropertySheet = false">✕</button>
      </div>

      <div v-if="propSheetLoading" class="mh-sheet-loading">
        <svg class="spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
        Loading…
      </div>

      <div v-else class="mh-sheet-body">

        <!-- ── Client ────────────���────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Client *</label>
          <select class="mh-input" v-model="propForm.client_id">
            <option :value="null">— Select client —</option>
            <option v-for="c in propClients" :key="c.id" :value="c.id">{{ c.name }}{{ c.company ? ` · ${c.company}` : '' }}</option>
          </select>
        </div>

        <!-- ── Address ────────────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Address *</label>
          <textarea class="mh-input mh-textarea" rows="3" placeholder="Full address including postcode…" v-model="propForm.address"></textarea>
        </div>

        <!-- ── Property Type ──────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Property Type</label>
          <select class="mh-input" v-model="propForm.property_type">
            <option value="">— Select type —</option>
            <option v-for="t in PROPERTY_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>

        <!-- ── Bedrooms / Bathrooms ───────────────────── -->
        <div class="mh-field-row">
          <div class="mh-field-group mh-field-half">
            <label class="mh-field-label">Bedrooms</label>
            <input class="mh-input" type="number" min="0" max="20" placeholder="0" v-model="propForm.bedrooms" />
          </div>
          <div class="mh-field-group mh-field-half">
            <label class="mh-field-label">Bathrooms</label>
            <input class="mh-input" type="number" min="0" max="20" placeholder="0" v-model="propForm.bathrooms" />
          </div>
        </div>

        <!-- ── Furnished ──────────────���───────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Furnished</label>
          <select class="mh-input" v-model="propForm.furnished">
            <option value="">— Select —</option>
            <option v-for="f in FURNISHED_OPTS" :key="f" :value="f">{{ f }}</option>
          </select>
        </div>

        <!-- ── Detachment / Elevation ───────���─────────── -->
        <div class="mh-field-row">
          <div class="mh-field-group mh-field-half">
            <label class="mh-field-label">Detachment</label>
            <select class="mh-input" v-model="propForm.detachment_type">
              <option value="">— Select —</option>
              <option v-for="d in DETACHMENT_OPTS" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>
          <div class="mh-field-group mh-field-half">
            <label class="mh-field-label">Elevation</label>
            <select class="mh-input" v-model="propForm.elevation">
              <option value="">— Select —</option>
              <option v-for="e in ELEVATION_OPTS" :key="e" :value="e">{{ e }}</option>
            </select>
          </div>
        </div>

        <!-- ── Feature toggles ───────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Features</label>
          <div class="mh-toggles">
            <label class="mh-toggle-chip" :class="{ active: propForm.parking }">
              <input type="checkbox" v-model="propForm.parking" />
              🚗 Parking
            </label>
            <label class="mh-toggle-chip" :class="{ active: propForm.garden }">
              <input type="checkbox" v-model="propForm.garden" />
              🌿 Garden
            </label>
            <label class="mh-toggle-chip" :class="{ active: propForm.elevator }">
              <input type="checkbox" v-model="propForm.elevator" />
              🛗 Elevator
            </label>
          </div>
        </div>

        <!-- ── Meter Readings ──────────��──────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Meter Readings</label>
          <div class="mh-meter-grid">
            <div class="mh-meter-row">
              <span class="mh-meter-label">⚡ Electricity</span>
              <input class="mh-input mh-meter-input" type="text" placeholder="Location / Serial" v-model="propForm.meter_electricity" />
            </div>
            <div class="mh-meter-row">
              <span class="mh-meter-label">🔥 Gas</span>
              <input class="mh-input mh-meter-input" type="text" placeholder="Location / Serial" v-model="propForm.meter_gas" />
            </div>
            <div class="mh-meter-row">
              <span class="mh-meter-label">♨️ Heat</span>
              <input class="mh-input mh-meter-input" type="text" placeholder="Location / Serial" v-model="propForm.meter_heat" />
            </div>
            <div class="mh-meter-row">
              <span class="mh-meter-label">💧 Water</span>
              <input class="mh-input mh-meter-input" type="text" placeholder="Location / Serial" v-model="propForm.meter_water" />
            </div>
          </div>
        </div>

        <!-- ── Notes ──────────────��──────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Notes</label>
          <textarea class="mh-input mh-textarea" rows="3" placeholder="Any notes about this property…" v-model="propForm.notes"></textarea>
        </div>

        <!-- Error -->
        <p v-if="propError" class="mh-create-error">{{ propError }}</p>

        <!-- Submit -->
        <button
          class="mh-submit-btn mh-submit-btn--green"
          :disabled="creatingProp || !propForm.client_id || !propForm.address.trim()"
          @click="submitProperty"
        >
          <svg v-if="!creatingProp" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          <svg v-else class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          {{ creatingProp ? 'Creating…' : 'Create Property' }}
        </button>

      </div>
    </div>
  </div>

  <!-- ══ CREATE INSPECTION SHEET ════════════════════════════════��═══════ -->
  <div v-if="showCreateSheet" class="mh-overlay" @click.self="showCreateSheet = false">
    <div class="mh-sheet">

      <!-- Sheet header -->
      <div class="mh-sheet-header">
        <h2 class="mh-sheet-title">New Inspection</h2>
        <button class="mh-sheet-close" @click="showCreateSheet = false">✕</button>
      </div>

      <!-- Loading skeleton -->
      <div v-if="createLoading" class="mh-sheet-loading">
        <svg class="spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
        Loading…
      </div>

      <div v-else class="mh-sheet-body">

        <!-- ── Property ────────────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Property *</label>

          <!-- Selected property chip -->
          <div v-if="selectedPropertyLabel" class="mh-selected-prop">
            <span class="mh-selected-prop-text">{{ selectedPropertyLabel }}</span>
            <button class="mh-selected-prop-clear" @click="createForm.property_id = null; createLifecycle = null">✕</button>
          </div>

          <!-- Search when none selected -->
          <template v-else>
            <input
              v-model="createPropertySearch"
              class="mh-input"
              type="text"
              placeholder="Search by address or postcode…"
            />
            <div v-if="filteredCreateProperties.length" class="mh-prop-list">
              <button
                v-for="p in filteredCreateProperties.slice(0, 20)"
                :key="p.id"
                class="mh-prop-item"
                @click="selectCreateProperty(p.id)"
              >
                {{ p.address }}
              </button>
            </div>
            <p v-else-if="createPropertySearch" class="mh-hint">No properties match</p>
          </template>
        </div>

        <!-- ── Inspection Type ────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Inspection Type</label>
          <div class="mh-type-grid">
            <button
              v-for="t in INSPECTION_TYPES"
              :key="t.value"
              class="mh-type-btn"
              :class="{ active: createForm.inspection_type === t.value }"
              @click="createForm.inspection_type = t.value"
            >{{ t.label }}</button>
          </div>
        </div>

        <!-- ── Lifecycle suggestion ───────────────────── -->
        <div v-if="historyLoading" class="mh-lifecycle-loading">
          <svg class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          Checking property history…
        </div>
        <div v-else-if="createLifecycle" class="mh-lifecycle-banner">
          <div class="mh-lifecycle-icon">🔗</div>
          <div class="mh-lifecycle-body">
            <strong>{{ createLifecycle.label }} found — {{ createLifecycle.dateStr }}</strong>
            <p>Pre-fill this {{ INSPECTION_TYPES.find(t=>t.value===createForm.inspection_type)?.label }} with conditions from the previous report.</p>
            <label class="mh-check-row">
              <input
                type="checkbox"
                :checked="createForm.source_inspection_id === createLifecycle.sourceId"
                @change="createForm.source_inspection_id = $event.target.checked ? createLifecycle.sourceId : null"
              />
              <span>Work from {{ createLifecycle.label }} report</span>
            </label>
            <label v-if="createForm.source_inspection_id" class="mh-check-row">
              <input type="checkbox" v-model="createForm.include_photos" />
              <span>Include photos from {{ createLifecycle.label }}</span>
            </label>
          </div>
        </div>

        <!-- ── Template ───────────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Template</label>
          <select class="mh-input" v-model="createForm.template_id">
            <option :value="null">— No template —</option>
            <option v-for="t in filteredCreateTemplates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <p v-if="!filteredCreateTemplates.length" class="mh-hint">No templates for this type</p>
        </div>

        <!-- ── Conduct Date ────────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Conduct Date</label>
          <input class="mh-input" type="date" v-model="createForm.conduct_date" />
        </div>

        <!-- ── Assign Clerk ───────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Assign Clerk</label>
          <select class="mh-input" v-model="createForm.inspector_id">
            <option :value="null">— Not assigned —</option>
            <option v-for="c in createClerks" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <!-- ── Key Location ───────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Key Location</label>
          <select class="mh-input" v-model="createForm.key_location">
            <option value="">— Not specified —</option>
            <option v-for="opt in KEY_LOCATION_OPTS" :key="opt" :value="opt">{{ opt }}</option>
          </select>
        </div>

        <!-- ── Tenant Email ───────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Tenant Email</label>
          <input class="mh-input" type="email" placeholder="tenant@example.com" v-model="createForm.tenant_email" />
        </div>

        <!-- ── Internal Notes ─────────────────────────── -->
        <div class="mh-field-group">
          <label class="mh-field-label">Internal Notes</label>
          <textarea class="mh-input mh-textarea" rows="3" placeholder="Any notes for the clerk…" v-model="createForm.internal_notes"></textarea>
        </div>

        <!-- Error -->
        <p v-if="createError" class="mh-create-error">{{ createError }}</p>

        <!-- Submit -->
        <button
          class="mh-submit-btn"
          :disabled="creating || !createForm.property_id"
          @click="submitCreate"
        >
          <svg v-if="!creating" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          <svg v-else class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          {{ creating ? 'Creating…' : 'Create Inspection' }}
        </button>

      </div>
    </div>
  </div>

</template>

<style scoped>
.mh-shell {
  min-height: 100vh;
  background: #0f172a;
  color: #f1f5f9;
  display: flex;
  flex-direction: column;
}

/* Header */
.mh-header {
  padding: 56px 20px 20px;
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mh-header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mh-title {
  font-size: 22px;
  font-weight: 800;
  color: #f8fafc;
  margin: 0;
}
.mh-online-pill {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 20px;
  border: 1px solid;
}
.mh-online-pill.online  { color: #4ade80; border-color: #166534; background: #052e16; }
.mh-online-pill.offline { color: #f87171; border-color: #7f1d1d; background: #1c0a0a; }
.mh-online-dot {
  width: 6px; height: 6px; border-radius: 50%; background: currentColor;
}

.mh-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.mh-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 10px 18px;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s;
  font-family: inherit;
}
.mh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.mh-btn-fetch { background: #6366f1; color: white; }
.mh-btn-sync  { background: #0ea5e9; color: white; }

.mh-error    { font-size: 13px; color: #f87171; margin: 0; }
.mh-sync-msg { font-size: 13px; color: #4ade80; margin: 0; }

/* List */
.mh-list {
  flex: 1;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}
.mh-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  text-align: center;
  color: #64748b;
}
.mh-empty p { margin: 0; font-size: 14px; }
.mh-empty-hint { font-size: 12px; color: #475569; }

.mh-card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 14px 16px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.mh-card:active { background: #273549; border-color: #6366f1; }

.mh-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mh-card-type-wrap { display: flex; align-items: center; gap: 8px; }
.mh-card-type {
  font-size: 11px;
  font-weight: 700;
  color: white;
  padding: 2px 9px;
  border-radius: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.mh-dirty-badge {
  font-size: 11px;
  font-weight: 600;
  color: #f59e0b;
}

.mh-remove-btn {
  background: none;
  border: none;
  color: #475569;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
}
.mh-remove-btn:active { background: #334155; color: #f87171; }

.mh-card-addr {
  font-size: 15px;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0;
  line-height: 1.3;
}
.mh-card-meta {
  font-size: 12px;
  color: #64748b;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.mh-card-status { font-weight: 600; }

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }

/* ── Speed-dial FAB ── */
.mh-fab-wrap {
  position: fixed;
  bottom: 32px;
  right: 24px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 14px;
  z-index: 40;
}
.mh-fab-backdrop {
  position: fixed;
  inset: 0;
  z-index: 38;
}
.mh-fab-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
  z-index: 39;
}
.mh-fab-action-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.mh-fab-action-label {
  background: rgba(15,23,42,0.92);
  color: #f1f5f9;
  font-size: 13px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 20px;
  white-space: nowrap;
  backdrop-filter: blur(6px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
}
.mh-fab-action-btn {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 3px 14px rgba(0,0,0,0.35);
  transition: transform 0.12s;
  color: white;
}
.mh-fab-action-btn:active { transform: scale(0.9); }
.mh-fab-btn-property  { background: #10b981; }
.mh-fab-btn-inspection { background: #6366f1; }

/* Main FAB */
.mh-fab {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #6366f1;
  color: white;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(99,102,241,0.5);
  z-index: 40;
  transition: transform 0.2s, box-shadow 0.15s, background 0.2s;
}
.mh-fab:active { transform: scale(0.93); }
.mh-fab--open { background: #475569; }
.mh-fab-icon {
  transition: transform 0.25s cubic-bezier(0.34,1.56,0.64,1);
}
.mh-fab--open .mh-fab-icon { transform: rotate(45deg); }

/* Speed-dial transition */
.fab-actions-enter-active { transition: opacity 0.18s, transform 0.18s; }
.fab-actions-leave-active { transition: opacity 0.14s, transform 0.14s; }
.fab-actions-enter-from  { opacity: 0; transform: translateY(12px) scale(0.95); }
.fab-actions-leave-to    { opacity: 0; transform: translateY(8px)  scale(0.95); }

/* ── Sheet overlay ── */
.mh-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.7);
  display: flex;
  align-items: flex-end;
  z-index: 50;
}
.mh-sheet {
  width: 100%;
  max-height: 92vh;
  background: #1e293b;
  border-radius: 20px 20px 0 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.mh-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 20px 16px;
  border-bottom: 1px solid #334155;
  flex-shrink: 0;
}
.mh-sheet-title {
  font-size: 18px;
  font-weight: 800;
  color: #f1f5f9;
  margin: 0;
}
.mh-sheet-close {
  background: #334155;
  border: none;
  color: #94a3b8;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mh-sheet-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: #64748b;
  font-size: 14px;
}
.mh-sheet-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ── Form fields ── */
.mh-field-group { display: flex; flex-direction: column; gap: 6px; }
.mh-field-label {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
}
.mh-input {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 10px;
  color: #f1f5f9;
  font-size: 14px;
  padding: 11px 14px;
  font-family: inherit;
  width: 100%;
  box-sizing: border-box;
  outline: none;
  -webkit-appearance: none;
}
.mh-input:focus { border-color: #6366f1; }
.mh-textarea { resize: vertical; min-height: 70px; }
.mh-hint { font-size: 12px; color: #64748b; margin: 0; }

/* Property picker */
.mh-selected-prop {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #0f172a;
  border: 1px solid #6366f1;
  border-radius: 10px;
  padding: 10px 14px;
  gap: 10px;
}
.mh-selected-prop-text { font-size: 14px; color: #a5b4fc; flex: 1; line-height: 1.3; }
.mh-selected-prop-clear {
  background: none; border: none; color: #64748b; cursor: pointer;
  font-size: 16px; padding: 2px 4px; flex-shrink: 0;
}
.mh-prop-list {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 10px;
  max-height: 200px;
  overflow-y: auto;
}
.mh-prop-item {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  border-bottom: 1px solid #1e293b;
  padding: 12px 14px;
  font-size: 14px;
  color: #e2e8f0;
  cursor: pointer;
  font-family: inherit;
}
.mh-prop-item:last-child { border-bottom: none; }
.mh-prop-item:active { background: #1e293b; color: #a5b4fc; }

/* Inspection type grid */
.mh-type-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.mh-type-btn {
  padding: 10px 6px;
  border: 1.5px solid #334155;
  border-radius: 10px;
  background: #0f172a;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.12s, color 0.12s;
  text-align: center;
}
.mh-type-btn.active {
  border-color: #6366f1;
  color: #a5b4fc;
  background: rgba(99,102,241,0.08);
}

/* Lifecycle banner */
.mh-lifecycle-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
  padding: 4px 0;
}
.mh-lifecycle-banner {
  display: flex;
  gap: 12px;
  background: rgba(99,102,241,0.08);
  border: 1px solid rgba(99,102,241,0.3);
  border-radius: 12px;
  padding: 14px;
}
.mh-lifecycle-icon { font-size: 20px; flex-shrink: 0; margin-top: 1px; }
.mh-lifecycle-body { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.mh-lifecycle-body strong { font-size: 13px; color: #a5b4fc; }
.mh-lifecycle-body p { font-size: 12px; color: #94a3b8; margin: 0; line-height: 1.4; }
.mh-check-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: #e2e8f0;
  cursor: pointer;
}
.mh-check-row input[type="checkbox"] { margin-top: 2px; flex-shrink: 0; accent-color: #6366f1; }

/* Error + Submit */
.mh-create-error {
  font-size: 13px;
  color: #f87171;
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px;
  padding: 10px 14px;
  margin: 0;
}
.mh-submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 16px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 14px;
  font-size: 16px;
  font-weight: 800;
  cursor: pointer;
  font-family: inherit;
  transition: opacity 0.15s;
  margin-top: 4px;
}
.mh-submit-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.mh-submit-btn--green { background: #10b981; }

/* Side-by-side field pairs */
.mh-field-row {
  display: flex;
  gap: 10px;
}
.mh-field-half { flex: 1; min-width: 0; }

/* Feature toggle chips */
.mh-toggles {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.mh-toggle-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1.5px solid #334155;
  border-radius: 20px;
  background: #0f172a;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.12s, color 0.12s, background 0.12s;
  user-select: none;
}
.mh-toggle-chip input[type="checkbox"] { display: none; }
.mh-toggle-chip.active {
  border-color: #10b981;
  color: #34d399;
  background: rgba(16,185,129,0.08);
}

/* Meter readings */
.mh-meter-grid {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 10px;
  overflow: hidden;
}
.mh-meter-row {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #1e293b;
  padding: 0 14px;
  gap: 10px;
}
.mh-meter-row:last-child { border-bottom: none; }
.mh-meter-label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
  width: 96px;
  flex-shrink: 0;
}
.mh-meter-input {
  flex: 1;
  border: none !important;
  border-radius: 0 !important;
  padding: 11px 0 !important;
  background: transparent !important;
  font-size: 13px;
}
</style>
