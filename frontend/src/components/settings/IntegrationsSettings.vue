<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

const connectingId = ref(null)
const comingSoonModal = ref(false)
const comingSoonName  = ref('')

// ── The Depositary config panel ───────────────────────────────────────────────
const showDepositaryPanel = ref(false)
const depositary = ref({ api_url: '', api_key: '' })
const depositorySaving = ref(false)
const depositorySaved  = ref(false)
const depositaryStatus = ref(null)  // null | 'configured' | 'not_configured'

async function loadDepositarySettings() {
  try {
    const res = await api.getSystemSettings()
    const s   = res.data || {}
    depositary.value.api_url = s.depositary_api_url || ''
    depositary.value.api_key = s.depositary_api_key || ''
    depositaryStatus.value   = (s.depositary_api_url && s.depositary_api_key) ? 'configured' : 'not_configured'
  } catch (e) {
    console.error('Failed to load Depositary settings:', e)
  }
}

async function saveDepositarySettings() {
  depositorySaving.value = true
  try {
    await api.updateSystemSettings({
      depositary_api_url: depositary.value.api_url,
      depositary_api_key: depositary.value.api_key,
    })
    depositaryStatus.value = (depositary.value.api_url && depositary.value.api_key) ? 'configured' : 'not_configured'
    depositorySaved.value  = true
    setTimeout(() => depositorySaved.value = false, 2500)
  } catch (e) {
    alert('Failed to save — please try again.')
  } finally {
    depositorySaving.value = false
  }
}

// ── Google OAuth ──────────────────────────────────────────────────────────────
// Status shared by Drive, Calendar, and Sheets cards
const googleStatus = ref({
  connected:    false,
  email:        '',
  has_drive:    false,
  has_calendar: false,
  has_sheets:   false,
})
const googleDisconnecting = ref(false)

// ── Google Sheets — Master Sheet config ───────────────────────────────────────
const showSheetsPanel  = ref(false)
const masterSheetId    = ref('')
const sheetsSaving     = ref(false)
const sheetsSaved      = ref(false)
const sheetsTestMsg    = ref('')
const sheetsTesting    = ref(false)

async function loadSheetsSettings() {
  try {
    const res = await api.getSystemSettings()
    masterSheetId.value = (res.data || {}).google_master_sheet_id || ''
  } catch (e) {
    console.error('Failed to load Sheets settings:', e)
  }
}

async function saveSheetsSettings() {
  sheetsSaving.value = true
  try {
    await api.updateSystemSettings({ google_master_sheet_id: masterSheetId.value.trim() })
    sheetsSaved.value = true
    setTimeout(() => sheetsSaved.value = false, 2500)
  } catch (e) {
    alert('Failed to save — please try again.')
  } finally {
    sheetsSaving.value = false
  }
}

async function loadGoogleStatus() {
  try {
    const res = await api.http.get('/api/google/status')
    googleStatus.value = res.data
  } catch (e) {
    // Not connected yet — keep defaults
  }
}

function connectGoogle() {
  // Redirect the browser to the backend OAuth start — it will redirect to
  // Google's consent screen and eventually back to
  // /settings?tab=integrations&google=connected
  const base = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
  window.location.href = `${base}/api/google/auth`
}

async function disconnectGoogle() {
  if (!confirm('Disconnect Google? Drive uploads and Calendar sync will stop.')) return
  googleDisconnecting.value = true
  try {
    await api.http.delete('/api/google/disconnect')
    googleStatus.value = { connected: false, email: '', has_drive: false, has_calendar: false }
  } catch (e) {
    alert('Failed to disconnect — please try again.')
  } finally {
    googleDisconnecting.value = false
  }
}

onMounted(async () => {
  await loadDepositarySettings()
  await loadGoogleStatus()
  await loadSheetsSettings()

  // Handle redirect-back from Google OAuth
  const params = new URLSearchParams(window.location.search)
  const googleResult = params.get('google')
  if (googleResult === 'connected') {
    await loadGoogleStatus()
    // Clean up the URL
    const clean = window.location.pathname + '?tab=integrations'
    window.history.replaceState({}, '', clean)
  } else if (googleResult === 'error') {
    alert('Google authorisation failed — please try again.')
    const clean = window.location.pathname + '?tab=integrations'
    window.history.replaceState({}, '', clean)
  }
})

// ── Integration catalogue ─────────────────────────────────────────────────────
// status: 'available' | 'configured' | 'coming_soon'
const integrations = [
  // ─ Deposit Management ─────────────────────────────────────────────────────
  {
    id: 'depositary',
    category: 'Deposit Management',
    name: 'The Depositary',
    logoText: 'TD',
    description: 'Automatically push completed Check Out reports to The Depositary. Tenant details, dilapidations, and the PDF report are sent the moment the inspection is marked complete — no manual data entry.',
    color: '#0f766e',
    status: 'available',
    badge: 'UK Deposit Platform',
    benefit: 'Saves ~3–4 hours per checkout',
    configurable: true,
  },

  // ─ Calendars ──────────────────────────────────────────────────────────────
  {
    id: 'google_calendar',
    category: 'Calendars',
    name: 'Google Calendar',
    logo: 'https://cdn.simpleicons.org/googlecalendar',
    description: 'Sync inspection schedules directly with Google Calendar. Clerks see their day\'s jobs, managers see team availability, and clients can be sent calendar invites automatically.',
    color: '#4285F4',
    status: 'available',
    badge: 'Free',
    benefit: 'Saves ~15 min/day per clerk',
    googleOAuth: true,
    scopeKey: 'has_calendar',
  },
  {
    id: 'outlook_calendar',
    category: 'Calendars',
    name: 'Microsoft Outlook / 365',
    logo: 'https://cdn.simpleicons.org/microsoftoutlook',
    description: 'Sync with Outlook calendars and Microsoft Teams. Ideal for agencies already on the Microsoft ecosystem.',
    color: '#0078D4',
    status: 'coming_soon',
    badge: 'Free',
  },
  {
    id: 'apple_calendar',
    category: 'Calendars',
    name: 'Apple Calendar',
    logo: 'https://cdn.simpleicons.org/applecalendar',
    description: 'Push inspection appointments to iCloud Calendar via CalDAV. Useful for clerks on iPhone.',
    color: '#FF3B30',
    status: 'coming_soon',
    badge: 'Free',
  },

  // ─ Property Management ────────────────────────────────────────────────────
  {
    id: 'arthur_online',
    category: 'Property Management',
    name: 'Arthur Online',
    logoText: 'AO',
    description: 'Import properties and tenancies from Arthur Online. Automatically create inspections when check-in / check-out events are triggered.',
    color: '#1A56DB',
    status: 'coming_soon',
    badge: 'Popular UK',
  },
  {
    id: 'fixflo',
    category: 'Property Management',
    name: 'Fixflo',
    logoText: 'Ff',
    description: 'Link inspection findings directly to Fixflo repair requests. Flag items as defects and raise jobs without leaving InspectPro.',
    color: '#F97316',
    status: 'coming_soon',
    badge: 'Popular UK',
  },
  {
    id: 'goodlord',
    category: 'Property Management',
    name: 'Goodlord',
    logoText: 'GL',
    description: 'Pull tenancy data and trigger check-in / check-out inspections at the right point in the tenancy lifecycle.',
    color: '#7C3AED',
    status: 'coming_soon',
  },

  // ─ Communication ─────────────────────────────────────────────────────────
  {
    id: 'slack',
    category: 'Communication',
    name: 'Slack',
    logo: 'https://cdn.simpleicons.org/slack',
    description: 'Post notifications to Slack channels when inspections are completed, reports are ready, or urgent defects are flagged.',
    color: '#4A154B',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'ms_teams',
    category: 'Communication',
    name: 'Microsoft Teams',
    logo: 'https://cdn.simpleicons.org/microsoftteams',
    description: 'Send inspection status updates to Teams channels. Ideal for letting agencies already using Microsoft 365.',
    color: '#6264A7',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'whatsapp',
    category: 'Communication',
    name: 'WhatsApp Business',
    logo: 'https://cdn.simpleicons.org/whatsapp',
    description: 'Send automated appointment reminders and report-ready notifications to clients and tenants via WhatsApp.',
    color: '#25D366',
    status: 'coming_soon',
  },

  // ─ Finance ───────────────────────────────────────────────────────────────
  {
    id: 'xero',
    category: 'Finance',
    name: 'Xero',
    logo: 'https://cdn.simpleicons.org/xero',
    description: 'Automatically raise invoices in Xero when an inspection report is marked complete. Track revenue per client and clerk.',
    color: '#13B5EA',
    status: 'coming_soon',
    badge: 'Popular UK',
  },
  {
    id: 'stripe',
    category: 'Finance',
    name: 'Stripe',
    logo: 'https://cdn.simpleicons.org/stripe',
    description: 'Collect payments for inspection reports online. Useful if you offer a pay-per-report model or want to bill clients directly.',
    color: '#635BFF',
    status: 'coming_soon',
    badge: 'Free to set up',
  },
  {
    id: 'quickbooks',
    category: 'Finance',
    name: 'QuickBooks',
    logo: 'https://cdn.simpleicons.org/quickbooks',
    description: 'Sync completed inspections to QuickBooks as invoices or billable items.',
    color: '#2CA01C',
    status: 'coming_soon',
  },

  // ─ Document Management ────────────────────────────────────────────────────
  {
    id: 'google_sheets',
    category: 'Document Management',
    name: 'Google Sheets — Master Sheet',
    logo: 'https://cdn.simpleicons.org/googlesheets',
    description: 'Automatically append a row to your master job-records spreadsheet whenever a new inspection is created. Writes: Client, Clerk, Date, Reference, Address, Job, Size — leaving your formula columns (H, I, J) untouched.',
    color: '#34A853',
    status: 'available',
    badge: 'Free',
    benefit: 'Replaces your Zapier → intake sheet workflow',
    googleOAuth: true,
    scopeKey: 'has_sheets',
    configurable: true,
  },
  {
    id: 'google_drive',
    category: 'Document Management',
    name: 'Google Drive',
    logo: 'https://cdn.simpleicons.org/googledrive',
    description: 'Automatically upload completed PDF reports to Google Drive, organised by client and property. Reports land in InspectPro Reports / {Client} / {Property} the moment an inspection is marked complete.',
    color: '#4285F4',
    status: 'available',
    badge: 'Free',
    benefit: 'Reports backed up automatically',
    googleOAuth: true,
    scopeKey: 'has_drive',
  },
  {
    id: 'dropbox',
    category: 'Document Management',
    name: 'Dropbox',
    logo: 'https://cdn.simpleicons.org/dropbox',
    description: 'Push reports to Dropbox folders shared with clients or landlords for easy access without logging in.',
    color: '#0061FF',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'onedrive',
    category: 'Document Management',
    name: 'OneDrive / SharePoint',
    logo: 'https://cdn.simpleicons.org/onedrive',
    description: 'Store reports in Microsoft OneDrive or SharePoint — ideal for corporate agencies on Microsoft 365.',
    color: '#0078D4',
    status: 'coming_soon',
  },

  // ─ e-Signatures ───────────────────────────────────────────────────────────
  {
    id: 'docusign',
    category: 'e-Signatures',
    name: 'DocuSign',
    logo: 'https://cdn.simpleicons.org/docusign',
    description: 'Send completed reports for electronic signature by tenants, landlords or clerks. Legally binding and fully audited.',
    color: '#FFB300',
    status: 'coming_soon',
  },
  {
    id: 'dropbox_sign',
    category: 'e-Signatures',
    name: 'Dropbox Sign (HelloSign)',
    logo: 'https://cdn.simpleicons.org/dropbox',
    description: 'Lightweight e-signature tool with a generous free tier. Great for smaller agencies who need digital sign-off on reports.',
    color: '#0061FF',
    status: 'coming_soon',
    badge: 'Free tier',
  },

  // ─ Automation ────────────────────────────────────────────────────────────
  {
    id: 'zapier',
    category: 'Automation',
    name: 'Zapier',
    logo: 'https://cdn.simpleicons.org/zapier',
    description: 'Connect InspectPro to 5,000+ apps via Zapier Zaps — without any code. Trigger workflows when inspections are created, completed, or moved to review.',
    color: '#FF4A00',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'make',
    category: 'Automation',
    name: 'Make (Integromat)',
    logo: 'https://cdn.simpleicons.org/make',
    description: 'Build powerful multi-step automations with Make\'s visual flow editor. A more flexible alternative to Zapier, with a generous free tier.',
    color: '#6D00CC',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'n8n',
    category: 'Automation',
    name: 'n8n',
    logo: 'https://cdn.simpleicons.org/n8n',
    description: 'Open-source automation you can self-host. Connect InspectPro to your own internal tools with full control over data.',
    color: '#EA4B71',
    status: 'coming_soon',
    badge: 'Free / Self-hosted',
  },
]

// Group by category
const categories = [...new Set(integrations.map(i => i.category))]
function forCategory(cat) {
  return integrations.filter(i => i.category === cat)
}

function handleConnect(integration) {
  if (integration.status === 'coming_soon') {
    comingSoonName.value = integration.name
    comingSoonModal.value = true
    return
  }
  if (integration.configurable) {
    if (integration.id === 'depositary')    { showDepositaryPanel.value = true }
    if (integration.id === 'google_sheets') { showSheetsPanel.value = true }
    return
  }
  if (integration.googleOAuth) {
    // Both Drive and Calendar share the same Google OAuth connection
    if (googleStatus.value.connected) {
      // Already connected — clicking again opens disconnect confirmation
      disconnectGoogle()
    } else {
      connectGoogle()
    }
    return
  }
}
</script>

<template>
  <div class="integrations">
    <!-- Header -->
    <div class="section-header">
      <div>
        <h2>Integrations</h2>
        <p class="section-sub">Connect InspectPro to the tools your team already uses. Free connections are available for the apps below — more coming soon.</p>
      </div>
    </div>

    <!-- Category sections -->
    <div v-for="cat in categories" :key="cat" class="category-block">
      <h3 class="category-title">{{ cat }}</h3>
      <div class="cards-grid">
        <div
          v-for="integration in forCategory(cat)"
          :key="integration.id"
          class="int-card"
          :class="{ 'int-card--available': integration.status === 'available' }"
        >
          <!-- Icon + badges row -->
          <div class="card-top">
            <div class="int-icon" :style="{ background: integration.color + '18', borderColor: integration.color + '30' }">
              <img v-if="integration.logo" :src="integration.logo" :alt="integration.name" class="int-logo-img" />
              <span v-else-if="integration.logoText" class="int-logo-text" :style="{ color: integration.color }">{{ integration.logoText }}</span>
            </div>
            <div class="badge-row">
              <span v-if="integration.badge" class="badge badge--info">{{ integration.badge }}</span>
              <span v-if="integration.status === 'available'" class="badge badge--available">Available</span>
              <span v-if="integration.status === 'coming_soon'" class="badge badge--soon">Coming Soon</span>
            </div>
          </div>

          <!-- Name + description -->
          <div class="int-name">{{ integration.name }}</div>
          <p class="int-desc">{{ integration.description }}</p>

          <!-- Benefit callout (for featured integrations) -->
          <div v-if="integration.benefit" class="int-benefit">
            <span>💡</span> {{ integration.benefit }}
          </div>

          <!-- Google connected badge (shown under description for connected Google cards) -->
          <div
            v-if="integration.googleOAuth && googleStatus.connected && googleStatus[integration.scopeKey]"
            class="int-connected-badge"
          >
            ✓ Connected as {{ googleStatus.email }}
          </div>

          <!-- CTA -->
          <button
            class="int-btn"
            :class="[
              integration.status !== 'available' ? 'int-btn--soon' :
              (integration.id === 'depositary' && depositaryStatus === 'configured') ? 'int-btn--configured' :
              (integration.googleOAuth && googleStatus.connected) ? 'int-btn--configured' :
              'int-btn--connect'
            ]"
            @click="handleConnect(integration)"
            :disabled="connectingId === integration.id || googleDisconnecting"
          >
            <span v-if="connectingId === integration.id">Connecting…</span>
            <span v-else-if="integration.id === 'depositary' && depositaryStatus === 'configured'">⚙ Configured →</span>
            <span v-else-if="integration.googleOAuth && googleStatus.connected && googleStatus[integration.scopeKey]">✓ Connected — Disconnect</span>
            <span v-else-if="integration.googleOAuth && googleStatus.connected && !googleStatus[integration.scopeKey]">Re-authorise →</span>
            <span v-else-if="integration.status === 'available'">Connect →</span>
            <span v-else>Notify Me</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Google Sheets — Master Sheet config panel -->
    <div v-if="showSheetsPanel" class="modal-overlay" @click.self="showSheetsPanel = false">
      <div class="modal modal--wide">
        <div class="modal-icon" style="font-size:28px;">📊</div>
        <h3>Google Sheets — Master Sheet</h3>
        <p class="modal-sub">
          When a new inspection is created, InspectPro will append one row to your master sheet automatically —
          no Zapier or intermediate intake sheet required.
        </p>

        <div v-if="!googleStatus.connected" class="config-notice config-notice--warn">
          ⚠ <strong>Google not connected.</strong> Connect your Google account first
          (Settings → Integrations → Google Drive / Calendar) then re-open this panel.
        </div>
        <div v-else-if="!googleStatus.has_sheets" class="config-notice config-notice--warn">
          ⚠ <strong>Sheets permission not granted.</strong>
          Your current Google connection was made before the Sheets scope was added.
          Please <a href="#" @click.prevent="connectGoogle()">re-authorise Google</a> to add spreadsheet access.
        </div>
        <div v-else class="config-notice">
          ✅ Connected as <strong>{{ googleStatus.email }}</strong> — spreadsheet access granted.
        </div>

        <div class="config-fields" style="margin-top:16px;">
          <div class="config-field">
            <label>Spreadsheet ID</label>
            <input
              v-model="masterSheetId"
              type="text"
              class="config-input"
              placeholder="e.g. 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
            />
            <p class="field-hint">
              Found in the sheet URL:
              <code>docs.google.com/spreadsheets/d/<strong>[ID here]</strong>/edit</code>
            </p>
          </div>
        </div>

        <div class="config-notice" style="margin-top:12px; font-size:12px; color:#475569;">
          <strong>Column order InspectPro writes (must match your header row):</strong><br>
          A: Client &nbsp;·&nbsp; B: Clerk &nbsp;·&nbsp; C: Date &nbsp;·&nbsp; D: Reference &nbsp;·&nbsp; E: Address &nbsp;·&nbsp; F: Job &nbsp;·&nbsp; G: Size
          <br><span style="color:#94a3b8;">Columns H, I, J (your formulas &amp; tick boxes) are not touched.</span>
        </div>

        <div class="config-status" v-if="masterSheetId && googleStatus.has_sheets">
          ✅ Ready — rows will be appended to this sheet when inspections are created.
        </div>
        <div class="config-status config-status--warn" v-else-if="!masterSheetId">
          ⚠ Enter a Spreadsheet ID above to enable.
        </div>

        <div class="modal-actions">
          <button class="btn-secondary" @click="showSheetsPanel = false">Close</button>
          <transition name="fade">
            <span v-if="sheetsSaved" class="saved-badge">✓ Saved</span>
          </transition>
          <button class="btn-primary" :disabled="sheetsSaving || !googleStatus.has_sheets" @click="saveSheetsSettings">
            {{ sheetsSaving ? 'Saving…' : 'Save' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Coming Soon modal -->
    <div v-if="comingSoonModal" class="modal-overlay" @click.self="comingSoonModal = false">
      <div class="modal">
        <div class="modal-icon">🔔</div>
        <h3>{{ comingSoonName }}</h3>
        <p>This integration is on the roadmap. We'll notify admins as soon as it's available.</p>
        <button class="btn-primary" @click="comingSoonModal = false">OK</button>
      </div>
    </div>

    <!-- The Depositary config panel -->
    <div v-if="showDepositaryPanel" class="modal-overlay" @click.self="showDepositaryPanel = false">
      <div class="modal modal--wide">
        <div class="modal-icon">🏦</div>
        <h3>The Depositary</h3>
        <p class="modal-sub">
          Once configured, completed Check Out inspections will be automatically pushed to The Depositary —
          including tenant details, dilapidations and the PDF report.
        </p>

        <div class="config-notice">
          <strong>API credentials required.</strong>
          Contact <a href="https://www.thedepositary.com/integrations" target="_blank" rel="noopener">thedepositary.com/integrations</a>
          to request API access. They will supply the URL and key below.
        </div>

        <div class="config-fields">
          <div class="config-field">
            <label>API Base URL</label>
            <!-- TODO: replace placeholder once confirmed by The Depositary -->
            <input
              v-model="depositary.api_url"
              type="url"
              class="config-input"
              placeholder="https://api.thedepositary.com  (supplied by The Depositary)"
            />
          </div>
          <div class="config-field">
            <label>API Key</label>
            <input
              v-model="depositary.api_key"
              type="password"
              class="config-input"
              placeholder="Your API key (supplied by The Depositary)"
            />
          </div>
        </div>

        <div class="config-status" v-if="depositaryStatus === 'configured'">
          ✅ Configured — Check Out completions will push automatically.
        </div>
        <div class="config-status config-status--warn" v-else-if="depositaryStatus === 'not_configured'">
          ⚠ Not configured — enter both fields above to enable.
        </div>

        <div class="modal-actions">
          <button class="btn-secondary" @click="showDepositaryPanel = false">Close</button>
          <transition name="fade">
            <span v-if="depositorySaved" class="saved-badge">✓ Saved</span>
          </transition>
          <button class="btn-primary" :disabled="depositorySaving" @click="saveDepositarySettings">
            {{ depositorySaving ? 'Saving…' : 'Save Credentials' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.integrations { max-width: 1100px; }

.section-header { margin-bottom: 28px; }
h2 { font-size: 18px; font-weight: 700; color: #0f172a; margin: 0 0 6px; }
.section-sub { font-size: 13px; color: #64748b; line-height: 1.5; max-width: 680px; }

/* ─ Category ────────────────────────────────────────────────────────────── */
.category-block { margin-bottom: 36px; }
.category-title {
  font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.7px; color: #94a3b8;
  margin: 0 0 12px; padding-bottom: 8px;
  border-bottom: 1px solid #f1f5f9;
}

/* ─ Grid ─────────────────────────────────────────────────────────────────── */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

/* ─ Card ─────────────────────────────────────────────────────────────────── */
.int-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: box-shadow 0.15s, transform 0.12s;
}
.int-card:hover { box-shadow: 0 3px 12px rgba(0,0,0,0.07); transform: translateY(-1px); }
.int-card--available {
  border-color: #c7d2fe;
  background: linear-gradient(135deg, #fafbff 0%, #f0f4ff 100%);
}

.card-top { display: flex; align-items: center; justify-content: space-between; }

.int-icon {
  width: 40px; height: 40px; border-radius: 9px;
  border: 1px solid;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.int-logo-img { width: 24px; height: 24px; object-fit: contain; }
.int-logo-text { font-size: 11px; font-weight: 800; }

.badge-row { display: flex; gap: 5px; flex-wrap: wrap; justify-content: flex-end; }

.badge {
  font-size: 10px; font-weight: 700;
  padding: 2px 7px; border-radius: 8px;
}
.badge--info    { background: #f0f9ff; color: #0369a1; }
.badge--available { background: #dcfce7; color: #166534; }
.badge--soon    { background: #fef9c3; color: #92400e; }

.int-name { font-size: 14px; font-weight: 700; color: #1e293b; }
.int-desc { font-size: 12px; color: #64748b; line-height: 1.5; margin: 0; flex: 1; }

.int-benefit {
  font-size: 11px; font-weight: 600; color: #0369a1;
  background: #eff6ff;
  border-radius: 6px; padding: 5px 9px;
  display: flex; align-items: center; gap: 5px;
}

.int-connected-badge {
  font-size: 11px; font-weight: 600; color: #166534;
  background: #dcfce7; border: 1px solid #bbf7d0;
  border-radius: 6px; padding: 5px 9px;
}

.int-btn {
  margin-top: 4px; padding: 7px 14px;
  border-radius: 7px; border: none;
  font-size: 12px; font-weight: 700;
  cursor: pointer; transition: all 0.15s;
  align-self: flex-start;
}
.int-btn--connect { background: #6366f1; color: white; }
.int-btn--connect:hover { background: #4f46e5; }
.int-btn--soon { background: #f1f5f9; color: #64748b; }
.int-btn--soon:hover { background: #e2e8f0; color: #1e293b; }

/* Modal */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; padding: 20px;
}
.modal {
  background: white; border-radius: 14px;
  padding: 28px 28px 24px;
  max-width: 400px; width: 100%;
  text-align: center;
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.2);
}
.modal-icon { font-size: 40px; }
.modal h3 { font-size: 17px; font-weight: 700; color: #0f172a; margin: 0; }
.modal p { font-size: 13px; color: #64748b; line-height: 1.6; margin: 0; }
.btn-primary {
  padding: 9px 22px; background: #6366f1; color: white;
  border: none; border-radius: 8px;
  font-size: 13px; font-weight: 700; cursor: pointer;
}
.btn-primary:hover { background: #4f46e5; }
.btn-secondary {
  padding: 9px 18px; background: white; color: #374151;
  border: 1px solid #d1d5db; border-radius: 8px;
  font-size: 13px; font-weight: 600; cursor: pointer;
}
.btn-secondary:hover { background: #f9fafb; }

.modal--wide { max-width: 520px; text-align: left; align-items: stretch; }
.modal-sub { font-size: 13px; color: #64748b; line-height: 1.6; margin: 0; }
.config-notice {
  background: #fffbeb; border: 1px solid #fde68a;
  border-radius: 8px; padding: 12px 14px;
  font-size: 12px; color: #92400e; line-height: 1.5;
}
.config-notice a { color: #0369a1; }
.field-hint { font-size: 11px; color: #64748b; margin: 3px 0 0; }
.field-hint code { background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 11px; }
.config-fields { display: flex; flex-direction: column; gap: 12px; width: 100%; }
.config-field { display: flex; flex-direction: column; gap: 5px; }
.config-field label { font-size: 12px; font-weight: 700; color: #374151; }
.config-input {
  padding: 9px 12px; border: 1px solid #d1d5db; border-radius: 8px;
  font-size: 13px; font-family: inherit; color: #1e293b; width: 100%; box-sizing: border-box;
}
.config-input:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,.1); }
.config-status {
  font-size: 12px; font-weight: 600; color: #166534;
  background: #dcfce7; border-radius: 7px; padding: 8px 12px; width: 100%; box-sizing: border-box;
}
.config-status--warn { color: #92400e; background: #fffbeb; }
.modal-actions { display: flex; align-items: center; gap: 10px; justify-content: flex-end; width: 100%; }
.saved-badge { font-size: 13px; font-weight: 600; color: #16a34a; }
.int-btn--configured { background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }
.int-btn--configured:hover { background: #bbf7d0; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 768px) {
  .cards-grid { grid-template-columns: 1fr; }
}
</style>
