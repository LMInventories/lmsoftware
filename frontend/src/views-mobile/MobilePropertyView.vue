<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera'
import { Capacitor } from '@capacitor/core'
import api from '../services/api'
import {
  getInspection,
  saveInspection,
  getReportData,
  saveReportData,
  markInspectionDirty,
} from '../services/offline'
import { syncInspection, savePhotoToFilesystem } from '../services/sync'

// Determine admin/manager from stored user token
const _storedUser = (() => { try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null } })()
const isAdminOrManager = _storedUser?.role === 'admin' || _storedUser?.role === 'manager'

const route  = useRoute()
const router = useRouter()

const id          = Number(route.params.id)
const inspection  = ref(null)
const syncing     = ref(false)
const syncMsg     = ref('')
const showConfirm = ref(false) // confirm "Finish & Sync" dialog

onMounted(async () => {
  // Load from local DB first for instant display
  inspection.value = await getInspection(id)
  // Then refresh from server if online
  try {
    const res = await api.getInspection(id)
    inspection.value = res.data
    await saveInspection(res.data)
  } catch { /* offline — local data is fine */ }
})

// ── Status helpers ────────────────────────────────────────────────────
const statusLabel = computed(() => ({
  scheduled:  'Scheduled',
  active:     'Active',
  processing: 'Processing',
  review:     'Review',
  complete:   'Complete',
}[inspection.value?.status] || inspection.value?.status || ''))

const typeLabel = computed(() => ({
  check_in:  'Check In',
  check_out: 'Check Out',
  interim:   'Interim Inspection',
  inventory: 'Inventory',
}[inspection.value?.inspection_type] || ''))

const canStart = computed(() =>
  inspection.value && ['scheduled', 'active'].includes(inspection.value.status)
)

const statusColour = computed(() => ({
  scheduled:  '#3b82f6',
  active:     '#8b5cf6',
  processing: '#f59e0b',
  review:     '#06b6d4',
  complete:   '#22c55e',
}[inspection.value?.status] || '#94a3b8'))

function fmtDate(d) {
  if (!d) return 'Not set'
  return new Date(d).toLocaleDateString('en-GB', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })
}

// ── Start inspection ──────────────────────────────────────────────────
async function startInspection() {
  // Advance status to active locally + on server if online
  if (inspection.value) {
    inspection.value.status = 'active'
    await saveInspection(inspection.value)
    try { await api.updateInspection(id, { status: 'active' }) } catch { /* queue for sync */ }
  }
  router.push(`/mobile/inspection/${id}/report`)
}

// ── Property overview photo ───────────────────────────────────────────
const overviewPhoto = ref(inspection.value?.overview_photo || null)

async function takePhoto() {
  try {
    const photo = await Camera.getPhoto({
      quality:      90,
      allowEditing: false,
      resultType:   CameraResultType.Base64,
      source:       CameraSource.Camera,
    })

    const base64 = `data:image/${photo.format};base64,${photo.base64String}`
    overviewPhoto.value = base64

    // Save locally and attempt server update
    try { await api.updateInspection(id, { overview_photo: base64 }) }
    catch { await markInspectionDirty(id) }
  } catch (err) {
    if (!err.message?.includes('cancelled')) console.error('Camera error:', err)
  }
}

// ── Sync ──────────────────────────────────────────────────────────────
async function doSync(markFinished = false) {
  syncing.value = true
  syncMsg.value  = 'Syncing…'
  showConfirm.value = false

  const result = await syncInspection(id, {
    markFinished,
    onProgress: (_, msg) => { syncMsg.value = msg }
  })

  syncMsg.value = result.success ? '✓ Synced successfully' : `Sync errors: ${result.errors.join(', ')}`
  syncing.value = false

  if (result.success && markFinished) {
    // Reload updated inspection
    inspection.value = await getInspection(id)
  }

  setTimeout(() => { syncMsg.value = '' }, 5000)
}

// ── Change Template ───────────────────────────────────────────────────
const showTemplateSheet    = ref(false)
const templateSheetList    = ref([])
const selectedTemplateId   = ref(null)
const templateChanging     = ref(false)
const templateSheetError   = ref('')
const templateSheetLoading = ref(false)

async function openTemplateSheet() {
  templateSheetError.value   = ''
  selectedTemplateId.value   = inspection.value?.template_id || null
  showTemplateSheet.value    = true
  templateSheetLoading.value = true
  try {
    const res = await api.getTemplates()
    const type = inspection.value?.inspection_type
    templateSheetList.value = (res.data || []).filter(t => t.inspection_type === type)
  } catch {
    templateSheetError.value = 'Failed to load templates — check connection'
  } finally {
    templateSheetLoading.value = false
  }
}

async function applyTemplateChange() {
  if (!selectedTemplateId.value) {
    templateSheetError.value = 'Please select a template'
    return
  }
  if (selectedTemplateId.value === inspection.value?.template_id) {
    showTemplateSheet.value = false
    return
  }
  templateChanging.value   = true
  templateSheetError.value = ''
  try {
    // Clear report_data and set new template
    await api.updateInspection(id, {
      template_id: selectedTemplateId.value,
      report_data: null,
    })
    // Reload full detail so we get the embedded template
    const res = await api.getInspection(id)
    inspection.value = res.data
    await saveInspection({
      ...res.data,
      property_address: res.data.property?.address || null,
      client_name:      res.data.client?.name      || null,
      inspector_name:   res.data.inspector?.name   || null,
      typist_name:      res.data.typist?.name       || null,
    })
    showTemplateSheet.value = false
  } catch (e) {
    templateSheetError.value = e.response?.data?.error || 'Failed to change template'
  } finally {
    templateChanging.value = false
  }
}
</script>

<template>
  <div class="mpv-shell" v-if="inspection">

    <!-- Nav bar -->
    <header class="mpv-nav">
      <button class="mpv-back" @click="router.push('/mobile')">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <span class="mpv-nav-title">{{ typeLabel }}</span>
      <button class="mpv-sync-btn" :disabled="syncing" @click="doSync(false)">
        <svg v-if="!syncing" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
        <svg v-else class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
      </button>
    </header>

    <div class="mpv-body">

      <!-- Overview photo -->
      <div class="mpv-photo-block" @click="takePhoto">
        <img v-if="overviewPhoto" :src="overviewPhoto" class="mpv-photo" />
        <div v-else class="mpv-photo-placeholder">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          <span>Tap to take property photo</span>
        </div>
        <div class="mpv-photo-btn">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          {{ overviewPhoto ? 'Retake' : 'Add photo' }}
        </div>
      </div>

      <!-- Status badge -->
      <div class="mpv-status-row">
        <span class="mpv-status-badge" :style="{ background: statusColour }">{{ statusLabel }}</span>
        <span class="mpv-type-label">{{ typeLabel }}</span>
      </div>

      <!-- Address -->
      <h1 class="mpv-address">{{ inspection.property_address }}</h1>

      <!-- Details grid -->
      <div class="mpv-details">
        <div class="mpv-detail" v-if="inspection.client_name">
          <span class="mpv-detail-label">Client</span>
          <span class="mpv-detail-value">{{ inspection.client_name }}</span>
        </div>
        <div class="mpv-detail">
          <span class="mpv-detail-label">Date</span>
          <span class="mpv-detail-value">{{ fmtDate(inspection.conduct_date) }}</span>
        </div>
        <div class="mpv-detail" v-if="inspection.inspector_name">
          <span class="mpv-detail-label">Inspector</span>
          <span class="mpv-detail-value">{{ inspection.inspector_name }}</span>
        </div>
        <div class="mpv-detail" v-if="inspection.typist_name">
          <span class="mpv-detail-label">Typist</span>
          <span class="mpv-detail-value">{{ inspection.typist_name }}</span>
        </div>
        <div class="mpv-detail" v-if="inspection.tenant_email">
          <span class="mpv-detail-label">Tenant</span>
          <span class="mpv-detail-value">{{ inspection.tenant_email }}</span>
        </div>
        <div class="mpv-detail" v-if="inspection.conduct_time_preference">
          <span class="mpv-detail-label">Time</span>
          <span class="mpv-detail-value">{{ inspection.conduct_time_preference }}</span>
        </div>
        <div class="mpv-detail" v-if="inspection.template_name || isAdminOrManager">
          <span class="mpv-detail-label">Template</span>
          <span class="mpv-detail-value">{{ inspection.template_name || 'None' }}</span>
          <button v-if="isAdminOrManager" class="mpv-edit-inline" @click="openTemplateSheet">✎</button>
        </div>
      </div>

      <!-- Sync message -->
      <p v-if="syncMsg" class="mpv-sync-msg" :class="{ error: syncMsg.includes('error') }">
        {{ syncMsg }}
      </p>

    </div>

    <!-- Bottom action bar -->
    <div class="mpv-footer">
      <!-- Start button -->
      <button
        v-if="canStart"
        class="mpv-start-btn"
        @click="startInspection"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Start Inspection
      </button>

      <!-- Continue editing (already active) -->
      <button
        v-else-if="inspection.status === 'active'"
        class="mpv-start-btn mpv-continue-btn"
        @click="router.push(`/mobile/inspection/${id}/report`)"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        Continue Report
      </button>

      <!-- Finish & sync button -->
      <button
        v-if="['active'].includes(inspection.status)"
        class="mpv-finish-btn"
        :disabled="syncing"
        @click="showConfirm = true"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
        Finish & Sync
      </button>
    </div>

    <!-- Confirm finish dialog -->
    <div v-if="showConfirm" class="mpv-overlay" @click.self="showConfirm = false">
      <div class="mpv-confirm">
        <h3>Finish this inspection?</h3>
        <p>
          Report data, photos, and recordings will be uploaded.
          The inspection will move to
          <strong>{{ inspection.typist_id ? 'Processing' : 'Review' }}</strong>.
        </p>
        <div class="mpv-confirm-btns">
          <button class="mpv-confirm-cancel" @click="showConfirm = false">Cancel</button>
          <button class="mpv-confirm-ok" @click="doSync(true)">Finish & Sync</button>
        </div>
      </div>
    </div>

  </div>

  <div v-else class="mpv-loading">
    <svg class="spin" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
  </div>

  <!-- ══ CHANGE TEMPLATE SHEET ══════════════════════════════════════════ -->
  <div v-if="showTemplateSheet" class="mpv-overlay" @click.self="showTemplateSheet = false">
    <div class="mpv-sheet">
      <div class="mpv-sheet-header">
        <h3 class="mpv-sheet-title">Change Template</h3>
        <button class="mpv-sheet-close" @click="showTemplateSheet = false">✕</button>
      </div>

      <!-- Loading -->
      <div v-if="templateSheetLoading" class="mpv-sheet-loading">
        <svg class="spin" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
        Loading templates…
      </div>

      <div v-else class="mpv-sheet-body">
        <!-- Warning -->
        <div class="mpv-tpl-warning">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <span>Changing the template will <strong>clear all saved report data</strong> for this inspection.</span>
        </div>

        <!-- Template list -->
        <div v-if="templateSheetList.length" class="mpv-tpl-list">
          <button
            v-for="t in templateSheetList"
            :key="t.id"
            class="mpv-tpl-item"
            :class="{ active: selectedTemplateId === t.id }"
            @click="selectedTemplateId = t.id"
          >
            <span class="mpv-tpl-name">{{ t.name }}</span>
            <svg v-if="selectedTemplateId === t.id" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          </button>
        </div>
        <p v-else class="mpv-tpl-empty">No templates available for this inspection type</p>

        <p v-if="templateSheetError" class="mpv-tpl-error">{{ templateSheetError }}</p>

        <div class="mpv-sheet-btns">
          <button class="mpv-confirm-cancel" @click="showTemplateSheet = false">Cancel</button>
          <button
            class="mpv-tpl-apply-btn"
            :disabled="templateChanging || !selectedTemplateId || selectedTemplateId === inspection?.template_id"
            @click="applyTemplateChange"
          >
            <svg v-if="!templateChanging" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            <svg v-else class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
            {{ templateChanging ? 'Applying…' : 'Apply Template' }}
          </button>
        </div>
      </div>
    </div>
  </div>

</template>

<style scoped>
.mpv-shell {
  min-height: 100vh;
  background: #0f172a;
  color: #f1f5f9;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* Nav */
.mpv-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 52px 16px 12px;
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
  position: sticky;
  top: 0;
  z-index: 10;
}
.mpv-back {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
}
.mpv-nav-title { font-size: 15px; font-weight: 700; color: #f1f5f9; }
.mpv-sync-btn {
  background: none;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px 10px;
  display: flex;
  align-items: center;
}

/* Body */
.mpv-body {
  flex: 1;
  overflow-y: auto;
  padding-bottom: 120px;
}

/* Photo */
.mpv-photo-block {
  position: relative;
  height: 220px;
  background: #1e293b;
  cursor: pointer;
  overflow: hidden;
}
.mpv-photo {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.mpv-photo-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #475569;
  font-size: 13px;
}
.mpv-photo-btn {
  position: absolute;
  bottom: 10px;
  right: 12px;
  background: rgba(0,0,0,0.6);
  color: white;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  gap: 5px;
  backdrop-filter: blur(4px);
}

/* Content */
.mpv-status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 20px 0;
}
.mpv-status-badge {
  font-size: 11px;
  font-weight: 700;
  color: white;
  padding: 3px 10px;
  border-radius: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.mpv-type-label { font-size: 13px; color: #94a3b8; font-weight: 600; }

.mpv-address {
  font-size: 20px;
  font-weight: 800;
  color: #f8fafc;
  margin: 8px 20px 16px;
  line-height: 1.2;
}

/* Details */
.mpv-details {
  padding: 0 20px;
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid #1e293b;
  border-radius: 12px;
  margin: 0 20px;
  overflow: hidden;
  background: #1e293b;
}
.mpv-detail {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #334155;
  gap: 12px;
}
.mpv-detail:last-child { border-bottom: none; }
.mpv-detail-label {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}
.mpv-detail-value { font-size: 14px; color: #e2e8f0; text-align: right; }

.mpv-sync-msg {
  margin: 12px 20px 0;
  font-size: 13px;
  color: #4ade80;
  font-weight: 600;
}
.mpv-sync-msg.error { color: #f87171; }

/* Footer */
.mpv-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 12px 20px 32px;
  background: linear-gradient(transparent, #0f172a 30%);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mpv-start-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 16px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 14px;
  font-size: 17px;
  font-weight: 800;
  cursor: pointer;
  font-family: inherit;
}
.mpv-continue-btn { background: #7c3aed; }
.mpv-finish-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 13px;
  background: #0f172a;
  color: #4ade80;
  border: 1.5px solid #16a34a;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
}
.mpv-finish-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Confirm overlay */
.mpv-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.7);
  display: flex;
  align-items: flex-end;
  z-index: 50;
}
.mpv-confirm {
  width: 100%;
  background: #1e293b;
  border-radius: 20px 20px 0 0;
  padding: 24px 20px 40px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mpv-confirm h3 { font-size: 18px; font-weight: 800; color: #f1f5f9; margin: 0; }
.mpv-confirm p  { font-size: 14px; color: #94a3b8; margin: 0; line-height: 1.5; }
.mpv-confirm-btns { display: flex; gap: 10px; margin-top: 8px; }
.mpv-confirm-cancel {
  flex: 1; padding: 14px; background: #334155; color: #94a3b8;
  border: none; border-radius: 12px; font-size: 15px; font-weight: 700; cursor: pointer; font-family: inherit;
}
.mpv-confirm-ok {
  flex: 2; padding: 14px; background: #16a34a; color: white;
  border: none; border-radius: 12px; font-size: 15px; font-weight: 800; cursor: pointer; font-family: inherit;
}

.mpv-loading {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f172a;
}
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }

/* ── Inline edit button for template row ── */
.mpv-edit-inline {
  background: none;
  border: 1px solid #334155;
  border-radius: 6px;
  color: #64748b;
  cursor: pointer;
  font-size: 13px;
  padding: 3px 8px;
  margin-left: 4px;
  flex-shrink: 0;
}
.mpv-edit-inline:active { background: #334155; color: #a5b4fc; }

/* ── Template sheet ── */
.mpv-sheet {
  width: 100%;
  max-height: 85vh;
  background: #1e293b;
  border-radius: 20px 20px 0 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.mpv-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 20px 16px;
  border-bottom: 1px solid #334155;
  flex-shrink: 0;
}
.mpv-sheet-title {
  font-size: 17px;
  font-weight: 800;
  color: #f1f5f9;
  margin: 0;
}
.mpv-sheet-close {
  background: #334155;
  border: none;
  color: #94a3b8;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mpv-sheet-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 36px;
  color: #64748b;
  font-size: 14px;
}
.mpv-sheet-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px 32px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.mpv-tpl-warning {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: rgba(245,158,11,0.08);
  border: 1px solid rgba(245,158,11,0.25);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 13px;
  color: #fcd34d;
  line-height: 1.4;
}
.mpv-tpl-warning svg { flex-shrink: 0; margin-top: 1px; }
.mpv-tpl-warning strong { color: #fbbf24; }
.mpv-tpl-list {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 12px;
  overflow: hidden;
}
.mpv-tpl-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  border-bottom: 1px solid #1e293b;
  padding: 14px 16px;
  font-size: 14px;
  color: #e2e8f0;
  cursor: pointer;
  font-family: inherit;
}
.mpv-tpl-item:last-child { border-bottom: none; }
.mpv-tpl-item.active { color: #a5b4fc; background: rgba(99,102,241,0.06); }
.mpv-tpl-item:active { background: #1e293b; }
.mpv-tpl-name { flex: 1; }
.mpv-tpl-empty { font-size: 13px; color: #64748b; text-align: center; margin: 8px 0; }
.mpv-tpl-error {
  font-size: 13px;
  color: #f87171;
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px;
  padding: 10px 14px;
  margin: 0;
}
.mpv-sheet-btns {
  display: flex;
  gap: 10px;
}
.mpv-tpl-apply-btn {
  flex: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
}
.mpv-tpl-apply-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
