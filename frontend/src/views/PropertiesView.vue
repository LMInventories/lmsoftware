<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../services/api'
import { useToast } from '../composables/useToast'
const toast = useToast()

const properties = ref([])
const clients = ref([])
const loading = ref(true)
const showModal = ref(false)
const editingProperty = ref(null)
const activeTab = ref('grid')

const filters = ref({ client_id: null, postcode: '', property_type: '' })

const form = ref({
  address: '', property_type: 'residential', bedrooms: null, bathrooms: null,
  furnished: '', parking: '', garden: '', client_id: null
})

async function fetchProperties() {
  loading.value = true
  try {
    const response = await api.getProperties()
    properties.value = response.data
  } catch (error) {
    console.error('Failed to fetch properties:', error)
    toast.error('Failed to load properties')
  } finally { loading.value = false }
}

async function fetchClients() {
  try { clients.value = (await api.getClients()).data }
  catch (e) { console.error(e) }
}

function openCreateModal() {
  editingProperty.value = null
  form.value = { address: '', property_type: 'residential', bedrooms: null, bathrooms: null, furnished: '', parking: '', garden: '', client_id: null }
  showModal.value = true
}

function openEditModal(property) {
  editingProperty.value = property
  form.value = {
    address: property.address, property_type: property.property_type || 'residential',
    bedrooms: property.bedrooms, bathrooms: property.bathrooms,
    furnished: property.furnished || '', parking: property.parking || '',
    garden: property.garden || '', client_id: property.client_id
  }
  showModal.value = true
}

async function handleSubmit() {
  if (!form.value.address || !form.value.client_id) { toast.warning('Address and portfolio are required'); return }
  try {
    if (editingProperty.value) { await api.updateProperty(editingProperty.value.id, form.value); toast.success('Property updated') }
    else { await api.createProperty(form.value); toast.success('Property created') }
    showModal.value = false; fetchProperties()
  } catch (e) { console.error(e); toast.error('Failed to save property') }
}

async function deleteProperty(id) {
  if (!confirm('Delete this property?')) return
  try { await api.deleteProperty(id); toast.success('Property deleted'); fetchProperties() }
  catch (e) { console.error(e); toast.error('Failed to delete property') }
}

function clearFilters() { filters.value = { client_id: null, postcode: '', property_type: '' } }

function extractPostcode(address) {
  if (!address) return ''
  const m = address.match(/[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}/i)
  return m ? m[0].toUpperCase() : ''
}

const filteredProperties = computed(() => {
  let r = [...properties.value]
  if (filters.value.client_id) r = r.filter(p => p.client_id === filters.value.client_id)
  if (filters.value.property_type) r = r.filter(p => p.property_type === filters.value.property_type)
  if (filters.value.postcode) {
    const s = filters.value.postcode.toLowerCase()
    r = r.filter(p => p.address && p.address.toLowerCase().includes(s))
  }
  return r
})

const typeColors = {
  residential: { bg: '#eff6ff', color: '#1d4ed8' },
  commercial:  { bg: '#fdf4ff', color: '#9333ea' },
  student:     { bg: '#f0fdf4', color: '#16a34a' },
}
function typeStyle(type) { return typeColors[type] || { bg: '#f1f5f9', color: '#64748b' } }

function openMapForProperty(property) {
  window.open('https://www.google.com/maps/search/' + encodeURIComponent(property.address), '_blank')
}

function openAllInMaps() {
  if (filteredProperties.value.length === 0) return
  window.open('https://www.google.com/maps/search/' + encodeURIComponent(filteredProperties.value[0].address), '_blank')
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
      <button @click="openCreateModal" class="btn-primary">+ Add Property</button>
    </div>

    <div class="filters-bar">
      <div class="filter-group">
        <label>Portfolio</label>
        <select v-model="filters.client_id" class="filter-select">
          <option :value="null">All Portfolios</option>
          <option v-for="c in clients" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Postcode</label>
        <input v-model="filters.postcode" type="text" placeholder="Search postcode..." class="filter-input" />
      </div>
      <div class="filter-group">
        <label>Type</label>
        <select v-model="filters.property_type" class="filter-select">
          <option value="">All Types</option>
          <option value="residential">Residential</option>
          <option value="commercial">Commercial</option>
          <option value="student">Student</option>
        </select>
      </div>
      <button @click="clearFilters" class="btn-clear">Clear</button>
      <div class="tab-toggle">
        <button :class="['toggle-btn', { active: activeTab==='grid' }]" @click="activeTab='grid'">Grid</button>
        <button :class="['toggle-btn', { active: activeTab==='map' }]" @click="activeTab='map'">Map</button>
      </div>
    </div>

    <div v-if="loading" class="loading">Loading properties...</div>

    <!-- Grid view -->
    <div v-else-if="activeTab === 'grid'" class="properties-grid">
      <div v-for="property in filteredProperties" :key="property.id" class="property-card">
        <div class="card-photo">
          <img v-if="property.overview_photo" :src="property.overview_photo" alt="" class="prop-img" />
          <div v-else class="photo-placeholder">
            <span>🏠</span>
          </div>
          <div class="card-type-badge" :style="typeStyle(property.property_type)">
            {{ property.property_type || 'residential' }}
          </div>
        </div>
        <div class="card-body">
          <div v-if="extractPostcode(property.address)" class="card-postcode">{{ extractPostcode(property.address) }}</div>
          <h3 class="card-address">{{ property.address }}</h3>
          <div v-if="property.client_name" class="card-client">{{ property.client_name }}</div>
          <div class="card-specs">
            <span v-if="property.bedrooms" class="spec-chip">{{ property.bedrooms }} bed</span>
            <span v-if="property.bathrooms" class="spec-chip">{{ property.bathrooms }} bath</span>
            <span v-if="property.furnished" class="spec-chip">{{ property.furnished }}</span>
          </div>
        </div>
        <div class="card-footer">
          <button @click="openMapForProperty(property)" class="btn-map" title="View on map">📍</button>
          <button @click="openEditModal(property)" class="btn-edit">Edit</button>
          <button @click="deleteProperty(property.id)" class="btn-delete">Delete</button>
        </div>
      </div>
      <div v-if="filteredProperties.length === 0" class="empty-state">
        {{ filters.client_id || filters.postcode || filters.property_type ? 'No properties match your filters.' : 'No properties yet. Add your first property!' }}
      </div>
    </div>

    <!-- Map view -->
    <div v-else class="map-view">
      <div class="map-sidebar">
        <div class="map-sidebar-header">{{ filteredProperties.length }} properties</div>
        <div class="map-list">
          <div v-for="property in filteredProperties" :key="property.id" class="map-list-item" @click="openMapForProperty(property)">
            <div class="mli-pin">📍</div>
            <div class="mli-body">
              <div class="mli-addr">{{ property.address }}</div>
              <div class="mli-meta">
                <span v-if="property.client_name" class="mli-client">{{ property.client_name }}</span>
                <span v-if="property.bedrooms" class="mli-spec">{{ property.bedrooms }}B</span>
              </div>
            </div>
            <div class="mli-type" :style="typeStyle(property.property_type)">
              {{ (property.property_type || 'res').slice(0,3).toUpperCase() }}
            </div>
          </div>
          <div v-if="filteredProperties.length === 0" class="map-empty-list">No properties to show.</div>
        </div>
      </div>

      <div class="map-canvas">
        <div class="map-bg">
          <div class="map-grid-overlay"></div>
          <div class="map-content">
            <div class="map-pins-wrap">
              <div
                v-for="(p, i) in filteredProperties.slice(0,16)"
                :key="p.id"
                class="map-pin-chip"
                :style="{ animationDelay: (i*35)+'ms' }"
                @click="openMapForProperty(p)"
              >
                <span>📍</span>
                <span class="pin-txt">{{ extractPostcode(p.address) || p.address.split(',').pop()?.trim() }}</span>
              </div>
            </div>
            <div v-if="filteredProperties.length > 16" class="map-overflow">
              +{{ filteredProperties.length - 16 }} more
            </div>
            <div v-if="filteredProperties.length > 0" class="map-cta">
              <button class="btn-open-maps" @click="openAllInMaps">Open in Google Maps</button>
              <span class="map-hint">Click any pin or use the list to open in Maps</span>
            </div>
            <div v-if="filteredProperties.length === 0" class="map-no-props">No properties to display</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>{{ editingProperty ? 'Edit Property' : 'Add Property' }}</h2>
          <button @click="showModal = false" class="btn-close">x</button>
        </div>
        <form @submit.prevent="handleSubmit" class="modal-body">
          <div class="form-group">
            <label>Portfolio *</label>
            <select v-model="form.client_id" required>
              <option :value="null" disabled>Select a portfolio...</option>
              <option v-for="c in clients" :key="c.id" :value="c.id">{{ c.name }}{{ c.company ? ' ('+c.company+')' : '' }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>Address *</label>
            <input v-model="form.address" type="text" required placeholder="123 Main Street, London, SW1A 1AA" />
          </div>
          <div class="form-group">
            <label>Property Type</label>
            <select v-model="form.property_type">
              <option value="residential">Residential</option>
              <option value="commercial">Commercial</option>
              <option value="student">Student</option>
            </select>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>Bedrooms</label>
              <input v-model.number="form.bedrooms" type="number" min="0" placeholder="2" />
            </div>
            <div class="form-group">
              <label>Bathrooms</label>
              <input v-model.number="form.bathrooms" type="number" min="0" placeholder="1" />
            </div>
          </div>
          <div class="form-group">
            <label>Furnished</label>
            <select v-model="form.furnished">
              <option value="">Not specified</option>
              <option value="furnished">Furnished</option>
              <option value="unfurnished">Unfurnished</option>
              <option value="part-furnished">Part Furnished</option>
            </select>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>Parking</label>
              <input v-model="form.parking" type="text" placeholder="e.g. 1 space" />
            </div>
            <div class="form-group">
              <label>Garden</label>
              <input v-model="form.garden" type="text" placeholder="e.g. Front and Rear" />
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" @click="showModal = false" class="btn-secondary">Cancel</button>
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

.properties-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }

.property-card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; transition: box-shadow 0.15s, transform 0.12s; display: flex; flex-direction: column; }
.property-card:hover { box-shadow: 0 4px 14px rgba(0,0,0,0.08); transform: translateY(-1px); }

.card-photo { position: relative; height: 120px; background: linear-gradient(135deg, #e0e7ff 0%, #ede9fe 100%); overflow: hidden; }
.prop-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.photo-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 36px; opacity: 0.4; }
.card-type-badge { position: absolute; top: 7px; left: 7px; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; text-transform: capitalize; }

.card-body { padding: 11px 13px 7px; flex: 1; }
.card-postcode { font-size: 10px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }
.card-address { font-size: 13px; font-weight: 700; color: #1e293b; line-height: 1.3; margin-bottom: 3px; }
.card-client { font-size: 11px; color: #6366f1; font-weight: 600; margin-bottom: 6px; }
.card-specs { display: flex; gap: 5px; flex-wrap: wrap; }
.spec-chip { font-size: 10px; font-weight: 600; padding: 2px 6px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; color: #64748b; text-transform: capitalize; }

.card-footer { display: flex; align-items: center; gap: 5px; padding: 7px 10px; border-top: 1px solid #f1f5f9; background: #fafbfc; }
.btn-map { padding: 4px 8px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 5px; font-size: 11px; cursor: pointer; }
.btn-map:hover { background: #dbeafe; }
.btn-edit { flex: 1; padding: 5px 8px; background: #eef2ff; color: #4338ca; border: none; border-radius: 5px; font-size: 11px; font-weight: 600; cursor: pointer; }
.btn-edit:hover { background: #c7d2fe; }
.btn-delete { flex: 1; padding: 5px 8px; background: #fee2e2; color: #991b1b; border: none; border-radius: 5px; font-size: 11px; font-weight: 600; cursor: pointer; }
.btn-delete:hover { background: #fecaca; }

.empty-state { grid-column: 1/-1; text-align: center; padding: 60px 20px; color: #94a3b8; }

.map-view { display: grid; grid-template-columns: 300px 1fr; gap: 12px; min-height: 560px; }
.map-sidebar { background: white; border: 1px solid #e9ecef; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }
.map-sidebar-header { padding: 10px 13px; background: #fafbfc; border-bottom: 1px solid #f1f5f9; font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.4px; }
.map-list { flex: 1; overflow-y: auto; }
.map-list-item { display: flex; align-items: flex-start; gap: 7px; padding: 9px 12px; border-bottom: 1px solid #f8fafc; cursor: pointer; transition: background 0.1s; }
.map-list-item:hover { background: #f8fafc; }
.mli-pin { font-size: 13px; flex-shrink: 0; margin-top: 1px; }
.mli-body { flex: 1; min-width: 0; }
.mli-addr { font-size: 11px; font-weight: 600; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mli-meta { display: flex; gap: 5px; margin-top: 2px; }
.mli-client { font-size: 10px; color: #6366f1; font-weight: 600; }
.mli-spec { font-size: 10px; color: #94a3b8; }
.mli-type { font-size: 9px; font-weight: 700; padding: 2px 5px; border-radius: 3px; flex-shrink: 0; align-self: flex-start; }
.map-empty-list { padding: 30px; text-align: center; color: #cbd5e1; font-size: 12px; font-style: italic; }

.map-canvas { background: white; border: 1px solid #e9ecef; border-radius: 10px; overflow: hidden; }
.map-bg { width: 100%; height: 100%; min-height: 400px; background: linear-gradient(135deg, #eef2f7 0%, #e8ecf5 100%); position: relative; display: flex; align-items: center; justify-content: center; }
.map-grid-overlay { position: absolute; inset: 0; background-image: linear-gradient(rgba(99,102,241,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.05) 1px, transparent 1px); background-size: 40px 40px; }
.map-content { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; gap: 18px; padding: 24px; width: 100%; }
.map-pins-wrap { display: flex; flex-wrap: wrap; gap: 7px; justify-content: center; max-width: 520px; }
.map-pin-chip { display: flex; align-items: center; gap: 4px; background: white; border: 1px solid #e2e8f0; border-radius: 20px; padding: 5px 11px; cursor: pointer; transition: all 0.15s; box-shadow: 0 1px 4px rgba(0,0,0,0.06); animation: pop-in 0.3s ease both; font-size: 12px; }
.map-pin-chip:hover { border-color: #6366f1; box-shadow: 0 2px 8px rgba(99,102,241,0.15); transform: translateY(-2px); }
.pin-txt { font-size: 11px; font-weight: 600; color: #374151; }
@keyframes pop-in { from { opacity:0; transform: scale(0.8) translateY(4px); } to { opacity:1; transform: scale(1) translateY(0); } }
.map-overflow { font-size: 12px; color: #94a3b8; }
.map-cta { display: flex; flex-direction: column; align-items: center; gap: 5px; }
.btn-open-maps { padding: 8px 18px; background: #6366f1; color: white; border: none; border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-open-maps:hover { background: #4f46e5; }
.map-hint { font-size: 10px; color: #94a3b8; }
.map-no-props { color: #cbd5e1; font-size: 13px; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: white; border-radius: 12px; width: 90%; max-width: 540px; max-height: 90vh; overflow-y: auto; }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #e5e7eb; position: sticky; top: 0; background: white; z-index: 1; }
.modal-header h2 { font-size: 15px; font-weight: 700; color: #0f172a; }
.btn-close { background: none; border: none; font-size: 16px; color: #94a3b8; cursor: pointer; padding: 4px 7px; border-radius: 4px; }
.btn-close:hover { background: #f1f5f9; }
.modal-body { padding: 18px 20px; display: flex; flex-direction: column; gap: 12px; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 11px; font-weight: 700; color: #374151; }
.form-group input, .form-group select { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; color: #1e293b; background: white; width: 100%; }
.form-group input:focus, .form-group select:focus { outline: none; border-color: #6366f1; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 20px; border-top: 1px solid #e5e7eb; background: #f8fafc; }
.btn-secondary { padding: 7px 14px; background: white; color: #64748b; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }

@media (max-width: 900px) { .map-view { grid-template-columns: 1fr; } .map-bg { min-height: 300px; } }
</style>
