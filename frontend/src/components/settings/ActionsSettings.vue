<script setup>
import { ref } from 'vue'

const actions = ref([
  { id: 1, name: 'Review', color: '#3b82f6' },
  { id: 2, name: 'Maintenance Required', color: '#f59e0b' },
  { id: 3, name: 'Cleaning Required', color: '#8b5cf6' },
  { id: 4, name: 'Missing Item', color: '#ef4444' }
])

const responsibilities = ref([
  'Tenant',
  'Landlord/Agent',
  'Investigate'
])
</script>

<template>
  <div class="settings-section">
    <h2>Actions Configuration</h2>
    <p class="section-description">
      Configure actions for Check Out inspections and condition changes. Each action can be tagged and assigned responsibility.
    </p>
    
    <div class="actions-grid">
      <div class="action-card" v-for="action in actions" :key="action.id">
        <div class="action-header">
          <div class="action-color" :style="{ backgroundColor: action.color }"></div>
          <h3>{{ action.name }}</h3>
        </div>
        <div class="action-body">
          <p class="action-label">Responsibility options:</p>
          <div class="responsibility-tags">
            <span v-for="resp in responsibilities" :key="resp" class="tag">
              {{ resp }}
            </span>
          </div>
        </div>
      </div>
    </div>
    
    <button class="btn-add" disabled>
      ➕ Add New Action
    </button>
    
    <p class="coming-soon">Full action editor coming soon...</p>
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
  margin-bottom: 32px;
}

.actions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}

.action-card {
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
}

.action-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.action-color {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  flex-shrink: 0;
}

.action-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.action-label {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 8px;
}

.responsibility-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag {
  padding: 4px 12px;
  background: #f1f5f9;
  color: #475569;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.btn-add {
  padding: 12px 24px;
  background: #e5e7eb;
  color: #94a3b8;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: not-allowed;
}

.coming-soon {
  text-align: center;
  color: #94a3b8;
  font-style: italic;
  margin-top: 32px;
}
</style>
