<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../services/api'
import { useAuthStore } from '../stores/auth'
const authStore = useAuthStore()

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

// Filter
const filterSearch = ref('')

const filteredClients = computed(() => {
  const q = filterSearch.value.trim().toLowerCase()
  if (q.length < 3) return clients.value
  return clients.value.filter(c =>
    (c.name && c.name.toLowerCase().includes(q)) ||
    (c.company && c.company.toLowerCase().includes(q))
  )
})

// Logo upload handling
const logoInput = ref(null)
const logoPreview = ref(null)

function triggerLogoUpload() {
  // Clear value first so selecting the same file again always fires 'change'
  if (logoInput.value) logoInput.value.value = ''
  logoInput.value.click()
}

function handleLogoUpload(event) {
  const file = event.target.files[0]
  if (!file) return

  if (file.size > 2 * 1024 * 1024) {
    alert('Logo must be under 2MB')
    event.target.value = ''
    return
  }

  const reader = new FileReader()
  reader.onload = (e) => {
    form.value.logo = e.target.result  // base64 data URL
    logoPreview.value = e.target.result
    // Clear so the same file can be re-selected if needed
    event.target.value = ''
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
      const res = await api.updateClient(editingClient.value.id, form.value)
      // Immediately patch the local list with the server response so the UI
      // reflects the new logo/colour without waiting for a full re-fetch.
      if (res.data) {
        const idx = clients.value.findIndex(c => c.id === res.data.id)
        if (idx !== -1) clients.value[idx] = res.data
      }
    } else {
      const res = await api.createClient(form.value)
      if (res.data) clients.value.push(res.data)
    }
    showEditModal.value = false
    // Re-fetch in the background to ensure full consistency
    fetchClients()
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
        <p class="subtitle">{{ clients.length }} portfolios</p>
      </div>
      <button @click="openCreateModal" class="btn-primary">+ Add Client</button>
    </div>

    <div class="filters-bar">
      <div class="filter-group">
        <label>Search clients</label>
        <input
          v-model="filterSearch"
          type="text"
          placeholder="Type 3+ letters to filter…"
          class="filter-input"
        />
      </div>
      <button v-if="filterSearch" @click="filterSearch = ''" class="btn-clear">Clear</button>
      <div class="filter-hint" v-if="filterSearch.length > 0 && filterSearch.length < 3">
        Type {{ 3 - filterSearch.length }} more letter{{ filterSearch.length === 2 ? '' : 's' }}…
      </div>
    </div>

    
    <button
      v-if="authStore.isAdmin || authStore.isManager"
      class="mobile-fab-add"
      @click="openCreateModal"
      title="Add Client"
    >+</button>
    <div v-if="loading" class="loading">Loading clients...</div>

    <div v-else-if="clients.length === 0" class="empty-state">
      No clients yet. Add your first client to get started.
    </div>

    <div v-else class="clients-grid">
      <div v-if="filteredClients.length === 0 && filterSearch.length >= 3" class="empty-state">
        No clients match "{{ filterSearch }}"
      </div>
      <div
        v-for="client in filteredClients"
        :key="client.id"
        class="client-card"
        :style="{ '--brand': client.primary_color || '#1E3A8A' }"
      >
        <div class="card-accent"></div>

        <div class="card-body">
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

          <div class="client-info">
            <div v-if="client.email" class="info-row">
              <span class="info-icon">✉</span>
              <span>{{ client.email }}</span>
            </div>
            <div v-if="client.phone" class="info-row">
              <span class="info-icon">✆</span>
              <span>{{ client.phone }}</span>
            </div>
            <div v-if="client.address" class="info-row">
              <span class="info-icon">📍</span>
              <span class="address-text">{{ client.address }}</span>
            </div>
          </div>
        </div>

        <div class="card-actions">
          <button @click="openViewModal(client)" class="btn-action btn-view">View</button>
          <button @click="openEditModal(client)" class="btn-action btn-edit">Edit</button>
          <button @click="deleteClient(client.id)" class="btn-action btn-delete">Delete</button>
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

                  <!-- Preview (shown when a logo is set) -->
                  <div v-if="logoPreview" class="logo-preview-area">
                    <div class="logo-preview-box" :style="{ background: form.primary_color || '#1E3A8A' }">
                      <img :src="logoPreview" alt="Logo preview" class="logo-preview-thumb" />
                    </div>
                    <div class="logo-preview-actions">
                      <label class="btn-logo-action btn-logo-replace">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                        Replace Logo
                        <input type="file" accept="image/*" style="display:none" @change="handleLogoUpload" ref="logoInput" />
                      </label>
                      <button type="button" class="btn-logo-action btn-logo-remove" @click="removeLogo">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>
                        Remove
                      </button>
                    </div>
                  </div>

                  <!-- Upload prompt (no logo yet) -->
                  <div v-else class="logo-upload-area" @click="triggerLogoUpload">
                    <div class="logo-upload-placeholder">
                      <div class="upload-icon">🖼️</div>
                      <div class="upload-text">Click to upload logo</div>
                      <div class="upload-hint">PNG, JPG, SVG · Max 2MB</div>
                    </div>
                    <input
                      ref="logoInput"
                      type="file"
                      accept="image/*"
                      style="display: none"
                      @change="handleLogoUpload"
                    />
                  </div>
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
                      <span class="mini-photo-icon">◻</span>
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
.page { max-width: 1400px; }

/* ── Page header ── */
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; gap: 16px; }
h1 { font-size: 21px; font-weight: 700; color: #0f172a; margin: 0 0 1px; }
.subtitle { font-size: 11px; color: #94a3b8; margin: 0; }

.btn-primary { padding: 7px 16px; background: #6366f1; color: white; border: none; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.btn-primary:hover { background: #4f46e5; }

/* ── Filters ── */
.filters-bar { display: flex; align-items: flex-end; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; background: white; border: 1px solid #e9ecef; border-radius: 9px; padding: 10px 14px; }
.filter-group { display: flex; flex-direction: column; gap: 4px; min-width: 220px; }
.filter-group label { font-size: 10px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.4px; }
.filter-input { padding: 6px 9px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; background: white; color: #1e293b; font-family: inherit; }
.filter-input:focus { outline: none; border-color: #6366f1; }
.btn-clear { padding: 6px 12px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 11px; font-weight: 600; color: #64748b; cursor: pointer; align-self: flex-end; }
.btn-clear:hover { background: #e2e8f0; }
.filter-hint { font-size: 11px; color: #94a3b8; align-self: flex-end; padding-bottom: 7px; font-style: italic; }

/* ── Grid ── */
.clients-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; }

/* ── Card ── */
.client-card { background: white; border-radius: 12px; border: 1px solid #e8ecf1; overflow: hidden; transition: box-shadow 0.15s, transform 0.12s; display: flex; flex-direction: column; }
.client-card:hover { box-shadow: 0 3px 10px rgba(0,0,0,0.07); transform: translateY(-1px); }
.card-accent { height: 3px; background: var(--brand); }
.card-body { padding: 11px 13px 8px; flex: 1; }

.client-identity { display: flex; align-items: center; gap: 10px; margin-bottom: 9px; }
.client-avatar { width: 36px; height: 36px; border-radius: 8px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.avatar-logo { width: 100%; height: 100%; object-fit: contain; padding: 3px; background: white; }
.avatar-initials { font-size: 12px; font-weight: 700; color: white; letter-spacing: -0.5px; }
.client-name-block h3 { font-size: 13px; font-weight: 700; color: #1e293b; margin-bottom: 1px; }
.company-label { font-size: 10px; color: #64748b; font-weight: 500; }

.client-info { display: flex; flex-direction: column; gap: 4px; }
.info-row { display: flex; align-items: flex-start; gap: 6px; font-size: 11px; color: #475569; }
.info-icon { font-size: 10px; margin-top: 1px; flex-shrink: 0; opacity: 0.6; }
.address-text { font-size: 11px; line-height: 1.4; }

.card-actions { display: flex; border-top: 1px solid #f1f5f9; }
.btn-action { flex: 1; padding: 7px 8px; border: none; background: transparent; font-size: 11px; font-weight: 600; cursor: pointer; transition: background 0.15s; border-right: 1px solid #f1f5f9; }
.btn-action:last-child { border-right: none; }
.btn-view { color: #3730a3; }
.btn-view:hover { background: #eef2ff; }
.btn-edit { color: #1d4ed8; }
.btn-edit:hover { background: #eff6ff; }
.btn-delete { color: #dc2626; }
.btn-delete:hover { background: #fef2f2; }

.loading { text-align: center; padding: 60px; color: #94a3b8; font-size: 13px; }
.empty-state { grid-column: 1/-1; text-align: center; padding: 60px 20px; color: #94a3b8; font-size: 13px; }

/* ── Shared modal ── */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 2000; padding: 20px; }
.modal { background: white; border-radius: 12px; width: 100%; max-height: 92vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.2); }

/* ── View modal ── */
.modal-view { max-width: 580px; }
.view-header { border-radius: 12px 12px 0 0; padding: 20px 24px; position: relative; }
.view-header-content { display: flex; align-items: center; gap: 14px; }
.view-logo-area { display: flex; align-items: center; gap: 12px; }
.view-logo { width: 48px; height: 48px; border-radius: 9px; display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; }
.view-logo-img { width: 100%; height: 100%; object-fit: contain; padding: 5px; background: rgba(255,255,255,0.9); border-radius: 6px; }
.view-logo-initials { font-size: 17px; font-weight: 700; color: white; }
.view-client-name { font-size: 18px; font-weight: 700; color: white; margin-bottom: 2px; }
.view-company { font-size: 12px; color: rgba(255,255,255,0.8); }
.btn-close-modal { position: absolute; top: 14px; right: 14px; width: 28px; height: 28px; background: rgba(255,255,255,0.2); border: none; border-radius: 6px; color: white; font-size: 13px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.btn-close-modal:hover { background: rgba(255,255,255,0.3); }

.view-body { padding: 20px 24px; display: flex; flex-direction: column; gap: 18px; }
.view-section-title { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #f1f5f9; }
.view-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.view-detail { display: flex; flex-direction: column; gap: 3px; }
.view-detail--full { grid-column: 1 / -1; }
.detail-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #94a3b8; }
.detail-value { font-size: 13px; color: #1e293b; font-weight: 500; line-height: 1.5; }
.detail-value.muted { color: #94a3b8; font-style: italic; font-weight: 400; }
.color-display { display: flex; align-items: center; gap: 7px; }
.color-swatch { width: 16px; height: 16px; border-radius: 4px; border: 1px solid rgba(0,0,0,0.1); flex-shrink: 0; }
.logo-preview-display { margin-top: 3px; }
.logo-preview-img { max-height: 48px; max-width: 160px; object-fit: contain; border: 1px solid #e5e7eb; border-radius: 5px; padding: 5px; background: #f8fafc; }
.disclaimer-preview { font-size: 12px; color: #475569; line-height: 1.6; padding: 12px; background: #f8fafc; border-radius: 7px; border: 1px solid #e5e7eb; white-space: pre-wrap; }

.view-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 24px; border-top: 1px solid #f1f5f9; background: #f8fafc; border-radius: 0 0 12px 12px; }

/* ── Edit modal ── */
.modal-edit { max-width: 820px; }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid #f1f5f9; }
.modal-header h2 { font-size: 15px; font-weight: 700; color: #0f172a; }
.btn-close-x { width: 28px; height: 28px; background: #f1f5f9; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; color: #64748b; display: flex; align-items: center; justify-content: center; }
.btn-close-x:hover { background: #e2e8f0; }

.modal-body { padding: 20px; }
.form-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.form-section-title { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; color: #94a3b8; margin-bottom: 12px; padding-bottom: 5px; border-bottom: 1px solid #f1f5f9; }
.form-group { margin-bottom: 13px; }
.form-group label { display: block; margin-bottom: 4px; font-weight: 600; font-size: 11px; color: #374151; }
.input-field { width: 100%; padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; transition: border-color 0.15s; color: #1e293b; }
.input-field:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,0.08); }
.textarea-field { resize: vertical; min-height: 70px; }
.helper-text { margin-top: 4px; font-size: 11px; color: #94a3b8; }

/* Logo upload */
.logo-upload-area { border: 2px dashed #e2e8f0; border-radius: 9px; cursor: pointer; transition: all 0.15s; overflow: hidden; }
.logo-upload-area:hover { border-color: #6366f1; background: #fafaff; }
.logo-upload-placeholder { padding: 18px; display: flex; flex-direction: column; align-items: center; gap: 5px; }
.upload-icon { font-size: 22px; }
.upload-text { font-size: 12px; font-weight: 600; color: #475569; }
.upload-hint { font-size: 10px; color: #94a3b8; }

/* Logo preview + explicit action buttons */
.logo-preview-area { display: flex; flex-direction: column; gap: 8px; }
.logo-preview-box {
  display: flex; align-items: center; justify-content: center;
  height: 64px; border-radius: 8px; overflow: hidden;
  border: 1px solid rgba(0,0,0,0.08);
}
.logo-preview-thumb { max-height: 52px; max-width: 100%; object-fit: contain; padding: 4px; }
.logo-preview-actions { display: flex; gap: 8px; }
.btn-logo-action {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 5px 12px; border-radius: 6px; font-size: 12px; font-weight: 600;
  cursor: pointer; border: 1px solid; transition: background 0.15s; line-height: 1;
}
.btn-logo-replace {
  background: #f1f5f9; color: #1e293b; border-color: #e2e8f0;
}
.btn-logo-replace:hover { background: #e2e8f0; }
.btn-logo-remove {
  background: transparent; color: #ef4444; border-color: #fecaca;
}
.btn-logo-remove:hover { background: #fef2f2; }

/* Colour picker */
.color-picker-row { margin-bottom: 8px; }
.color-input-group { display: flex; align-items: center; gap: 8px; }
.color-native { width: 38px; height: 34px; padding: 2px; border: 1px solid #e2e8f0; border-radius: 6px; cursor: pointer; background: white; flex-shrink: 0; }
.color-hex-input { flex: 1; font-family: 'Courier New', monospace; font-size: 13px; font-weight: 600; }
.color-presets { display: flex; gap: 5px; flex-wrap: wrap; }
.color-preset-swatch { width: 20px; height: 20px; border-radius: 4px; cursor: pointer; border: 2px solid transparent; transition: transform 0.1s; }
.color-preset-swatch:hover { transform: scale(1.2); }
.color-preset-swatch.active { border-color: white; outline: 2px solid #6366f1; transform: scale(1.1); }

/* Mini cover preview */
.mini-cover-preview { width: 100%; height: 120px; border-radius: 7px; overflow: hidden; border: 1px solid #e5e7eb; display: flex; flex-direction: column; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.mini-cover-top { background: var(--pcolor); padding: 10px 12px; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.mini-logo { width: 24px; height: 24px; border-radius: 4px; background: rgba(255,255,255,0.2); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; }
.mini-logo-img { width: 100%; height: 100%; object-fit: contain; background: rgba(255,255,255,0.9); }
.mini-logo-initials { font-size: 9px; font-weight: 700; color: white; }
.mini-company { font-size: 11px; font-weight: 700; color: white; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mini-photo-area { flex: 1; background: #f1f5f9; display: flex; align-items: center; justify-content: center; font-size: 20px; opacity: 0.4; }
.mini-footer { background: var(--pcolor); padding: 5px 12px; font-size: 9px; color: rgba(255,255,255,0.8); flex-shrink: 0; }

.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid #f1f5f9; background: #f8fafc; border-radius: 0 0 12px 12px; }
.btn-secondary { padding: 7px 14px; background: white; color: #64748b; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-secondary:hover { background: #f8fafc; }

@media (max-width: 640px) { .form-cols { grid-template-columns: 1fr; } }

/* ══════════════════════════════════════
   MOBILE  ≤ 768px
══════════════════════════════════════ */
@media (max-width: 768px) {
  .page-header .btn-primary { display: none; }
  .mobile-fab-add { display: flex !important; }

  .filters-bar { flex-direction: column; padding: 10px 12px; gap: 8px; }
  .filter-group { min-width: 100%; }

  .clients-grid { grid-template-columns: 1fr; gap: 8px; }

  .modal-overlay { align-items: flex-end; padding: 0; }
  .modal { border-radius: 20px 20px 0 0; max-width: 100%; max-height: 94vh; }
  .form-cols { grid-template-columns: 1fr !important; }
  .view-detail-grid { grid-template-columns: 1fr !important; }

  /* Logo upload area: compact on mobile */
  .logo-upload-placeholder { padding: 14px; }
  .upload-icon { font-size: 20px; }

  /* Color presets: more swatches visible */
  .color-preset-swatch { width: 24px; height: 24px; }

  /* Mini cover preview: hide on small screens (saves space) */
  .mini-cover-preview { height: 100px; }
}


.mobile-fab-add {
  display: none;
  position: fixed;
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