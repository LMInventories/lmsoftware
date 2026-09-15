<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAuthStore } from '../stores/auth'
const toast = useToast()
const confirmDialog = useConfirm()
const router = useRouter()
const authStore = useAuthStore()

const properties = ref([])
const clients = ref([])
const loading = ref(false)
const showModal = ref(false)
const editingProperty = ref(null)
const activeTab = ref('grid')

// Grid density picker — a target column count at the current width, not a hard lock;
// the grid still reflows responsively via auto-fill as the window resizes (see
// .properties-grid.grid-cols-N rules). Persisted the same ad-hoc way as other UI
// choices in this app (e.g. inspections_view in InspectionsView.vue).
const gridCols = ref(Number(localStorage.getItem('properties_grid_cols')) || 5)
function setGridCols(n) {
  gridCols.value = n
  localStorage.setItem('properties_grid_cols', n)
}

// List density picker — same idea as gridCols, but a hard column count (no
// auto-fill reflow) since List cards are text-only and don't need it.
const listCols = ref(Number(localStorage.getItem('properties_list_cols')) || 2)
function setListCols(n) {
  listCols.value = n
  localStorage.setItem('properties_list_cols', n)
}

// ── Address Lookup ────────────────────────────────────────────────────────────
// Mode A — postcode entered  → fetch full address list, show picker
// Mode B — street/number     → autocomplete suggestions, select → fetch postcode list
const addressQuery        = ref('')
const addressResults      = ref([])   // [{line1,line2,line3,city,county}] for postcode mode
const autocompleteResults = ref([])   // [{address, url}] for text autocomplete mode
const addressSearching    = ref(false)
const showAddressDropdown = ref(false)
const lookupMode          = ref(null) // 'postcode' | 'autocomplete'
const lookupPostcode      = ref('')   // postcode resolved from autocomplete selection

const PC_RE = /^[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}$/i
let autocompleteTimer = null

const filters = ref({ client_id: null, postcode: '' })

const form = ref({
  address_line1: '', address_line2: '', city: '', postcode: '',
  bedrooms: '', bathrooms: '', furnished: '',
  detachment_type: '', elevation: '',
  parking: false, garden: false, elevator: false,
  meter_electricity: '', meter_gas: '', meter_heat: '', meter_water: '',
  client_id: null
})

// Build a single address string from structured fields
function buildAddress() {
  const parts = [form.value.address_line1, form.value.address_line2, form.value.city, form.value.postcode].filter(Boolean)
  return parts.join(', ')
}

// Debounced autocomplete as user types (text mode only)
function onAddressInput() {
  const q = addressQuery.value.trim()
  showAddressDropdown.value = false
  autocompleteResults.value = []
  addressResults.value = []
  if (!q || q.length < 3) return
  if (PC_RE.test(q)) return  // postcode — wait for explicit Search
  clearTimeout(autocompleteTimer)
  autocompleteTimer = setTimeout(() => runAutocomplete(q), 350)
}

async function runAutocomplete(q) {
  addressSearching.value = true
  try {
    const res = await api.addressAutocomplete(q)
    autocompleteResults.value = res.data.suggestions || []
    lookupMode.value = 'autocomplete'
    showAddressDropdown.value = true
  } catch (e) {
    toast.error('Address lookup failed')
  } finally {
    addressSearching.value = false
  }
}

// Search button — postcode → full list, text → autocomplete
async function searchAddress() {
  const q = addressQuery.value.trim()
  if (!q || q.length < 2) return
  addressSearching.value = true
  addressResults.value = []
  autocompleteResults.value = []
  showAddressDropdown.value = false

  if (PC_RE.test(q)) {
    try {
      const res = await api.addressFindByPostcode(q)
      addressResults.value = res.data.addresses || []
      lookupPostcode.value  = res.data.postcode  || q.toUpperCase()
      lookupMode.value = 'postcode'
      showAddressDropdown.value = true
      if (!addressResults.value.length) toast.warning('No addresses found for that postcode')
    } catch (e) {
      toast.error('Postcode lookup failed')
    } finally { addressSearching.value = false }
  } else {
    await runAutocomplete(q)
  }
}

// Autocomplete suggestion selected — resolve full address via /get/{id}
async function selectAutocomplete(suggestion) {
  if (!suggestion.url) {
    // No URL — fall back to best-effort string parse
    const parts = suggestion.address.split(',').map(s => s.trim())
    form.value.address_line1 = parts[0] || ''
    form.value.address_line2 = parts[1] || ''
    form.value.city          = parts[3] || parts[2] || ''
    form.value.postcode      = ''
    showAddressDropdown.value = false
    addressQuery.value = ''
    return
  }
  addressSearching.value = true
  showAddressDropdown.value = false
  try {
    const res = await api.addressGet(suggestion.url)
    const a = res.data
    form.value.address_line1 = a.line1  || ''
    form.value.address_line2 = [a.line2, a.line3].filter(Boolean).join(', ')
    form.value.city          = a.city   || ''
    form.value.postcode      = a.postcode || ''
    addressQuery.value = ''
    autocompleteResults.value = []
  } catch (e) {
    toast.error('Could not resolve address details')
  } finally {
    addressSearching.value = false
  }
}

// Full address selected from postcode list
function selectAddress(addr) {
  form.value.address_line1 = addr.line1
  form.value.address_line2 = [addr.line2, addr.line3].filter(Boolean).join(', ')
  form.value.city          = addr.city
  form.value.postcode      = addr.postcode || lookupPostcode.value
  addressQuery.value       = ''
  showAddressDropdown.value = false
  addressResults.value     = []
  autocompleteResults.value = []
}

function closeDropdown() { showAddressDropdown.value = false }

async function fetchProperties() {
  loading.value = true
  try {
    const response = await api.getProperties()
    properties.value = response.data
  } catch (error) {
    toast.error('Failed to load properties')
  } finally { loading.value = false }
}

async function fetchClients() {
  try { clients.value = (await api.getClients()).data }
  catch (e) { console.error(e) }
}

function blankForm() {
  return {
    address_line1: '', address_line2: '', city: '', postcode: '',
    bedrooms: '', bathrooms: '', furnished: '',
    detachment_type: '', elevation: '',
    parking: false, garden: false, elevator: false,
    meter_electricity: '', meter_gas: '', meter_heat: '', meter_water: '',
    client_id: authStore.isClient ? authStore.user.client_id : null
  }
}

function parseAddress(addressStr) {
  if (!addressStr) return { address_line1: '', address_line2: '', city: '', postcode: '' }
  // Try to extract postcode from end
  const pcMatch = addressStr.match(/([A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2})\s*$/i)
  const postcode = pcMatch ? pcMatch[1].toUpperCase() : ''
  const withoutPc = addressStr.replace(postcode, '').replace(/,\s*$/, '').trim()
  const parts = withoutPc.split(',').map(s => s.trim()).filter(Boolean)
  return {
    address_line1: parts[0] || '',
    address_line2: parts[1] || '',
    city: parts[2] || parts[1] || '',
    postcode
  }
}

function openCreateModal() {
  editingProperty.value = null
  form.value = blankForm()
  addressQuery.value = ''
  showModal.value = true
}

function openEditModal(property) {
  editingProperty.value = property
  const parsed = parseAddress(property.address)
  form.value = {
    ...parsed,
    bedrooms: property.bedrooms ?? '',
    bathrooms: property.bathrooms ?? '',
    furnished: property.furnished || '',
    detachment_type: property.detachment_type || '',
    elevation: property.elevation || '',
    parking: !!property.parking,
    garden: !!property.garden,
    elevator: !!property.elevator,
    meter_electricity: property.meter_electricity || '',
    meter_gas: property.meter_gas || '',
    meter_heat: property.meter_heat || '',
    meter_water: property.meter_water || '',
    client_id: property.client_id
  }
  addressQuery.value = ''
  showModal.value = true
}

async function saveProperty() {
  const address = buildAddress()
  if (!form.value.address_line1.trim()) { toast.warning('Address Line 1 is required'); return null }
  if (!form.value.postcode.trim()) { toast.warning('Postcode is required'); return null }
  if (!address) { toast.warning('Address is required'); return null }
  if (!form.value.client_id) { toast.warning('Client is required'); return null }
  const DETACHMENT_TYPE_MAP = {
    'Terraced':           'house',
    'Semi-Detached':      'house',
    'Detached':           'house',
    'Purpose Built Flat': 'flat',
    'Converted Flat':     'flat',
    'Bungalow':           'bungalow',
    'Penthouse':          'flat',
  }
  const payload = {
    address,
    property_type: DETACHMENT_TYPE_MAP[form.value.detachment_type] || 'residential',
    bedrooms: form.value.bedrooms === '' ? null : Number(form.value.bedrooms),
    bathrooms: form.value.bathrooms === '' ? null : Number(form.value.bathrooms),
    furnished: form.value.furnished,
    detachment_type: form.value.detachment_type,
    elevation: form.value.elevation,
    parking: form.value.parking,
    garden: form.value.garden,
    elevator: form.value.elevator,
    meter_electricity: form.value.meter_electricity,
    meter_gas: form.value.meter_gas,
    meter_heat: form.value.meter_heat,
    meter_water: form.value.meter_water,
    client_id: form.value.client_id
  }
  try {
    if (editingProperty.value) {
      await api.updateProperty(editingProperty.value.id, payload)
      toast.success('Property updated')
      return { id: editingProperty.value.id, client_id: form.value.client_id }
    } else {
      const res = await api.createProperty(payload)
      toast.success('Property created')
      return res.data
    }
  } catch (e) { console.error(e); toast.error('Failed to save property'); return null }
}

async function handleSubmit() {
  const saved = await saveProperty()
  if (!saved) return
  showModal.value = false
  fetchProperties()
}

async function handleSubmitAndAddInspection() {
  const saved = await saveProperty()
  if (!saved) return
  showModal.value = false
  router.push({
    path: '/inspections',
    query: {
      autoOpen: '1',
      clientId: String(form.value.client_id),
      ...(saved.id ? { propertyId: String(saved.id) } : {})
    }
  })
}

async function deleteProperty(id) {
  const ok = await confirmDialog.ask('Delete this property?', { title: 'Delete property', confirmText: 'Delete', danger: true })
  if (!ok) return
  try { await api.deleteProperty(id); toast.success('Property deleted'); fetchProperties() }
  catch (e) { toast.error('Failed to delete property') }
}

function clearFilters() { filters.value = { client_id: null, postcode: '' } }

function extractPostcode(address) {
  if (!address) return ''
  const m = address.match(/[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}/i)
  return m ? m[0].toUpperCase() : ''
}

const filteredProperties = computed(() => {
  let r = [...properties.value]
  if (filters.value.client_id) r = r.filter(p => p.client_id === filters.value.client_id)
  if (filters.value.postcode) {
    const s = filters.value.postcode.toLowerCase()
    r = r.filter(p => p.address && p.address.toLowerCase().includes(s))
  }
  return r
})

function openMapForProperty(property) {
  window.open('https://www.google.com/maps/search/' + encodeURIComponent(property.address), '_blank')
}

onMounted(() => { fetchProperties(); fetchClients() })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Properties</h1>
        <p class="subtitle">{{ filteredProperties.length }} of {{ properties.length }} shown</p>
      </div>
      <button v-if="authStore.isAdmin || authStore.isManager || authStore.isClient" @click="openCreateModal" class="btn-primary">+ Add Property</button>
    </div>

    <div class="filters-bar">
      <div v-if="!authStore.isClient" class="filter-group">
        <label>Client</label>
        <select v-model="filters.client_id" class="filter-select">
          <option :value="null">All Clients</option>
          <option v-for="c in clients" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Postcode / Address</label>
        <input v-model="filters.postcode" type="text" placeholder="Search..." class="filter-input" />
      </div>
      <button @click="clearFilters" class="btn-clear">Clear</button>
      <div class="tab-toggle">
        <button :class="['toggle-btn', { active: activeTab==='grid' }]" @click="activeTab='grid'">Grid</button>
        <button :class="['toggle-btn', { active: activeTab==='list' }]" @click="activeTab='list'">List</button>
      </div>
      <div v-if="activeTab === 'grid'" class="tab-toggle grid-cols-picker" title="Cards per row (target — still adapts to window width)">
        <button
          v-for="n in [4,5,6,7,8]" :key="n"
          :class="['toggle-btn', { active: gridCols === n }]"
          @click="setGridCols(n)"
        >{{ n }}</button>
      </div>
      <div v-if="activeTab === 'list'" class="tab-toggle grid-cols-picker" title="Cards per row">
        <button
          v-for="n in [2,3,4,5]" :key="n"
          :class="['toggle-btn', { active: listCols === n }]"
          @click="setListCols(n)"
        >{{ n }}</button>
      </div>
    </div>

    
    <button
      v-if="authStore.isAdmin || authStore.isManager || authStore.isClient"
      class="mobile-fab-add"
      @click="openCreateModal"
      title="Add Property"
    >+</button>
    <!-- Skeleton loader -->
    <div v-if="loading" :class="['properties-grid', 'grid-cols-' + gridCols]">
      <div v-for="n in 8" :key="n" class="skeleton-card">
        <div class="sk-photo"></div>
        <div class="sk-body">
          <div class="sk-line sk-line--short"></div>
          <div class="sk-line sk-line--full"></div>
          <div class="sk-line sk-line--med"></div>
        </div>
        <div class="sk-footer"></div>
      </div>
    </div>

    <!-- Grid view -->
    <div v-else-if="activeTab === 'grid'" :class="['properties-grid', 'grid-cols-' + gridCols]">
      <div v-for="property in filteredProperties" :key="property.id" class="property-card">
        <div class="card-photo">
          <img v-if="property.overview_photo" :src="property.overview_photo" alt="" class="prop-img" loading="lazy" />
          <div v-else class="photo-placeholder"><span class="photo-placeholder-txt">No Photo</span></div>
        </div>
        <div class="card-body">
          <div v-if="extractPostcode(property.address)" class="card-postcode">{{ extractPostcode(property.address) }}</div>
          <h3 class="card-address">{{ property.address }}</h3>
          <div v-if="property.client_name" class="card-client">{{ property.client_name }}</div>
          <div class="card-specs">
            <span v-if="property.bedrooms" class="spec-chip">{{ property.bedrooms }} bed</span>
            <span v-if="property.bathrooms" class="spec-chip">{{ property.bathrooms }} bath</span>
            <span v-if="property.furnished" class="spec-chip">{{ property.furnished }}</span>
            <span v-if="property.parking" class="spec-chip">Parking</span>
            <span v-if="property.garden" class="spec-chip">Garden</span>
            <span v-if="property.elevator" class="spec-chip">Lift</span>
          </div>
        </div>
        <div class="card-footer">
          <button @click="openMapForProperty(property)" class="btn-map" title="View on map">Map</button>
          <button @click="router.push(`/properties/${property.id}`)" class="btn-view">View</button>
          <button @click="openEditModal(property)" class="btn-edit">Edit</button>
          <button @click="deleteProperty(property.id)" class="btn-delete">Delete</button>
        </div>
      </div>
      <div v-if="filteredProperties.length === 0" class="empty-state">
        {{ filters.client_id || filters.postcode ? 'No properties match your filters.' : 'No properties yet. Add your first property!' }}
      </div>
    </div>

    <!-- List view -->
    <div v-else :class="['properties-list', 'list-cols-' + listCols]">
      <div v-for="property in filteredProperties" :key="property.id" class="property-card">
        <div class="card-body">
          <div v-if="extractPostcode(property.address)" class="card-postcode">{{ extractPostcode(property.address) }}</div>
          <h3 class="card-address">{{ property.address }}</h3>
          <div v-if="property.client_name" class="card-client">{{ property.client_name }}</div>
          <div class="card-specs">
            <span v-if="property.bedrooms" class="spec-chip">{{ property.bedrooms }} bed</span>
            <span v-if="property.bathrooms" class="spec-chip">{{ property.bathrooms }} bath</span>
            <span v-if="property.furnished" class="spec-chip">{{ property.furnished }}</span>
            <span v-if="property.parking" class="spec-chip">Parking</span>
            <span v-if="property.garden" class="spec-chip">Garden</span>
            <span v-if="property.elevator" class="spec-chip">Lift</span>
          </div>
        </div>
        <div class="card-footer">
          <button @click="openMapForProperty(property)" class="btn-map" title="View on map">Map</button>
          <button @click="router.push(`/properties/${property.id}`)" class="btn-view">View</button>
          <button @click="openEditModal(property)" class="btn-edit">Edit</button>
          <button @click="deleteProperty(property.id)" class="btn-delete">Delete</button>
        </div>
      </div>
      <div v-if="filteredProperties.length === 0" class="empty-state">
        {{ filters.client_id || filters.postcode ? 'No properties match your filters.' : 'No properties yet. Add your first property!' }}
      </div>
    </div>

    <!-- ═══ ADD / EDIT PROPERTY MODAL ═══ -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal modal-wide">
        <div class="modal-header">
          <h2>{{ editingProperty ? 'Edit Property' : 'Add Property' }}</h2>
          <button @click="showModal = false" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleSubmit">
          <div class="modal-cols">

            <!-- ── Column 1: Address + Basic Details ── -->
            <div class="modal-col">
              <div class="col-section-title">Property Details</div>

              <!-- Portfolio — hidden for client role (auto-filled) -->
              <div v-if="!authStore.isClient" class="form-group">
                <label>Client *</label>
                <select v-model="form.client_id" required>
                  <option :value="null" disabled>Select a client...</option>
                  <option v-for="c in clients" :key="c.id" :value="c.id">{{ c.name }}{{ c.company ? ' ('+c.company+')' : '' }}</option>
                </select>
              </div>

              <!-- Address lookup -->
              <div class="form-group" style="position:relative">
                <label>Address Lookup</label>
                <div class="addr-hint">Enter a postcode for a full address list, or start typing a street name.</div>
                <div class="addr-lookup-row">
                  <input
                    v-model="addressQuery"
                    type="text"
                    placeholder="e.g. SW1A 1AA  or  10 Downing Street"
                    class="addr-search-input"
                    @input="onAddressInput"
                    @keydown.enter.prevent="searchAddress"
                    autocomplete="off"
                  />
                  <button type="button" class="btn-lookup" @click="searchAddress" :disabled="addressSearching">
                    <span v-if="addressSearching">…</span>
                    <span v-else>Search</span>
                  </button>
                </div>

                <!-- Autocomplete suggestions (text mode) -->
                <div v-if="showAddressDropdown && lookupMode === 'autocomplete' && autocompleteResults.length" class="addr-dropdown">
                  <div class="addr-dropdown-header">Select an address to find its postcode</div>
                  <div
                    v-for="(s, i) in autocompleteResults"
                    :key="i"
                    class="addr-option"
                    @click="selectAutocomplete(s)"
                  >
                    {{ s.address }}
                  </div>
                </div>

                <!-- Full address list (postcode mode) -->
                <div v-if="showAddressDropdown && lookupMode === 'postcode' && addressResults.length" class="addr-dropdown">
                  <div class="addr-dropdown-header">{{ addressResults.length }} addresses found for {{ lookupPostcode }}</div>
                  <div
                    v-for="(a, i) in addressResults"
                    :key="i"
                    class="addr-option"
                    @click="selectAddress(a)"
                  >
                    <span class="addr-line1">{{ a.line1 }}</span>
                    <span v-if="a.line2" class="addr-line2">, {{ a.line2 }}</span>
                    <span v-if="a.line3" class="addr-line2">, {{ a.line3 }}</span>
                  </div>
                </div>

                <div v-if="showAddressDropdown && !addressSearching && !autocompleteResults.length && !addressResults.length" class="addr-no-results">No results found</div>

                <!-- Backdrop to close dropdown -->
                <div v-if="showAddressDropdown" class="addr-backdrop" @click="closeDropdown"></div>
              </div>

              <!-- Structured address -->
              <div class="form-group">
                <label>Address Line 1 *</label>
                <input v-model="form.address_line1" type="text" placeholder="123 High Street" required />
              </div>
              <div class="form-group">
                <label>Address Line 2</label>
                <input v-model="form.address_line2" type="text" />
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>City / Town *</label>
                  <input v-model="form.city" type="text" placeholder="London" />
                </div>
                <div class="form-group">
                  <label>Postcode *</label>
                  <input v-model="form.postcode" type="text" placeholder="SW1A 1AA" required />
                </div>
              </div>

              <!-- Bed / Bath -->
              <div class="form-row">
                <div class="form-group">
                  <label>Bedrooms</label>
                  <select v-model="form.bedrooms">
                    <option value="">—</option>
                    <option v-for="n in 10" :key="n" :value="n-1">{{ n-1 }}</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Bathrooms</label>
                  <select v-model="form.bathrooms">
                    <option value="">—</option>
                    <option v-for="n in 10" :key="n" :value="n-1">{{ n-1 }}</option>
                  </select>
                </div>
              </div>

              <!-- Furnishing -->
              <div class="form-group">
                <label>Furnishing</label>
                <select v-model="form.furnished">
                  <option value="">Not specified</option>
                  <option value="Furnished">Furnished</option>
                  <option value="Part Furnished">Part Furnished</option>
                  <option value="Unfurnished">Unfurnished</option>
                </select>
              </div>
            </div>

            <!-- ── Column 2: Property Characteristics ── -->
            <div class="modal-col modal-col-divider">
              <div class="col-section-title">Property Characteristics</div>

              <!-- Detachment type -->
              <div class="form-group">
                <label>Detachment Type</label>
                <select v-model="form.detachment_type">
                  <option value="">Not specified</option>
                  <option value="Terraced">Terraced</option>
                  <option value="Semi-Detached">Semi-Detached</option>
                  <option value="Detached">Detached</option>
                  <option value="Purpose Built Flat">Purpose Built Flat</option>
                  <option value="Converted Flat">Converted Flat</option>
                  <option value="Bungalow">Bungalow</option>
                  <option value="Penthouse">Penthouse</option>
                </select>
              </div>

              <!-- Elevation -->
              <div class="form-group">
                <label>Elevation / Floor</label>
                <select v-model="form.elevation">
                  <option value="">Not specified</option>
                  <option value="Ground Floor">Ground Floor</option>
                  <option value="1st Floor">1st Floor</option>
                  <option value="2nd Floor">2nd Floor</option>
                  <option value="3rd Floor">3rd Floor</option>
                  <option value="4th Floor or Above">4th Floor or Above</option>
                </select>
              </div>

              <!-- Toggles -->
              <div class="form-group">
                <label>Features</label>
                <div class="toggle-group">
                  <label class="toggle-row" :class="{ 'toggle-on': form.parking }">
                    <span class="toggle-label">Parking</span>
                    <div class="toggle-switch" @click="form.parking = !form.parking">
                      <div class="toggle-knob" :class="{ 'toggle-knob-on': form.parking }"></div>
                    </div>
                  </label>
                  <label class="toggle-row" :class="{ 'toggle-on': form.garden }">
                    <span class="toggle-label">Garden</span>
                    <div class="toggle-switch" @click="form.garden = !form.garden">
                      <div class="toggle-knob" :class="{ 'toggle-knob-on': form.garden }"></div>
                    </div>
                  </label>
                  <label class="toggle-row" :class="{ 'toggle-on': form.elevator }">
                    <span class="toggle-label">Elevator / Lift</span>
                    <div class="toggle-switch" @click="form.elevator = !form.elevator">
                      <div class="toggle-knob" :class="{ 'toggle-knob-on': form.elevator }"></div>
                    </div>
                  </label>
                </div>
              </div>

              <!-- Meter locations -->
              <div class="form-group">
                <label>Meter Locations</label>
                <div class="meter-grid">
                  <div class="meter-field">
                    <span class="meter-label-txt">Electricity</span>
                    <input v-model="form.meter_electricity" type="text" placeholder="Electricity meter location" />
                  </div>
                  <div class="meter-field">
                    <span class="meter-label-txt">Gas</span>
                    <input v-model="form.meter_gas" type="text" placeholder="Gas meter location" />
                  </div>
                  <div class="meter-field">
                    <span class="meter-label-txt">Heat</span>
                    <input v-model="form.meter_heat" type="text" placeholder="Heat meter location" />
                  </div>
                  <div class="meter-field">
                    <span class="meter-label-txt">Water</span>
                    <input v-model="form.meter_water" type="text" placeholder="Water meter location" />
                  </div>
                </div>
              </div>

            </div>
          </div>

          <div class="modal-footer">
            <button type="button" @click="showModal = false" class="btn-secondary">Cancel</button>
            <button v-if="!editingProperty" type="button" @click="handleSubmitAndAddInspection" class="btn-inspect">Create Property &amp; Add Inspection</button>
            <button type="submit" class="btn-primary">{{ editingProperty ? 'Update' : 'Create' }} Property</button>
          </div>
        </form>
      </div>
    </div>

  </div>
</template>


<style scoped>
.page { max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
h1 { font-size: 21px; font-weight: 700; color: #0f172a; margin: 0 0 2px; }
.subtitle { font-size: 12px; color: #94a3b8; margin: 0; }
.btn-primary { padding: 9px 18px; background: #6366f1; color: white; border: none; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn-primary:hover { background: #4f46e5; }

.filters-bar { display: flex; align-items: flex-end; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; background: white; border: 1px solid #e9ecef; border-radius: 9px; padding: 10px 14px; }
.filter-group { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.filter-group label { font-size: 10px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.4px; }
.filter-select, .filter-input { padding: 6px 9px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; background: white; color: #1e293b; font-family: inherit; }
.btn-clear { padding: 6px 12px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 11px; font-weight: 600; color: #64748b; cursor: pointer; align-self: flex-end; }
.btn-clear:hover { background: #e2e8f0; }
.tab-toggle { display: flex; border: 1px solid #e2e8f0; border-radius: 7px; overflow: hidden; margin-left: auto; align-self: flex-end; }
.toggle-btn { padding: 6px 12px; font-size: 11px; font-weight: 600; background: white; border: none; color: #64748b; cursor: pointer; }
.toggle-btn.active { background: #6366f1; color: white; }

.loading { text-align: center; padding: 60px; color: #94a3b8; }

/* ── Skeleton loader ─────────────────────────────────────────────────────── */
@keyframes shimmer {
  0%   { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}
.skeleton-card { background: white; border: 1px solid #e8ecf1; border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; }
.sk-photo { height: clamp(60px, 28cqw, 120px); background: linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%); background-size: 800px 100%; animation: shimmer 1.4s infinite linear; }
.sk-body { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
.sk-line { height: 12px; border-radius: 6px; background: linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%); background-size: 800px 100%; animation: shimmer 1.4s infinite linear; }
.sk-line--short { width: 40%; }
.sk-line--med   { width: 60%; }
.sk-line--full  { width: 90%; }
.sk-footer { height: 36px; border-top: 1px solid #f1f5f9; background: linear-gradient(90deg, #f8fafc 25%, #f1f5f9 50%, #f8fafc 75%); background-size: 800px 100%; animation: shimmer 1.4s infinite linear; }

.properties-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
/* Grid density picker — sets the auto-fill floor (a target at the current width, not a
   hard lock); the grid still reflows responsively as the window resizes. Floors tuned so
   N is the typical column count at the page's ~1360px usable grid width. */
.properties-grid.grid-cols-4 { grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.properties-grid.grid-cols-5 { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
.properties-grid.grid-cols-6 { grid-template-columns: repeat(auto-fill, minmax(195px, 1fr)); }
.properties-grid.grid-cols-7 { grid-template-columns: repeat(auto-fill, minmax(165px, 1fr)); }
.properties-grid.grid-cols-8 { grid-template-columns: repeat(auto-fill, minmax(145px, 1fr)); }

/* Card content scales continuously with the card's own rendered width (container query
   units), not in discrete size tiers — responds correctly whether the card got narrower
   from a denser picker choice or from the window itself narrowing. */
.property-card { background: white; border: 1px solid #e8ecf1; border-radius: 12px; overflow: hidden; transition: box-shadow 0.15s, transform 0.12s; display: flex; flex-direction: column; container-type: inline-size; }
.property-card:hover { box-shadow: 0 4px 14px rgba(0,0,0,0.08); transform: translateY(-1px); }
.card-photo { position: relative; height: clamp(60px, 28cqw, 120px); background: linear-gradient(135deg, #e0e7ff 0%, #ede9fe 100%); overflow: hidden; }
.prop-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.photo-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: clamp(20px, 10cqw, 36px); opacity: 0.4; }
.card-body { padding: clamp(6px, 3cqw, 11px) clamp(8px, 3.5cqw, 13px) clamp(4px, 2cqw, 7px); flex: 1; }
.card-postcode { font-size: clamp(8px, 3cqw, 10px); font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }
.card-address { font-size: clamp(10px, 4.5cqw, 13px); font-weight: 700; color: #1e293b; line-height: 1.3; margin-bottom: clamp(1px, 0.8cqw, 3px); }
.card-client { font-size: clamp(9px, 3.5cqw, 11px); color: #6366f1; font-weight: 600; margin-bottom: clamp(3px, 1.6cqw, 6px); }
.card-specs { display: flex; gap: clamp(3px, 1.3cqw, 5px); flex-wrap: wrap; }
.spec-chip { font-size: clamp(8px, 2.6cqw, 10px); font-weight: 600; padding: clamp(1px, 0.5cqw, 2px) clamp(3px, 1.5cqw, 6px); background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; color: #64748b; text-transform: capitalize; }
.spec-icon { padding: 2px 4px; }
.card-footer { display: flex; align-items: center; gap: clamp(3px, 1.3cqw, 5px); padding: clamp(4px, 1.8cqw, 7px) clamp(6px, 2.6cqw, 10px); border-top: 1px solid #f1f5f9; background: #fafbfc; }
.btn-map { padding: clamp(2px, 1cqw, 4px) clamp(4px, 2cqw, 8px); background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 5px; font-size: clamp(9px, 2.9cqw, 11px); cursor: pointer; }
.btn-map:hover { background: #dbeafe; }
.btn-view { flex: 1; padding: clamp(3px, 1.3cqw, 5px) clamp(4px, 2cqw, 8px); background: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; border-radius: 5px; font-size: clamp(9px, 2.9cqw, 11px); font-weight: 600; cursor: pointer; }
.btn-view:hover { background: #dcfce7; }
.btn-edit { flex: 1; padding: clamp(3px, 1.3cqw, 5px) clamp(4px, 2cqw, 8px); background: #eef2ff; color: #4338ca; border: none; border-radius: 5px; font-size: clamp(9px, 2.9cqw, 11px); font-weight: 600; cursor: pointer; }
.btn-edit:hover { background: #c7d2fe; }
.btn-delete { flex: 1; padding: clamp(3px, 1.3cqw, 5px) clamp(4px, 2cqw, 8px); background: #fee2e2; color: #991b1b; border: none; border-radius: 5px; font-size: clamp(9px, 2.9cqw, 11px); font-weight: 600; cursor: pointer; }
.btn-delete:hover { background: #fecaca; }
.empty-state { grid-column: 1/-1; text-align: center; padding: 60px 20px; color: #94a3b8; }

/* List view — same card content as Grid, minus the cover photo */
.properties-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.properties-list.list-cols-2 { grid-template-columns: repeat(2, 1fr); }
.properties-list.list-cols-3 { grid-template-columns: repeat(3, 1fr); }
.properties-list.list-cols-4 { grid-template-columns: repeat(4, 1fr); }
.properties-list.list-cols-5 { grid-template-columns: repeat(5, 1fr); }

/* ── Modal ── */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: white; border-radius: 12px; max-height: 92vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.2); }
.modal-wide { width: min(820px, 96vw); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 22px; border-bottom: 1px solid #e5e7eb; position: sticky; top: 0; background: white; z-index: 1; }
.modal-header h2 { font-size: 15px; font-weight: 700; color: #0f172a; }
.btn-close { background: none; border: none; font-size: 16px; color: #94a3b8; cursor: pointer; padding: 4px 7px; border-radius: 4px; }
.btn-close:hover { background: #f1f5f9; }

/* Two-column modal layout */
.modal-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.modal-col { padding: 20px 22px; display: flex; flex-direction: column; gap: 12px; }
.modal-col-divider { border-left: 1px solid #f1f5f9; }
.col-section-title { font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.8px; color: #94a3b8; padding-bottom: 4px; border-bottom: 1px solid #f1f5f9; margin-bottom: 2px; }

.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 11px; font-weight: 700; color: #374151; }
.form-group input, .form-group select, .form-group textarea { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; color: #1e293b; background: white; width: 100%; }
.form-group input:focus, .form-group select:focus { outline: none; border-color: #6366f1; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

/* Address lookup */
.addr-hint { font-size: 11px; color: #94a3b8; margin-bottom: 5px; }
.addr-lookup-row { display: flex; gap: 6px; }
.addr-search-input { flex: 1; padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; color: #1e293b; }
.addr-search-input:focus { outline: none; border-color: #6366f1; }
.btn-lookup { padding: 7px 14px; background: #6366f1; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.btn-lookup:hover:not(:disabled) { background: #4f46e5; }
.btn-lookup:disabled { background: #94a3b8; cursor: not-allowed; }
.addr-dropdown { position: absolute; left: 0; right: 0; top: calc(100% - 2px); z-index: 300; margin-top: 4px; background: white; border: 1px solid #c7d2fe; border-radius: 8px; box-shadow: 0 8px 24px rgba(99,102,241,0.12); overflow: hidden; max-height: 240px; overflow-y: auto; }
.addr-dropdown-header { padding: 7px 12px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #6366f1; background: #f5f3ff; border-bottom: 1px solid #e0e7ff; }
.addr-option { padding: 9px 12px; font-size: 12px; color: #1e293b; cursor: pointer; border-bottom: 1px solid #f8fafc; line-height: 1.4; }
.addr-option:hover { background: #f0f4ff; color: #4338ca; }
.addr-option:last-child { border-bottom: none; }
.addr-line1 { font-weight: 600; }
.addr-line2 { color: #64748b; }
.addr-no-results { padding: 10px 12px; font-size: 12px; color: #94a3b8; font-style: italic; }
.addr-backdrop { position: fixed; inset: 0; z-index: 299; }

/* Toggles */
.toggle-group { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; }
.toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; transition: all 0.15s; }
.toggle-row.toggle-on { background: #f0fdf4; border-color: #86efac; }
.toggle-label { font-size: 13px; color: #374151; font-weight: 500; }
.toggle-switch { width: 38px; height: 22px; background: #cbd5e1; border-radius: 11px; position: relative; transition: background 0.2s; flex-shrink: 0; }
.toggle-row.toggle-on .toggle-switch { background: #22c55e; }
.toggle-knob { width: 16px; height: 16px; background: white; border-radius: 50%; position: absolute; top: 3px; left: 3px; transition: transform 0.2s; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
.toggle-knob-on { transform: translateX(16px); }

/* Meters */
.meter-grid { display: flex; flex-direction: column; gap: 6px; }
.meter-field { display: flex; align-items: center; gap: 0; }
.meter-label-txt { font-size: 11px; font-weight: 600; color: #64748b; width: 72px; flex-shrink: 0; text-transform: uppercase; letter-spacing: 0.3px; }
.meter-field input { flex: 1; padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; font-family: inherit; color: #1e293b; }
.meter-field input:focus { outline: none; border-color: #6366f1; }

.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 22px; border-top: 1px solid #e5e7eb; background: #f8fafc; flex-wrap: wrap; }
.btn-secondary { padding: 7px 14px; background: white; color: #64748b; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-inspect { padding: 7px 14px; background: #ecfdf5; color: #047857; border: 1px solid #6ee7b7; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.btn-inspect:hover { background: #d1fae5; border-color: #34d399; }

@media (max-width: 640px) { .modal-cols { grid-template-columns: 1fr; } .modal-col-divider { border-left: none; border-top: 1px solid #f1f5f9; } }

/* ══════════════════════════════════════
   MOBILE  ≤ 768px
══════════════════════════════════════ */
@media (max-width: 768px) {

  .page-header .btn-primary { display: none; }
  .mobile-fab-add { display: flex !important; }

  .filters-bar {
    flex-direction: column;
    gap: 8px;
    padding: 10px 12px;
  }
  .filter-group { min-width: 100%; }

  .properties-grid { gap: 8px; }
  .grid-cols-picker { display: none; }
  .properties-list { grid-template-columns: 1fr !important; gap: 8px; }

  /* Property cards: overview photo full-width on mobile */
  .property-overview-photo {
    height: 140px;
  }

  /* Address lookup dropdown: full-screen width */
  .address-dropdown {
    position: fixed;
    left: 14px;
    right: 14px;
    top: auto;
    width: auto;
    max-height: 50vh;
    z-index: 500;
  }

  .modal-overlay {
    align-items: flex-end;
    padding: 0;
  }
  .modal {
    border-radius: 20px 20px 0 0;
    max-width: 100%;
    max-height: 94vh;
  }
  .modal-cols,
  .form-cols {
    grid-template-columns: 1fr !important;
  }

  /* Feature toggles: 2 per row */
  .feature-toggles {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* Mobile grid density is fixed, not picker-driven: 2 columns portrait, 4 landscape.
   Landscape uses a wider bound (900px) than portrait (768px) since a phone turned
   sideways is physically wider — this still excludes real tablets/small laptops from
   being force-locked to 4 columns. */
@media (max-width: 768px) and (orientation: portrait) {
  .properties-grid { grid-template-columns: repeat(2, 1fr) !important; }
}
@media (max-width: 900px) and (orientation: landscape) {
  .properties-grid { grid-template-columns: repeat(4, 1fr) !important; }
}


.mobile-fab-add {
  display: none;
  position: fixed;
  z-index: 100;
  bottom: 76px; right: 18px;
  width: 52px; height: 52px;
  background: #6366f1; color: white;
  border: none; border-radius: 50%;
  font-size: 26px; line-height: 1;
  box-shadow: 0 4px 14px rgba(99,102,241,0.4);
  cursor: pointer; z-index: 150;
  align-items: center; justify-content: center;
  transition: transform 0.15s;
}
.mobile-fab-add:hover { transform: scale(1.07); }

</style>