<script setup>
import { ref } from 'vue'

const connectingId = ref(null)
const connectedModal = ref(false)
const comingSoonModal = ref(false)
const comingSoonName  = ref('')

// ── Integration catalogue ─────────────────────────────────────────────────────
// status: 'available' | 'coming_soon'
// available = shows a Connect button (placeholder flow)
// coming_soon = shows a "Coming Soon" badge
const integrations = [
  // ─ Calendars ──────────────────────────────────────────────────────────────
  {
    id: 'google_calendar',
    category: 'Calendars',
    name: 'Google Calendar',
    description: 'Sync inspection schedules directly with Google Calendar. Clerks see their day\'s jobs, managers see team availability, and clients can be sent calendar invites automatically.',
    icon: '📅',
    color: '#4285F4',
    status: 'available',
    badge: 'Free',
    benefit: 'Saves ~15 min/day per clerk',
  },
  {
    id: 'outlook_calendar',
    category: 'Calendars',
    name: 'Microsoft Outlook / 365',
    description: 'Sync with Outlook calendars and Microsoft Teams. Ideal for agencies already on the Microsoft ecosystem.',
    icon: '📆',
    color: '#0078D4',
    status: 'coming_soon',
    badge: 'Free',
  },
  {
    id: 'apple_calendar',
    category: 'Calendars',
    name: 'Apple Calendar',
    description: 'Push inspection appointments to iCloud Calendar via CalDAV. Useful for clerks on iPhone.',
    icon: '🗓',
    color: '#FF3B30',
    status: 'coming_soon',
    badge: 'Free',
  },

  // ─ Property Management ────────────────────────────────────────────────────
  {
    id: 'arthur_online',
    category: 'Property Management',
    name: 'Arthur Online',
    description: 'Import properties and tenancies from Arthur Online. Automatically create inspections when check-in / check-out events are triggered.',
    icon: '🏠',
    color: '#1A56DB',
    status: 'coming_soon',
    badge: 'Popular UK',
  },
  {
    id: 'fixflo',
    category: 'Property Management',
    name: 'Fixflo',
    description: 'Link inspection findings directly to Fixflo repair requests. Flag items as defects and raise jobs without leaving InspectPro.',
    icon: '🔧',
    color: '#F97316',
    status: 'coming_soon',
    badge: 'Popular UK',
  },
  {
    id: 'goodlord',
    category: 'Property Management',
    name: 'Goodlord',
    description: 'Pull tenancy data and trigger check-in / check-out inspections at the right point in the tenancy lifecycle.',
    icon: '📝',
    color: '#7C3AED',
    status: 'coming_soon',
  },

  // ─ Communication ─────────────────────────────────────────────────────────
  {
    id: 'slack',
    category: 'Communication',
    name: 'Slack',
    description: 'Post notifications to Slack channels when inspections are completed, reports are ready, or urgent defects are flagged.',
    icon: '💬',
    color: '#4A154B',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'ms_teams',
    category: 'Communication',
    name: 'Microsoft Teams',
    description: 'Send inspection status updates to Teams channels. Ideal for letting agencies already using Microsoft 365.',
    icon: '💼',
    color: '#6264A7',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'whatsapp',
    category: 'Communication',
    name: 'WhatsApp Business',
    description: 'Send automated appointment reminders and report-ready notifications to clients and tenants via WhatsApp.',
    icon: '📱',
    color: '#25D366',
    status: 'coming_soon',
  },

  // ─ Finance ───────────────────────────────────────────────────────────────
  {
    id: 'xero',
    category: 'Finance',
    name: 'Xero',
    description: 'Automatically raise invoices in Xero when an inspection report is marked complete. Track revenue per client and clerk.',
    icon: '💷',
    color: '#13B5EA',
    status: 'coming_soon',
    badge: 'Popular UK',
  },
  {
    id: 'stripe',
    category: 'Finance',
    name: 'Stripe',
    description: 'Collect payments for inspection reports online. Useful if you offer a pay-per-report model or want to bill clients directly.',
    icon: '💳',
    color: '#635BFF',
    status: 'coming_soon',
    badge: 'Free to set up',
  },
  {
    id: 'quickbooks',
    category: 'Finance',
    name: 'QuickBooks',
    description: 'Sync completed inspections to QuickBooks as invoices or billable items.',
    icon: '📊',
    color: '#2CA01C',
    status: 'coming_soon',
  },

  // ─ Document Management ────────────────────────────────────────────────────
  {
    id: 'google_drive',
    category: 'Document Management',
    name: 'Google Drive',
    description: 'Automatically upload completed PDF reports to a designated Google Drive folder, organised by client or property.',
    icon: '📂',
    color: '#4285F4',
    status: 'coming_soon',
    badge: 'Free',
  },
  {
    id: 'dropbox',
    category: 'Document Management',
    name: 'Dropbox',
    description: 'Push reports to Dropbox folders shared with clients or landlords for easy access without logging in.',
    icon: '📦',
    color: '#0061FF',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'onedrive',
    category: 'Document Management',
    name: 'OneDrive / SharePoint',
    description: 'Store reports in Microsoft OneDrive or SharePoint — ideal for corporate agencies on Microsoft 365.',
    icon: '☁️',
    color: '#0078D4',
    status: 'coming_soon',
  },

  // ─ e-Signatures ───────────────────────────────────────────────────────────
  {
    id: 'docusign',
    category: 'e-Signatures',
    name: 'DocuSign',
    description: 'Send completed reports for electronic signature by tenants, landlords or clerks. Legally binding and fully audited.',
    icon: '✍️',
    color: '#FFB300',
    status: 'coming_soon',
  },
  {
    id: 'dropbox_sign',
    category: 'e-Signatures',
    name: 'Dropbox Sign (HelloSign)',
    description: 'Lightweight e-signature tool with a generous free tier. Great for smaller agencies who need digital sign-off on reports.',
    icon: '🖊️',
    color: '#0061FF',
    status: 'coming_soon',
    badge: 'Free tier',
  },

  // ─ Automation ────────────────────────────────────────────────────────────
  {
    id: 'zapier',
    category: 'Automation',
    name: 'Zapier',
    description: 'Connect InspectPro to 5,000+ apps via Zapier Zaps — without any code. Trigger workflows when inspections are created, completed, or moved to review.',
    icon: '⚡',
    color: '#FF4A00',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'make',
    category: 'Automation',
    name: 'Make (Integromat)',
    description: 'Build powerful multi-step automations with Make\'s visual flow editor. A more flexible alternative to Zapier, with a generous free tier.',
    icon: '🔄',
    color: '#6D00CC',
    status: 'coming_soon',
    badge: 'Free tier',
  },
  {
    id: 'n8n',
    category: 'Automation',
    name: 'n8n',
    description: 'Open-source automation you can self-host. Connect InspectPro to your own internal tools with full control over data.',
    icon: '🛠',
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
  // Placeholder: Google Calendar OAuth flow would launch here
  connectingId.value = integration.id
  setTimeout(() => {
    connectingId.value = null
    connectedModal.value = true
  }, 800)
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
              <span>{{ integration.icon }}</span>
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

          <!-- CTA -->
          <button
            class="int-btn"
            :class="integration.status === 'available' ? 'int-btn--connect' : 'int-btn--soon'"
            @click="handleConnect(integration)"
            :disabled="connectingId === integration.id"
          >
            <span v-if="connectingId === integration.id">Connecting…</span>
            <span v-else-if="integration.status === 'available'">Connect →</span>
            <span v-else>Notify Me</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Google Calendar "Connected" placeholder modal -->
    <div v-if="connectedModal" class="modal-overlay" @click.self="connectedModal = false">
      <div class="modal">
        <div class="modal-icon">✅</div>
        <h3>Google Calendar</h3>
        <p>This is a placeholder for the Google Calendar OAuth flow. When implemented, clerks will be able to authorise InspectPro to read &amp; write their Google Calendar.</p>
        <button class="btn-primary" @click="connectedModal = false">Got it</button>
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
  font-size: 20px;
  flex-shrink: 0;
}

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

/* ─ Modal ────────────────────────────────────────────────────────────────── */
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

/* ─ Responsive ─────────────────────────────────────────────────────────── */
@media (max-width: 768px) {
  .cards-grid { grid-template-columns: 1fr; }
}
</style>
