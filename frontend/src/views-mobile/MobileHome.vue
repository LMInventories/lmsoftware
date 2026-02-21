<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Network } from '@capacitor/network'
import api from '../services/api'
import {
  getAllInspections,
  saveInspection,
  getReportData,
  deleteInspection,
} from '../services/offline'
import { syncAll } from '../services/sync'

const router = useRouter()

const localInspections = ref([])
const fetching         = ref(false)
const syncing          = ref(false)
const isOnline         = ref(true)
const syncMessage      = ref('')
const fetchError       = ref('')

// Track which user is logged in for "my inspections" filtering
const currentUser = ref(null)

onMounted(async () => {
  await checkNetwork()
  await loadLocal()
  try {
    const res = await api.getCurrentUser()
    currentUser.value = res.data
  } catch { /* offline, fine */ }
})

async function checkNetwork() {
  const status = await Network.getStatus()
  isOnline.value = status.connected
  Network.addListener('networkStatusChange', s => { isOnline.value = s.connected })
}

async function loadLocal() {
  localInspections.value = await getAllInspections()
}

// ── Fetch assigned inspections from server ────────────────────────────
async function fetchInspections() {
  if (!isOnline.value) {
    fetchError.value = 'No internet connection'
    return
  }
  fetching.value   = true
  fetchError.value = ''

  try {
    const res  = await api.getInspections()
    const all  = res.data || []

    // Filter to inspections assigned to the current user (clerk or typist)
    const mine = currentUser.value
      ? all.filter(i =>
          i.inspector_id === currentUser.value.id ||
          i.typist_id    === currentUser.value.id
        )
      : all

    // Save each to local DB
    for (const insp of mine) {
      await saveInspection(insp)
    }

    await loadLocal()
  } catch (err) {
    fetchError.value = `Fetch failed: ${err.message}`
  } finally {
    fetching.value = false
  }
}

// ── Sync all dirty inspections ────────────────────────────────────────
async function syncAllInspections() {
  if (!isOnline.value) { syncMessage.value = 'No connection — sync when back online'; return }
  syncing.value    = true
  syncMessage.value = 'Syncing…'

  const results = await syncAll((step, msg) => { syncMessage.value = msg })

  const ok   = results.filter(r => r.success).length
  const fail = results.filter(r => !r.success).length
  syncMessage.value = fail === 0
    ? `✓ ${ok} inspection(s) synced`
    : `${ok} synced, ${fail} failed`

  await loadLocal()
  syncing.value = false
  setTimeout(() => { syncMessage.value = '' }, 4000)
}

// ── Remove inspection from device ─────────────────────────────────────
async function removeLocal(id) {
  if (!confirm('Remove this inspection from device?')) return
  await deleteInspection(id)
  await loadLocal()
}

// ── Computed ──────────────────────────────────────────────────────────
const dirtyCount = computed(() => localInspections.value.filter(i => i._is_dirty).length)

const typeLabel = (t) => ({
  check_in:  'Check In',
  check_out: 'Check Out',
  interim:   'Interim',
  inventory: 'Inventory',
}[t] || t)

const statusColour = (s) => ({
  scheduled:  '#3b82f6',
  active:     '#8b5cf6',
  processing: '#f59e0b',
  review:     '#06b6d4',
  complete:   '#22c55e',
}[s] || '#94a3b8')

function fmtDate(d) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}
</script>

<template>
  <div class="mh-shell">

    <!-- Header -->
    <header class="mh-header">
      <div class="mh-header-top">
        <h1 class="mh-title">My Inspections</h1>
        <div class="mh-online-pill" :class="isOnline ? 'online' : 'offline'">
          <span class="mh-online-dot"></span>
          {{ isOnline ? 'Online' : 'Offline' }}
        </div>
      </div>

      <div class="mh-actions">
        <button
          class="mh-btn mh-btn-fetch"
          :disabled="fetching || !isOnline"
          @click="fetchInspections"
        >
          <svg v-if="!fetching" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <svg v-else class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          {{ fetching ? 'Fetching…' : 'Fetch Inspections' }}
        </button>

        <button
          v-if="dirtyCount > 0"
          class="mh-btn mh-btn-sync"
          :disabled="syncing || !isOnline"
          @click="syncAllInspections"
        >
          <svg v-if="!syncing" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          <svg v-else class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          Sync {{ dirtyCount }} unsaved
        </button>
      </div>

      <p v-if="fetchError" class="mh-error">{{ fetchError }}</p>
      <p v-if="syncMessage" class="mh-sync-msg">{{ syncMessage }}</p>
    </header>

    <!-- List -->
    <div class="mh-list">
      <div v-if="localInspections.length === 0" class="mh-empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="1"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
        <p>No inspections on device</p>
        <p class="mh-empty-hint">Tap "Fetch Inspections" to download your assigned work</p>
      </div>

      <div
        v-for="insp in localInspections"
        :key="insp.id"
        class="mh-card"
        @click="router.push(`/mobile/inspection/${insp.id}`)"
      >
        <div class="mh-card-top">
          <div class="mh-card-type-wrap">
            <span class="mh-card-type" :style="{ background: statusColour(insp.status) }">
              {{ typeLabel(insp.inspection_type) }}
            </span>
            <span v-if="insp._is_dirty" class="mh-dirty-badge">● Unsynced</span>
          </div>
          <button class="mh-remove-btn" @click.stop="removeLocal(insp.id)" title="Remove from device">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
          </button>
        </div>
        <p class="mh-card-addr">{{ insp.property_address }}</p>
        <div class="mh-card-meta">
          <span>{{ fmtDate(insp.conduct_date) }}</span>
          <span v-if="insp.inspector_name">· {{ insp.inspector_name }}</span>
          <span class="mh-card-status" :style="{ color: statusColour(insp.status) }">
            · {{ insp.status }}
          </span>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.mh-shell {
  min-height: 100vh;
  background: #0f172a;
  color: #f1f5f9;
  display: flex;
  flex-direction: column;
}

/* Header */
.mh-header {
  padding: 56px 20px 20px;
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mh-header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mh-title {
  font-size: 22px;
  font-weight: 800;
  color: #f8fafc;
  margin: 0;
}
.mh-online-pill {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 20px;
  border: 1px solid;
}
.mh-online-pill.online  { color: #4ade80; border-color: #166534; background: #052e16; }
.mh-online-pill.offline { color: #f87171; border-color: #7f1d1d; background: #1c0a0a; }
.mh-online-dot {
  width: 6px; height: 6px; border-radius: 50%; background: currentColor;
}

.mh-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.mh-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 10px 18px;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s;
  font-family: inherit;
}
.mh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.mh-btn-fetch { background: #6366f1; color: white; }
.mh-btn-sync  { background: #0ea5e9; color: white; }

.mh-error    { font-size: 13px; color: #f87171; margin: 0; }
.mh-sync-msg { font-size: 13px; color: #4ade80; margin: 0; }

/* List */
.mh-list {
  flex: 1;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}
.mh-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  text-align: center;
  color: #64748b;
}
.mh-empty p { margin: 0; font-size: 14px; }
.mh-empty-hint { font-size: 12px; color: #475569; }

.mh-card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 14px 16px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.mh-card:active { background: #273549; border-color: #6366f1; }

.mh-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mh-card-type-wrap { display: flex; align-items: center; gap: 8px; }
.mh-card-type {
  font-size: 11px;
  font-weight: 700;
  color: white;
  padding: 2px 9px;
  border-radius: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.mh-dirty-badge {
  font-size: 11px;
  font-weight: 600;
  color: #f59e0b;
}

.mh-remove-btn {
  background: none;
  border: none;
  color: #475569;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
}
.mh-remove-btn:active { background: #334155; color: #f87171; }

.mh-card-addr {
  font-size: 15px;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0;
  line-height: 1.3;
}
.mh-card-meta {
  font-size: 12px;
  color: #64748b;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.mh-card-status { font-weight: 600; }

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }
</style>
