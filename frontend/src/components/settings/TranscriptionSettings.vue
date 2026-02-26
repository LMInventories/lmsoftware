<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

const saving      = ref(false)
const saved       = ref(false)
const apiStatus   = ref({ openai: null, anthropic: null })
const usage       = ref(null)
const usagePeriod = ref(30)
const usageLoading = ref(false)

const settings = ref({
  turnaroundTime: '24',
  typistNotes: '',
})

async function checkApiKeys() {
  try {
    const res = await api.getTranscribeStatus()
    apiStatus.value = res.data
  } catch {}
}

async function loadUsage() {
  usageLoading.value = true
  try {
    const res = await api.getTranscribeUsage(usagePeriod.value)
    usage.value = res.data
  } catch {}
  finally { usageLoading.value = false }
}

async function saveSettings() {
  saving.value = true
  try {
    await api.post('/api/settings', { transcription: settings.value })
    saved.value = true
    setTimeout(() => { saved.value = false }, 2500)
  } catch { alert('Failed to save settings') }
  finally { saving.value = false }
}

function formatGBP(val) {
  if (val === undefined || val === null) return '£0.00'
  if (val < 0.01) return `£${val.toFixed(4)}`
  return `£${val.toFixed(2)}`
}

onMounted(() => { checkApiKeys(); loadUsage() })
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
          <div class="api-status-body">
            <strong>OpenAI Whisper</strong>
            <p>Audio transcription</p>
            <p v-if="apiStatus.openai === 'missing'" class="status-error">
              Set <code>OPENAI_API_KEY</code> in Render environment variables
            </p>
          </div>
          <a href="https://platform.openai.com/usage" target="_blank" rel="noopener" class="billing-btn">View Billing ↗</a>
        </div>
        <div class="api-status-item" :class="apiStatus.anthropic">
          <span class="api-status-icon">
            <span v-if="apiStatus.anthropic === 'ok'">✅</span>
            <span v-else-if="apiStatus.anthropic === 'missing'">❌</span>
            <span v-else>⏳</span>
          </span>
          <div class="api-status-body">
            <strong>Claude (Anthropic)</strong>
            <p>Intelligent field filling</p>
            <p v-if="apiStatus.anthropic === 'missing'" class="status-error">
              Set <code>ANTHROPIC_API_KEY</code> in Render environment variables
            </p>
          </div>
          <a href="https://console.anthropic.com/settings/billing" target="_blank" rel="noopener" class="billing-btn">View Billing ↗</a>
        </div>
      </div>
      <p class="api-hint">API keys are configured in <strong>Render → Your Service → Environment</strong> and are never exposed to the browser.</p>
    </div>

    <!-- Usage & Cost Tracker -->
    <div class="usage-panel">
      <div class="usage-header">
        <h3>Usage &amp; Cost Estimate</h3>
        <div class="usage-period">
          <label>Period:</label>
          <select v-model="usagePeriod" @change="loadUsage" class="period-select">
            <option :value="7">Last 7 days</option>
            <option :value="30">Last 30 days</option>
            <option :value="90">Last 90 days</option>
            <option :value="365">Last 12 months</option>
          </select>
        </div>
      </div>

      <div v-if="usageLoading" class="usage-loading">Loading usage data…</div>

      <div v-else-if="usage">
        <div class="cost-cards">
          <div class="cost-card total">
            <span class="cost-label">Total Cost</span>
            <span class="cost-value">{{ formatGBP(usage.total_cost_gbp) }}</span>
            <span class="cost-sub">{{ usage.total_calls }} calls · {{ usage.audio_minutes }} mins audio</span>
          </div>
          <div class="cost-card whisper">
            <span class="cost-label">OpenAI Whisper</span>
            <span class="cost-value">{{ formatGBP(usage.whisper_cost_gbp) }}</span>
            <span class="cost-sub">{{ usage.audio_minutes }} mins transcribed</span>
          </div>
          <div class="cost-card claude">
            <span class="cost-label">Claude Haiku</span>
            <span class="cost-value">{{ formatGBP(usage.claude_cost_gbp) }}</span>
            <span class="cost-sub">{{ usage.item_calls }} item · {{ usage.full_calls }} full calls</span>
          </div>
        </div>

        <p class="usage-disclaimer">
          ⚠️ Estimates only. Whisper at $0.006/min, Claude Haiku at $0.80/$4.00 per 1M tokens, converted at £1 = $1.27. Verify actual charges in your provider billing dashboards above.
        </p>

        <div v-if="usage.recent && usage.recent.length" class="recent-calls">
          <h4>Recent Calls</h4>
          <table class="usage-table">
            <thead>
              <tr><th>Date</th><th>Type</th><th>Section</th><th>Audio</th><th>Est. Cost</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in usage.recent" :key="row.id">
                <td>{{ new Date(row.created_at).toLocaleDateString('en-GB') }}</td>
                <td><span class="call-badge" :class="row.call_type">{{ row.call_type }}</span></td>
                <td>{{ row.section_type }}</td>
                <td>{{ Math.round(row.audio_seconds) }}s</td>
                <td class="cost-cell">{{ formatGBP(row.cost_gbp) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="usage-empty">No transcription calls recorded in this period yet.</div>
      </div>

      <div v-else class="usage-empty">Usage tracking not available — deploy the latest backend to enable it.</div>
    </div>

    <!-- How AI Typist works -->
    <div class="info-panel">
      <h3>How AI Typist works</h3>
      <div class="info-flow">
        <div class="flow-step">
          <span class="flow-num">1</span>
          <div><strong>Assign AI Typist</strong><p>Select "AI Typist" when creating or editing an inspection</p></div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-step">
          <span class="flow-num">2</span>
          <div><strong>Clerk records audio</strong><p>Per-item clips fill immediately. Continuous recordings process at inspection end.</p></div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-step">
          <span class="flow-num">3</span>
          <div><strong>AI fills the report</strong><p>Whisper transcribes → Claude maps to description &amp; condition fields</p></div>
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
        <textarea v-model="settings.typistNotes" class="textarea-field" rows="5" placeholder="Enter any standard instructions or notes for typists..."></textarea>
        <p class="helper-text">These notes will be included with every inspection sent to processing</p>
      </div>
      <div class="save-row">
        <span v-if="saved" class="saved-confirmation">✅ Settings saved</span>
        <button class="btn-save" :disabled="saving" @click="saveSettings">{{ saving ? 'Saving…' : '💾 Save Settings' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-section h2 { font-size: 24px; font-weight: 600; color: #1e293b; margin-bottom: 8px; }
.section-description { color: #64748b; font-size: 15px; margin-bottom: 32px; }

.api-status-panel { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px 24px; margin-bottom: 28px; }
.api-status-panel h3 { font-size: 15px; font-weight: 700; color: #1e293b; margin-bottom: 16px; }
.api-status-grid { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }
.api-status-item { display: flex; gap: 12px; align-items: center; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; flex: 1; min-width: 220px; }
.api-status-item.ok      { border-color: #bbf7d0; background: #f0fdf4; }
.api-status-item.missing { border-color: #fca5a5; background: #fef2f2; }
.api-status-icon { font-size: 20px; flex-shrink: 0; }
.api-status-body { flex: 1; }
.api-status-body strong { font-size: 14px; font-weight: 700; color: #1e293b; display: block; margin-bottom: 2px; }
.api-status-body p { font-size: 12px; color: #64748b; margin: 0; }
.status-error { color: #ef4444 !important; margin-top: 4px !important; }
.status-error code { background: #fef2f2; padding: 1px 5px; border-radius: 3px; font-size: 11px; }
.billing-btn { flex-shrink: 0; padding: 6px 12px; background: #6366f1; color: white; border-radius: 6px; font-size: 12px; font-weight: 600; text-decoration: none; white-space: nowrap; transition: background 0.15s; }
.billing-btn:hover { background: #4f46e5; }
.api-hint { font-size: 12px; color: #64748b; }
.api-hint strong { color: #374151; }

.usage-panel { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px 24px; margin-bottom: 28px; }
.usage-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
.usage-header h3 { font-size: 15px; font-weight: 700; color: #1e293b; margin: 0; }
.usage-period { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #64748b; }
.period-select { padding: 5px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 13px; background: white; cursor: pointer; }
.usage-loading { color: #64748b; font-size: 14px; padding: 20px 0; text-align: center; }
.usage-empty { color: #94a3b8; font-size: 13px; padding: 16px 0; text-align: center; }

.cost-cards { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.cost-card { flex: 1; min-width: 160px; border-radius: 8px; padding: 16px 20px; display: flex; flex-direction: column; gap: 4px; }
.cost-card.total   { background: #1e293b; }
.cost-card.whisper { background: #eff6ff; border: 1px solid #bfdbfe; }
.cost-card.claude  { background: #faf5ff; border: 1px solid #e9d5ff; }
.cost-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; }
.cost-card.total .cost-label { color: rgba(255,255,255,0.6); }
.cost-value { font-size: 28px; font-weight: 800; line-height: 1.1; color: #1e293b; }
.cost-card.total   .cost-value { color: white; }
.cost-card.whisper .cost-value { color: #1d4ed8; }
.cost-card.claude  .cost-value { color: #7c3aed; }
.cost-sub { font-size: 11px; color: #64748b; }
.cost-card.total .cost-sub { color: rgba(255,255,255,0.5); }
.usage-disclaimer { font-size: 11px; color: #94a3b8; margin-bottom: 20px; line-height: 1.5; }

.recent-calls h4 { font-size: 13px; font-weight: 700; color: #374151; margin-bottom: 10px; }
.usage-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.usage-table th { text-align: left; padding: 8px 10px; border-bottom: 2px solid #e2e8f0; color: #64748b; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
.usage-table td { padding: 8px 10px; border-bottom: 1px solid #f1f5f9; color: #374151; }
.usage-table tr:last-child td { border-bottom: none; }
.call-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.call-badge.item { background: #dbeafe; color: #1d4ed8; }
.call-badge.full { background: #ede9fe; color: #7c3aed; }
.cost-cell { font-weight: 600; color: #1e293b; }

.info-panel { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 20px 24px; margin-bottom: 28px; }
.info-panel h3 { font-size: 15px; font-weight: 700; color: #1e3a8a; margin-bottom: 16px; }
.info-flow { display: flex; gap: 0; align-items: flex-start; flex-wrap: wrap; }
.flow-step { display: flex; gap: 12px; flex: 1; min-width: 160px; }
.flow-num { width: 28px; height: 28px; background: #6366f1; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 13px; flex-shrink: 0; }
.flow-step strong { font-size: 13px; font-weight: 700; color: #1e3a8a; display: block; margin-bottom: 3px; }
.flow-step p { font-size: 12px; color: #3730a3; margin: 0; line-height: 1.4; }
.flow-arrow { font-size: 22px; color: #93c5fd; padding: 4px 8px; align-self: flex-start; margin-top: 2px; }

.form-section { max-width: 600px; }
.form-section h3 { font-size: 16px; font-weight: 700; color: #1e293b; margin-bottom: 20px; padding-top: 8px; border-top: 1px solid #e2e8f0; }
.form-group { margin-bottom: 24px; }
.form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #475569; font-size: 14px; }
.input-field, .textarea-field { width: 100%; padding: 10px 14px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; font-family: inherit; }
.input-field:focus, .textarea-field:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
.helper-text { margin-top: 6px; font-size: 12px; color: #64748b; }
.save-row { display: flex; justify-content: flex-end; align-items: center; gap: 16px; }
.saved-confirmation { font-size: 14px; font-weight: 600; color: #16a34a; }
.btn-save { padding: 12px 24px; background: #6366f1; color: white; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { background: #94a3b8; cursor: not-allowed; }
</style>
