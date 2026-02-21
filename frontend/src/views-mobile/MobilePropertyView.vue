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
</style>
