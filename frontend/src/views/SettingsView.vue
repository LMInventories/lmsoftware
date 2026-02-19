<script setup>
import { ref } from 'vue'
import TemplatesSettings from '../components/settings/TemplatesSettings.vue'
import GeneralSettings from '../components/settings/GeneralSettings.vue'
import ReportsSettings from '../components/settings/ReportsSettings.vue'
import ActionsSettings from '../components/settings/ActionsSettings.vue'
import TranscriptionSettings from '../components/settings/TranscriptionSettings.vue'
import EmailsSettings from '../components/settings/EmailsSettings.vue'

const activeTab = ref('general')

const tabs = [
  { id: 'general', label: 'General', icon: '⚙️' },
  { id: 'reports', label: 'Reports', icon: '📄' },
  { id: 'actions', label: 'Actions', icon: '🏷️' },
  { id: 'templates', label: 'Templates', icon: '📋' },
  { id: 'transcription', label: 'Transcription', icon: '✍️' },
  { id: 'emails', label: 'Emails', icon: '📧' }
]
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>⚙️ Settings</h1>
    </div>

    <!-- Tabs Navigation -->
    <div class="tabs-container">
      <div class="tabs">
        <button 
          v-for="tab in tabs" 
          :key="tab.id"
          @click="activeTab = tab.id"
          class="tab-button"
          :class="{ active: activeTab === tab.id }"
        >
          <span class="tab-icon">{{ tab.icon }}</span>
          <span class="tab-label">{{ tab.label }}</span>
        </button>
      </div>
    </div>

    <!-- Tab Content -->
    <div class="tab-content">
      <GeneralSettings v-if="activeTab === 'general'" />
      <ReportsSettings v-if="activeTab === 'reports'" />
      <ActionsSettings v-if="activeTab === 'actions'" />
      <TemplatesSettings v-if="activeTab === 'templates'" />
      <TranscriptionSettings v-if="activeTab === 'transcription'" />
      <EmailsSettings v-if="activeTab === 'emails'" />
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1400px;
}

.page-header {
  margin-bottom: 32px;
}

.page-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
}

.tabs-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  margin-bottom: 24px;
  padding: 8px;
}

.tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.tab-button {
  flex: 1;
  min-width: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 20px;
  background: transparent;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-button:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.tab-button.active {
  background: #6366f1;
  color: white;
}

.tab-icon {
  font-size: 18px;
}

.tab-label {
  white-space: nowrap;
}

.tab-content {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  padding: 32px;
  min-height: 400px;
}

@media (max-width: 768px) {
  .tab-button {
    min-width: 100px;
    padding: 12px 16px;
    font-size: 14px;
  }
  
  .tab-icon {
    font-size: 16px;
  }
}
</style>
