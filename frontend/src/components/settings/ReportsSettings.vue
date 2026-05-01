<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../../services/api'

// ── Per-client settings ────────────────────────────────────
const clients       = ref([])
const loadingClients = ref(true)
const saving        = ref(false)
const saved         = ref(false)

const selectedClientId = ref(null)
const selectedClient   = ref(null)

const form = ref({
  report_color_override:      '',
  useColorOverride:           false,
  report_disclaimer:          '',
  report_header_text_color:   '#FFFFFF',
  report_body_text_color:     '#1e293b',
  report_orientation:         'portrait',
  // Photo position settings
  photo_property_overview:    'cover',        // always 'cover' — fixed, shown for clarity
  photo_room_overview:        'above',        // 'above' | 'below'
  photo_room_item:            'below',        // 'above' | 'below' | 'hyperlink'
  show_photo_timestamp:       false,          // overlay timestamp on enlarged photos
  action_summary_position:    'bottom',       // 'top' | 'bottom' | 'none'
  invert_logo:                false,          // use inverted logo on PDF cover footer
  logo_inverted:              null,           // base64 data URL of the white/inverted logo
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
    form.value.report_disclaimer          = selectedClient.value.report_disclaimer          || ''
    form.value.report_color_override      = selectedClient.value.report_color_override      || selectedClient.value.primary_color || '#1E3A8A'
    form.value.useColorOverride           = !!selectedClient.value.report_color_override
    form.value.report_header_text_color   = selectedClient.value.report_header_text_color   || '#FFFFFF'
    form.value.report_body_text_color     = selectedClient.value.report_body_text_color     || '#1e293b'
    form.value.report_orientation         = selectedClient.value.report_orientation         || 'portrait'
    // Photo settings — stored as JSON in report_photo_settings
    const ps = (() => {
      try { return JSON.parse(selectedClient.value.report_photo_settings || '{}') } catch { return {} }
    })()
    form.value.photo_room_overview    = ps.photo_room_overview    || 'above'
    form.value.photo_room_item        = ps.photo_room_item        || 'below'
    form.value.show_photo_timestamp      = ps.show_photo_timestamp      || false
    form.value.action_summary_position  = ps.action_summary_position  || 'bottom'
    form.value.invert_logo               = !!selectedClient.value.invert_logo
    form.value.logo_inverted             = selectedClient.value.logo_inverted || null
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
      report_disclaimer:          form.value.report_disclaimer,
      report_color_override:      form.value.useColorOverride ? form.value.report_color_override : null,
      report_header_text_color:   form.value.report_header_text_color,
      report_body_text_color:     form.value.report_body_text_color,
      report_orientation:         form.value.report_orientation,
      invert_logo:                form.value.invert_logo,
      logo_inverted:              form.value.logo_inverted,
      report_photo_settings:      JSON.stringify({
        photo_room_overview:   form.value.photo_room_overview,
        photo_room_item:       form.value.photo_room_item,
        show_photo_timestamp:      form.value.show_photo_timestamp,
        action_summary_position:  form.value.action_summary_position,
      }),
    })
    saved.value = true
    if (selectedClient.value) {
      selectedClient.value.report_disclaimer        = form.value.report_disclaimer
      selectedClient.value.report_color_override    = form.value.useColorOverride ? form.value.report_color_override : null
      selectedClient.value.report_header_text_color = form.value.report_header_text_color
      selectedClient.value.report_body_text_color   = form.value.report_body_text_color
      selectedClient.value.report_orientation       = form.value.report_orientation
      selectedClient.value.report_photo_settings     = JSON.stringify({
        photo_room_overview:      form.value.photo_room_overview,
        photo_room_item:          form.value.photo_room_item,
        show_photo_timestamp:     form.value.show_photo_timestamp,
        action_summary_position:  form.value.action_summary_position,
      })
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

const headerTextPresets = ['#FFFFFF', '#F1F5F9', '#1e293b', '#374151', '#000000']
const bodyTextPresets   = ['#1e293b', '#374151', '#4b5563', '#6b7280', '#000000']

onMounted(() => fetchClients())
</script>

<template>
  <div class="rs-root">

    <!-- Page title -->
    <div class="rs-title-row">
      <div>
        <h2>Report Customisation</h2>
        <p class="rs-subtitle">Per-client branding, colours, orientation, and disclaimers.</p>
      </div>
    </div>

    <!-- Client selector -->
    <div class="client-bar">
      <label class="client-bar-label">Client</label>
      <select v-model="selectedClientId" class="client-select" :disabled="loadingClients">
        <option :value="null">— Select a client —</option>
        <option v-for="c in clients" :key="c.id" :value="c.id">
          {{ c.company || c.name }}
        </option>
      </select>
      <span v-if="loadingClients" class="loading-text">Loading…</span>
    </div>

    <!-- Empty state -->
    <div v-if="!selectedClientId" class="empty-state">
      <div class="empty-icon">🎨</div>
      <p class="empty-title">Select a client to configure their report settings</p>
      <p class="empty-sub">Each client has their own colour scheme, orientation, and disclaimer.</p>
    </div>

    <div v-else-if="!selectedClient" class="empty-state">
      <div class="spinner"></div>
      <p class="empty-sub">Loading client data…</p>
    </div>

    <!-- Main layout -->
    <div v-else class="rs-layout">

      <!-- LEFT col -->
      <div class="rs-panels">

        <!-- Branding summary -->
        <div class="panel">
          <div class="panel-hd">
            <span class="panel-icon">🏢</span>
            Client Branding
            <span class="badge badge--blue">From client record</span>
          </div>
          <div class="brand-row">
            <div class="brand-logo" :style="{ background: selectedClient.primary_color || '#1E3A8A' }">
              <img v-if="selectedClient.logo" :src="selectedClient.logo" :alt="selectedClient.name" class="brand-logo-img" />
              <span v-else class="brand-logo-init">{{ clientInitials }}</span>
            </div>
            <div class="brand-info">
              <div class="brand-name">{{ selectedClient.company || selectedClient.name }}</div>
              <div class="brand-color-row">
                <div class="swatch-sm" :style="{ background: selectedClient.primary_color || '#1E3A8A' }"></div>
                <span class="mono">{{ selectedClient.primary_color || '#1E3A8A' }}</span>
                <span class="muted">Brand colour</span>
              </div>
              <div v-if="!selectedClient.logo" class="brand-warn">
                ⚠️ No logo uploaded.
                <a href="#" @click.prevent="$router.push('/clients')" class="lnk">Upload in Clients →</a>
              </div>
            </div>
          </div>
          <label class="toggle-row" style="margin-top:12px">
            <div class="toggle" :class="{ on: form.invert_logo }" @click="form.invert_logo = !form.invert_logo">
              <div class="toggle-thumb"></div>
            </div>
            <div>
              <div class="toggle-title">Use alternate logo on PDF cover footer</div>
              <div class="toggle-desc">
                Upload a white or light-coloured version of the logo below — used on the coloured footer so it stays visible. Email text also turns white.
              </div>
            </div>
          </label>
          <div v-if="form.invert_logo" class="inv-logo-block">
            <div class="inv-logo-preview" :style="{ background: selectedClient.report_color_override || selectedClient.primary_color || '#1E3A8A' }">
              <img v-if="form.logo_inverted" :src="form.logo_inverted" alt="Inverted logo preview" class="inv-logo-img" />
              <span v-else class="inv-logo-placeholder">Upload a white / light logo</span>
            </div>
            <div class="inv-logo-actions">
              <label class="btn-upload btn-upload--sm">
                <input type="file" accept="image/*" style="display:none" @change="e => {
                  const file = e.target.files[0]; if (!file) return
                  const reader = new FileReader()
                  reader.onload = ev => { form.logo_inverted = ev.target.result }
                  reader.readAsDataURL(file)
                }" />
                {{ form.logo_inverted ? 'Replace' : 'Upload' }} Inverted Logo
              </label>
              <button v-if="form.logo_inverted" class="btn-remove-sm" @click.prevent="form.logo_inverted = null">Remove</button>
            </div>
            <p class="inv-logo-hint">PNG with transparent background recommended. Preview shows how it will appear on the footer colour.</p>
          </div>
        </div>

        <!-- Report colour -->
        <div class="panel">
          <div class="panel-hd">
            <span class="panel-icon">🎨</span>
            Report Colour
          </div>
          <label class="toggle-row">
            <div class="toggle" :class="{ on: form.useColorOverride }" @click="form.useColorOverride = !form.useColorOverride">
              <div class="toggle-thumb"></div>
            </div>
            <div>
              <div class="toggle-title">Use a different colour for reports</div>
              <div class="toggle-desc">Override brand colour on report covers and section headers</div>
            </div>
          </label>

          <div v-if="form.useColorOverride" class="color-block">
            <div class="color-row">
              <input v-model="form.report_color_override" type="color" class="color-native" />
              <input v-model="form.report_color_override" type="text" class="input mono" placeholder="#1E3A8A" maxlength="7" />
            </div>
            <div class="swatches">
              <div v-for="p in presetColors" :key="p" class="swatch" :style="{ background: p }"
                :class="{ active: form.report_color_override === p }" @click="form.report_color_override = p" :title="p"></div>
            </div>
            <div class="compare-row">
              <div class="compare-chip">
                <div class="compare-dot" :style="{ background: selectedClient.primary_color || '#1E3A8A' }"></div>
                Brand: <span class="mono">{{ selectedClient.primary_color || '#1E3A8A' }}</span>
              </div>
              <span class="arrow">→</span>
              <div class="compare-chip">
                <div class="compare-dot" :style="{ background: form.report_color_override }"></div>
                Report: <span class="mono">{{ form.report_color_override }}</span>
              </div>
            </div>
          </div>

          <div v-else class="using-brand">
            <div class="swatch-sm" :style="{ background: selectedClient.primary_color || '#1E3A8A' }"></div>
            Using brand colour: <strong>{{ selectedClient.primary_color || '#1E3A8A' }}</strong>
          </div>
        </div>

        <!-- Orientation -->
        <div class="panel">
          <div class="panel-hd">
            <span class="panel-icon">📐</span>
            Report Orientation
          </div>
          <div class="orient-row">
            <button class="orient-btn" :class="{ active: form.report_orientation === 'portrait' }"
              @click="form.report_orientation = 'portrait'">
              <div class="orient-page orient-page--p">
                <div class="orient-lines">
                  <div class="ol"></div><div class="ol ol--s"></div><div class="ol"></div>
                </div>
              </div>
              <span class="orient-lbl">Portrait</span>
              <span class="orient-dim">210 × 297mm</span>
            </button>
            <button class="orient-btn" :class="{ active: form.report_orientation === 'landscape' }"
              @click="form.report_orientation = 'landscape'">
              <div class="orient-page orient-page--l">
                <div class="orient-lines">
                  <div class="ol"></div><div class="ol ol--s"></div><div class="ol"></div>
                </div>
              </div>
              <span class="orient-lbl">Landscape</span>
              <span class="orient-dim">297 × 210mm</span>
            </button>
          </div>
        </div>

        <!-- Text colours -->
        <div class="panel">
          <div class="panel-hd">
            <span class="panel-icon">🖊️</span>
            Report Text Colours
          </div>

          <!-- Header text -->
          <div class="tc-row">
            <div class="tc-meta">
              <span class="tc-label">Header Text</span>
              <span class="tc-desc">Text on section header bars</span>
            </div>
            <div class="tc-controls">
              <div class="color-row">
                <input v-model="form.report_header_text_color" type="color" class="color-native" />
                <input v-model="form.report_header_text_color" type="text" class="input mono" placeholder="#FFFFFF" maxlength="7" />
                <div class="preview-chip" :style="{ background: effectiveColor }">
                  <span :style="{ color: form.report_header_text_color }">Section Header</span>
                </div>
              </div>
              <div class="swatches">
                <div v-for="p in headerTextPresets" :key="p" class="swatch"
                  :class="{ active: form.report_header_text_color === p, 'swatch--light': p === '#FFFFFF' || p === '#F1F5F9' }"
                  :style="{ background: p }" @click="form.report_header_text_color = p" :title="p"></div>
              </div>
            </div>
          </div>

          <div class="tc-divider"></div>

          <!-- Body text -->
          <div class="tc-row">
            <div class="tc-meta">
              <span class="tc-label">Body Text</span>
              <span class="tc-desc">Tables, descriptions, content</span>
            </div>
            <div class="tc-controls">
              <div class="color-row">
                <input v-model="form.report_body_text_color" type="color" class="color-native" />
                <input v-model="form.report_body_text_color" type="text" class="input mono" placeholder="#1e293b" maxlength="7" />
                <div class="preview-chip preview-chip--body">
                  <span :style="{ color: form.report_body_text_color }">Body text sample</span>
                </div>
              </div>
              <div class="swatches">
                <div v-for="p in bodyTextPresets" :key="p" class="swatch"
                  :class="{ active: form.report_body_text_color === p }"
                  :style="{ background: p }" @click="form.report_body_text_color = p" :title="p"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Photo Position -->
        <div class="panel">
          <div class="panel-hd">
            <span class="panel-icon">📷</span>
            Photo Placement
          </div>
          <p class="panel-desc">
            Control where photos appear in compiled reports. Photos are always laid out 4 per row.
          </p>

          <!-- Property overview — fixed -->
          <div class="photo-setting-row">
            <div class="photo-setting-meta">
              <span class="photo-setting-label">Property Overview Photo</span>
              <span class="photo-setting-desc">The main exterior/property photo</span>
            </div>
            <div class="photo-setting-fixed">
              <span class="photo-fixed-badge">📌 Always on cover page</span>
            </div>
          </div>

          <div class="photo-setting-divider"></div>

          <!-- Room overview photos -->
          <div class="photo-setting-row">
            <div class="photo-setting-meta">
              <span class="photo-setting-label">Room Overview Photos</span>
              <span class="photo-setting-desc">Wide shots of each room, uploaded per-room</span>
            </div>
            <div class="photo-pos-btns">
              <button class="pos-btn" :class="{ active: form.photo_room_overview === 'above' }"
                @click="form.photo_room_overview = 'above'">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                  <rect x="2" y="2" width="24" height="7" rx="2" :fill="form.photo_room_overview === 'above' ? '#6366f1' : '#e2e8f0'"/>
                  <rect x="2" y="12" width="24" height="3" rx="1" fill="#cbd5e1"/>
                  <rect x="2" y="17" width="18" height="3" rx="1" fill="#e2e8f0"/>
                  <rect x="2" y="22" width="21" height="3" rx="1" fill="#e2e8f0"/>
                </svg>
                <span>Above data</span>
              </button>
              <button class="pos-btn" :class="{ active: form.photo_room_overview === 'below' }"
                @click="form.photo_room_overview = 'below'">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                  <rect x="2" y="2" width="24" height="3" rx="1" fill="#cbd5e1"/>
                  <rect x="2" y="7" width="18" height="3" rx="1" fill="#e2e8f0"/>
                  <rect x="2" y="12" width="21" height="3" rx="1" fill="#e2e8f0"/>
                  <rect x="2" y="19" width="24" height="7" rx="2" :fill="form.photo_room_overview === 'below' ? '#6366f1' : '#e2e8f0'"/>
                </svg>
                <span>Below data</span>
              </button>
            </div>
          </div>

          <div class="photo-setting-divider"></div>

          <!-- Room item photos -->
          <div class="photo-setting-row">
            <div class="photo-setting-meta">
              <span class="photo-setting-label">Room Item Photos</span>
              <span class="photo-setting-desc">Photos attached to individual items (door, window, etc.)</span>
            </div>
            <div class="photo-pos-btns">
              <button class="pos-btn" :class="{ active: form.photo_room_item === 'above' }"
                @click="form.photo_room_item = 'above'">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                  <rect x="2" y="2" width="24" height="7" rx="2" :fill="form.photo_room_item === 'above' ? '#6366f1' : '#e2e8f0'"/>
                  <rect x="2" y="12" width="24" height="3" rx="1" fill="#cbd5e1"/>
                  <rect x="2" y="17" width="18" height="3" rx="1" fill="#e2e8f0"/>
                  <rect x="2" y="22" width="21" height="3" rx="1" fill="#e2e8f0"/>
                </svg>
                <span>Above data</span>
              </button>
              <button class="pos-btn" :class="{ active: form.photo_room_item === 'below' }"
                @click="form.photo_room_item = 'below'">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                  <rect x="2" y="2" width="24" height="3" rx="1" fill="#cbd5e1"/>
                  <rect x="2" y="7" width="18" height="3" rx="1" fill="#e2e8f0"/>
                  <rect x="2" y="12" width="21" height="3" rx="1" fill="#e2e8f0"/>
                  <rect x="2" y="19" width="24" height="7" rx="2" :fill="form.photo_room_item === 'below' ? '#6366f1' : '#e2e8f0'"/>
                </svg>
                <span>Below data</span>
              </button>
              <button class="pos-btn pos-btn--link" :class="{ active: form.photo_room_item === 'hyperlink' }"
                @click="form.photo_room_item = 'hyperlink'">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                  <rect x="2" y="2" width="24" height="3" rx="1" fill="#cbd5e1"/>
                  <rect x="2" y="7" width="18" height="3" rx="1" fill="#e2e8f0"/>
                  <rect x="2" y="12" width="21" height="3" rx="1" fill="#e2e8f0"/>
                  <path d="M4 22 Q8 18 12 22 Q16 26 20 22" :stroke="form.photo_room_item === 'hyperlink' ? '#6366f1' : '#94a3b8'" stroke-width="2" fill="none" stroke-linecap="round"/>
                  <circle cx="4" cy="22" r="1.5" :fill="form.photo_room_item === 'hyperlink' ? '#6366f1' : '#94a3b8'"/>
                  <circle cx="20" cy="22" r="1.5" :fill="form.photo_room_item === 'hyperlink' ? '#6366f1' : '#94a3b8'"/>
                </svg>
                <span>Hyperlink</span>
              </button>
            </div>
          </div>

          <div v-if="form.photo_room_item === 'hyperlink'" class="hyperlink-notice">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            Hyperlink mode is a placeholder — photo linking will be configured once the storage server is set up. Photos will still be saved to the inspection; they just won't be embedded in the PDF.
          </div>

          <div class="photo-setting-divider" style="margin-top:10px"></div>

          <!-- Timestamp overlay -->
          <div class="photo-setting-row" style="padding-top:14px">
            <div class="photo-setting-meta">
              <span class="photo-setting-label">Photo Timestamps</span>
              <span class="photo-setting-desc">Show date &amp; time overlay on enlarged photos — useful for deposit disputes</span>
            </div>
            <label class="toggle-row" style="margin-bottom:0">
              <div class="toggle" :class="{ on: form.show_photo_timestamp }" @click="form.show_photo_timestamp = !form.show_photo_timestamp">
                <div class="toggle-thumb"></div>
              </div>
              <span class="toggle-title" style="font-size:12px">{{ form.show_photo_timestamp ? 'On' : 'Off' }}</span>
            </label>
          </div>
        </div>

        <!-- Action Summary -->
        <div class="panel">
          <div class="panel-hd">
            <span class="panel-icon">📋</span>
            Check Out Action Summary
          </div>
          <p class="panel-desc">
            Adds a summary page to Check Out reports listing all flagged items grouped by their assigned action — e.g. Repair, Replace, Clean. Helps clients see what needs doing and by whom at a glance.
          </p>

          <div class="action-pos-row">
            <button class="action-pos-btn" :class="{ active: form.action_summary_position === 'top' }" @click="form.action_summary_position = 'top'">
              <div class="action-pos-diagram">
                <div class="apd-bar apd-bar--summary" :class="{ lit: form.action_summary_position === 'top' }">Summary</div>
                <div class="apd-bar apd-bar--fixed">Fixed sections</div>
                <div class="apd-bar apd-bar--room">Rooms</div>
              </div>
              <span class="action-pos-label">Top of report</span>
              <span class="action-pos-desc">Before fixed sections</span>
            </button>

            <button class="action-pos-btn" :class="{ active: form.action_summary_position === 'bottom' }" @click="form.action_summary_position = 'bottom'">
              <div class="action-pos-diagram">
                <div class="apd-bar apd-bar--fixed">Fixed sections</div>
                <div class="apd-bar apd-bar--room">Rooms</div>
                <div class="apd-bar apd-bar--summary" :class="{ lit: form.action_summary_position === 'bottom' }">Summary</div>
              </div>
              <span class="action-pos-label">Bottom of report</span>
              <span class="action-pos-desc">After all rooms</span>
            </button>

            <button class="action-pos-btn" :class="{ active: form.action_summary_position === 'none' }" @click="form.action_summary_position = 'none'">
              <div class="action-pos-diagram">
                <div class="apd-bar apd-bar--fixed">Fixed sections</div>
                <div class="apd-bar apd-bar--room">Rooms</div>
                <div class="apd-bar apd-bar--none">No summary</div>
              </div>
              <span class="action-pos-label">Don't include</span>
              <span class="action-pos-desc">No summary page</span>
            </button>
          </div>
        </div>

        <!-- Disclaimer -->
        <div class="panel">
          <div class="panel-hd">
            <span class="panel-icon">📄</span>
            Report Disclaimer
          </div>
          <p class="panel-desc">Appears on the disclaimer page of every report generated for this client.</p>
          <textarea v-model="form.report_disclaimer" class="disclaimer-ta" rows="8"
            placeholder="Enter the disclaimer text for this client's reports…"></textarea>
          <div class="char-count">{{ form.report_disclaimer.length }} characters</div>
        </div>

        <!-- Save -->
        <div class="save-row">
          <transition name="fade">
            <div v-if="saved" class="saved-badge">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              Saved for {{ selectedClient.company || selectedClient.name }}
            </div>
          </transition>
          <button class="btn-save" :disabled="saving" @click="saveSettings">
            {{ saving ? 'Saving…' : '💾  Save Report Settings' }}
          </button>
        </div>

      </div>

      <!-- RIGHT col: live preview -->
      <div class="preview-col">
        <div class="preview-label">Live Preview</div>
        <div class="preview-sub">Updates as you change settings</div>

        <div class="cover-preview" :style="{ '--brand': effectiveColor }">
          <div class="cp-top">
            <div class="cp-logo">
              <img v-if="selectedClient.logo" :src="selectedClient.logo" :alt="selectedClient.name" class="cp-logo-img" />
              <span v-else class="cp-logo-init">{{ clientInitials }}</span>
            </div>
            <div class="cp-type">Check In Report</div>
          </div>
          <div class="cp-photo">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            <span>Property photo</span>
          </div>
          <div class="cp-grid">
            <div class="cp-cell">
              <div class="cp-lbl">Address</div>
              <div class="cp-val" :style="{ color: form.report_body_text_color }">12 Example St, London</div>
            </div>
            <div class="cp-cell">
              <div class="cp-lbl">Date</div>
              <div class="cp-val" :style="{ color: form.report_body_text_color }">{{ today }}</div>
            </div>
            <div class="cp-cell">
              <div class="cp-lbl">Inspector</div>
              <div class="cp-val" :style="{ color: form.report_body_text_color }">Robyn Lee</div>
            </div>
            <div class="cp-cell">
              <div class="cp-lbl">Reference</div>
              <div class="cp-val" :style="{ color: form.report_body_text_color }">CHK-2026-0001</div>
            </div>
          </div>
          <div class="cp-footer">
            <span :style="{ color: form.report_header_text_color }">L&amp;M Inventories</span>
            <span :style="{ color: form.report_header_text_color }">Confidential</span>
          </div>
        </div>

        <!-- Section header preview -->
        <div class="shp">
          <div class="shp-label">Section header</div>
          <div class="shp-bar" :style="{ background: effectiveColor }">
            <span :style="{ color: form.report_header_text_color }">Condition Summary</span>
            <span :style="{ color: form.report_header_text_color, opacity: 0.7, fontSize: '9px' }">{{ clientInitials }}</span>
          </div>
        </div>

        <!-- Orientation pill -->
        <div class="orient-pill" :class="{ 'orient-pill--l': form.report_orientation === 'landscape' }">
          <svg v-if="form.report_orientation === 'portrait'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2"/></svg>
          <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/></svg>
          {{ form.report_orientation === 'portrait' ? 'Portrait' : 'Landscape' }}
        </div>

        <div class="client-settings-note">
          <span class="client-settings-text">To change the logo or base brand colour, edit the</span>
          <a
            href="#"
            @click.prevent="$router.push('/clients')"
            class="client-settings-pill"
            :style="{
              background: brandColor + '18',
              color: brandColor,
              borderColor: brandColor + '40'
            }"
          >Client Settings</a>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
/* ── Root ─────────────────────────────────────────────────── */
.rs-root { }

.rs-title-row { margin-bottom: 20px; }

.rs-title-row h2 {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 3px;
}

.rs-subtitle { font-size: 13px; color: #64748b; }

/* ── Client bar ───────────────────────────────────────────── */
.client-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  margin-bottom: 20px;
}

.client-bar-label {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}

.client-select {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  background: white;
  cursor: pointer;
  max-width: 280px;
}

.client-select:focus { outline: none; border-color: #6366f1; }
.loading-text { font-size: 12px; color: #94a3b8; }

/* ── Empty state ──────────────────────────────────────────── */
.empty-state {
  text-align: center;
  padding: 48px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-icon { font-size: 40px; margin-bottom: 4px; }
.empty-title { font-size: 16px; font-weight: 600; color: #1e293b; }
.empty-sub { font-size: 13px; color: #64748b; max-width: 360px; }

.spinner {
  width: 28px;
  height: 28px;
  border: 2px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* ── Main layout ──────────────────────────────────────────── */
.rs-layout {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 20px;
  align-items: start;
}

/* ── Panels ───────────────────────────────────────────────── */
.rs-panels {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 18px 20px;
}

.panel-hd {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 14px;
}

.panel-icon { font-size: 15px; }

.panel-desc { font-size: 12px; color: #64748b; margin-bottom: 12px; line-height: 1.5; }

.badge {
  margin-left: auto;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.badge--blue { background: #e0f2fe; color: #0369a1; }

/* ── Branding summary ─────────────────────────────────────── */
.brand-row { display: flex; align-items: center; gap: 14px; }

.brand-logo {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.brand-logo-img { width: 100%; height: 100%; object-fit: contain; padding: 3px; }
.brand-logo-init { font-size: 16px; font-weight: 700; color: white; }

.brand-name { font-size: 14px; font-weight: 700; color: #1e293b; margin-bottom: 5px; }

.brand-color-row { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }

.swatch-sm { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }

.mono { font-size: 12px; font-family: 'Courier New', monospace; font-weight: 600; color: #374151; }
.muted { font-size: 11px; color: #94a3b8; }

.brand-warn { font-size: 11px; color: #f59e0b; margin-top: 4px; }

/* ── Inverted logo upload ─────────────────────────────────── */
.inv-logo-block { margin-top: 12px; }
.inv-logo-preview {
  display: flex; align-items: center; justify-content: center;
  height: 56px; border-radius: 8px; margin-bottom: 8px; overflow: hidden;
}
.inv-logo-img { max-height: 44px; max-width: 100%; object-fit: contain; }
.inv-logo-placeholder { font-size: 11px; color: rgba(255,255,255,0.55); font-style: italic; }
.inv-logo-actions { display: flex; gap: 8px; align-items: center; }
.btn-upload--sm {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  padding: 5px 12px; border-radius: 6px; font-size: 12px; font-weight: 600;
  background: #f1f5f9; color: #1e293b; border: 1px solid #e2e8f0;
  transition: background 0.15s;
}
.btn-upload--sm:hover { background: #e2e8f0; }
.btn-remove-sm {
  padding: 5px 10px; border-radius: 6px; font-size: 12px; font-weight: 600;
  background: transparent; color: #ef4444; border: 1px solid #fecaca; cursor: pointer;
}
.btn-remove-sm:hover { background: #fef2f2; }
.inv-logo-hint { font-size: 11px; color: #94a3b8; margin-top: 6px; }
.lnk { color: #6366f1; text-decoration: underline; cursor: pointer; }

/* ── Toggle ───────────────────────────────────────────────── */
.toggle-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  cursor: pointer;
  margin-bottom: 14px;
}

.toggle {
  width: 38px;
  height: 22px;
  border-radius: 11px;
  background: #e5e7eb;
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
  flex-shrink: 0;
  margin-top: 2px;
}

.toggle.on { background: #6366f1; }

.toggle-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: white;
  position: absolute;
  top: 3px;
  left: 3px;
  transition: transform 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

.toggle.on .toggle-thumb { transform: translateX(16px); }

.toggle-title { font-size: 13px; font-weight: 600; color: #1e293b; }
.toggle-desc { font-size: 12px; color: #64748b; margin-top: 1px; }

/* ── Colour block ─────────────────────────────────────────── */
.color-block {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.color-row { display: flex; align-items: center; gap: 8px; }

.color-native {
  width: 38px;
  height: 34px;
  padding: 2px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
  background: white;
  flex-shrink: 0;
}

.input {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
}

.input:focus { outline: none; border-color: #6366f1; }

.mono.input { width: 110px; font-family: 'Courier New', monospace; font-weight: 600; }

.swatches { display: flex; gap: 5px; flex-wrap: wrap; }

.swatch {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: transform 0.1s;
}

.swatch:hover { transform: scale(1.2); }
.swatch.active { border-color: white; outline: 2px solid #6366f1; }
.swatch--light { border: 2px solid #e5e7eb; }

.compare-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #64748b; }

.compare-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  background: white;
  border-radius: 20px;
  border: 1px solid #e5e7eb;
  font-size: 11px;
}

.compare-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.arrow { color: #94a3b8; }

.using-brand {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #64748b;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
}

/* ── Orientation ──────────────────────────────────────────── */
.orient-row { display: flex; gap: 12px; }

.orient-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 14px 12px;
  border: 2px solid #e5e7eb;
  border-radius: 9px;
  background: white;
  cursor: pointer;
  transition: all 0.15s;
}

.orient-btn:hover { border-color: #a5b4fc; background: #fafaff; }
.orient-btn.active { border-color: #6366f1; background: #eef2ff; }

.orient-page {
  background: white;
  border: 2px solid #94a3b8;
  border-radius: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.orient-page--p { width: 28px; height: 38px; }
.orient-page--l { width: 38px; height: 28px; }

.orient-lines { display: flex; flex-direction: column; gap: 4px; width: 70%; }
.ol { height: 2px; background: #cbd5e1; border-radius: 1px; }
.ol--s { width: 60%; }

.orient-lbl { font-size: 13px; font-weight: 700; color: #1e293b; }
.orient-dim { font-size: 10px; color: #94a3b8; }

/* ── Text colours ─────────────────────────────────────────── */
.tc-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 12px 0;
}

.tc-divider { height: 1px; background: #f1f5f9; }

.tc-meta { width: 150px; flex-shrink: 0; }
.tc-label { display: block; font-size: 13px; font-weight: 600; color: #1e293b; margin-bottom: 3px; }
.tc-desc { display: block; font-size: 11px; color: #94a3b8; line-height: 1.4; }

.tc-controls { flex: 1; display: flex; flex-direction: column; gap: 8px; }

.preview-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid #e5e7eb;
  white-space: nowrap;
}

.preview-chip--body { background: #f9fafb; }

/* ── Disclaimer ───────────────────────────────────────────── */
.disclaimer-ta {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 7px;
  font-family: inherit;
  font-size: 13px;
  resize: vertical;
  color: #1e293b;
  line-height: 1.6;
  box-sizing: border-box;
}

.disclaimer-ta:focus { outline: none; border-color: #6366f1; }
.char-count { text-align: right; font-size: 11px; color: #94a3b8; margin-top: 5px; }

/* ── Save row ─────────────────────────────────────────────── */
.save-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 14px;
}

.saved-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  color: #16a34a;
  font-weight: 600;
}

.btn-save {
  padding: 9px 22px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { opacity: 0.6; cursor: not-allowed; }

.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* ── Action summary position ──────────────────────────────── */
.action-pos-row { display: flex; gap: 10px; }

.action-pos-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 10px;
  border: 2px solid #e5e7eb;
  border-radius: 10px;
  background: white;
  cursor: pointer;
  transition: all 0.15s;
  text-align: center;
}
.action-pos-btn:hover { border-color: #a5b4fc; background: #fafaff; }
.action-pos-btn.active { border-color: #6366f1; background: #eef2ff; }

.action-pos-diagram { display: flex; flex-direction: column; gap: 3px; width: 100%; }

.apd-bar {
  border-radius: 3px;
  padding: 3px 0;
  font-size: 9px;
  font-weight: 700;
  text-align: center;
  letter-spacing: 0.02em;
}
.apd-bar--fixed   { background: #e2e8f0; color: #64748b; }
.apd-bar--room    { background: #dbeafe; color: #1d4ed8; }
.apd-bar--summary { background: #fde68a; color: #92400e; transition: background 0.15s, color 0.15s; }
.apd-bar--summary.lit { background: #f59e0b; color: white; }
.apd-bar--none    { background: #f1f5f9; color: #cbd5e1; font-style: italic; }

.action-pos-label { font-size: 12px; font-weight: 700; color: #1e293b; }
.action-pos-btn.active .action-pos-label { color: #4338ca; }
.action-pos-desc  { font-size: 10px; color: #94a3b8; }

/* ── Photo placement ──────────────────────────────────────── */
.photo-setting-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
}

.photo-setting-meta { flex: 1; min-width: 0; }
.photo-setting-label { display: block; font-size: 13px; font-weight: 600; color: #1e293b; margin-bottom: 3px; }
.photo-setting-desc  { display: block; font-size: 11px; color: #94a3b8; line-height: 1.4; }
.photo-setting-divider { height: 1px; background: #f1f5f9; margin: 2px 0; }

.photo-setting-fixed {
  flex-shrink: 0;
}

.photo-fixed-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.photo-pos-btns {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.pos-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 8px 10px;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  background: white;
  cursor: pointer;
  transition: all 0.15s;
  min-width: 68px;
}

.pos-btn span {
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}

.pos-btn:hover { border-color: #a5b4fc; background: #fafaff; }
.pos-btn.active { border-color: #6366f1; background: #eef2ff; }
.pos-btn.active span { color: #4338ca; }

.pos-btn--link { min-width: 76px; }

.hyperlink-notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 10px;
  padding: 10px 12px;
  background: #fefce8;
  border: 1px solid #fde68a;
  border-radius: 7px;
  font-size: 12px;
  color: #92400e;
  line-height: 1.5;
}

.hyperlink-notice svg { flex-shrink: 0; margin-top: 1px; color: #d97706; }

/* ── Preview column ───────────────────────────────────────── */
.preview-col { position: sticky; top: 24px; }

.preview-label { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 3px; }
.preview-sub { font-size: 11px; color: #94a3b8; margin-bottom: 12px; }

/* Cover mini preview */
.cover-preview {
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  overflow: hidden;
  background: white;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  font-size: 10px;
}

.cp-top {
  background: var(--brand);
  padding: 12px 14px 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.cp-logo {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  background: rgba(255,255,255,0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.cp-logo-img { width: 100%; height: 100%; object-fit: contain; }
.cp-logo-init { font-size: 11px; font-weight: 700; color: white; }
.cp-type { font-size: 8px; font-weight: 700; color: rgba(255,255,255,0.8); text-transform: uppercase; letter-spacing: 0.1em; }

.cp-photo {
  height: 50px;
  background: #f1f5f9;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  color: #94a3b8;
  font-size: 9px;
}

.cp-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: #f1f5f9;
}

.cp-cell { background: white; padding: 6px 8px; }
.cp-lbl { font-size: 7px; color: #94a3b8; margin-bottom: 2px; font-weight: 600; }
.cp-val { font-size: 9px; font-weight: 600; }

.cp-footer {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  font-size: 7px;
  font-weight: 600;
  background: var(--brand);
}

/* Section header preview */
.shp { margin-top: 10px; }
.shp-label { font-size: 10px; color: #94a3b8; margin-bottom: 5px; }
.shp-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 5px;
  font-size: 10px;
  font-weight: 700;
}

/* Orientation pill */
.orient-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 8px;
  padding: 3px 9px;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
}

.orient-pill--l { background: #f0fdf4; color: #166534; }

.client-settings-note {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}
.client-settings-text {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
  white-space: nowrap;
}
.client-settings-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border-radius: 20px;
  border: 1px solid;
  font-size: 11px;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  transition: opacity 0.12s;
  white-space: nowrap;
  letter-spacing: 0.2px;
}
.client-settings-pill:hover { opacity: 0.75; }
</style>
