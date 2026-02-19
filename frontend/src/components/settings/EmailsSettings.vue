<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

const clients = ref([])
const loading = ref(true)

const emailSettings = ref({
  inspection_created: true,
  inspection_updated: true,
  inspection_completed: true,
  inspection_reminder: true
})

async function fetchClients() {
  try {
    const response = await api.getClients()
    clients.value = response.data
  } catch (error) {
    console.error('Failed to fetch clients:', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchClients()
})
</script>

<template>
  <div class="settings-section">
    <h2>Email Notifications</h2>
    <p class="section-description">
      Configure email notification settings per client. Control which notifications are sent for different inspection events.
    </p>
    
    <div class="email-settings-preview">
      <h3>Default Notification Settings</h3>
      
      <div class="notification-list">
        <div class="notification-item">
          <div class="notification-info">
            <span class="notification-icon">🆕</span>
            <div>
              <h4>Inspection Created</h4>
              <p>Sent when a new inspection is created</p>
            </div>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="emailSettings.inspection_created" disabled>
            <span class="toggle-slider"></span>
          </label>
        </div>
        
        <div class="notification-item">
          <div class="notification-info">
            <span class="notification-icon">✏️</span>
            <div>
              <h4>Inspection Updated</h4>
              <p>Sent when inspection details are changed</p>
            </div>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="emailSettings.inspection_updated" disabled>
            <span class="toggle-slider"></span>
          </label>
        </div>
        
        <div class="notification-item">
          <div class="notification-info">
            <span class="notification-icon">✅</span>
            <div>
              <h4>Inspection Completed</h4>
              <p>Sent when inspection is marked complete</p>
            </div>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="emailSettings.inspection_completed" disabled>
            <span class="toggle-slider"></span>
          </label>
        </div>
        
        <div class="notification-item">
          <div class="notification-info">
            <span class="notification-icon">⏰</span>
            <div>
              <h4>Inspection Reminder</h4>
              <p>Sent 24 hours before scheduled inspection</p>
            </div>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="emailSettings.inspection_reminder" disabled>
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
      
      <button class="btn-save" disabled>
        💾 Save Email Settings
      </button>
    </div>
    
    <p class="coming-soon">Per-client email configuration coming soon...</p>
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

.email-settings-preview {
  max-width: 700px;
}

.email-settings-preview h3 {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 20px;
}

.notification-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 32px;
}

.notification-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
}

.notification-info {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.notification-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.notification-item h4 {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.notification-item p {
  font-size: 13px;
  color: #64748b;
}

.toggle {
  position: relative;
  display: inline-block;
  width: 50px;
  height: 28px;
  flex-shrink: 0;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: not-allowed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #cbd5e1;
  transition: 0.3s;
  border-radius: 28px;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 20px;
  width: 20px;
  left: 4px;
  bottom: 4px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
}

.toggle input:checked + .toggle-slider {
  background-color: #94a3b8;
}

.toggle input:checked + .toggle-slider:before {
  transform: translateX(22px);
}

.btn-save {
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
