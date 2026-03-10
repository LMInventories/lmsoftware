<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../../services/api'

// ── State ────────────────────────────────────────────────────────────────────
const clients        = ref([])
const loading        = ref(true)
const saving         = ref(false)
const savingGlobal   = ref(false)
const testSending    = ref(false)
const testEmail      = ref('')
const testResult     = ref(null)   // { success, error }
const saveMsg        = ref('')
const activeTab      = ref('clients')  // 'clients' | 'clerk' | 'smtp'

const globalSettings = ref({
  clerk_summary_enabled: true,
  clerk_summary_time:    '18:00',
})

// Per-client prefs keyed by client id
const clientPrefs = ref({})   // { [clientId]: { inspection_created, inspection_updated, ... } }
const clientSaveMsg = ref({}) // { [clientId]: 'Saved!' }

const EVENTS = [
  { key: 'inspection_created',   icon: '🆕', label: 'Inspection Created',   desc: 'Sent when a new inspection is scheduled' },
  { key: 'inspection_updated',   icon: '✏️', label: 'Inspection Updated',    desc: 'Sent when inspection details are changed' },
  { key: 'inspection_completed', icon: '✅', label: 'Inspection Completed',  desc: 'Sent when an inspection is marked complete' },
  { key: 'inspection_reminder',  icon: '⏰', label: '24-Hour Reminder',       desc: 'Sent 24 hours before the scheduled inspection' },
]

// ── Load ─────────────────────────────────────────────────────────────────────
async function loadAll() {
  loading.value = true
  try {
    const [clientsRes, globalRes] = await Promise.all([
      api.getClients(),
      api.getEmailGlobalSettings(),
    ])
    clients.value = clientsRes.data

    if (globalRes.data) {
      globalSettings.value = { ...globalSettings.value, ...globalRes.data }
    }

    // Load per-client prefs in parallel
    const prefsResults = await Promise.all(
      clients.value.map(c => api.getClientEmailSettings(c.id).catch(() => null))
    )
    prefsResults.forEach((res, i) => {
      if (res && res.data && res.data.prefs) {
        clientPrefs.value[clients.value[i].id] = { ...res.data.prefs }
      } else {
        clientPrefs.value[clients.value[i].id] = {
          inspection_created: true, inspection_updated: true,
          inspection_completed: true, inspection_reminder: true,
        }
      }
    })
  } catch (err) {
    console.error('Failed to load email settings:', err)
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

// ── Save global ───────────────────────────────────────────────────────────────
async function saveGlobal() {
  savingGlobal.value = true
  try {
    await api.saveEmailGlobalSettings(globalSettings.value)
    saveMsg.value = '✓ Saved'
    setTimeout(() => saveMsg.value = '', 3000)
  } catch (err) {
    saveMsg.value = '✗ Failed to save'
  } finally {
    savingGlobal.value = false
  }
}

// ── Save per-client prefs ─────────────────────────────────────────────────────
async function saveClientPrefs(clientId) {
  try {
    await api.saveClientEmailSettings(clientId, clientPrefs.value[clientId])
    clientSaveMsg.value[clientId] = '✓ Saved'
    setTimeout(() => { clientSaveMsg.value[clientId] = '' }, 3000)
  } catch (err) {
    clientSaveMsg.value[clientId] = '✗ Failed'
  }
}

function toggleAll(clientId, value) {
  const prefs = clientPrefs.value[clientId]
  if (!prefs) return
  EVENTS.forEach(e => { prefs[e.key] = value })
}

function allEnabled(clientId) {
  const prefs = clientPrefs.value[clientId]
  return prefs && EVENTS.every(e => prefs[e.key])
}

// ── Test email ────────────────────────────────────────────────────────────────
async function sendTest() {
  if (!testEmail.value) return
  testSending.value = true
  testResult.value  = null
  try {
    const res = await api.sendTestEmail(testEmail.value)
    testResult.value = res.data
  } catch (err) {
    testResult.value = { success: false, error: 'Request failed' }
  } finally {
    testSending.value = false
  }
}

// ── Clerk summary manual trigger ──────────────────────────────────────────────
const triggerResult = ref(null)
const triggering    = ref(false)
async function triggerClerkSummaries() {
  triggering.value = true
  triggerResult.value = null
  try {
    const res = await api.triggerClerkSummaries()
    triggerResult.value = res.data
  } catch (err) {
    triggerResult.value = { success: false, error: 'Request failed' }
  } finally {
    triggering.value = false
  }
}
</script>

<template>
  <div class="settings-section">
    <h2>Email Notifications</h2>
    <p class="section-description">
      Configure notification emails per client, set up clerk daily work summaries, and test your email connection.
    </p>

    <!-- Tab bar -->
    <div class="tab-bar">
      <button :class="['tab-btn', activeTab === 'clients' && 'active']" @click="activeTab = 'clients'">
        👥 Client Notifications
      </button>
      <button :class="['tab-btn', activeTab === 'clerk' && 'active']" @click="activeTab = 'clerk'">
        📋 Clerk Summaries
      </button>
      <button :class="['tab-btn', activeTab === 'smtp' && 'active']" @click="activeTab = 'smtp'">
        🔧 Test Connection
      </button>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         TAB 1 — Per-client notifications
    ═══════════════════════════════════════════════════════════════ -->
    <div v-if="activeTab === 'clients'" class="tab-content">
      <div v-if="loading" class="loading-state">Loading clients…</div>

      <div v-else-if="clients.length === 0" class="empty-state">
        No clients found. Add clients first.
      </div>

      <div v-else class="client-list">
        <div v-for="client in clients" :key="client.id" class="client-card">
          <!-- Client header -->
          <div class="client-card-header">
            <div class="client-avatar">{{ client.name.charAt(0).toUpperCase() }}</div>
            <div class="client-meta">
              <h3>{{ client.name }}</h3>
              <span class="client-email-badge">{{ client.email || 'No email set' }}</span>
            </div>
            <div class="client-header-actions">
              <button
                class="toggle-all-btn"
                :class="allEnabled(client.id) ? 'all-off' : 'all-on'"
                @click="toggleAll(client.id, !allEnabled(client.id))">
                {{ allEnabled(client.id) ? 'Disable All' : 'Enable All' }}
              </button>
            </div>
          </div>

          <!-- Notification toggles -->
          <div class="notification-grid" v-if="clientPrefs[client.id]">
            <div
              v-for="event in EVENTS"
              :key="event.key"
              class="notif-row"
              :class="{ disabled: !clientPrefs[client.id][event.key] }">
              <span class="notif-icon">{{ event.icon }}</span>
              <div class="notif-text">
                <span class="notif-label">{{ event.label }}</span>
                <span class="notif-desc">{{ event.desc }}</span>
              </div>
              <label class="toggle">
                <input
                  type="checkbox"
                  v-model="clientPrefs[client.id][event.key]"
                  :disabled="!client.email" />
                <span class="toggle-slider"></span>
              </label>
            </div>
          </div>

          <div v-if="!client.email" class="no-email-warning">
            ⚠️ No email address on record — notifications cannot be sent to this client.
          </div>

          <!-- Save row -->
          <div class="card-footer">
            <span class="save-msg" :class="{ visible: clientSaveMsg[client.id] }">
              {{ clientSaveMsg[client.id] }}
            </span>
            <button
              class="btn-save-client"
              :disabled="!client.email"
              @click="saveClientPrefs(client.id)">
              Save
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         TAB 2 — Clerk daily summary
    ═══════════════════════════════════════════════════════════════ -->
    <div v-if="activeTab === 'clerk'" class="tab-content">
      <div class="settings-card">
        <h3>Daily Work Summary</h3>
        <p class="card-description">
          Each clerk receives an email at the configured time listing their inspections for the following day,
          including time, address, property details, client address, key collection/return, and any internal notes.
        </p>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Enable Daily Summaries</span>
            <span class="setting-desc">Send each clerk a schedule for the following day</span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="globalSettings.clerk_summary_enabled" />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="setting-row" :class="{ faded: !globalSettings.clerk_summary_enabled }">
          <div class="setting-info">
            <span class="setting-label">Send Time</span>
            <span class="setting-desc">Time each day to send the summary emails (UK time)</span>
          </div>
          <input
            type="time"
            class="time-input"
            v-model="globalSettings.clerk_summary_time"
            :disabled="!globalSettings.clerk_summary_enabled" />
        </div>

        <div class="info-note">
          <span>📋</span>
          <div>
            <strong>What's included:</strong> Inspection time · Property address · Bedrooms/bathrooms ·
            Client name & address · Key collect and return info · Internal notes (if any).
            Clerks with no inspections the following day will not receive an email.
          </div>
        </div>

        <div class="card-footer">
          <span class="save-msg" :class="{ visible: saveMsg }">{{ saveMsg }}</span>
          <div class="footer-btns">
            <button
              class="btn-secondary"
              :disabled="triggering"
              @click="triggerClerkSummaries"
              title="Send summaries now for testing">
              {{ triggering ? 'Sending…' : '▶ Send Now (Test)' }}
            </button>
            <button class="btn-save" :disabled="savingGlobal" @click="saveGlobal">
              {{ savingGlobal ? 'Saving…' : '💾 Save Settings' }}
            </button>
          </div>
        </div>

        <div v-if="triggerResult" class="test-result" :class="triggerResult.success ? 'success' : 'fail'">
          <span v-if="triggerResult.success">✓ Sent {{ triggerResult.sent }} summary email(s).</span>
          <span v-else>✗ {{ triggerResult.error }}</span>
          <span v-if="triggerResult.errors && triggerResult.errors.length">
            Issues: {{ triggerResult.errors.join(', ') }}
          </span>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         TAB 3 — SMTP test
    ═══════════════════════════════════════════════════════════════ -->
    <div v-if="activeTab === 'smtp'" class="tab-content">
      <div class="settings-card">
        <h3>Test Email Connection</h3>
        <p class="card-description">
          Send a test email to confirm your SMTP credentials on Render are working correctly.
        </p>

        <div class="smtp-info-box">
          <div class="smtp-row"><span class="smtp-label">From Address</span><span class="smtp-value">no-reply@lminventories.co.uk</span></div>
          <div class="smtp-row"><span class="smtp-label">SMTP Host</span><span class="smtp-value">smtp.fasthosts.co.uk</span></div>
          <div class="smtp-row"><span class="smtp-label">Port</span><span class="smtp-value">587 (STARTTLS)</span></div>
          <div class="smtp-row"><span class="smtp-label">Credentials</span><span class="smtp-value">Set via Render environment variables</span></div>
        </div>

        <div class="setting-row" style="margin-top: 20px;">
          <div class="setting-info">
            <span class="setting-label">Send test to</span>
            <span class="setting-desc">Enter any email address to receive the test</span>
          </div>
          <div class="test-input-row">
            <input
              type="email"
              class="email-input"
              v-model="testEmail"
              placeholder="you@example.com"
              @keyup.enter="sendTest" />
            <button class="btn-test" :disabled="testSending || !testEmail" @click="sendTest">
              {{ testSending ? 'Sending…' : 'Send Test' }}
            </button>
          </div>
        </div>

        <div v-if="testResult" class="test-result" :class="testResult.success ? 'success' : 'fail'">
          <span v-if="testResult.success">✓ Test email sent successfully.</span>
          <span v-else>✗ Failed: {{ testResult.error }}</span>
        </div>

        <div class="info-note" style="margin-top: 24px;">
          <span>🔑</span>
          <div>
            <strong>Required Render environment variables:</strong><br/>
            <code>SMTP_HOST</code> · <code>SMTP_PORT</code> · <code>SMTP_USER</code> ·
            <code>SMTP_PASSWORD</code> · <code>SMTP_FROM</code> · <code>SMTP_FROM_REPORTS</code>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-section h2 {
  font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 6px;
}
.section-description {
  color: #64748b; font-size: 14px; margin-bottom: 24px;
}

/* ── Tabs ── */
.tab-bar {
  display: flex; gap: 4px; margin-bottom: 24px;
  border-bottom: 2px solid #e2e8f0; padding-bottom: 0;
}
.tab-btn {
  padding: 10px 18px; background: none; border: none; border-radius: 6px 6px 0 0;
  font-size: 14px; font-weight: 600; color: #64748b; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all .15s;
}
.tab-btn:hover { color: #1e293b; background: #f8fafc; }
.tab-btn.active { color: #1e3a8a; border-bottom-color: #1e3a8a; background: none; }

/* ── Loading / empty ── */
.loading-state, .empty-state {
  padding: 48px 0; text-align: center; color: #94a3b8; font-size: 14px;
}

/* ── Client cards ── */
.client-list { display: flex; flex-direction: column; gap: 16px; max-width: 780px; }

.client-card {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden;
}

.client-card-header {
  display: flex; align-items: center; gap: 14px;
  padding: 16px 20px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;
}
.client-avatar {
  width: 38px; height: 38px; border-radius: 50%; background: #1e3a8a;
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 700; flex-shrink: 0;
}
.client-meta { flex: 1; min-width: 0; }
.client-meta h3 { font-size: 15px; font-weight: 700; color: #1e293b; margin: 0 0 3px; }
.client-email-badge {
  font-size: 12px; color: #64748b; background: #e2e8f0;
  padding: 2px 8px; border-radius: 999px;
}
.toggle-all-btn {
  font-size: 12px; font-weight: 600; padding: 5px 12px; border-radius: 6px;
  border: 1px solid; cursor: pointer; white-space: nowrap;
}
.toggle-all-btn.all-on { background: #dbeafe; color: #1e40af; border-color: #bfdbfe; }
.toggle-all-btn.all-off { background: #fee2e2; color: #b91c1c; border-color: #fecaca; }

/* ── Notification rows ── */
.notification-grid { padding: 4px 0; }
.notif-row {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 20px; border-bottom: 1px solid #f1f5f9; transition: background .15s;
}
.notif-row:last-child { border-bottom: none; }
.notif-row.disabled { opacity: .55; }
.notif-icon { font-size: 18px; flex-shrink: 0; width: 24px; text-align: center; }
.notif-text { flex: 1; min-width: 0; }
.notif-label { display: block; font-size: 14px; font-weight: 600; color: #1e293b; }
.notif-desc { display: block; font-size: 12px; color: #94a3b8; margin-top: 1px; }

/* ── Toggle switch ── */
.toggle { position: relative; display: inline-block; width: 46px; height: 26px; flex-shrink: 0; }
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
  position: absolute; cursor: pointer; inset: 0;
  background: #cbd5e1; border-radius: 26px; transition: .25s;
}
.toggle-slider:before {
  position: absolute; content: ""; height: 18px; width: 18px;
  left: 4px; bottom: 4px; background: #fff; border-radius: 50%; transition: .25s;
  box-shadow: 0 1px 3px rgba(0,0,0,.2);
}
.toggle input:checked + .toggle-slider { background: #1e3a8a; }
.toggle input:checked + .toggle-slider:before { transform: translateX(20px); }
.toggle input:disabled + .toggle-slider { cursor: not-allowed; opacity: .6; }

/* ── No email warning ── */
.no-email-warning {
  margin: 0 20px 12px; padding: 10px 14px; background: #fef3c7;
  border: 1px solid #fde68a; border-radius: 8px; font-size: 13px; color: #92400e;
}

/* ── Card footer ── */
.card-footer {
  display: flex; align-items: center; justify-content: flex-end; gap: 12px;
  padding: 12px 20px; background: #f8fafc; border-top: 1px solid #e2e8f0;
}
.save-msg {
  font-size: 13px; font-weight: 600; color: #166534;
  opacity: 0; transition: opacity .2s;
}
.save-msg.visible { opacity: 1; }

.btn-save-client {
  padding: 7px 18px; background: #1e3a8a; color: #fff;
  border: none; border-radius: 7px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: background .15s;
}
.btn-save-client:hover:not(:disabled) { background: #1e40af; }
.btn-save-client:disabled { background: #cbd5e1; cursor: not-allowed; }

/* ── Settings card (clerk / smtp tabs) ── */
.settings-card {
  max-width: 680px; background: #fff; border: 1px solid #e2e8f0;
  border-radius: 12px; overflow: hidden;
}
.settings-card h3 {
  font-size: 16px; font-weight: 700; color: #1e293b;
  padding: 18px 20px 0; margin: 0 0 6px;
}
.card-description {
  font-size: 13px; color: #64748b; padding: 0 20px 16px; border-bottom: 1px solid #f1f5f9;
  margin: 0;
}

/* ── Setting rows (clerk tab) ── */
.setting-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid #f1f5f9; gap: 16px;
  transition: opacity .2s;
}
.setting-row.faded { opacity: .45; }
.setting-info { display: flex; flex-direction: column; gap: 3px; }
.setting-label { font-size: 14px; font-weight: 600; color: #1e293b; }
.setting-desc { font-size: 12px; color: #94a3b8; }

.time-input {
  padding: 7px 12px; border: 1px solid #e2e8f0; border-radius: 7px;
  font-size: 14px; color: #1e293b; background: #fff; width: 120px;
}
.time-input:disabled { background: #f8fafc; color: #cbd5e1; }

/* ── Info note ── */
.info-note {
  display: flex; gap: 12px; align-items: flex-start;
  margin: 0 20px 4px; padding: 12px 14px; background: #f0f9ff;
  border: 1px solid #bae6fd; border-radius: 8px; font-size: 13px; color: #0369a1; line-height: 1.5;
}
.info-note span:first-child { font-size: 16px; flex-shrink: 0; }
.info-note code {
  background: #e0f2fe; padding: 1px 5px; border-radius: 4px; font-size: 12px;
}

/* ── Footer btns ── */
.footer-btns { display: flex; gap: 8px; }
.btn-secondary {
  padding: 7px 16px; background: #f1f5f9; color: #1e293b;
  border: 1px solid #e2e8f0; border-radius: 7px; font-size: 13px;
  font-weight: 600; cursor: pointer;
}
.btn-secondary:hover:not(:disabled) { background: #e2e8f0; }
.btn-secondary:disabled { opacity: .5; cursor: not-allowed; }
.btn-save {
  padding: 7px 18px; background: #1e3a8a; color: #fff;
  border: none; border-radius: 7px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: background .15s;
}
.btn-save:hover:not(:disabled) { background: #1e40af; }
.btn-save:disabled { background: #cbd5e1; cursor: not-allowed; }

/* ── SMTP tab ── */
.smtp-info-box {
  margin: 16px 20px; background: #f8fafc; border: 1px solid #e2e8f0;
  border-radius: 8px; overflow: hidden;
}
.smtp-row {
  display: flex; gap: 12px; padding: 10px 14px; border-bottom: 1px solid #f1f5f9;
  font-size: 13px;
}
.smtp-row:last-child { border-bottom: none; }
.smtp-label { color: #94a3b8; font-weight: 600; min-width: 130px; flex-shrink: 0; }
.smtp-value { color: #1e293b; font-family: monospace; }

.test-input-row { display: flex; gap: 8px; align-items: center; }
.email-input {
  padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 7px;
  font-size: 14px; width: 220px;
}
.btn-test {
  padding: 8px 16px; background: #0284c7; color: #fff;
  border: none; border-radius: 7px; font-size: 13px; font-weight: 600;
  cursor: pointer; white-space: nowrap;
}
.btn-test:hover:not(:disabled) { background: #0369a1; }
.btn-test:disabled { background: #cbd5e1; cursor: not-allowed; }

/* ── Test result ── */
.test-result {
  margin: 12px 20px; padding: 10px 14px; border-radius: 8px;
  font-size: 13px; font-weight: 600;
}
.test-result.success { background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }
.test-result.fail    { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }
</style>
