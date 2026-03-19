<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '../composables/useToast'
import api from '../services/api'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const property = ref(null)
const loading = ref(true)
const photoUploading = ref(false)
const localPhoto = ref(null)

// Edit modals
const showEditDetails = ref(false)
const showEditMeters = ref(false)
const showPhotoModal = ref(false)

const editForm = ref({
  address_line1: '', address_line2: '', city: '', postcode: '',
  bedrooms: '', bathrooms: '', furnished: '',
  detachment_type: '', elevation: '',
  parking: false, garden: false, elevator: false,
  client_id: null
})

const metersForm = ref({
  meter_electricity: '', meter_gas: '', meter_heat: '', meter_water: ''
})

// Address lookup (same as PropertiesView)
const addressQuery = ref('')
const addressResults = ref([])
const addressSearching = ref(false)
const showAddressDropdown = ref(false)

async function lookupAddress() {
  const q = addressQuery.value.trim()
  if (!q || q.length < 3) return
  addressSearching.value = true
  addressResults.value = []
  try {
    const isPostcode = /^[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}$/i.test(q)
    if (isPostcode) {
      const pc = q.replace(/\s/g, '').toUpperCase()
      const res = await fetch(`https://api.postcodes.io/postcodes/${pc}`)
      const data = await res.json()
      if (data.status === 200 && data.result) {
        const r = data.result
        addressResults.value = [{ line1: '', line2: '', city: r.admin_district || '', postcode: r.postcode, display: `${r.postcode} — ${r.admin_district || ''}` }]
      }
    } else {
      const res = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&countrycodes=gb&format=json&addressdetails=1&limit=6`, { headers: { 'Accept-Language': 'en' } })
      const data = await res.json()
      addressResults.value = data.map(item => {
        const a = item.address || {}
        return {
          line1: [a.house_number, a.road].filter(Boolean).join(' '),
          line2: a.suburb || '',
          city: a.city || a.town || a.village || '',
          postcode: a.postcode || '',
          display: item.display_name
        }
      }).slice(0, 6)
    }
    showAddressDropdown.value = true
  } catch (e) { toast.error('Address lookup failed') }
  finally { addressSearching.value = false }
}

function selectAddress(result) {
  editForm.value.address_line1 = result.line1
  editForm.value.address_line2 = result.line2
  editForm.value.city = result.city
  editForm.value.postcode = result.postcode
  addressQuery.value = ''
  showAddressDropdown.value = false
  addressResults.value = []
}

function parseAddress(addressStr) {
  if (!addressStr) return { address_line1: '', address_line2: '', city: '', postcode: '' }
  const pcMatch = addressStr.match(/([A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2})\s*$/i)
  const postcode = pcMatch ? pcMatch[1].toUpperCase() : ''
  const withoutPc = addressStr.replace(postcode, '').replace(/,\s*$/, '').trim()
  const parts = withoutPc.split(',').map(s => s.trim()).filter(Boolean)
  return { address_line1: parts[0] || '', address_line2: parts[1] || '', city: parts[2] || parts[1] || '', postcode }
}

function buildAddress() {
  const parts = [editForm.value.address_line1, editForm.value.address_line2, editForm.value.city, editForm.value.postcode].filter(Boolean)
  return parts.join(', ')
}

async function fetchProperty() {
  loading.value = true
  try {
    const res = await api.getProperty(route.params.id)
    property.value = res.data
    localPhoto.value = res.data.overview_photo || null
  } catch (e) {
    toast.error('Failed to load property')
    router.push('/properties')
  } finally { loading.value = false }
}

function openEditDetails() {
  const p = property.value
  const parsed = parseAddress(p.address)
  editForm.value = {
    ...parsed,
    bedrooms: p.bedrooms ?? '',
    bathrooms: p.bathrooms ?? '',
    furnished: p.furnished || '',
    detachment_type: p.detachment_type || '',
    elevation: p.elevation || '',
    parking: !!p.parking,
    garden: !!p.garden,
    elevator: !!p.elevator,
    client_id: p.client_id
  }
  addressQuery.value = ''
  showEditDetails.value = true
}

async function saveDetails() {
  const address = buildAddress()
  if (!address) { toast.warning('Address is required'); return }
  const payload = {
    address,
    property_type: 'residential',
    bedrooms: editForm.value.bedrooms === '' ? null : Number(editForm.value.bedrooms),
    bathrooms: editForm.value.bathrooms === '' ? null : Number(editForm.value.bathrooms),
    furnished: editForm.value.furnished,
    detachment_type: editForm.value.detachment_type,
    elevation: editForm.value.elevation,
    parking: editForm.value.parking,
    garden: editForm.value.garden,
    elevator: editForm.value.elevator,
    client_id: editForm.value.client_id
  }
  try {
    await api.updateProperty(property.value.id, payload)
    toast.success('Property updated')
    showEditDetails.value = false
    fetchProperty()
  } catch (e) { toast.error('Failed to update property') }
}

function openEditMeters() {
  const p = property.value
  metersForm.value = {
    meter_electricity: p.meter_electricity || '',
    meter_gas: p.meter_gas || '',
    meter_heat: p.meter_heat || '',
    meter_water: p.meter_water || ''
  }
  showEditMeters.value = true
}

async function saveMeters() {
  try {
    await api.updateProperty(property.value.id, metersForm.value)
    toast.success('Meter locations updated')
    showEditMeters.value = false
    fetchProperty()
  } catch (e) { toast.error('Failed to update meters') }
}

async function handlePhotoUpload(e) {
  const file = e.target.files[0]
  if (!file) return
  photoUploading.value = true
  try {
    const formData = new FormData()
    formData.append('photo', file)
    const res = await api.uploadPropertyPhoto(property.value.id, formData)
    localPhoto.value = res.data.overview_photo
    property.value.overview_photo = res.data.overview_photo
    toast.success('Photo uploaded')
  } catch (e) { toast.error('Failed to upload photo') }
  finally { photoUploading.value = false }
}

async function removePhoto() {
  try {
    await api.updateProperty(property.value.id, { overview_photo: null })
    localPhoto.value = null
    property.value.overview_photo = null
    showPhotoModal.value = false
    toast.success('Photo removed')
  } catch (e) { toast.error('Failed to remove photo') }
}

const inspectionCount = computed(() => property.value?.inspections?.length || 0)

const featureChips = computed(() => {
  if (!property.value) return []
  const chips = []
  if (property.value.parking) chips.push({ icon: '🚗', label: 'Parking' })
  if (property.value.garden) chips.push({ icon: '🌿', label: 'Garden' })
  if (property.value.elevator) chips.push({ icon: '🛗', label: 'Elevator' })
  return chips
})

const hasMeters = computed(() => {
  const p = property.value
  return p && (p.meter_electricity || p.meter_gas || p.meter_heat || p.meter_water)
})

onMounted(fetchProperty)
</script>

<template>
  <div v-if="loading" class="loading-screen">
    <div class="ring"></div>
    <p>Loading property…</p>
  </div>

  <div v-else-if="property" class="shell">

    <!-- Top bar -->
    <header class="topbar">
      <button class="back-btn" @click="router.push('/properties')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="15 18 9 12 15 6"/></svg>
        Properties
      </button>
      <div class="topbar-center">
        <div class="topbar-address">{{ property.address }}</div>
        <div v-if="property.client_name" class="topbar-client">{{ property.client_name }}</div>
      </div>
      <div class="topbar-actions">
        <a :href="`https://maps.google.com/?q=${encodeURIComponent(property.address)}`" target="_blank" class="btn-maps">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
          Maps
        </a>
      </div>
    </header>

    <!-- Main content -->
    <main class="main">
      <div class="content-grid">

        <!-- ── Left column ── -->
        <div class="left-col">

          <!-- Property photo -->
          <div class="info-card photo-card">
            <div class="card-header">
              <h3>🏠 Property Photo</h3>
              <button class="btn-edit" @click="showPhotoModal = true">{{ localPhoto ? 'Edit' : 'Add Photo' }}</button>
            </div>
            <div class="photo-card-body">
              <img v-if="localPhoto" :src="localPhoto" alt="Property photo" class="property-photo-img" />
              <div v-else class="photo-placeholder">
                <span class="photo-icon">🏠</span>
                <p>No photo yet</p>
              </div>
            </div>
          </div>

          <!-- Property details -->
          <div class="info-card">
            <div class="card-header">
              <h3>🏘 Property Details</h3>
              <button class="btn-edit" @click="openEditDetails">✏️ Edit</button>
            </div>
            <div class="card-content">
              <div class="detail-row">
                <strong>Address</strong>
                <span>{{ property.address }}</span>
              </div>
              <div v-if="property.detachment_type" class="detail-row">
                <strong>Type</strong>
                <span>{{ property.detachment_type }}</span>
              </div>
              <div v-if="property.elevation" class="detail-row">
                <strong>Floor</strong>
                <span>{{ property.elevation }}</span>
              </div>
              <div v-if="property.bedrooms != null" class="detail-row">
                <strong>Bedrooms</strong>
                <span>{{ property.bedrooms }}</span>
              </div>
              <div v-if="property.bathrooms != null" class="detail-row">
                <strong>Bathrooms</strong>
                <span>{{ property.bathrooms }}</span>
              </div>
              <div v-if="property.furnished" class="detail-row">
                <strong>Furnishing</strong>
                <span>{{ property.furnished }}</span>
              </div>
              <!-- Feature chips -->
              <div v-if="featureChips.length" class="feature-chips">
                <span v-for="chip in featureChips" :key="chip.label" class="feature-chip">
                  {{ chip.icon }} {{ chip.label }}
                </span>
              </div>
            </div>
          </div>

          <!-- Portfolio -->
          <div class="info-card" v-if="property.client_name">
            <div class="card-header">
              <h3>Client</h3>
            </div>
            <div class="card-content">
              <div class="detail-row">
                <strong>Client</strong>
                <span>{{ property.client_name }}</span>
              </div>
              <div v-if="property.client_company" class="detail-row">
                <strong>Company</strong>
                <span>{{ property.client_company }}</span>
              </div>
            </div>
          </div>

        </div>

        <!-- ── Right column ── -->
        <div class="right-col">

          <!-- Meter locations -->
          <div class="info-card">
            <div class="card-header">
              <h3>🔧 Meter Locations</h3>
              <button class="btn-edit" @click="openEditMeters">✏️ Edit</button>
            </div>
            <div class="card-content">
              <div v-if="hasMeters">
                <div v-if="property.meter_electricity" class="meter-row">
                  <span class="meter-lbl">Electricity</span>
                  <div>
                    <div class="meter-label">Electricity</div>
                    <div class="meter-value">{{ property.meter_electricity }}</div>
                  </div>
                </div>
                <div v-if="property.meter_gas" class="meter-row">
                  <span class="meter-lbl">Gas</span>
                  <div>
                    <div class="meter-label">Gas</div>
                    <div class="meter-value">{{ property.meter_gas }}</div>
                  </div>
                </div>
                <div v-if="property.meter_heat" class="meter-row">
                  <span class="meter-lbl">Heat</span>
                  <div>
                    <div class="meter-label">Heat</div>
                    <div class="meter-value">{{ property.meter_heat }}</div>
                  </div>
                </div>
                <div v-if="property.meter_water" class="meter-row">
                  <span class="meter-lbl">Water</span>
                  <div>
                    <div class="meter-label">Water</div>
                    <div class="meter-value">{{ property.meter_water }}</div>
                  </div>
                </div>
              </div>
              <p v-else class="empty-hint">No meter locations recorded yet.</p>
            </div>
          </div>

          <!-- Inspection history -->
          <div class="info-card">
            <div class="card-header">
              <h3>📋 Inspection History</h3>
              <span class="count-badge">{{ inspectionCount }}</span>
            </div>
            <div class="card-content card-content-flush">
              <div v-if="property.inspections && property.inspections.length">
                <div
                  v-for="insp in property.inspections"
                  :key="insp.id"
                  class="insp-row"
                  @click="router.push(`/inspections/${insp.id}`)"
                >
                  <div class="insp-row-left">
                    <div class="insp-type">{{ insp.inspection_type?.replace(/_/g, ' ').toUpperCase() }}</div>
                    <div class="insp-date">{{ insp.conduct_date ? new Date(insp.conduct_date).toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' }) : 'No date set' }}</div>
                  </div>
                  <div class="insp-status-chip" :class="`status-${insp.status}`">{{ insp.status }}</div>
                  <svg class="insp-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </div>
              <div v-else class="empty-hint" style="padding: 20px 24px;">No inspections recorded for this property.</div>
            </div>
          </div>

        </div>
      </div>
    </main>

    <!-- ═══ MODALS ═══ -->

    <!-- Photo modal -->
    <div v-if="showPhotoModal" class="modal-overlay" @click.self="showPhotoModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>Property Photo</h2>
          <button @click="showPhotoModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="localPhoto" class="photo-preview">
            <img :src="localPhoto" class="photo-preview-img" alt="Current photo" />
            <button class="photo-remove-btn" @click="removePhoto">Remove Photo</button>
          </div>
          <div v-if="photoUploading" class="upload-hint">Uploading…</div>
          <label class="photo-upload-label">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            {{ localPhoto ? 'Replace Photo' : 'Upload Photo' }}
            <input type="file" accept="image/*" style="display:none" @change="handlePhotoUpload" />
          </label>
        </div>
        <div class="modal-footer">
          <button @click="showPhotoModal = false" class="btn-secondary">Close</button>
        </div>
      </div>
    </div>

    <!-- Edit Details modal -->
    <div v-if="showEditDetails" class="modal-overlay" @click.self="showEditDetails = false">
      <div class="modal modal-wide">
        <div class="modal-header">
          <h2>Edit Property Details</h2>
          <button @click="showEditDetails = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="modal-cols">
            <!-- Col 1 -->
            <div class="modal-col">
              <div class="col-section-title">Address</div>
              <div class="form-group">
                <label>Address Lookup</label>
                <div class="addr-lookup-row">
                  <input v-model="addressQuery" type="text" placeholder="Search by address or postcode…" class="addr-search-input" @keydown.enter.prevent="lookupAddress" />
                  <button type="button" class="btn-lookup" @click="lookupAddress" :disabled="addressSearching">{{ addressSearching ? '…' : 'Search' }}</button>
                </div>
                <div v-if="showAddressDropdown && addressResults.length" class="addr-dropdown">
                  <div v-for="(r, i) in addressResults" :key="i" class="addr-option" @click="selectAddress(r)">{{ r.display }}</div>
                </div>
              </div>
              <div class="form-group"><label>Address Line 1</label><input v-model="editForm.address_line1" type="text" /></div>
              <div class="form-group"><label>Address Line 2</label><input v-model="editForm.address_line2" type="text" /></div>
              <div class="form-row">
                <div class="form-group"><label>City</label><input v-model="editForm.city" type="text" /></div>
                <div class="form-group"><label>Postcode</label><input v-model="editForm.postcode" type="text" /></div>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Bedrooms</label>
                  <select v-model="editForm.bedrooms">
                    <option value="">—</option>
                    <option v-for="n in 10" :key="n" :value="n-1">{{ n-1 }}</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Bathrooms</label>
                  <select v-model="editForm.bathrooms">
                    <option value="">—</option>
                    <option v-for="n in 10" :key="n" :value="n-1">{{ n-1 }}</option>
                  </select>
                </div>
              </div>
              <div class="form-group">
                <label>Furnishing</label>
                <select v-model="editForm.furnished">
                  <option value="">Not specified</option>
                  <option value="Furnished">Furnished</option>
                  <option value="Part Furnished">Part Furnished</option>
                  <option value="Unfurnished">Unfurnished</option>
                </select>
              </div>
            </div>
            <!-- Col 2 -->
            <div class="modal-col modal-col-divider">
              <div class="col-section-title">Characteristics</div>
              <div class="form-group">
                <label>Detachment Type</label>
                <select v-model="editForm.detachment_type">
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
              <div class="form-group">
                <label>Floor / Elevation</label>
                <select v-model="editForm.elevation">
                  <option value="">Not specified</option>
                  <option value="Ground Floor">Ground Floor</option>
                  <option value="1st Floor">1st Floor</option>
                  <option value="2nd Floor">2nd Floor</option>
                  <option value="3rd Floor">3rd Floor</option>
                  <option value="4th Floor or Above">4th Floor or Above</option>
                </select>
              </div>
              <div class="form-group">
                <label>Features</label>
                <div class="toggle-group">
                  <label class="toggle-row" :class="{ 'toggle-on': editForm.parking }">
                    <span class="toggle-label">🚗 Parking</span>
                    <div class="toggle-switch" @click="editForm.parking = !editForm.parking"><div class="toggle-knob" :class="{ 'toggle-knob-on': editForm.parking }"></div></div>
                  </label>
                  <label class="toggle-row" :class="{ 'toggle-on': editForm.garden }">
                    <span class="toggle-label">🌿 Garden</span>
                    <div class="toggle-switch" @click="editForm.garden = !editForm.garden"><div class="toggle-knob" :class="{ 'toggle-knob-on': editForm.garden }"></div></div>
                  </label>
                  <label class="toggle-row" :class="{ 'toggle-on': editForm.elevator }">
                    <span class="toggle-label">🛗 Elevator / Lift</span>
                    <div class="toggle-switch" @click="editForm.elevator = !editForm.elevator"><div class="toggle-knob" :class="{ 'toggle-knob-on': editForm.elevator }"></div></div>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showEditDetails = false" class="btn-secondary">Cancel</button>
          <button @click="saveDetails" class="btn-primary">Save Changes</button>
        </div>
      </div>
    </div>

    <!-- Edit Meters modal -->
    <div v-if="showEditMeters" class="modal-overlay" @click.self="showEditMeters = false">
      <div class="modal">
        <div class="modal-header">
          <h2>Meter Locations</h2>
          <button @click="showEditMeters = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="meter-edit-grid">
            <div class="meter-edit-row">
              <span class="meter-lbl-lg">Electricity</span>
              <div class="form-group" style="flex:1">
                <label>Electricity Meter</label>
                <input v-model="metersForm.meter_electricity" type="text" placeholder="e.g. Under stairs cupboard" />
              </div>
            </div>
            <div class="meter-edit-row">
              <span class="meter-lbl-lg">Gas</span>
              <div class="form-group" style="flex:1">
                <label>Gas Meter</label>
                <input v-model="metersForm.meter_gas" type="text" placeholder="e.g. External box on front wall" />
              </div>
            </div>
            <div class="meter-edit-row">
              <span class="meter-lbl-lg">Heat</span>
              <div class="form-group" style="flex:1">
                <label>Heat Meter</label>
                <input v-model="metersForm.meter_heat" type="text" placeholder="e.g. Boiler cupboard" />
              </div>
            </div>
            <div class="meter-edit-row">
              <span class="meter-lbl-lg">Water</span>
              <div class="form-group" style="flex:1">
                <label>Water Meter</label>
                <input v-model="metersForm.meter_water" type="text" placeholder="e.g. Under kitchen sink" />
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showEditMeters = false" class="btn-secondary">Cancel</button>
          <button @click="saveMeters" class="btn-primary">Save</button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
* { box-sizing: border-box; }

/* Layout */
.loading-screen { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; gap: 14px; }
.ring { width: 36px; height: 36px; border: 3px solid #e2e8f0; border-top-color: #6366f1; border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-screen p { font-size: 14px; color: #64748b; }

.shell { display: flex; flex-direction: column; min-height: 100vh; background: #f1f5f9; }

/* Topbar */
.topbar { display: flex; align-items: center; gap: 14px; padding: 0 24px; height: 52px; background: #0f172a; border-bottom: 1px solid #1e293b; flex-shrink: 0; }
.back-btn { display: flex; align-items: center; gap: 5px; padding: 5px 10px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 5px; font-size: 12px; color: #94a3b8; cursor: pointer; transition: all 0.15s; flex-shrink: 0; }
.back-btn:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }
.topbar-center { flex: 1; min-width: 0; }
.topbar-address { font-size: 13px; font-weight: 700; color: #e2e8f0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.topbar-client { font-size: 11px; color: #6366f1; font-weight: 600; }
.topbar-actions { display: flex; gap: 8px; flex-shrink: 0; }
.btn-maps { display: flex; align-items: center; gap: 5px; padding: 5px 12px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 5px; font-size: 12px; color: #94a3b8; text-decoration: none; cursor: pointer; transition: all 0.15s; }
.btn-maps:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }

/* Main */
.main { padding: 28px 32px 60px; }
.content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; max-width: 1100px; }
.left-col, .right-col { display: flex; flex-direction: column; gap: 20px; }

/* Info cards */
.info-card { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }
.card-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #e5e7eb; background: #f8fafc; }
.card-header h3 { font-size: 14px; font-weight: 600; color: #1e293b; margin: 0; }
.btn-edit { padding: 5px 11px; background: #6366f1; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-edit:hover { background: #4f46e5; }
.card-content { padding: 20px; }
.card-content-flush { padding: 0; }
.count-badge { background: #e0e7ff; color: #4338ca; border-radius: 12px; padding: 2px 9px; font-size: 11px; font-weight: 700; }

/* Detail rows */
.detail-row { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid #f8fafc; font-size: 13px; align-items: flex-start; }
.detail-row:last-child { border-bottom: none; }
.detail-row strong { color: #64748b; min-width: 90px; font-size: 12px; flex-shrink: 0; }
.detail-row span { color: #1e293b; }

/* Feature chips */
.feature-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.feature-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 20px; font-size: 12px; color: #16a34a; font-weight: 600; }

/* Photo card */
.photo-card .card-content { padding: 0; }
.photo-card-body { position: relative; }
.property-photo-img { width: 100%; height: auto; max-height: 260px; object-fit: cover; display: block; }
.photo-placeholder { height: 180px; background: linear-gradient(135deg, #1e3a5f 0%, #1e293b 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; color: white; gap: 8px; }
.photo-icon { font-size: 40px; }
.photo-placeholder p { font-size: 13px; font-weight: 500; opacity: 0.7; }

/* Meters */
.meter-row { display: flex; align-items: center; gap: 0; padding: 8px 0; border-bottom: 1px solid #f8fafc; }
.meter-lbl { font-size: 11px; font-weight: 600; color: #64748b; width: 80px; flex-shrink: 0; text-transform: uppercase; letter-spacing: 0.3px; }
.meter-row:last-child { border-bottom: none; }
.meter-icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
.meter-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; color: #94a3b8; margin-bottom: 2px; }
.meter-value { font-size: 13px; color: #1e293b; }
.empty-hint { font-size: 13px; color: #94a3b8; font-style: italic; }

/* Inspection history */
.insp-row { display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid #f8fafc; cursor: pointer; transition: background 0.1s; }
.insp-row:hover { background: #fafbff; }
.insp-row:last-child { border-bottom: none; }
.insp-row-left { flex: 1; }
.insp-type { font-size: 12px; font-weight: 700; color: #1e293b; }
.insp-date { font-size: 11px; color: #64748b; margin-top: 1px; }
.insp-arrow { color: #cbd5e1; flex-shrink: 0; }
.insp-status-chip { padding: 3px 8px; border-radius: 10px; font-size: 10px; font-weight: 700; text-transform: capitalize; flex-shrink: 0; }
.status-created   { background: #f1f5f9; color: #64748b; }
.status-scheduled { background: #eff6ff; color: #1d4ed8; }
.status-active    { background: #fef9c3; color: #a16207; }
.status-processing{ background: #fdf4ff; color: #9333ea; }
.status-review    { background: #fff7ed; color: #c2410c; }
.status-complete  { background: #f0fdf4; color: #16a34a; }

/* ── Modal ── */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: white; border-radius: 12px; max-height: 92vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.2); width: min(500px, 95vw); }
.modal-wide { width: min(780px, 96vw); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 22px; border-bottom: 1px solid #e5e7eb; position: sticky; top: 0; background: white; z-index: 1; }
.modal-header h2 { font-size: 15px; font-weight: 700; color: #0f172a; }
.btn-close { background: none; border: none; font-size: 16px; color: #94a3b8; cursor: pointer; padding: 4px 7px; border-radius: 4px; }
.btn-close:hover { background: #f1f5f9; }
.modal-body { padding: 20px 22px; display: flex; flex-direction: column; gap: 14px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 22px; border-top: 1px solid #e5e7eb; background: #f8fafc; }

/* Two-col modal */
.modal-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.modal-col { padding: 20px 22px; display: flex; flex-direction: column; gap: 12px; }
.modal-col-divider { border-left: 1px solid #f1f5f9; }
.col-section-title { font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.8px; color: #94a3b8; padding-bottom: 4px; border-bottom: 1px solid #f1f5f9; margin-bottom: 2px; }

/* Form */
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 11px; font-weight: 700; color: #374151; }
.form-group input, .form-group select { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; color: #1e293b; background: white; width: 100%; }
.form-group input:focus, .form-group select:focus { outline: none; border-color: #6366f1; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.btn-primary { padding: 7px 16px; background: #6366f1; color: white; border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn-primary:hover { background: #4f46e5; }
.btn-secondary { padding: 7px 14px; background: white; color: #64748b; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }

/* Address lookup */
.addr-lookup-row { display: flex; gap: 6px; }
.addr-search-input { flex: 1; padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; color: #1e293b; }
.addr-search-input:focus { outline: none; border-color: #6366f1; }
.btn-lookup { padding: 7px 14px; background: #6366f1; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-lookup:hover:not(:disabled) { background: #4f46e5; }
.btn-lookup:disabled { background: #94a3b8; cursor: not-allowed; }
.addr-dropdown { margin-top: 4px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); overflow: hidden; max-height: 200px; overflow-y: auto; }
.addr-option { padding: 9px 12px; font-size: 12px; color: #1e293b; cursor: pointer; border-bottom: 1px solid #f8fafc; line-height: 1.4; }
.addr-option:hover { background: #f0f4ff; color: #4338ca; }
.addr-option:last-child { border-bottom: none; }

/* Toggles */
.toggle-group { display: flex; flex-direction: column; gap: 8px; }
.toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; transition: all 0.15s; }
.toggle-row.toggle-on { background: #f0fdf4; border-color: #86efac; }
.toggle-label { font-size: 13px; color: #374151; font-weight: 500; }
.toggle-switch { width: 38px; height: 22px; background: #cbd5e1; border-radius: 11px; position: relative; transition: background 0.2s; flex-shrink: 0; }
.toggle-row.toggle-on .toggle-switch { background: #22c55e; }
.toggle-knob { width: 16px; height: 16px; background: white; border-radius: 50%; position: absolute; top: 3px; left: 3px; transition: transform 0.2s; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
.toggle-knob-on { transform: translateX(16px); }

/* Meter edit */
.meter-edit-grid { display: flex; flex-direction: column; gap: 14px; }
.meter-edit-row { display: flex; align-items: center; gap: 12px; }
.meter-lbl-lg { font-size: 12px; font-weight: 600; color: #64748b; width: 90px; flex-shrink: 0; text-transform: uppercase; }

/* Photo modal */
.photo-preview { display: flex; flex-direction: column; gap: 10px; margin-bottom: 6px; }
.photo-preview-img { width: 100%; max-height: 240px; object-fit: cover; border-radius: 8px; border: 1px solid #e2e8f0; }
.photo-remove-btn { background: #fee2e2; color: #dc2626; border: none; border-radius: 6px; padding: 6px 12px; font-size: 13px; font-weight: 600; cursor: pointer; align-self: flex-start; }
.photo-remove-btn:hover { background: #fecaca; }
.upload-hint { font-size: 13px; color: #94a3b8; }
.photo-upload-label { display: inline-flex; align-items: center; gap: 7px; padding: 8px 16px; background: #6366f1; color: white; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; }
.photo-upload-label:hover { background: #4f46e5; }

@media (max-width: 768px) {
  .content-grid { grid-template-columns: 1fr; }
  .main { padding: 16px 14px 40px; }
  .modal-cols { grid-template-columns: 1fr; }
  .modal-col-divider { border-left: none; border-top: 1px solid #f1f5f9; }
}

/* ══════════════════════════════════════
   MOBILE  ≤ 768px
══════════════════════════════════════ */
@media (max-width: 768px) {

  /* Header */
  .detail-header,
  .property-header {
    flex-direction: column;
    gap: 10px;
    margin-bottom: 12px;
  }

  /* 2-col content → single col */
  .content-grid,
  .property-grid {
    grid-template-columns: 1fr !important;
    gap: 10px;
  }

  /* Overview photo: taller on mobile for visual impact */
  .overview-photo-area,
  .property-overview {
    height: 200px !important;
    border-radius: 10px;
  }

  /* Panels: compact */
  .info-panel,
  .detail-panel {
    border-radius: 10px;
  }

  /* Address lookup */
  .address-dropdown {
    position: fixed;
    left: 14px;
    right: 14px;
    top: auto;
    width: auto;
    max-height: 50vh;
    z-index: 500;
  }

  /* Modals → bottom sheets */
  .modal-overlay {
    align-items: flex-end;
    padding: 0;
  }
  .modal,
  .edit-modal {
    border-radius: 20px 20px 0 0;
    max-width: 100%;
    max-height: 94vh;
  }

  .form-cols {
    grid-template-columns: 1fr !important;
  }

  /* Feature toggles */
  .feature-toggles {
    grid-template-columns: repeat(2, 1fr);
  }

  /* Action buttons */
  .property-actions {
    flex-wrap: wrap;
  }
  .property-actions .btn-primary,
  .property-actions .btn-secondary {
    flex: 1;
    text-align: center;
    justify-content: center;
  }
}

</style>
