<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../../services/api'

// ── Global report style settings (system-wide) ──────────────────────
const globalSaving = ref(false)
const globalSaved = ref(false)
const globalLoading = ref(true)

const globalForm = ref({
  report_header_text_color: '#FFFFFF',
  report_body_text_color:   '#1e293b',
  report_orientation:       'portrait'
})

async function fetchGlobalSettings() {
  globalLoading.value = true
  try {
    const res = await api.getSystemSettings()
    const s = res.data || {}
    globalForm.value.report_header_text_color = s.report_header_text_color || '#FFFFFF'
    globalForm.value.report_body_text_color   = s.report_body_text_color   || '#1e293b'
    globalForm.value.report_orientation       = s.report_orientation       || 'portrait'
  } catch (err) {
    console.error('Failed to load global report settings:', err)
  } finally {
    globalLoading.value = false
  }
}

async function saveGlobalSettings() {
  globalSaving.value = true
  try {
    await api.updateSystemSettings({
      report_header_text_color: globalForm.value.report_header_text_color,
      report_body_text_color:   globalForm.value.report_body_text_color,
      report_orientation:       globalForm.value.report_orientation,
    })
    globalSaved.value = true
    setTimeout(() => globalSaved.value = false, 2500)
  } catch (err) {
    console.error('Failed to save global settings:', err)
    alert('Failed to save — please try again.')
  } finally {
    globalSaving.value = false
  }
}

// ── Per-client settings (existing) ─────────────────────────────────
const clients = ref([])
const loadingClients = ref(true)
const saving = ref(false)
const saved = ref(false)

const selectedClientId = ref(null)
const selectedClient = ref(null)

const form = ref({
  report_color_override: '',
  useColorOverride: false,
  report_disclaimer: ''
})

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
  if (!id) { selectedClient.value = null; return }
  try {
    const response = await api.getClient(id)
    selectedClient.value = response.data
    form.value.report_disclaimer    = selectedClient.value.report_disclaimer    || ''
    form.value.report_color_override = selectedClient.value.report_color_override || selectedClient.value.primary_color || '#1E3A8A'
    form.value.useColorOverride      = !!selectedClient.value.report_color_override
  } catch (err) {
    console.error('Failed to load client:', err)
  }
}

watch(selectedClientId, (newId) => selectClient(newId))

async function saveSettings() {
  if (!selectedClientId.value) return
  saving.value = true
  try {
    await api.updateClient(selectedClientId.value, {
      report_disclaimer:    form.value.report_disclaimer,
      report_color_override: form.value.useColorOverride ? form.value.report_color_override : null
    })
    saved.value = true
    if (selectedClient.value) {
      selectedClient.value.report_disclaimer    = form.value.report_disclaimer
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

const headerTextPresets  = ['#FFFFFF', '#F1F5F9', '#1e293b', '#374151', '#000000']
const bodyTextPresets    = ['#1e293b', '#374151', '#4b5563', '#6b7280', '#000000']

onMounted(() => {
  fetchClients()
  fetchGlobalSettings()
})
</script>

<template>
  <div class="settings-section">
    <div class="section-header">
      <div>
        <h2>Report Customisation</h2>
        <p class="section-description">
          Configure global report style settings and per-client branding, cover page colours, and disclaimers.
        </p>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════ -->
    <!-- GLOBAL REPORT STYLE                                         -->
    <!-- ═══════════════════════════════════════════════════════════ -->
    <div class="global-section">
      <div class="global-section-title">
        <span class="gs-icon">🌐</span>
        Global Report Style
        <span class="gs-badge">Applied to all reports</span>
      </div>

      <div v-if="globalLoading" class="loading-inline-sm">
        <div class="spinner-sm"></div> Loading…
      </div>

      <div v-else class="global-panels">

        <!-- Orientation -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">📐</span>
            Report Orientation
          </div>
          <p class="panel-desc">Choose whether reports are generated in portrait or landscape format.</p>

          <div class="orientation-toggle">
            <button
              class="orient-btn"
              :class="{ active: globalForm.report_orientation === 'portrait' }"
              @click="globalForm.report_orientation = 'portrait'"
            >
              <div class="orient-icon orient-icon--portrait">
                <div class="orient-page orient-page--portrait">
                  <div class="orient-lines">
                    <div class="orient-line"></div>
                    <div class="orient-line orient-line--short"></div>
                    <div class="orient-line"></div>
                  </div>
                </div>
              </div>
              <span class="orient-label">Portrait</span>
              <span class="orient-size">A4 · 210 × 297mm</span>
            </button>
            <button
              class="orient-btn"
              :class="{ active: globalForm.report_orientation === 'landscape' }"
              @click="globalForm.report_orientation = 'landscape'"
            >
              <div class="orient-icon orient-icon--landscape">
                <div class="orient-page orient-page--landscape">
                  <div class="orient-lines">
                    <div class="orient-line"></div>
                    <div class="orient-line orient-line--short"></div>
                    <div class="orient-line"></div>
                  </div>
                </div>
              </div>
              <span class="orient-label">Landscape</span>
              <span class="orient-size">A4 · 297 × 210mm</span>
            </button>
          </div>
        </div>

        <!-- Text Colours -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">🖊️</span>
            Report Text Colours
          </div>
          <p class="panel-desc">
            Control the text colour within section headers (on top of the brand colour background) and the body text throughout the report.
          </p>

          <div class="text-color-grid">

            <!-- Header text colour -->
            <div class="text-color-row">
              <div class="tcr-label-group">
                <span class="tcr-label">Header Text</span>
                <span class="tcr-desc">Text on section header bars (on top of brand colour)</span>
              </div>
              <div class="tcr-controls">
                <div class="color-input-group">
                  <input
                    v-model="globalForm.report_header_text_color"
                    type="color"
                    class="color-native"
                  />
                  <input
                    v-model="globalForm.report_header_text_color"
                    type="text"
                    class="input-field color-hex-input"
                    placeholder="#FFFFFF"
                    maxlength="7"
                  />
                </div>
                <div class="color-presets">
                  <div
                    v-for="p in headerTextPresets"
                    :key="p"
                    class="color-preset-swatch"
                    :class="{ active: globalForm.report_header_text_color === p, 'swatch-light': p === '#FFFFFF' || p === '#F1F5F9' }"
                    :style="{ background: p }"
                    :title="p"
                    @click="globalForm.report_header_text_color = p"
                  ></div>
                </div>
                <!-- Live preview chip -->
                <div class="color-preview-chip" :style="{ background: '#1E3A8A' }">
                  <span :style="{ color: globalForm.report_header_text_color }">Section Header</span>
                </div>
              </div>
            </div>

            <div class="tcr-divider"></div>

            <!-- Body text colour -->
            <div class="text-color-row">
              <div class="tcr-label-group">
                <span class="tcr-label">Body Text</span>
                <span class="tcr-desc">Main report body content, tables, and descriptions</span>
              </div>
              <div class="tcr-controls">
                <div class="color-input-group">
                  <input
                    v-model="globalForm.report_body_text_color"
                    type="color"
                    class="color-native"
                  />
                  <input
                    v-model="globalForm.report_body_text_color"
                    type="text"
                    class="input-field color-hex-input"
                    placeholder="#1e293b"
                    maxlength="7"
                  />
                </div>
                <div class="color-presets">
                  <div
                    v-for="p in bodyTextPresets"
                    :key="p"
                    class="color-preset-swatch"
                    :style="{ background: p }"
                    :class="{ active: globalForm.report_body_text_color === p }"
                    :title="p"
                    @click="globalForm.report_body_text_color = p"
                  ></div>
                </div>
                <!-- Live preview chip -->
                <div class="color-preview-chip color-preview-chip--body">
                  <span :style="{ color: globalForm.report_body_text_color }">Body text example</span>
                </div>
              </div>
            </div>

          </div>
        </div>

        <!-- Global save -->
        <div class="save-row">
          <transition name="fade">
            <div v-if="globalSaved" class="saved-badge">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              Global style saved
            </div>
          </transition>
          <button class="btn-save" :disabled="globalSaving" @click="saveGlobalSettings">
            {{ globalSaving ? 'Saving…' : '💾  Save Style Settings' }}
          </button>
        </div>

      </div>
    </div>

    <!-- Divider -->
    <div class="section-divider">
      <span class="divider-label">Per-Client Report Settings</span>
    </div>

    <!-- ═══════════════════════════════════════════════════════════ -->
    <!-- PER-CLIENT SETTINGS (existing)                              -->
    <!-- ═══════════════════════════════════════════════════════════ -->

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

        <!-- 1. Client branding summary (read-only) -->
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
              <input v-model="form.report_color_override" type="color" class="color-native" />
              <input v-model="form.report_color_override" type="text" class="input-field color-hex-input" placeholder="#1E3A8A" maxlength="7" />
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
          <p class="panel-desc">This text appears on the disclaimer page of every report generated for this client.</p>
          <textarea
            v-model="form.report_disclaimer"
            class="disclaimer-textarea"
            rows="10"
            placeholder="Enter the disclaimer text for this client's reports..."
          ></textarea>
          <div class="char-count">{{ form.report_disclaimer.length }} characters</div>
        </div>

        <!-- 4. Save -->
        <div class="save-row">
          <div v-if="saved" class="saved-badge">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            Settings saved for {{ selectedClient.company || selectedClient.name }}
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
              <div class="cp-value" :style="{ color: globalForm.report_body_text_color }">12 Example Street, London</div>
            </div>
            <div class="cp-info-item">
              <div class="cp-label">Inspection Date</div>
              <div class="cp-value" :style="{ color: globalForm.report_body_text_color }">{{ today }}</div>
            </div>
            <div class="cp-info-item">
              <div class="cp-label">Inspector</div>
              <div class="cp-value" :style="{ color: globalForm.report_body_text_color }">Robyn Lee</div>
            </div>
            <div class="cp-info-item">
              <div class="cp-label">Reference</div>
              <div class="cp-value" :style="{ color: globalForm.report_body_text_color }">CHK-2026-0001</div>
            </div>
          </div>

          <!-- Footer -->
          <div class="cp-footer" :style="{ background: effectiveColor }">
            <span :style="{ color: globalForm.report_header_text_color }">Prepared by L&amp;M Inventories</span>
            <span :style="{ color: globalForm.report_header_text_color }">Confidential</span>
          </div>
        </div>

        <!-- Section header preview -->
        <div class="section-header-preview">
          <div class="shp-label">Section header style:</div>
          <div class="shp-bar" :style="{ background: effectiveColor }">
            <span class="shp-title" :style="{ color: globalForm.report_header_text_color }">Condition Summary</span>
            <span class="shp-logo" :style="{ color: globalForm.report_header_text_color }">{{ clientInitials }}</span>
          </div>
        </div>

        <!-- Orientation indicator -->
        <div class="orient-indicator">
          <div class="orient-pill" :class="{ 'orient-pill--landscape': globalForm.report_orientation === 'landscape' }">
            <svg v-if="globalForm.report_orientation === 'portrait'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2"/></svg>
            <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/></svg>
            {{ globalForm.report_orientation === 'portrait' ? 'Portrait' : 'Landscape' }}
          </div>
          <span class="orient-note">Global orientation setting</span>
        </div>

        <div class="preview-note">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          To change the logo or base brand colour, edit the <a href="#" @click.prevent="$router.push('/clients')" class="link">client record</a>.
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

.section-header { margin-bottom: 28px; }

/* ─── GLOBAL SECTION ─── */
.global-section {
  background: #fafbff;
  border: 1px solid #e0e7ff;
  border-radius: 14px;
  padding: 24px;
  margin-bottom: 32px;
}

.global-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 20px;
}

.gs-icon { font-size: 18px; }

.gs-badge {
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  background: #e0e7ff;
  color: #4338ca;
  border-radius: 20px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.loading-inline-sm {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #94a3b8;
  padding: 20px 0;
}

.spinner-sm {
  width: 20px;
  height: 20px;
  border: 2px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.global-panels {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ─── ORIENTATION TOGGLE ─── */
.orientation-toggle {
  display: flex;
  gap: 16px;
  margin-top: 4px;
}

.orient-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 20px 16px;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
}

.orient-btn:hover { border-color: #a5b4fc; background: #fafaff; }
.orient-btn.active {
  border-color: #6366f1;
  background: #eef2ff;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.orient-icon { display: flex; align-items: center; justify-content: center; }

.orient-page {
  background: white;
  border: 2px solid #94a3b8;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.orient-page--portrait  { width: 36px; height: 48px; }
.orient-page--landscape { width: 48px; height: 36px; }

.orient-lines {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 70%;
}

.orient-line {
  height: 2px;
  background: #cbd5e1;
  border-radius: 1px;
}

.orient-line--short { width: 60%; }

.orient-label {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
}

.orient-size {
  font-size: 11px;
  color: #94a3b8;
}

/* ─── TEXT COLOUR GRID ─── */
.text-color-grid {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.text-color-row {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  padding: 16px 0;
}

.tcr-divider {
  height: 1px;
  background: #f1f5f9;
}

.tcr-label-group {
  width: 200px;
  flex-shrink: 0;
}

.tcr-label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.tcr-desc {
  display: block;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.4;
}

.tcr-controls {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* ─── COLOUR PREVIEW CHIP ─── */
.color-preview-chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid #e5e7eb;
  min-width: 160px;
}

.color-preview-chip--body {
  background: #f9fafb;
}

/* ─── SECTION DIVIDER ─── */
.section-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 0 28px;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.section-divider::before, .section-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #e5e7eb;
}

.divider-label { white-space: nowrap; }

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

.selector-wrap { flex: 1; max-width: 320px; }

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

.client-select:focus { outline: none; border-color: #6366f1; }
.loading-inline { font-size: 13px; color: #94a3b8; }

/* ─── NO CLIENT ─── */
.no-client-state {
  text-align: center;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.no-client-icon { font-size: 48px; }

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
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.panel-badge--info { background: #e0f2fe; color: #0369a1; }
.panel-desc { font-size: 13px; color: #64748b; margin-bottom: 16px; line-height: 1.5; }

/* ─── BRANDING SUMMARY ─── */
.brand-logo-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-logo-display {
  width: 60px;
  height: 60px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.brand-logo-img { width: 100%; height: 100%; object-fit: contain; padding: 4px; }

.brand-logo-initials {
  font-size: 18px;
  font-weight: 700;
  color: white;
}

.brand-name { font-size: 15px; font-weight: 700; color: #1e293b; margin-bottom: 6px; }

.brand-color-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.brand-color-swatch { width: 14px; height: 14px; border-radius: 3px; }
.brand-color-hex { font-size: 13px; font-family: monospace; font-weight: 600; color: #374151; }
.brand-color-label { font-size: 12px; color: #94a3b8; }
.brand-note { font-size: 12px; color: #f59e0b; margin-top: 4px; }
.link { color: #6366f1; text-decoration: underline; cursor: pointer; }

/* ─── TOGGLE ─── */
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
  border-radius: 12px;
  background: #e5e7eb;
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
  flex-shrink: 0;
  margin-top: 2px;
}

.toggle-switch.active { background: #6366f1; }

.toggle-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: white;
  position: absolute;
  top: 3px;
  left: 3px;
  transition: transform 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

.toggle-switch.active .toggle-thumb { transform: translateX(20px); }

.toggle-title { font-size: 14px; font-weight: 600; color: #1e293b; display: block; margin-bottom: 2px; }
.toggle-desc { font-size: 12px; color: #64748b; line-height: 1.4; }

/* ─── COLOUR OVERRIDES ─── */
.color-override-section {
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.color-input-group { display: flex; align-items: center; gap: 10px; }

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

.input-field:focus { outline: none; border-color: #6366f1; }

.color-hex-input {
  width: 120px;
  font-family: 'Courier New', monospace;
  font-weight: 600;
}

.color-presets { display: flex; gap: 6px; flex-wrap: wrap; }

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

.color-preset-swatch.swatch-light {
  border: 2px solid #e5e7eb;
}

.override-note { margin-top: 4px; }

.note-color-compare { display: flex; align-items: center; gap: 10px; font-size: 12px; }

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

.compare-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
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

.using-dot { width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; }

/* ─── DISCLAIMER ─── */
.disclaimer-textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-family: inherit;
  font-size: 14px;
  resize: vertical;
  color: #1e293b;
  line-height: 1.6;
  box-sizing: border-box;
}

.disclaimer-textarea:focus { outline: none; border-color: #6366f1; }
.char-count { text-align: right; font-size: 12px; color: #94a3b8; margin-top: 6px; }

/* ─── SAVE ROW ─── */
.save-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
}

.saved-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #16a34a;
  font-weight: 600;
}

.btn-save {
  padding: 11px 28px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 9px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { opacity: 0.6; cursor: not-allowed; }

/* Fade */
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* ─── RIGHT: PREVIEW PANEL ─── */
.preview-panel { position: sticky; top: 24px; }

.preview-panel-title {
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
}

.preview-panel-desc { font-size: 12px; color: #94a3b8; margin-bottom: 16px; }

/* Cover mini-preview */
.cover-preview {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  background: white;
  box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  font-size: 11px;
}

.cp-top {
  background: var(--brand);
  padding: 14px 16px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.cp-logo {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: rgba(255,255,255,0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.cp-logo-img { width: 100%; height: 100%; object-fit: contain; }

.cp-logo-initials {
  font-size: 13px;
  font-weight: 700;
  color: white;
}

.cp-type-badge {
  font-size: 9px;
  font-weight: 700;
  color: rgba(255,255,255,0.85);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.cp-photo {
  height: 60px;
  background: #f1f5f9;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: #94a3b8;
  font-size: 10px;
}

.cp-info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: #f1f5f9;
}

.cp-info-item {
  background: white;
  padding: 8px 10px;
}

.cp-label { font-size: 8px; color: #94a3b8; margin-bottom: 2px; font-weight: 600; }
.cp-value { font-size: 10px; font-weight: 600; }

.cp-footer {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 8px;
  font-weight: 600;
  background: var(--brand);
}

/* Section header preview */
.section-header-preview { margin-top: 12px; }
.shp-label { font-size: 11px; color: #94a3b8; margin-bottom: 6px; }

.shp-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 11px;
}

.shp-title { font-weight: 700; }
.shp-logo { font-size: 9px; font-weight: 600; opacity: 0.8; }

/* Orientation indicator */
.orient-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.orient-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}

.orient-note { font-size: 11px; color: #94a3b8; }

/* Preview note */
.preview-note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 14px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.preview-note svg { flex-shrink: 0; margin-top: 1px; }
</style>
