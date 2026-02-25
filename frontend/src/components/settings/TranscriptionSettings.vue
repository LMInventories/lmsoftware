<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

const saving     = ref(false)
const saved      = ref(false)
const apiStatus  = ref({ openai: null, anthropic: null }) // null | 'ok' | 'missing'

const settings = ref({
  turnaroundTime: '24',
  typistNotes: '',
})

async function checkApiKeys() {
  try {
    const res = await api.get('/api/transcribe/status')
    apiStatus.value = res.data
  } catch {
    // endpoint not yet available — show neutral state
  }
}

async function saveSettings() {
  saving.value = true
  try {
    // Transcription settings stored in general settings endpoint
    await api.post('/api/settings', { transcription: settings.value })
    saved.value = true
    setTimeout(() => { saved.value = false }, 2500)
  } catch {
    alert('Failed to save settings')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  checkApiKeys()
})
</script>

<template>
  <div class="settings-section">
    <h2>Transcription Settings</h2>
    <p class="section-description">
      Configure AI and human typist settings. The AI Typist uses OpenAI Whisper for transcription
      and Claude for intelligent report filling.
    </p>

    <!-- API Key Status -->
    <div class="api-status-panel">
      <h3>AI Service Status</h3>
      <div class="api-status-grid">
        <div class="api-status-item" :class="apiStatus.openai">
          <span class="api-status-icon">
            <span v-if="apiStatus.openai === 'ok'">✅</span>
            <span v-else-if="apiStatus.openai === 'missing'">❌</span>
            <span v-else>⏳</span>
          </span>
          <div>
            <strong>OpenAI Whisper</strong>
            <p>Used for audio transcription</p>
            <p v-if="apiStatus.openai === 'missing'" class="status-error">
              Set <code>OPENAI_API_KEY</code> in Render environment variables
            </p>
          </div>
        </div>
        <div class="api-status-item" :class="apiStatus.anthropic">
          <span class="api-status-icon">
            <span v-if="apiStatus.anthropic === 'ok'">✅</span>
            <span v-else-if="apiStatus.anthropic === 'missing'">❌</span>
            <span v-else>⏳</span>
          </span>
          <div>
            <strong>Claude (Anthropic)</strong>
            <p>Used for intelligent field filling</p>
            <p v-if="apiStatus.anthropic === 'missing'" class="status-error">
              Set <code>ANTHROPIC_API_KEY</code> in Render environment variables
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- How AI Typist works -->
    <div class="info-panel">
      <h3>How AI Typist works</h3>
      <div class="info-flow">
        <div class="flow-step">
          <span class="flow-num">1</span>
          <div>
            <strong>Assign AI Typist</strong>
            <p>Select "AI Typist" when creating or editing an inspection</p>
          </div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-step">
          <span class="flow-num">2</span>
          <div>
            <strong>Clerk records audio</strong>
            <p>Per-item clips fill immediately (3–10s). Continuous recordings process at inspection end.</p>
          </div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-step">
          <span class="flow-num">3</span>
          <div>
            <strong>AI fills the report</strong>
            <p>Whisper transcribes → Claude maps to description & condition fields</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Human typist settings -->
    <div class="form-section">
      <h3>Human Typist Settings</h3>
      <div class="form-group">
        <label>Default Turnaround Time</label>
        <select v-model="settings.turnaroundTime" class="input-field">
          <option value="6">6 hours (Rush)</option>
          <option value="24">24 hours (Standard)</option>
          <option value="72">72 hours (Economy)</option>
        </select>
        <p class="helper-text">Default expected completion time for human typists</p>
      </div>

      <div class="form-group">
        <label>Default Notes for Typist</label>
        <textarea
          v-model="settings.typistNotes"
          class="textarea-field"
          rows="5"
          placeholder="Enter any standard instructions or notes for typists..."
        ></textarea>
        <p class="helper-text">These notes will be included with every inspection sent to processing</p>
      </div>

      <div class="save-row">
        <span v-if="saved" class="saved-confirmation">✅ Settings saved</span>
        <button class="btn-save" :disabled="saving" @click="saveSettings">
          {{ saving ? 'Saving…' : '💾 Save Settings' }}
        </button>
      </div>
    </div>

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

/* API Status */
.api-status-panel {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 28px;
}
.api-status-panel h3 { font-size: 15px; font-weight: 700; color: #1e293b; margin-bottom: 16px; }
.api-status-grid { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }
.api-status-item {
  display: flex; gap: 12px; align-items: flex-start;
  background: white; border: 1px solid #e2e8f0; border-radius: 8px;
  padding: 14px 18px; flex: 1; min-width: 220px;
}
.api-status-item.ok   { border-color: #bbf7d0; background: #f0fdf4; }
.api-status-item.missing { border-color: #fca5a5; background: #fef2f2; }
.api-status-icon { font-size: 20px; flex-shrink: 0; margin-top: 1px; }
.api-status-item strong { font-size: 14px; font-weight: 700; color: #1e293b; display: block; margin-bottom: 2px; }
.api-status-item p { font-size: 12px; color: #64748b; margin: 0; }
.status-error { color: #ef4444 !important; margin-top: 4px !important; }
.status-error code { background: #fef2f2; padding: 1px 5px; border-radius: 3px; font-size: 11px; }
.api-hint { font-size: 12px; color: #64748b; }
.api-hint strong { color: #374151; }

/* Info panel */
.info-panel {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 28px;
}
.info-panel h3 { font-size: 15px; font-weight: 700; color: #1e3a8a; margin-bottom: 16px; }
.info-flow { display: flex; gap: 0; align-items: flex-start; flex-wrap: wrap; }
.flow-step { display: flex; gap: 12px; flex: 1; min-width: 160px; }
.flow-num { width: 28px; height: 28px; background: #6366f1; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 13px; flex-shrink: 0; }
.flow-step strong { font-size: 13px; font-weight: 700; color: #1e3a8a; display: block; margin-bottom: 3px; }
.flow-step p { font-size: 12px; color: #3730a3; margin: 0; line-height: 1.4; }
.flow-arrow { font-size: 22px; color: #93c5fd; padding: 4px 8px; align-self: flex-start; margin-top: 2px; }

/* Form */
.form-section { max-width: 600px; }
.form-section h3 { font-size: 16px; font-weight: 700; color: #1e293b; margin-bottom: 20px; padding-top: 8px; border-top: 1px solid #e2e8f0; }
.form-group { margin-bottom: 24px; }
.form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #475569; font-size: 14px; }
.input-field, .textarea-field {
  width: 100%; padding: 10px 14px; border: 1px solid #cbd5e1; border-radius: 6px;
  font-size: 14px; font-family: inherit;
}
.input-field:focus, .textarea-field:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
.helper-text { margin-top: 6px; font-size: 12px; color: #64748b; }
.save-row { display: flex; justify-content: flex-end; align-items: center; gap: 16px; }
.saved-confirmation { font-size: 14px; font-weight: 600; color: #16a34a; }
.btn-save {
  padding: 12px 24px; background: #6366f1; color: white; border: none; border-radius: 8px;
  font-size: 15px; font-weight: 600; cursor: pointer; transition: background 0.15s;
}
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { background: #94a3b8; cursor: not-allowed; }
</style>
