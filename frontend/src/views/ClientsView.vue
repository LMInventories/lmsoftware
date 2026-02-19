<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../services/api'

const clients = ref([])
const loading = ref(true)

// Modal states
const showViewModal = ref(false)
const showEditModal = ref(false)
const viewingClient = ref(null)
const editingClient = ref(null)

const form = ref({
  name: '',
  email: '',
  phone: '',
  company: '',
  address: '',
  primary_color: '#1E3A8A',
  logo: null
})

// Logo upload handling
const logoInput = ref(null)
const logoPreview = ref(null)

function triggerLogoUpload() {
  logoInput.value.click()
}

function handleLogoUpload(event) {
  const file = event.target.files[0]
  if (!file) return

  if (file.size > 2 * 1024 * 1024) {
    alert('Logo must be under 2MB')
    return
  }

  const reader = new FileReader()
  reader.onload = (e) => {
    form.value.logo = e.target.result  // base64 data URL
    logoPreview.value = e.target.result
  }
  reader.readAsDataURL(file)
}

function removeLogo() {
  form.value.logo = null
  logoPreview.value = null
  if (logoInput.value) logoInput.value.value = ''
}

// Initials fallback for logo display
function getInitials(client) {
  if (!client) return '?'
  const name = client.company || client.name
  return name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
}

async function fetchClients() {
  loading.value = true
  try {
    const response = await api.getClients()
    clients.value = response.data
  } catch (error) {
    console.error('Failed to fetch clients:', error)
  } finally {
    loading.value = false
  }
}

async function openViewModal(client) {
  try {
    const response = await api.getClient(client.id)
    viewingClient.value = response.data
    showViewModal.value = true
  } catch (error) {
    // Fallback to local data if getClient isn't available yet
    viewingClient.value = client
    showViewModal.value = true
  }
}

function openCreateModal() {
  editingClient.value = null
  form.value = { name: '', email: '', phone: '', company: '', address: '', primary_color: '#1E3A8A', logo: null }
  logoPreview.value = null
  showEditModal.value = true
}

function openEditModal(client) {
  editingClient.value = client
  form.value = {
    name: client.name || '',
    email: client.email || '',
    phone: client.phone || '',
    company: client.company || '',
    address: client.address || '',
    primary_color: client.primary_color || '#1E3A8A',
    logo: client.logo || null
  }
  logoPreview.value = client.logo || null
  showEditModal.value = true
}

async function handleSubmit() {
  try {
    if (editingClient.value) {
      await api.updateClient(editingClient.value.id, form.value)
    } else {
      await api.createClient(form.value)
    }
    showEditModal.value = false
    await fetchClients()
  } catch (error) {
    console.error('Failed to save client:', error)
    alert('Failed to save client')
  }
}

async function deleteClient(id) {
  if (!confirm('Delete this client? This will also remove all their properties and inspections.')) return
  try {
    await api.deleteClient(id)
    fetchClients()
  } catch (error) {
    console.error('Failed to delete client:', error)
    alert('Failed to delete client')
  }
}

// Preset brand colours for quick pick
const presetColors = [
  '#1E3A8A', '#1D4ED8', '#0EA5E9', '#0D9488',
  '#16A34A', '#CA8A04', '#DC2626', '#9333EA',
  '#DB2777', '#EA580C', '#374151', '#000000'
]

onMounted(() => {
  fetchClients()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Clients</h1>
        <p class="page-subtitle">Manage your client accounts and branding</p>
      </div>
      <button @click="openCreateModal" class="btn-primary">+ Add Client</button>
    </div>

    <div v-if="loading" class="loading">Loading clients...</div>

    <div v-else-if="clients.length === 0" class="empty-state">
      <div class="empty-icon">🏢</div>
      <h3>No clients yet</h3>
      <p>Add your first client to get started</p>
      <button @click="openCreateModal" class="btn-primary">+ Add Client</button>
    </div>

    <div v-else class="clients-grid">
      <div
        v-for="client in clients"
        :key="client.id"
        class="client-card"
        :style="{ '--brand': client.primary_color || '#1E3A8A' }"
      >
        <!-- Colour accent bar -->
        <div class="card-accent"></div>

        <div class="card-body">
          <!-- Logo / Initials -->
          <div class="client-identity">
            <div class="client-avatar" :style="{ background: client.primary_color || '#1E3A8A' }">
              <img v-if="client.logo" :src="client.logo" :alt="client.name" class="avatar-logo" />
              <span v-else class="avatar-initials">{{ getInitials(client) }}</span>
            </div>
            <div class="client-name-block">
              <h3>{{ client.name }}</h3>
              <span v-if="client.company" class="company-label">{{ client.company }}</span>
            </div>
          </div>

          <!-- Contact info -->
          <div class="client-info">
            <div v-if="client.email" class="info-row">
              <span class="info-icon">✉</span>
              <span>{{ client.email }}</span>
            </div>
            <div v-if="client.phone" class="info-row">
              <span class="info-icon">📞</span>
              <span>{{ client.phone }}</span>
            </div>
            <div v-if="client.address" class="info-row">
              <span class="info-icon">📍</span>
              <span class="address-text">{{ client.address }}</span>
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="card-actions">
          <button @click="openViewModal(client)" class="btn-action btn-view">
            View
          </button>
          <button @click="openEditModal(client)" class="btn-action btn-edit">
            Edit
          </button>
          <button @click="deleteClient(client.id)" class="btn-action btn-delete">
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- ══════════════════════════════════════ -->
    <!-- VIEW MODAL                             -->
    <!-- ══════════════════════════════════════ -->
    <Teleport to="body">
      <div v-if="showViewModal && viewingClient" class="modal-overlay" @click.self="showViewModal = false">
        <div class="modal modal-view">
          <!-- Branded header -->
          <div class="view-header" :style="{ background: viewingClient.primary_color || '#1E3A8A' }">
            <div class="view-header-content">
              <div class="view-logo-area">
                <div class="view-logo" :style="{ background: 'rgba(255,255,255,0.15)', border: '2px solid rgba(255,255,255,0.3)' }">
                  <img v-if="viewingClient.logo" :src="viewingClient.logo" :alt="viewingClient.name" class="view-logo-img" />
                  <span v-else class="view-logo-initials">{{ getInitials(viewingClient) }}</span>
                </div>
                <div>
                  <h2 class="view-client-name">{{ viewingClient.name }}</h2>
                  <span v-if="viewingClient.company" class="view-company">{{ viewingClient.company }}</span>
                </div>
              </div>
            </div>
            <button @click="showViewModal = false" class="btn-close-modal">✕</button>
          </div>

          <div class="view-body">
            <!-- Contact details -->
            <div class="view-section">
              <div class="view-section-title">Contact Details</div>
              <div class="view-detail-grid">
                <div class="view-detail">
                  <span class="detail-label">Email</span>
                  <span class="detail-value">{{ viewingClient.email || '—' }}</span>
                </div>
                <div class="view-detail">
                  <span class="detail-label">Phone</span>
                  <span class="detail-value">{{ viewingClient.phone || '—' }}</span>
                </div>
                <div class="view-detail view-detail--full">
                  <span class="detail-label">Address</span>
                  <span class="detail-value">{{ viewingClient.address || '—' }}</span>
                </div>
              </div>
            </div>

            <!-- Branding -->
            <div class="view-section">
              <div class="view-section-title">Branding</div>
              <div class="view-detail-grid">
                <div class="view-detail">
                  <span class="detail-label">Brand Colour</span>
                  <div class="color-display">
                    <div class="color-swatch" :style="{ background: viewingClient.primary_color || '#1E3A8A' }"></div>
                    <span class="detail-value">{{ viewingClient.primary_color || '#1E3A8A' }}</span>
                  </div>
                </div>
                <div class="view-detail">
                  <span class="detail-label">Report Colour Override</span>
                  <div class="color-display">
                    <template v-if="viewingClient.report_color_override">
                      <div class="color-swatch" :style="{ background: viewingClient.report_color_override }"></div>
                      <span class="detail-value">{{ viewingClient.report_color_override }}</span>
                    </template>
                    <span v-else class="detail-value muted">Uses brand colour</span>
                  </div>
                </div>
                <div class="view-detail view-detail--full">
                  <span class="detail-label">Logo</span>
                  <div v-if="viewingClient.logo" class="logo-preview-display">
                    <img :src="viewingClient.logo" :alt="viewingClient.name" class="logo-preview-img" />
                  </div>
                  <span v-else class="detail-value muted">No logo uploaded — initials used as fallback</span>
                </div>
              </div>
            </div>

            <!-- Report disclaimer -->
            <div class="view-section" v-if="viewingClient.report_disclaimer">
              <div class="view-section-title">Report Disclaimer</div>
              <div class="disclaimer-preview">{{ viewingClient.report_disclaimer }}</div>
            </div>

            <!-- Stats -->
            <div class="view-section">
              <div class="view-section-title">Account Info</div>
              <div class="view-detail-grid">
                <div class="view-detail">
                  <span class="detail-label">Properties</span>
                  <span class="detail-value">{{ viewingClient.property_count ?? '—' }}</span>
                </div>
                <div class="view-detail">
                  <span class="detail-label">Client Since</span>
                  <span class="detail-value">{{ viewingClient.created_at ? new Date(viewingClient.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' }) : '—' }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="view-footer">
            <button @click="showViewModal = false; openEditModal(viewingClient)" class="btn-secondary">Edit Client</button>
            <button @click="showViewModal = false" class="btn-primary">Close</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ══════════════════════════════════════ -->
    <!-- CREATE / EDIT MODAL                    -->
    <!-- ══════════════════════════════════════ -->
    <Teleport to="body">
      <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
        <div class="modal modal-edit">
          <div class="modal-header">
            <h2>{{ editingClient ? 'Edit Client' : 'Add Client' }}</h2>
            <button @click="showEditModal = false" class="btn-close-x">✕</button>
          </div>

          <div class="modal-body">
            <div class="form-cols">
              <!-- Left column -->
              <div class="form-col">
                <div class="form-section-title">Contact Information</div>

                <div class="form-group">
                  <label>Client Name *</label>
                  <input v-model="form.name" type="text" class="input-field" placeholder="e.g. John Smith" required />
                </div>

                <div class="form-group">
                  <label>Company</label>
                  <input v-model="form.company" type="text" class="input-field" placeholder="e.g. Yellands Estates" />
                </div>

                <div class="form-group">
                  <label>Email(s) for Reports</label>
                  <input v-model="form.email" type="text" class="input-field" placeholder="email@example.com, another@example.com" />
                  <p class="helper-text">Separate multiple addresses with commas</p>
                </div>

                <div class="form-group">
                  <label>Phone</label>
                  <input v-model="form.phone" type="tel" class="input-field" placeholder="020 1234 5678" />
                </div>

                <div class="form-group">
                  <label>Address</label>
                  <textarea v-model="form.address" class="input-field textarea-field" rows="3" placeholder="Client's business address"></textarea>
                </div>
              </div>

              <!-- Right column — branding -->
              <div class="form-col">
                <div class="form-section-title">Branding</div>

                <!-- Logo upload -->
                <div class="form-group">
                  <label>Client Logo</label>
                  <div class="logo-upload-area" @click="triggerLogoUpload">
                    <div v-if="logoPreview" class="logo-upload-preview">
                      <img :src="logoPreview" alt="Logo preview" class="logo-preview-thumb" />
                      <button @click.stop="removeLogo" class="btn-remove-logo">✕ Remove</button>
                    </div>
                    <div v-else class="logo-upload-placeholder">
                      <div class="upload-icon">🖼️</div>
                      <div class="upload-text">Click to upload logo</div>
                      <div class="upload-hint">PNG, JPG, SVG · Max 2MB</div>
                    </div>
                  </div>
                  <input
                    ref="logoInput"
                    type="file"
                    accept="image/*"
                    style="display: none"
                    @change="handleLogoUpload"
                  />
                </div>

                <!-- Brand colour -->
                <div class="form-group">
                  <label>Brand Colour</label>
                  <div class="color-picker-row">
                    <div class="color-input-group">
                      <input
                        v-model="form.primary_color"
                        type="color"
                        class="color-native"
                      />
                      <input
                        v-model="form.primary_color"
                        type="text"
                        class="input-field color-hex-input"
                        placeholder="#1E3A8A"
                        maxlength="7"
                      />
                    </div>
                  </div>
                  <!-- Preset swatches -->
                  <div class="color-presets">
                    <div
                      v-for="preset in presetColors"
                      :key="preset"
                      class="color-preset-swatch"
                      :style="{ background: preset }"
                      :class="{ active: form.primary_color === preset }"
                      @click="form.primary_color = preset"
                      :title="preset"
                    ></div>
                  </div>
                </div>

                <!-- Live mini preview -->
                <div class="form-group">
                  <label>Preview</label>
                  <div class="mini-cover-preview" :style="{ '--pcolor': form.primary_color }">
                    <div class="mini-cover-top">
                      <div class="mini-logo">
                        <img v-if="logoPreview" :src="logoPreview" class="mini-logo-img" />
                        <span v-else class="mini-logo-initials">{{ form.company ? form.company.substring(0,2).toUpperCase() : form.name ? form.name.substring(0,2).toUpperCase() : 'CL' }}</span>
                      </div>
                      <span class="mini-company">{{ form.company || form.name || 'Client Name' }}</span>
                    </div>
                    <div class="mini-photo-area">
                      <span class="mini-photo-icon">🏠</span>
                    </div>
                    <div class="mini-footer">
                      <span>Check In Report</span>
                    </div>
                  </div>
                  <p class="helper-text">How the report cover will look</p>
                </div>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button @click="showEditModal = false" class="btn-secondary">Cancel</button>
            <button @click="handleSubmit" class="btn-primary">
              {{ editingClient ? 'Save Changes' : 'Create Client' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
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
  margin-bottom: 32px;
  gap: 20px;
}

.page-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}

.page-subtitle {
  font-size: 15px;
  color: #64748b;
}

/* ─── GRID ─── */
.clients-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

/* ─── CARD ─── */
.client-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  overflow: hidden;
  border: 1px solid #e5e7eb;
  transition: box-shadow 0.2s;
}

.client-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}

.card-accent {
  height: 4px;
  background: var(--brand);
}

.card-body {
  padding: 20px;
}

.client-identity {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
}

.client-avatar {
  width: 52px;
  height: 52px;
  border-radius: 10px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.avatar-logo {
  width: 100%;
  height: 100%;
  object-fit: contain;
  padding: 4px;
  background: white;
}

.avatar-initials {
  font-size: 18px;
  font-weight: 700;
  color: white;
  letter-spacing: -0.5px;
}

.client-name-block h3 {
  font-size: 17px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 2px;
}

.company-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.client-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: #475569;
}

.info-icon {
  font-size: 12px;
  margin-top: 1px;
  flex-shrink: 0;
  opacity: 0.6;
}

.address-text {
  font-size: 12px;
  line-height: 1.4;
}

.card-actions {
  display: flex;
  border-top: 1px solid #f1f5f9;
}

.btn-action {
  flex: 1;
  padding: 10px 8px;
  border: none;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  border-right: 1px solid #f1f5f9;
}

.btn-action:last-child { border-right: none; }

.btn-view { color: #3730a3; }
.btn-view:hover { background: #eef2ff; }

.btn-edit { color: #1d4ed8; }
.btn-edit:hover { background: #eff6ff; }

.btn-delete { color: #dc2626; }
.btn-delete:hover { background: #fef2f2; }

/* ─── SHARED MODAL ─── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 20px;
}

.modal {
  background: white;
  border-radius: 16px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 40px rgba(0,0,0,0.2);
}

/* ─── VIEW MODAL ─── */
.modal-view {
  max-width: 640px;
}

.view-header {
  border-radius: 16px 16px 0 0;
  padding: 28px 32px;
  position: relative;
}

.view-header-content {
  display: flex;
  align-items: center;
  gap: 20px;
}

.view-logo-area {
  display: flex;
  align-items: center;
  gap: 16px;
}

.view-logo {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
}

.view-logo-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  padding: 6px;
  background: rgba(255,255,255,0.9);
  border-radius: 8px;
}

.view-logo-initials {
  font-size: 22px;
  font-weight: 700;
  color: white;
  letter-spacing: -0.5px;
}

.view-client-name {
  font-size: 24px;
  font-weight: 700;
  color: white;
  margin-bottom: 4px;
}

.view-company {
  font-size: 14px;
  color: rgba(255,255,255,0.8);
}

.btn-close-modal {
  position: absolute;
  top: 20px;
  right: 20px;
  width: 32px;
  height: 32px;
  background: rgba(255,255,255,0.2);
  border: none;
  border-radius: 6px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close-modal:hover { background: rgba(255,255,255,0.3); }

.view-body {
  padding: 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.view-section-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #94a3b8;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f1f5f9;
}

.view-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.view-detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.view-detail--full {
  grid-column: 1 / -1;
}

.detail-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #94a3b8;
}

.detail-value {
  font-size: 14px;
  color: #1e293b;
  font-weight: 500;
  line-height: 1.5;
}

.detail-value.muted { color: #94a3b8; font-style: italic; font-weight: 400; }

.color-display {
  display: flex;
  align-items: center;
  gap: 8px;
}

.color-swatch {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  border: 1px solid rgba(0,0,0,0.1);
  flex-shrink: 0;
}

.logo-preview-display {
  margin-top: 4px;
}

.logo-preview-img {
  max-height: 60px;
  max-width: 200px;
  object-fit: contain;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 6px;
  background: #f8fafc;
}

.disclaimer-preview {
  font-size: 13px;
  color: #475569;
  line-height: 1.7;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  white-space: pre-wrap;
}

.view-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 32px;
  border-top: 1px solid #f1f5f9;
  background: #f8fafc;
  border-radius: 0 0 16px 16px;
}

/* ─── EDIT MODAL ─── */
.modal-edit {
  max-width: 860px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px 28px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
}

.btn-close-x {
  width: 32px;
  height: 32px;
  background: #f1f5f9;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close-x:hover { background: #e2e8f0; }

.modal-body {
  padding: 28px;
}

.form-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
}

.form-section-title {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #94a3b8;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f1f5f9;
}

.form-group {
  margin-bottom: 18px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-weight: 600;
  font-size: 13px;
  color: #475569;
}

.input-field {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 14px;
  font-family: inherit;
  transition: border-color 0.15s;
}

.input-field:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
}

.textarea-field {
  resize: vertical;
  min-height: 80px;
}

.helper-text {
  margin-top: 5px;
  font-size: 12px;
  color: #94a3b8;
}

/* Logo upload */
.logo-upload-area {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  overflow: hidden;
}

.logo-upload-area:hover {
  border-color: #6366f1;
  background: #fafaff;
}

.logo-upload-placeholder {
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.upload-icon { font-size: 28px; }
.upload-text { font-size: 13px; font-weight: 600; color: #475569; }
.upload-hint { font-size: 11px; color: #94a3b8; }

.logo-upload-preview {
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #f8fafc;
}

.logo-preview-thumb {
  max-height: 50px;
  max-width: 140px;
  object-fit: contain;
}

.btn-remove-logo {
  padding: 5px 10px;
  background: #fee2e2;
  color: #dc2626;
  border: none;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

/* Colour picker */
.color-picker-row {
  margin-bottom: 10px;
}

.color-input-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.color-native {
  width: 44px;
  height: 38px;
  padding: 2px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  cursor: pointer;
  background: white;
  flex-shrink: 0;
}

.color-hex-input {
  flex: 1;
  font-family: 'Courier New', monospace;
  font-size: 14px;
  font-weight: 600;
}

.color-presets {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.color-preset-swatch {
  width: 24px;
  height: 24px;
  border-radius: 5px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: transform 0.1s;
}

.color-preset-swatch:hover {
  transform: scale(1.2);
}

.color-preset-swatch.active {
  border-color: white;
  outline: 2px solid #6366f1;
  transform: scale(1.1);
}

/* Mini cover preview */
.mini-cover-preview {
  width: 100%;
  height: 140px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

.mini-cover-top {
  background: var(--pcolor);
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.mini-logo {
  width: 28px;
  height: 28px;
  border-radius: 5px;
  background: rgba(255,255,255,0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
}

.mini-logo-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: rgba(255,255,255,0.9);
}

.mini-logo-initials {
  font-size: 10px;
  font-weight: 700;
  color: white;
}

.mini-company {
  font-size: 12px;
  font-weight: 700;
  color: white;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mini-photo-area {
  flex: 1;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  opacity: 0.4;
}

.mini-footer {
  background: var(--pcolor);
  padding: 6px 14px;
  font-size: 10px;
  color: rgba(255,255,255,0.8);
  flex-shrink: 0;
}

/* Modal footer */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 28px;
  border-top: 1px solid #e5e7eb;
  background: #f8fafc;
  border-radius: 0 0 16px 16px;
}

/* Shared buttons */
.btn-primary {
  padding: 10px 24px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-primary:hover { background: #4f46e5; }

.btn-secondary {
  padding: 10px 20px;
  background: white;
  color: #64748b;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-secondary:hover { background: #f8fafc; }

/* Loading / empty */
.loading {
  text-align: center;
  padding: 80px;
  color: #64748b;
}

.empty-state {
  text-align: center;
  padding: 80px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.empty-icon { font-size: 56px; }

.empty-state h3 {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
}

.empty-state p { color: #64748b; margin-bottom: 8px; }
</style>
