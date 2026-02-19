<script setup>
import { ref, onMounted } from 'vue'
import api from '../services/api'
import { useToast } from '../composables/useToast'
const toast = useToast()

const properties = ref([])
const clients = ref([])
const loading = ref(true)
const showModal = ref(false)
const editingProperty = ref(null)

const form = ref({
  address: '',
  property_type: 'residential',
  bedrooms: null,
  bathrooms: null,
  furnished: '',
  parking: '',
  garden: '',
  client_id: null
})

async function fetchProperties() {
  loading.value = true
  try {
    const response = await api.getProperties()
    properties.value = response.data
  } catch (error) {
    console.error('Failed to fetch properties:', error)
    toast.error('Failed to load properties')
  } finally {
    loading.value = false
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

function openCreateModal() {
  editingProperty.value = null
  form.value = {
    address: '',
    property_type: 'residential',
    bedrooms: null,
    bathrooms: null,
    furnished: '',
    parking: '',
    garden: '',
    client_id: null
  }
  showModal.value = true
}

function openEditModal(property) {
  editingProperty.value = property
  form.value = {
    address: property.address,
    property_type: property.property_type || 'residential',
    bedrooms: property.bedrooms,
    bathrooms: property.bathrooms,
    furnished: property.furnished || '',
    parking: property.parking || '',
    garden: property.garden || '',
    client_id: property.client_id
  }
  showModal.value = true
}

async function handleSubmit() {
  if (!form.value.address || !form.value.client_id) {
    toast.warning('Address and client are required')
    return
  }

  try {
    if (editingProperty.value) {
      // Update existing property
      await api.updateProperty(editingProperty.value.id, form.value)
      toast.success('Property updated')
    } else {
      // Create new property
      await api.createProperty(form.value)
      toast.success('Property created')
    }
    showModal.value = false
    fetchProperties()
  } catch (error) {
    console.error('Failed to save property:', error)
    toast.error('Failed to save property')
  }
}

async function deleteProperty(id) {
  if (!confirm('Delete this property?')) return
  
  try {
    await api.deleteProperty(id)
    toast.success('Property deleted')
    fetchProperties()
  } catch (error) {
    console.error('Failed to delete property:', error)
    toast.error('Failed to delete property')
  }
}

onMounted(() => {
  fetchProperties()
  fetchClients()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>🏢 Properties</h1>
      <button @click="openCreateModal" class="btn-primary">➕ Add Property</button>
    </div>

    <div v-if="loading" class="loading">Loading...</div>

    <div v-else class="properties-grid">
      <div v-for="property in properties" :key="property.id" class="property-card">
        <h3>{{ property.address }}</h3>
        <p class="property-type">{{ property.property_type }}</p>
        <div class="property-details">
          <span v-if="property.bedrooms">🛏️ {{ property.bedrooms }} bed</span>
          <span v-if="property.bathrooms">🚿 {{ property.bathrooms }} bath</span>
        </div>
        <p v-if="property.client_name" class="client-name">👤 {{ property.client_name }}</p>
        
        <div class="card-actions">
          <button @click="openEditModal(property)" class="btn-edit">✏️ Edit</button>
          <button @click="deleteProperty(property.id)" class="btn-delete">🗑️ Delete</button>
        </div>
      </div>

      <div v-if="properties.length === 0" class="empty-state">
        No properties yet. Add your first property!
      </div>
    </div>

    <!-- Add/Edit Property Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>{{ editingProperty ? 'Edit Property' : 'Add Property' }}</h2>
          <button @click="showModal = false" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleSubmit" class="modal-body">
          <div class="form-group">
            <label>Client *</label>
            <select v-model="form.client_id" required>
              <option :value="null" disabled>Select a client...</option>
              <option v-for="client in clients" :key="client.id" :value="client.id">
                {{ client.name }} {{ client.company ? `(${client.company})` : '' }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label>Address *</label>
            <input v-model="form.address" type="text" required placeholder="123 Main Street, London" />
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

          <div class="form-group">
            <label>Parking</label>
            <input v-model="form.parking" type="text" placeholder="e.g., 1 space, Street parking" />
          </div>

          <div class="form-group">
            <label>Garden</label>
            <input v-model="form.garden" type="text" placeholder="e.g., Front & Rear, None" />
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

.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
}

.properties-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.property-card {
  background: white;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.property-card h3 {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #1e293b;
  line-height: 1.4;
}

.property-type {
  display: inline-block;
  padding: 4px 12px;
  background: #e0e7ff;
  color: #4338ca;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  text-transform: capitalize;
  margin-bottom: 12px;
}

.property-details {
  display: flex;
  gap: 16px;
  margin: 12px 0;
  font-size: 14px;
  color: #64748b;
}

.client-name {
  font-size: 14px;
  color: #6366f1;
  font-weight: 600;
  margin: 8px 0;
}

.card-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.btn-edit {
  flex: 1;
  padding: 8px 16px;
  background: #e0e7ff;
  color: #4338ca;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-edit:hover {
  background: #c7d2fe;
}

.btn-delete {
  flex: 1;
  padding: 8px 16px;
  background: #fee2e2;
  color: #991b1b;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-delete:hover {
  background: #fecaca;
}

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
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
}

.modal {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 600px;
  max-height: 90vh;
  overflow-y: auto;
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

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #6366f1;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
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
}
</style>
