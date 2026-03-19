<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const stats = ref({
  status_counts: { created: 0, assigned: 0, active: 0, processing: 0, review: 0, complete: 0 },
  totals: { clients: 0, properties: 0, users: 0, inspections: 0 },
  recent_inspections: [],
  activity: [],
  upcoming: []
})

const loading = ref(true)

const statusConfig = {
  created:    { color: '#94a3b8', bg: '#f8fafc', label: 'Created'    },
  assigned:   { color: '#3b82f6', bg: '#eff6ff', label: 'Assigned'   },
  active:     { color: '#10b981', bg: '#f0fdf4', label: 'Active'     },
  processing: { color: '#f59e0b', bg: '#fffbeb', label: 'Processing' },
  review:     { color: '#8b5cf6', bg: '#fdf4ff', label: 'Review'     },
  complete:   { color: '#10b981', bg: '#f0fdf4', label: 'Complete'   }
}

async function fetchDashboardStats() {
  loading.value = true
  try {
    const response = await api.getDashboardStats()
    const data = response.data

    const now = new Date(); now.setHours(0,0,0,0)

    const upcoming = (data.recent_inspections || [])
      .filter(i => i.conduct_date && new Date(i.conduct_date) >= now)
      .sort((a, b) => new Date(a.conduct_date) - new Date(b.conduct_date))

    const activity = data.activity || (data.recent_inspections || []).slice(0, 15).map(i => ({
      type: 'inspection',
      label: i.property_address,
      sub: i.client_name,
      time: i.updated_at || i.created_at,
      status: i.status,
      id: i.id
    }))

    stats.value = { ...data, upcoming, activity }
  } catch (error) {
    console.error('Failed to fetch dashboard stats:', error)
  } finally {
    loading.value = false
  }
}

const upcomingToday = computed(() => {
  const today = new Date(); today.setHours(0,0,0,0)
  return (stats.value.upcoming || []).filter(i => {
    const d = new Date(i.conduct_date); d.setHours(0,0,0,0)
    return d.getTime() === today.getTime()
  })
})
const upcomingTomorrow = computed(() => {
  const tom = new Date(); tom.setHours(0,0,0,0); tom.setDate(tom.getDate()+1)
  return (stats.value.upcoming || []).filter(i => {
    const d = new Date(i.conduct_date); d.setHours(0,0,0,0)
    return d.getTime() === tom.getTime()
  })
})
const upcomingNext7Days = computed(() => {
  const tom = new Date(); tom.setHours(0,0,0,0); tom.setDate(tom.getDate()+1)
  const cutoff = new Date(); cutoff.setHours(0,0,0,0); cutoff.setDate(cutoff.getDate()+8)
  return (stats.value.upcoming || []).filter(i => {
    const d = new Date(i.conduct_date); d.setHours(0,0,0,0)
    return d.getTime() > tom.getTime() && d.getTime() < cutoff.getTime()
  })
})

function activityIcon(item) {
  const m = { complete: '✅', review: '👁', processing: '✍️', active: '🔍', assigned: '👤', created: '📋' }
  return m[item.status] || '📌'
}

function activityVerb(item) {
  const m = { created: 'Created', assigned: 'Assigned', active: 'Started', processing: 'Processing', review: 'Sent for review', complete: 'Completed' }
  return m[item.status] || (item.status || 'Updated')
}

function timeAgo(dateStr) {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h/24)}d ago`
}

function typeShort(type) {
  return { check_in: 'C/I', check_out: 'C/O', inventory: 'INV', interim: 'INT' }[type] || (type || '').substring(0,3).toUpperCase()
}

function viewInspection(id) { router.push(`/inspections/${id}`) }

onMounted(fetchDashboardStats)
</script>

<template>
  <div class="dashboard">
    <div class="page-header">
      <h1>Dashboard</h1>
      <p class="subtitle">Overview &amp; activity</p>
    </div>

    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <span>Loading…</span>
    </div>

    <div v-else>
      <!-- Top layout: workflow tiles left, account stats top-right -->
      <div class="dash-top">
        <div class="dash-top-left">
          <div class="section-label">At a Glance</div>
          <!-- Status tiles -->
          <div class="status-tiles">
        <div
          v-for="(cfg, key) in statusConfig"
          :key="key"
          class="status-tile"
          @click="router.push('/inspections')"
        >
          <div class="tile-bar" :style="{ background: cfg.color }"></div>
          <div class="tile-count">{{ stats.status_counts[key] || 0 }}</div>
          <div class="tile-label">{{ cfg.label }}</div>
        </div>
          </div><!-- /status-tiles -->
        </div><!-- /dash-top-left -->

        <!-- Account stats 2x2 (admin/manager only) -->
        <div class="account-stats-wrap" v-if="authStore.isAdmin || authStore.isManager">
          <div class="stats-header">
            <span class="stats-divider"></span>
            <span class="stats-label">Account Statistics</span>
            <span class="stats-divider"></span>
          </div>
          <div class="account-stats">
          <div class="stat-card" @click="router.push('/clients')">
            <span class="stat-num">{{ stats.totals.clients }}</span>
            <span class="stat-lbl">Portfolios</span>
          </div>
          <div class="stat-card" @click="router.push('/properties')">
            <span class="stat-num">{{ stats.totals.properties }}</span>
            <span class="stat-lbl">Properties</span>
          </div>
          <div class="stat-card" @click="router.push('/users')">
            <span class="stat-num">{{ stats.totals.users }}</span>
            <span class="stat-lbl">Users</span>
          </div>
          <div class="stat-card" @click="router.push('/inspections')">
            <span class="stat-num">{{ stats.totals.inspections }}</span>
            <span class="stat-lbl">Total Inspections</span>
          </div>
          </div><!-- /account-stats -->
        </div><!-- /account-stats-wrap -->
      </div><!-- /dash-top -->

      <!-- Two-col content -->
      <div class="main-grid">

        <!-- LEFT: Activity -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">Activity</span>
            <span class="panel-meta">{{ stats.activity?.length || 0 }} recent events</span>
          </div>
          <div class="activity-feed">
            <div
              v-for="(item, i) in (stats.activity || [])"
              :key="i"
              class="activity-row"
              :class="{ clickable: !!item.id }"
              @click="item.id && viewInspection(item.id)"
            >
              <div class="activity-icon">{{ activityIcon(item) }}</div>
              <div class="activity-body">
                <div class="activity-top">
                  <span class="activity-verb">{{ activityVerb(item) }}</span>
                  <span
                    v-if="item.status"
                    class="activity-pill"
                    :style="{ background: statusConfig[item.status]?.bg, color: statusConfig[item.status]?.color }"
                  >{{ item.status }}</span>
                </div>
                <div class="activity-addr">{{ item.label }}</div>
                <div v-if="item.sub" class="activity-sub">{{ item.sub }}</div>
              </div>
              <div class="activity-time">{{ timeAgo(item.time) }}</div>
            </div>
            <div v-if="!stats.activity?.length" class="feed-empty">No recent activity.</div>
          </div>
        </div>

        <!-- RIGHT: Upcoming -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">Upcoming Inspections</span>
            <button class="panel-link" @click="router.push('/inspections')">View all →</button>
          </div>

          <div class="upcoming-scroll">

            <div class="upcoming-section">
              <div class="upcoming-heading">
                <span class="uphead-dot" style="background:#10b981"></span>Today
                <span class="uphead-count">{{ upcomingToday.length }}</span>
              </div>
              <p v-if="upcomingToday.length === 0" class="up-empty">No inspections today</p>
              <div v-for="insp in upcomingToday" :key="insp.id" class="up-card" @click="viewInspection(insp.id)">
                <div class="up-type">{{ typeShort(insp.inspection_type) }}</div>
                <div class="up-body">
                  <div class="up-addr">{{ insp.property_address }}</div>
                  <div class="up-meta">{{ insp.client_name }}<span v-if="insp.inspector_name"> · {{ insp.inspector_name }}</span></div>
                </div>
                <div class="up-dot" :style="{ background: statusConfig[insp.status]?.color }"></div>
              </div>
            </div>

            <div class="upcoming-section">
              <div class="upcoming-heading">
                <span class="uphead-dot" style="background:#3b82f6"></span>Tomorrow
                <span class="uphead-count">{{ upcomingTomorrow.length }}</span>
              </div>
              <p v-if="upcomingTomorrow.length === 0" class="up-empty">No inspections tomorrow</p>
              <div v-for="insp in upcomingTomorrow" :key="insp.id" class="up-card" @click="viewInspection(insp.id)">
                <div class="up-type">{{ typeShort(insp.inspection_type) }}</div>
                <div class="up-body">
                  <div class="up-addr">{{ insp.property_address }}</div>
                  <div class="up-meta">{{ insp.client_name }}<span v-if="insp.inspector_name"> · {{ insp.inspector_name }}</span></div>
                </div>
                <div class="up-dot" :style="{ background: statusConfig[insp.status]?.color }"></div>
              </div>
            </div>

            <div class="upcoming-section">
              <div class="upcoming-heading">
                <span class="uphead-dot" style="background:#94a3b8"></span>Next 7 Days
                <span class="uphead-count">{{ upcomingNext7Days.length }}</span>
              </div>
              <p v-if="upcomingNext7Days.length === 0" class="up-empty">Nothing in the next 7 days</p>
              <div v-for="insp in upcomingNext7Days" :key="insp.id" class="up-card beyond-card" @click="viewInspection(insp.id)">
                <div class="up-date-col">
                  <div class="up-day">{{ new Date(insp.conduct_date).getDate() }}</div>
                  <div class="up-mon">{{ new Date(insp.conduct_date).toLocaleDateString('en-GB',{month:'short'}) }}</div>
                </div>
                <div class="up-type">{{ typeShort(insp.inspection_type) }}</div>
                <div class="up-body">
                  <div class="up-addr">{{ insp.property_address }}</div>
                  <div class="up-meta">{{ insp.client_name }}<span v-if="insp.inspector_name"> · {{ insp.inspector_name }}</span></div>
                </div>
                <div class="up-dot" :style="{ background: statusConfig[insp.status]?.color }"></div>
              </div>
            </div>

          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard { max-width: 1400px; }

.page-header { margin-bottom: 18px; }
h1 { font-size: 21px; font-weight: 700; color: #0f172a; margin: 0 0 2px; }
.subtitle { font-size: 12px; color: #94a3b8; margin: 0; }

.loading-state {
  display: flex; align-items: center; gap: 10px;
  padding: 60px; justify-content: center;
  color: #94a3b8; font-size: 14px;
}
.spinner {
  width: 18px; height: 18px;
  border: 2px solid #e2e8f0; border-top-color: #6366f1;
  border-radius: 50%; animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Status tiles */
.status-tiles {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
  margin-bottom: 0;
  flex: 1;
}

.status-tile {
  background: white;
  border-radius: 9px;
  padding: 16px 14px;
  border: 1px solid #e9ecef;
  cursor: pointer;
  transition: box-shadow 0.15s, transform 0.12s;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.status-tile:hover {
  box-shadow: 0 3px 10px rgba(0,0,0,0.07);
  transform: translateY(-1px);
}

.tile-bar {
  position: absolute; top: 0; left: 0; right: 0;
  height: 3px; border-radius: 9px 9px 0 0;
}
.tile-count { font-size: 26px; font-weight: 700; color: #0f172a; line-height: 1; margin-bottom: 4px; }
.tile-label { font-size: 10px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.4px; }

/* Totals strip */

.total-chip { display: flex; align-items: baseline; gap: 6px; flex: 1; justify-content: center; }
.total-num { font-size: 18px; font-weight: 700; color: #0f172a; }
.total-txt { font-size: 11px; color: #94a3b8; }
.strip-div { width: 1px; height: 28px; background: #e9ecef; margin: 0 6px; }

/* Grid */
.main-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }

/* Panels */
.panel {
  background: white; border-radius: 11px;
  border: 1px solid #e9ecef; overflow: hidden;
  display: flex; flex-direction: column;
}

.panel-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid #f1f5f9;
  background: #fafbfc; flex-shrink: 0;
}
.panel-title { font-size: 11px; font-weight: 700; color: #374151; text-transform: uppercase; letter-spacing: 0.5px; }
.panel-meta { font-size: 11px; color: #94a3b8; }
.panel-link { font-size: 11px; color: #6366f1; font-weight: 600; background: none; border: none; cursor: pointer; padding: 0; }
.panel-link:hover { text-decoration: underline; }

/* Activity feed */
.activity-feed { flex: 1; overflow-y: auto; max-height: 500px; }

.activity-row {
  display: flex; align-items: flex-start; gap: 9px;
  padding: 9px 14px; border-bottom: 1px solid #f8fafc;
  transition: background 0.1s;
}
.activity-row.clickable { cursor: pointer; }
.activity-row.clickable:hover { background: #f8fafc; }

.activity-icon { font-size: 14px; width: 20px; flex-shrink: 0; text-align: center; margin-top: 1px; }
.activity-body { flex: 1; min-width: 0; }

.activity-top { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
.activity-verb { font-size: 12px; font-weight: 600; color: #374151; }
.activity-pill {
  font-size: 10px; font-weight: 700;
  padding: 1px 6px; border-radius: 6px;
  text-transform: capitalize;
}

.activity-addr { font-size: 11px; color: #475569; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.activity-sub { font-size: 11px; color: #94a3b8; margin-top: 1px; }
.activity-time { font-size: 10px; color: #cbd5e1; white-space: nowrap; flex-shrink: 0; padding-top: 2px; }

.feed-empty { padding: 40px 20px; text-align: center; color: #cbd5e1; font-size: 13px; }

/* Upcoming */
.dash-top { display: flex; align-items: stretch; gap: 20px; margin-bottom: 20px; }
.dash-top-left { flex: 1; display: flex; flex-direction: column; }
.section-label { font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 8px; }
.account-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.stat-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 3px; cursor: pointer; transition: box-shadow 0.12s, border-color 0.12s; min-height: 90px; }
.stat-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.07); border-color: #c7d2fe; }
.stat-num { font-size: 26px; font-weight: 700; color: #0f172a; line-height: 1; margin-bottom: 4px; }
.stat-lbl { font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.3px; }
.account-stats-wrap { min-width: 220px; display: flex; flex-direction: column; gap: 8px; }
.stats-header { display: flex; align-items: center; gap: 8px; }
.stats-label { font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.6px; white-space: nowrap; }
.stats-divider { flex: 1; height: 1px; background: #e2e8f0; }
.upcoming-scroll { flex: 1; overflow-y: auto; max-height: 500px; }

.upcoming-section { padding: 10px 14px 6px; border-bottom: 1px solid #f1f5f9; }
.upcoming-section:last-child { border-bottom: none; }

.upcoming-heading {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; font-weight: 700; color: #64748b;
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 7px;
}
.uphead-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.uphead-count {
  margin-left: auto; background: #f1f5f9; color: #64748b;
  font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 7px;
}

.up-empty { font-size: 11px; color: #cbd5e1; padding: 2px 0 8px; font-style: italic; }

.up-card {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 7px;
  cursor: pointer; transition: background 0.1s;
  margin-bottom: 4px; border: 1px solid #f1f5f9;
}
.up-card:hover { background: #f8fafc; border-color: #e2e8f0; }

.up-date-col { display: flex; flex-direction: column; align-items: center; min-width: 28px; }
.up-day { font-size: 15px; font-weight: 700; color: #0f172a; line-height: 1; }
.up-mon { font-size: 9px; color: #94a3b8; text-transform: uppercase; }

.up-type {
  font-size: 9px; font-weight: 700;
  background: #eef2ff; color: #6366f1;
  padding: 2px 6px; border-radius: 4px;
  flex-shrink: 0; letter-spacing: 0.3px;
}

.up-body { flex: 1; min-width: 0; }
.up-addr { font-size: 11px; font-weight: 600; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.up-meta { font-size: 10px; color: #94a3b8; margin-top: 1px; }

.up-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

@media (max-width: 1100px) {
  .status-tiles { grid-template-columns: repeat(3, 1fr); }
  .main-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .status-tiles { grid-template-columns: repeat(2, 1fr); }
  .totals-strip { flex-wrap: wrap; gap: 10px; }
}

/* ══════════════════════════════════════
   MOBILE  ≤ 768px
══════════════════════════════════════ */
@media (max-width: 768px) {
  /* Status tiles: 3 across (they're small enough) */
  .status-tiles {
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
  }

  .status-tile {
    padding: 10px 8px;
  }

  .tile-count {
    font-size: 22px !important;
  }

  .tile-label {
    font-size: 9px !important;
  }

  /* Totals strip: 2x2 grid */
  .totals-strip {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    flex-wrap: unset;
  }

  .total-item {
    justify-content: flex-start;
    padding: 10px 12px;
    background: white;
    border-radius: 8px;
    border: 1px solid #e2e8f0;
  }

  /* Main grid: already 1-col from 1100px breakpoint */
  .main-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  /* Panel header */
  .panel-title { font-size: 11px; }
  .panel-meta { font-size: 10px; }

  /* Activity feed: tighter rows */
  .feed-row { padding: 8px 12px; }
  .feed-action { font-size: 11px; }
  .feed-meta { font-size: 10px; }

  /* Upcoming inspection cards */
  .up-card { padding: 8px 12px; }
  .up-address { font-size: 12px; }
  .up-meta { font-size: 10px; }

  /* Page header */
  .page-header {
    flex-direction: row;
    align-items: center;
  }
}

</style>
