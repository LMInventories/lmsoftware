<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../../services/api'

const clients = ref([])
const loadingClients = ref(true)
const saving = ref(false)
const saved = ref(false)

const selectedClientId = ref(null)
const selectedClient = ref(null)

// Report settings form — mirrors the fields on the Client model
const form = ref({
  report_color_override: '',
  useColorOverride: false,
  report_disclaimer: ''
})

// Whether the override colour is active
const effectiveColor = computed(() => {
  if (form.value.useColorOverride && form.value.report_color_override) {
    return form.value.report_color_override
  }
  return selectedClient.value?.primary_color || '#1E3A8A'
})

const clientInitials = computed(() => {
  if (!selectedClient.value) return '?'
  const name = selectedClient.value.company || selectedClient.value.name
  return name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
})

const today = new Date().toLocaleDateString('en-GB', {
  day: '2-digit', month: 'long', year: 'numeric'
})

async function fetchClients() {
  loadingClients.value = true
  try {
    const response = await api.getClients()
    clients.value = response.data
  } catch (err) {
    console.error('Failed to load clients:', err)
  } finally {
    loadingClients.value = false
  }
}

async function selectClient(id) {
  if (!id) {
    selectedClient.value = null
    return
  }

  try {
    const response = await api.getClient(id)
    selectedClient.value = response.data

    // Populate form from client data
    form.value.report_disclaimer = selectedClient.value.report_disclaimer || ''
    form.value.report_color_override = selectedClient.value.report_color_override || selectedClient.value.primary_color || '#1E3A8A'
    form.value.useColorOverride = !!selectedClient.value.report_color_override
  } catch (err) {
    console.error('Failed to load client:', err)
  }
}

watch(selectedClientId, (newId) => {
  selectClient(newId)
})

async function saveSettings() {
  if (!selectedClientId.value) return
  saving.value = true

  try {
    await api.updateClient(selectedClientId.value, {
      report_disclaimer: form.value.report_disclaimer,
      report_color_override: form.value.useColorOverride ? form.value.report_color_override : null
    })
    saved.value = true
    // Update local client data
    if (selectedClient.value) {
      selectedClient.value.report_disclaimer = form.value.report_disclaimer
      selectedClient.value.report_color_override = form.value.useColorOverride ? form.value.report_color_override : null
    }
    setTimeout(() => saved.value = false, 2500)
  } catch (err) {
    console.error('Failed to save:', err)
    alert('Failed to save settings')
  } finally {
    saving.value = false
  }
}

const presetColors = [
  '#1E3A8A', '#1D4ED8', '#0EA5E9', '#0D9488',
  '#16A34A', '#CA8A04', '#DC2626', '#9333EA',
  '#DB2777', '#EA580C', '#374151', '#000000'
]

onMounted(fetchClients)
</script>

<template>
  <div class="settings-section">
    <div class="section-header">
      <div>
        <h2>Report Customisation</h2>
        <p class="section-description">
          Configure per-client report branding, cover page colours, and disclaimers. Logo and brand colour are set on the client record.
        </p>
      </div>
    </div>

    <!-- Client selector -->
    <div class="client-selector-bar">
      <div class="selector-label">Configure settings for:</div>
      <div class="selector-wrap">
        <select
          v-model="selectedClientId"
          class="client-select"
          :disabled="loadingClients"
        >
          <option :value="null">— Select a client —</option>
          <option v-for="c in clients" :key="c.id" :value="c.id">
            {{ c.company || c.name }}
          </option>
        </select>
      </div>
      <div v-if="loadingClients" class="loading-inline">Loading clients...</div>
    </div>

    <!-- Placeholder state -->
    <div v-if="!selectedClientId" class="no-client-state">
      <div class="no-client-icon">🎨</div>
      <h3>Select a client to configure their report settings</h3>
      <p>Each client can have their own colour scheme, disclaimer text, and report preferences.</p>
    </div>

    <div v-else-if="!selectedClient" class="no-client-state">
      <div class="spinner"></div>
      <p>Loading client data...</p>
    </div>

    <!-- Settings panels -->
    <div v-else class="settings-layout">

      <!-- LEFT: configuration panels -->
      <div class="config-panels">

        <!-- 1. Client branding summary (read-only, links to client) -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">🏢</span>
            Client Branding
            <span class="panel-badge panel-badge--info">From client record</span>
          </div>
          <div class="branding-summary">
            <div class="brand-logo-row">
              <div class="brand-logo-display" :style="{ background: selectedClient.primary_color || '#1E3A8A' }">
                <img v-if="selectedClient.logo" :src="selectedClient.logo" :alt="selectedClient.name" class="brand-logo-img" />
                <span v-else class="brand-logo-initials">{{ clientInitials }}</span>
              </div>
              <div class="brand-info">
                <div class="brand-name">{{ selectedClient.company || selectedClient.name }}</div>
                <div class="brand-color-row">
                  <div class="brand-color-swatch" :style="{ background: selectedClient.primary_color || '#1E3A8A' }"></div>
                  <span class="brand-color-hex">{{ selectedClient.primary_color || '#1E3A8A' }}</span>
                  <span class="brand-color-label">Brand colour</span>
                </div>
                <div v-if="!selectedClient.logo" class="brand-note">
                  ⚠️ No logo uploaded — initials will be used. <a href="#" @click.prevent="$router.push('/clients')" class="link">Upload in Clients</a>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 2. Report colour override -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">🎨</span>
            Report Colour
          </div>

          <label class="toggle-row">
            <div class="toggle-switch" :class="{ active: form.useColorOverride }" @click="form.useColorOverride = !form.useColorOverride">
              <div class="toggle-thumb"></div>
            </div>
            <div class="toggle-label">
              <span class="toggle-title">Use a different colour for reports</span>
              <span class="toggle-desc">Override the brand colour specifically on report covers and section headers</span>
            </div>
          </label>

          <div v-if="form.useColorOverride" class="color-override-section">
            <div class="color-input-group">
              <input
                v-model="form.report_color_override"
                type="color"
                class="color-native"
              />
              <input
                v-model="form.report_color_override"
                type="text"
                class="input-field color-hex-input"
                placeholder="#1E3A8A"
                maxlength="7"
              />
            </div>
            <div class="color-presets">
              <div
                v-for="preset in presetColors"
                :key="preset"
                class="color-preset-swatch"
                :style="{ background: preset }"
                :class="{ active: form.report_color_override === preset }"
                @click="form.report_color_override = preset"
                :title="preset"
              ></div>
            </div>
            <div class="override-note">
              <div class="note-color-compare">
                <div class="compare-chip">
                  <div class="compare-dot" :style="{ background: selectedClient.primary_color || '#1E3A8A' }"></div>
                  <span>Brand: {{ selectedClient.primary_color || '#1E3A8A' }}</span>
                </div>
                <span class="compare-arrow">→</span>
                <div class="compare-chip">
                  <div class="compare-dot" :style="{ background: form.report_color_override }"></div>
                  <span>Report: {{ form.report_color_override }}</span>
                </div>
              </div>
            </div>
          </div>

          <div v-else class="using-brand-color">
            <div class="using-dot" :style="{ background: selectedClient.primary_color || '#1E3A8A' }"></div>
            Using brand colour: <strong>{{ selectedClient.primary_color || '#1E3A8A' }}</strong>
          </div>
        </div>

        <!-- 3. Disclaimer -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">📄</span>
            Report Disclaimer
          </div>
          <p class="panel-desc">This text appears on the disclaimer page of every report generated for this client. It will be rendered in full on page 3.</p>
          <textarea
            v-model="form.report_disclaimer"
            class="disclaimer-textarea"
            rows="10"
            placeholder="Enter the disclaimer text for this client's reports.

For example:
This report has been prepared by [Company Name] on behalf of [Client Name]. The findings in this report are based on a visual inspection of the property carried out on the date stated. This report does not constitute a structural survey..."
          ></textarea>
          <div class="char-count">{{ form.report_disclaimer.length }} characters</div>
        </div>

        <!-- 4. Save -->
        <div class="save-row">
          <div v-if="saved" class="saved-confirmation">
            ✅ Settings saved for {{ selectedClient.company || selectedClient.name }}
          </div>
          <div v-else></div>
          <button @click="saveSettings" :disabled="saving" class="btn-save">
            {{ saving ? 'Saving...' : '💾 Save Report Settings' }}
          </button>
        </div>

      </div>

      <!-- RIGHT: live cover preview -->
      <div class="preview-panel">
        <div class="preview-panel-title">Live Cover Preview</div>
        <div class="preview-panel-desc">Updates as you change settings</div>

        <div class="cover-preview" :style="{ '--brand': effectiveColor }">
          <!-- Top brand area -->
          <div class="cp-top">
            <div class="cp-logo-centered">
              <div class="cp-logo">
                <img v-if="selectedClient.logo" :src="selectedClient.logo" :alt="selectedClient.name" class="cp-logo-img" />
                <span v-else class="cp-logo-initials">{{ clientInitials }}</span>
              </div>
            </div>
            <div class="cp-type-badge">Check In Report</div>
          </div>

          <!-- Photo placeholder -->
          <div class="cp-photo">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            <span>Property overview photo</span>
          </div>

          <!-- Info grid -->
          <div class="cp-info-grid">
            <div class="cp-info-item">
              <div class="cp-label">Property Address</div>
              <div class="cp-value">12 Example Street, London</div>
            </div>
            <div class="cp-info-item">
              <div class="cp-label">Inspection Date</div>
              <div class="cp-value">{{ today }}</div>
            </div>
            <div class="cp-info-item">
              <div class="cp-label">Inspector</div>
              <div class="cp-value">Robyn Lee</div>
            </div>
            <div class="cp-info-item">
              <div class="cp-label">Reference</div>
              <div class="cp-value">CHK-2026-0001</div>
            </div>
          </div>

          <!-- Footer -->
          <div class="cp-footer">
            <span>Prepared by L&amp;M Inventories</span>
            <span>Confidential</span>
          </div>
        </div>

        <!-- Section header preview -->
        <div class="section-header-preview">
          <div class="shp-label">Section header style:</div>
          <div class="shp-bar" :style="{ background: effectiveColor }">
            <span class="shp-title">Condition Summary</span>
            <span class="shp-logo">{{ clientInitials }}</span>
          </div>
        </div>

        <div class="preview-note">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          This is how the report will look. To change the logo or base brand colour, edit the <a href="#" @click.prevent="$router.push('/clients')" class="link">client record</a>.
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.settings-section h2 {
  font-size: 24px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.section-description {
  color: #64748b;
  font-size: 15px;
  line-height: 1.5;
}

.section-header {
  margin-bottom: 28px;
}

/* ─── CLIENT SELECTOR ─── */
.client-selector-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  margin-bottom: 28px;
}

.selector-label {
  font-size: 14px;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}

.selector-wrap {
  flex: 1;
  max-width: 320px;
}

.client-select {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 14px;
  font-family: inherit;
  background: white;
  cursor: pointer;
}

.client-select:focus {
  outline: none;
  border-color: #6366f1;
}

.loading-inline {
  font-size: 13px;
  color: #94a3b8;
}

/* ─── NO CLIENT ─── */
.no-client-state {
  text-align: center;
  padding: 80px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.no-client-icon { font-size: 56px; }

.no-client-state h3 {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
}

.no-client-state p { color: #64748b; max-width: 400px; }

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* ─── SETTINGS LAYOUT ─── */
.settings-layout {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 28px;
  align-items: start;
}

/* ─── PANELS ─── */
.config-panels {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.panel {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 24px;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 16px;
}

.panel-icon { font-size: 16px; }

.panel-badge {
  margin-left: auto;
  padding: 3px 9px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}

.panel-badge--info {
  background: #e0e7ff;
  color: #3730a3;
}

.panel-desc {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 14px;
  line-height: 1.6;
}

/* Branding summary */
.brand-logo-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.brand-logo-display {
  width: 52px;
  height: 52px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.brand-logo-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: rgba(255,255,255,0.9);
  padding: 4px;
}

.brand-logo-initials {
  font-size: 18px;
  font-weight: 700;
  color: white;
}

.brand-name {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 6px;
}

.brand-color-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.brand-color-swatch {
  width: 16px;
  height: 16px;
  border-radius: 3px;
  border: 1px solid rgba(0,0,0,0.1);
  flex-shrink: 0;
}

.brand-color-hex {
  font-size: 12px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
  color: #1e293b;
}

.brand-color-label {
  font-size: 11px;
  color: #94a3b8;
}

.brand-note {
  font-size: 12px;
  color: #f59e0b;
}

.link {
  color: #6366f1;
  text-decoration: none;
  font-weight: 600;
}
.link:hover { text-decoration: underline; }

/* Toggle */
.toggle-row {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  cursor: pointer;
  margin-bottom: 16px;
}

.toggle-switch {
  width: 44px;
  height: 24px;
  background: #e2e8f0;
  border-radius: 12px;
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
  flex-shrink: 0;
  margin-top: 2px;
}

.toggle-switch.active {
  background: #6366f1;
}

.toggle-thumb {
  position: absolute;
  width: 18px;
  height: 18px;
  background: white;
  border-radius: 50%;
  top: 3px;
  left: 3px;
  transition: transform 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

.toggle-switch.active .toggle-thumb {
  transform: translateX(20px);
}

.toggle-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  display: block;
  margin-bottom: 2px;
}

.toggle-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}

.color-override-section {
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 12px;
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

.input-field {
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 14px;
  font-family: inherit;
}

.input-field:focus {
  outline: none;
  border-color: #6366f1;
}

.color-hex-input {
  width: 120px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
}

.color-presets {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.color-preset-swatch {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: transform 0.1s;
}

.color-preset-swatch:hover { transform: scale(1.2); }
.color-preset-swatch.active {
  border-color: white;
  outline: 2px solid #6366f1;
}

.override-note { margin-top: 4px; }

.note-color-compare {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.compare-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: white;
  border-radius: 20px;
  border: 1px solid #e5e7eb;
  font-size: 12px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
}

.compare-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.compare-arrow { color: #94a3b8; font-size: 16px; }

.using-brand-color {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
  padding: 10px 14px;
  background: #f8fafc;
  border-radius: 7px;
}

.using-dot {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  flex-shrink: 0;
}

/* Disclaimer */
.disclaimer-textarea {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  line-height: 1.7;
  resize: vertical;
  min-height: 180px;
  color: #334155;
}

.disclaimer-textarea:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
}

.char-count {
  font-size: 11px;
  color: #94a3b8;
  text-align: right;
  margin-top: 4px;
}

/* Save row */
.save-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.saved-confirmation {
  font-size: 14px;
  font-weight: 600;
  color: #16a34a;
}

.btn-save {
  padding: 12px 28px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}

.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { background: #94a3b8; cursor: not-allowed; }

/* ─── PREVIEW PANEL ─── */
.preview-panel {
  position: sticky;
  top: 80px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.preview-panel-title {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.preview-panel-desc {
  font-size: 12px;
  color: #94a3b8;
  margin-top: -8px;
  margin-bottom: 4px;
}

/* Mini A4 cover */
.cover-preview {
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  display: flex;
  flex-direction: column;
}

.cp-top {
  background: var(--brand);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cp-logo-centered {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
}

.cp-logo {
  width: 100%;
  display: flex;
  justify-content: center;
}

.cp-logo-img {
  width: 100%;
  height: auto;
  display: block;
  object-fit: contain;
}

.cp-logo-initials {
  font-size: 18px;
  font-weight: 700;
  color: rgba(255,255,255,0.5);
  padding: 12px 0;
}

.cp-client-name {
  font-size: 14px;
  font-weight: 700;
  color: white;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cp-type-badge {
  font-size: 11px;
  color: rgba(255,255,255,0.85);
  padding: 4px 10px;
  background: rgba(255,255,255,0.15);
  border-radius: 4px;
  border: 1px solid rgba(255,255,255,0.25);
  align-self: flex-start;
  font-style: italic;
}

.cp-photo {
  background: #f1f5f9;
  height: 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 11px;
  color: #94a3b8;
}

.cp-info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 2px solid var(--brand);
}

.cp-info-item {
  padding: 10px 14px;
  border-right: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
}

.cp-info-item:nth-child(even) { border-right: none; }

.cp-label {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #94a3b8;
  font-weight: 700;
  margin-bottom: 2px;
}

.cp-value {
  font-size: 11px;
  font-weight: 600;
  color: #1e293b;
}

.cp-footer {
  background: var(--brand);
  padding: 8px 14px;
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: rgba(255,255,255,0.75);
}

/* Section header preview */
.section-header-preview {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 14px;
}

.shp-label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.shp-bar {
  border-radius: 5px;
  padding: 8px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.shp-title {
  font-size: 12px;
  font-weight: 700;
  color: white;
}

.shp-logo {
  font-size: 11px;
  font-weight: 700;
  color: rgba(255,255,255,0.7);
}

.preview-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 7px;
  border: 1px solid #e5e7eb;
}

.preview-note svg {
  flex-shrink: 0;
  margin-top: 1px;
  color: #f59e0b;
}
</style>
