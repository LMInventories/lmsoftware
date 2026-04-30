<script setup>
import { ref } from 'vue'
import TemplatesSettings      from '../components/settings/TemplatesSettings.vue'
import GeneralSettings        from '../components/settings/GeneralSettings.vue'
import ReportsSettings        from '../components/settings/ReportsSettings.vue'
import ActionsSettings        from '../components/settings/ActionsSettings.vue'
import TranscriptionSettings  from '../components/settings/TranscriptionSettings.vue'
import EmailsSettings         from '../components/settings/EmailsSettings.vue'
import IntegrationsSettings   from '../components/settings/IntegrationsSettings.vue'
import FixedSectionsSettings   from './settings/FixedSectionsSettings.vue'
import MidtermSectionsSettings from './settings/MidtermSectionsSettings.vue'

const activeTab = ref(localStorage.getItem('settings_tab') || 'general')
function setTab(id) { activeTab.value = id; localStorage.setItem('settings_tab', id) }

const tabs = [
  { id: 'general',        label: 'General'        },
  { id: 'reports',        label: 'Reports'        },
  { id: 'actions',        label: 'Actions'        },
  { id: 'templates',      label: 'Templates'      },
  { id: 'fixed-sections',   label: 'Fixed Sections'   },
  { id: 'midterm-sections', label: 'Midterm Sections' },
  { id: 'transcription',    label: 'Transcription'    },
  { id: 'emails',         label: 'Emails'         },
  { id: 'integrations',   label: 'Integrations'   },
]
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>Settings</h1>
    </div>

    <div class="settings-shell">
      <!-- Tab rail -->
      <div class="tab-rail">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="tab-btn"
          :class="{ active: activeTab === tab.id }"
          @click="setTab(tab.id)"
        >
          <span class="tab-label">{{ tab.label }}</span>
        </button>
      </div>

      <!-- Content pane -->
      <div class="tab-pane">
        <GeneralSettings        v-if="activeTab === 'general'"         />
        <ReportsSettings        v-if="activeTab === 'reports'"         />
        <ActionsSettings        v-if="activeTab === 'actions'"         />
        <TemplatesSettings      v-if="activeTab === 'templates'"       />
        <FixedSectionsSettings   v-if="activeTab === 'fixed-sections'"   />
        <MidtermSectionsSettings v-if="activeTab === 'midterm-sections'" />
        <TranscriptionSettings  v-if="activeTab === 'transcription'"   />
        <EmailsSettings         v-if="activeTab === 'emails'"          />
        <IntegrationsSettings   v-if="activeTab === 'integrations'"    />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1300px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h1 {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
}

/* ── Shell ────────────────────────────────────────────────── */
.settings-shell {
  background: white;
  border-radius: 12px;
  border: 1px solid #e8ecf1;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Tab rail ─────────────────────────────────────────────── */
.tab-rail {
  display: flex;
  gap: 2px;
  padding: 8px 10px;
  border-bottom: 1px solid #f1f5f9;
  background: transparent;
  flex-wrap: wrap;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  background: transparent;
  border: none;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.tab-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.tab-btn.active {
  background: #6366f1;
  color: white;
}

.tab-icon { font-size: 14px; }

/* ── Pane ─────────────────────────────────────────────────── */
.tab-pane {
  padding: 24px 28px;
  min-height: 400px;
}

@media (max-width: 768px) {
  .tab-btn { padding: 7px 10px; font-size: 12px; }
  .tab-pane { padding: 18px; }
}
</style>
