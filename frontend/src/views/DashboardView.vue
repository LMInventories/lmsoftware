<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'

const router = useRouter()

const stats = ref({
  status_counts: {
    created: 0,
    assigned: 0,
    active: 0,
    processing: 0,
    review: 0,
    complete: 0
  },
  totals: {
    clients: 0,
    properties: 0,
    users: 0,
    inspections: 0
  },
  recent_inspections: []
})

const loading = ref(true)

const statusColors = {
  created: '#94a3b8',
  assigned: '#3b82f6',
  active: '#10b981',
  processing: '#f59e0b',
  review: '#8b5cf6',
  complete: '#10b981'
}

async function fetchDashboardStats() {
  loading.value = true
  try {
    const response = await api.getDashboardStats()
    stats.value = response.data
  } catch (error) {
    console.error('Failed to fetch dashboard stats:', error)
  } finally {
    loading.value = false
  }
}

function viewInspection(id) {
  router.push(`/inspections/${id}`)
}

onMounted(() => {
  fetchDashboardStats()
})
</script>

<template>
  <div class="dashboard">
    <h1>📊 Dashboard</h1>

    <div v-if="loading" class="loading">Loading dashboard...</div>

    <div v-else>
      <!-- Status Cards -->
      <div class="stats-grid">
        <div class="stat-card created">
          <div class="stat-number">{{ stats.status_counts.created }}</div>
          <div class="stat-label">Created/Pending</div>
        </div>

        <div class="stat-card assigned">
          <div class="stat-number">{{ stats.status_counts.assigned }}</div>
          <div class="stat-label">Assigned</div>
        </div>

        <div class="stat-card active">
          <div class="stat-number">{{ stats.status_counts.active }}</div>
          <div class="stat-label">Active</div>
        </div>

        <div class="stat-card processing">
          <div class="stat-number">{{ stats.status_counts.processing }}</div>
          <div class="stat-label">Processing</div>
        </div>

        <div class="stat-card review">
          <div class="stat-number">{{ stats.status_counts.review }}</div>
          <div class="stat-label">Review</div>
        </div>

        <div class="stat-card complete">
          <div class="stat-number">{{ stats.status_counts.complete }}</div>
          <div class="stat-label">Complete</div>
        </div>
      </div>

      <!-- Totals -->
      <div class="totals-grid">
        <div class="total-card">
          <div class="total-number">{{ stats.totals.clients }}</div>
          <div class="total-label">Total Clients</div>
        </div>

        <div class="total-card">
          <div class="total-number">{{ stats.totals.properties }}</div>
          <div class="total-label">Total Properties</div>
        </div>

        <div class="total-card">
          <div class="total-number">{{ stats.totals.users }}</div>
          <div class="total-label">Total Users</div>
        </div>

        <div class="total-card">
          <div class="total-number">{{ stats.totals.inspections }}</div>
          <div class="total-label">Total Inspections</div>
        </div>
      </div>

      <!-- Recent Inspections -->
      <div class="recent-section">
        <h2>Recent Inspections</h2>
        
        <div v-if="stats.recent_inspections.length === 0" class="empty-state">
          No inspections yet. Create your first inspection to get started!
        </div>

        <div v-else class="inspections-list">
          <div 
            v-for="inspection in stats.recent_inspections" 
            :key="inspection.id" 
            class="inspection-card"
            @click="viewInspection(inspection.id)"
          >
            <div class="inspection-header">
              <div>
                <h3>{{ inspection.property_address }}</h3>
                <p class="inspection-client">{{ inspection.client_name }}</p>
              </div>
              <span 
                class="status-badge" 
                :style="{ backgroundColor: statusColors[inspection.status] }"
              >
                {{ inspection.status }}
              </span>
            </div>
            <div class="inspection-meta">
              <span class="inspection-type">{{ inspection.inspection_type.replace('_', ' ').toUpperCase() }}</span>
              <span v-if="inspection.conduct_date" class="inspection-date">
                📅 {{ new Date(inspection.conduct_date).toLocaleDateString('en-GB') }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 1400px;
}

h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 32px;
}

.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
}

/* Status Cards */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 20px;
  margin-bottom: 32px;
}

.stat-card {
  background: white;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  border-left: 4px solid;
}

.stat-card.created {
  border-left-color: #94a3b8;
}

.stat-card.assigned {
  border-left-color: #3b82f6;
}

.stat-card.active {
  border-left-color: #10b981;
}

.stat-card.processing {
  border-left-color: #f59e0b;
}

.stat-card.review {
  border-left-color: #8b5cf6;
}

.stat-card.complete {
  border-left-color: #10b981;
}

.stat-number {
  font-size: 48px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Totals */
.totals-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 20px;
  margin-bottom: 40px;
}

.total-card {
  background: white;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  border-left: 4px solid #6366f1;
}

.total-number {
  font-size: 36px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 8px;
}

.total-label {
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
}

/* Recent Inspections */
.recent-section {
  background: white;
  padding: 32px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.recent-section h2 {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 24px;
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: #64748b;
}

.inspections-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.inspection-card {
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.inspection-card:hover {
  border-color: #6366f1;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
}

.inspection-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.inspection-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.inspection-client {
  font-size: 13px;
  color: #6366f1;
  font-weight: 600;
}

.status-badge {
  padding: 4px 12px;
  color: white;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.inspection-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #64748b;
}

.inspection-type {
  font-weight: 600;
}

.inspection-date {
  font-weight: 500;
}
</style>
