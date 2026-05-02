<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

const saving = ref(false)
const saved = ref(false)
const loading = ref(true)
const logoPreview = ref(null)
const logoFile = ref(null)
const logoInputRef = ref(null)
const aiicLogoPreview = ref(null)
const aiicLogoFile = ref(null)
const aiicLogoInputRef = ref(null)
const logoInvertedPreview = ref(null)
const logoInvertedFile = ref(null)
const logoInvertedInputRef = ref(null)

const form = ref({
  company_name: '',
  address_line1: '',
  address_line2: '',
  city: '',
  postcode: '',
  email: '',
  phone: '',
  website: '',
  logo: '',
  aiic_logo: '',
  logo_inverted: '',
  report_disclaimer: '',
})

async function fetchSettings() {
  loading.value = true
  try {
    const res = await api.getSystemSettings()
    const s = res.data || {}
    form.value.company_name  = s.company_name  || ''
    form.value.address_line1 = s.address_line1 || ''
    form.value.address_line2 = s.address_line2 || ''
    form.value.city          = s.city          || ''
    form.value.postcode      = s.postcode      || ''
    form.value.email         = s.email         || ''
    form.value.phone         = s.phone         || ''
    form.value.website       = s.website       || ''
    form.value.logo              = s.logo              || ''
    form.value.aiic_logo         = s.aiic_logo         || ''
    form.value.logo_inverted     = s.logo_inverted     || ''
    form.value.report_disclaimer = s.report_disclaimer || ''
    if (s.logo) logoPreview.value = s.logo
    if (s.aiic_logo) aiicLogoPreview.value = s.aiic_logo
    if (s.logo_inverted) logoInvertedPreview.value = s.logo_inverted
  } catch (err) {
    console.error('Failed to load system settings:', err)
  } finally {
    loading.value = false
  }
}

function onLogoChange(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const inputEl = e.target
  logoFile.value = file
  // Show preview immediately (synchronous — no async wait)
  const objectUrl = URL.createObjectURL(file)
  logoPreview.value = objectUrl
  const reader = new FileReader()
  reader.onload = () => {
    form.value.logo = reader.result
    logoPreview.value = reader.result   // switch to persistent base64
    URL.revokeObjectURL(objectUrl)
    inputEl.value = ''
  }
  reader.onerror = () => {
    console.error('[GeneralSettings] Failed to read logo')
    logoPreview.value = form.value.logo || null
    logoFile.value = null
    URL.revokeObjectURL(objectUrl)
  }
  reader.readAsDataURL(file)
}

function removeLogo() {
  logoPreview.value = null
  logoFile.value = null
  form.value.logo = ''
  if (logoInputRef.value) logoInputRef.value.value = ''
}

function onAiicLogoChange(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const inputEl = e.target
  aiicLogoFile.value = file
  const objectUrl = URL.createObjectURL(file)
  aiicLogoPreview.value = objectUrl
  const reader = new FileReader()
  reader.onload = () => {
    form.value.aiic_logo = reader.result
    aiicLogoPreview.value = reader.result
    URL.revokeObjectURL(objectUrl)
    inputEl.value = ''
  }
  reader.onerror = () => {
    console.error('[GeneralSettings] Failed to read AIIC logo')
    aiicLogoPreview.value = form.value.aiic_logo || null
    aiicLogoFile.value = null
    URL.revokeObjectURL(objectUrl)
  }
  reader.readAsDataURL(file)
}

function removeAiicLogo() {
  aiicLogoPreview.value = null
  aiicLogoFile.value = null
  form.value.aiic_logo = ''
  if (aiicLogoInputRef.value) aiicLogoInputRef.value.value = ''
}

function onLogoInvertedChange(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const inputEl = e.target
  logoInvertedFile.value = file
  const objectUrl = URL.createObjectURL(file)
  logoInvertedPreview.value = objectUrl
  const reader = new FileReader()
  reader.onload = () => {
    form.value.logo_inverted = reader.result
    logoInvertedPreview.value = reader.result
    URL.revokeObjectURL(objectUrl)
    inputEl.value = ''
  }
  reader.onerror = () => {
    console.error('[GeneralSettings] Failed to read inverted logo')
    logoInvertedPreview.value = form.value.logo_inverted || null
    logoInvertedFile.value = null
    URL.revokeObjectURL(objectUrl)
  }
  reader.readAsDataURL(file)
}

function removeLogoInverted() {
  logoInvertedPreview.value = null
  logoInvertedFile.value = null
  form.value.logo_inverted = ''
  if (logoInvertedInputRef.value) logoInvertedInputRef.value.value = ''
}

async function save() {
  saving.value = true
  try {
    const res = await api.updateSystemSettings({
      company_name:  form.value.company_name,
      address_line1: form.value.address_line1,
      address_line2: form.value.address_line2,
      city:          form.value.city,
      postcode:      form.value.postcode,
      email:         form.value.email,
      phone:         form.value.phone,
      website:       form.value.website,
      logo:               form.value.logo,
      aiic_logo:          form.value.aiic_logo,
      logo_inverted:      form.value.logo_inverted,
      report_disclaimer:  form.value.report_disclaimer,
    })
    // Sync previews from what the server actually confirmed it stored.
    // If a logo save silently failed, the preview will correctly revert.
    const s = res.data?.settings || {}
    if ('logo' in s) {
      form.value.logo = s.logo || ''
      logoPreview.value = s.logo || null
    }
    if ('aiic_logo' in s) {
      form.value.aiic_logo = s.aiic_logo || ''
      aiicLogoPreview.value = s.aiic_logo || null
    }
    if ('logo_inverted' in s) {
      form.value.logo_inverted = s.logo_inverted || ''
      logoInvertedPreview.value = s.logo_inverted || null
    }
    saved.value = true
    setTimeout(() => saved.value = false, 2500)
  } catch (err) {
    console.error('Failed to save system settings:', err)
    alert('Failed to save settings — please try again.')
  } finally {
    saving.value = false
  }
}

onMounted(fetchSettings)
</script>

<template>
  <div class="settings-section">
    <div class="section-header">
      <div>
        <h2>Company Information</h2>
        <p class="section-description">
          These details appear on automated emails and will eventually be used as the default branding for your InspectPro instance.
        </p>
      </div>
    </div>

    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>Loading settings…</p>
    </div>

    <div v-else class="settings-layout">

      <!-- LEFT: form fields -->
      <div class="form-panels">

        <!-- Logo -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">🖼️</span>
            Company Logo
          </div>
          <p class="panel-desc">Used in automated emails and reports. PNG or SVG recommended, min 200×60px.</p>

          <div class="logo-zone">
            <div class="logo-preview-wrap">
              <div class="logo-preview" :class="{ 'logo-preview--empty': !logoPreview }">
                <img v-if="logoPreview" :src="logoPreview" alt="Company logo" class="logo-img" />
                <div v-else class="logo-placeholder">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                  </svg>
                  <span>No logo uploaded</span>
                </div>
              </div>
            </div>
            <div class="logo-actions">
              <label class="btn-upload">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="17 8 12 3 7 8"/>
                  <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
                {{ logoPreview ? 'Replace Logo' : 'Upload Logo' }}
                <input ref="logoInputRef" type="file" accept="image/*" style="display:none" @change="onLogoChange" />
              </label>
              <button v-if="logoPreview" class="btn-remove-logo" @click="removeLogo">Remove</button>
            </div>
          </div>
        </div>

        <!-- AIIC Logo -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">🏅</span>
            AIIC Membership Logo
          </div>
          <p class="panel-desc">Displayed on the bottom-right of the PDF cover page alongside your company branding. Leave blank if not an AIIC member. PNG recommended.</p>

          <div class="logo-zone">
            <div class="logo-preview-wrap">
              <div class="logo-preview" :class="{ 'logo-preview--empty': !aiicLogoPreview }">
                <img v-if="aiicLogoPreview" :src="aiicLogoPreview" alt="AIIC logo" class="logo-img" />
                <div v-else class="logo-placeholder">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                  </svg>
                  <span>No AIIC logo uploaded</span>
                </div>
              </div>
            </div>
            <div class="logo-actions">
              <label class="btn-upload">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="17 8 12 3 7 8"/>
                  <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
                {{ aiicLogoPreview ? 'Replace Logo' : 'Upload Logo' }}
                <input ref="aiicLogoInputRef" type="file" accept="image/*" style="display:none" @change="onAiicLogoChange" />
              </label>
              <button v-if="aiicLogoPreview" class="btn-remove-logo" @click="removeAiicLogo">Remove</button>
            </div>
          </div>
        </div>

        <!-- Inverted / light logo for dark PDF footers -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">🌗</span>
            Light / Inverted Logo
          </div>
          <p class="panel-desc">
            A white or light-coloured version of your logo, used on coloured PDF cover footers when the
            <strong>Use alternate logo</strong> toggle is enabled for a client in Report Settings.
            PNG with a transparent background recommended.
          </p>

          <div class="logo-zone">
            <div class="logo-preview-wrap">
              <!-- Preview against a dark tile so a white PNG is visible -->
              <div class="logo-preview logo-preview--dark" :class="{ 'logo-preview--empty': !logoInvertedPreview }">
                <img v-if="logoInvertedPreview" :src="logoInvertedPreview" alt="Inverted logo" class="logo-img" />
                <div v-else class="logo-placeholder logo-placeholder--dark">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                  </svg>
                  <span>No inverted logo uploaded</span>
                </div>
              </div>
            </div>
            <div class="logo-actions">
              <label class="btn-upload">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="17 8 12 3 7 8"/>
                  <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
                {{ logoInvertedPreview ? 'Replace Logo' : 'Upload Logo' }}
                <input ref="logoInvertedInputRef" type="file" accept="image/*" style="display:none" @change="onLogoInvertedChange" />
              </label>
              <button v-if="logoInvertedPreview" class="btn-remove-logo" @click="removeLogoInverted">Remove</button>
            </div>
          </div>
        </div>

        <!-- Company Details -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">🏢</span>
            Company Details
          </div>

          <div class="field-grid">
            <div class="field field--full">
              <label class="field-label">Company Name <span class="req">*</span></label>
              <input v-model="form.company_name" class="field-input" type="text" placeholder="e.g. L&M Inventories Ltd" />
            </div>

            <div class="field field--full">
              <label class="field-label">Address Line 1</label>
              <input v-model="form.address_line1" class="field-input" type="text" placeholder="e.g. 123 High Street" />
            </div>

            <div class="field field--full">
              <label class="field-label">Address Line 2</label>
              <input v-model="form.address_line2" class="field-input" type="text" placeholder="e.g. Suite 4 (optional)" />
            </div>

            <div class="field">
              <label class="field-label">City / Town</label>
              <input v-model="form.city" class="field-input" type="text" placeholder="e.g. London" />
            </div>

            <div class="field">
              <label class="field-label">Postcode</label>
              <input v-model="form.postcode" class="field-input" type="text" placeholder="e.g. EC1A 1BB" />
            </div>
          </div>
        </div>

        <!-- Contact Details -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">📬</span>
            Contact Details
          </div>
          <p class="panel-desc">
            The email address and company name will appear in automated emails sent to clients.
          </p>

          <div class="field-grid">
            <div class="field">
              <label class="field-label">Email Address <span class="req">*</span></label>
              <input v-model="form.email" class="field-input" type="email" placeholder="e.g. hello@yourcompany.com" />
              <p class="field-hint">Used as the sender address in automated emails.</p>
            </div>

            <div class="field">
              <label class="field-label">Phone Number</label>
              <input v-model="form.phone" class="field-input" type="tel" placeholder="e.g. 020 7123 4567" />
            </div>

            <div class="field field--full">
              <label class="field-label">Website</label>
              <input v-model="form.website" class="field-input" type="url" placeholder="e.g. https://yourcompany.com" />
            </div>
          </div>
        </div>

        <!-- Report Disclaimer -->
        <div class="panel">
          <div class="panel-title">
            <span class="panel-icon">📄</span>
            Report Disclaimer
          </div>
          <p class="panel-desc">
            This text will appear on the Disclaimers page of every exported PDF report.
            Leave blank to omit the disclaimer page entirely.
          </p>
          <textarea
            v-model="form.report_disclaimer"
            class="field-input disclaimer-textarea"
            rows="6"
            placeholder="e.g. This report has been prepared with reasonable care and skill. The contents are confidential to the instructing parties. All measurements are approximate."
          ></textarea>
        </div>

        <!-- Save -->
        <div class="save-row">
          <transition name="fade">
            <div v-if="saved" class="saved-badge">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              Settings saved
            </div>
          </transition>
          <button class="btn-save" :disabled="saving" @click="save">
            {{ saving ? 'Saving…' : '💾  Save Company Info' }}
          </button>
        </div>

      </div>

      <!-- RIGHT: preview card -->
      <div class="preview-col">
        <div class="preview-card-title">Email Sender Preview</div>
        <div class="email-preview">
          <div class="ep-header">
            <div class="ep-logo">
              <img v-if="logoPreview" :src="logoPreview" alt="logo" class="ep-logo-img" />
              <div v-else class="ep-logo-initials">
                {{ (form.company_name || 'CO').split(' ').map(w => w[0]).slice(0,2).join('').toUpperCase() }}
              </div>
            </div>
          </div>
          <div class="ep-body">
            <p class="ep-greeting">Dear [Client Name],</p>
            <p class="ep-text">Your inspection report for <strong>15 Example Street, London</strong> is now ready.</p>
            <div class="ep-btn">View Report</div>
          </div>
          <div class="ep-footer">
            <div class="ep-footer-name">{{ form.company_name || 'Your Company Name' }}</div>
            <div v-if="form.email" class="ep-footer-detail">{{ form.email }}</div>
            <div v-if="form.phone" class="ep-footer-detail">{{ form.phone }}</div>
            <div v-if="form.website" class="ep-footer-detail">{{ form.website }}</div>
            <div v-if="form.address_line1" class="ep-footer-addr">
              {{ [form.address_line1, form.address_line2, form.city, form.postcode].filter(Boolean).join(', ') }}
            </div>
          </div>
        </div>

        <div class="preview-note">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          This shows how your company details will appear in automated emails. Email sending will be configured separately.
        </div>
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
  line-height: 1.5;
}

.section-header { margin-bottom: 28px; }

/* Loading */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 20px;
  color: #94a3b8;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* Layout */
.settings-layout {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 28px;
  align-items: start;
}

/* Panels */
.form-panels {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.panel {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 24px;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 14px;
}

.panel-icon { font-size: 16px; }

.panel-desc {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 18px;
  line-height: 1.5;
}

/* Logo zone */
.logo-zone {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.logo-preview {
  width: 220px;
  height: 80px;
  border: 2px dashed #d1d5db;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
  overflow: hidden;
}

.logo-preview--empty { }

.logo-preview--dark {
  background: #1e293b;
  border-color: #334155;
}

.logo-placeholder--dark span {
  color: rgba(255, 255, 255, 0.4);
}

.logo-img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  padding: 6px;
}

.logo-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: #94a3b8;
  font-size: 12px;
}

.logo-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.btn-upload {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 18px;
  background: #6366f1;
  color: white;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}

.btn-upload:hover { background: #4f46e5; }

.btn-remove-logo {
  padding: 7px 14px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  font-size: 13px;
  color: #ef4444;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-remove-logo:hover { background: #fef2f2; border-color: #fca5a5; }

/* Fields */
.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.field { display: flex; flex-direction: column; gap: 6px; }
.field--full { grid-column: 1 / -1; }

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.req { color: #ef4444; }

.field-input {
  padding: 9px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  color: #1e293b;
  transition: border-color 0.15s;
}

.field-input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.field-hint {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.4;
}

.disclaimer-textarea {
  width: 100%;
  resize: vertical;
  line-height: 1.6;
  box-sizing: border-box;
}

/* Save row */
.save-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
}

.saved-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #16a34a;
  font-weight: 600;
}

.btn-save {
  padding: 11px 28px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 9px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { opacity: 0.6; cursor: not-allowed; }

/* Fade transition */
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* ── RIGHT COLUMN: email preview ── */
.preview-col { position: sticky; top: 24px; }

.preview-card-title {
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 12px;
}

.email-preview {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
  background: white;
  box-shadow: 0 2px 8px rgba(0,0,0,0.07);
}

.ep-header {
  background: #ffffff;
  border-bottom: 2px solid #1e3a8a;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ep-logo {
  flex-shrink: 0;
  width: 160px;
  height: 52px;
  overflow: hidden;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ep-logo-img { width: 100%; height: 100%; object-fit: contain; }

.ep-logo-initials {
  font-size: 14px;
  font-weight: 700;
  color: #6366f1;
  background: #eef2ff;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}

.ep-body {
  padding: 20px;
  border-bottom: 1px solid #f1f5f9;
}

.ep-greeting {
  font-size: 14px;
  color: #374151;
  margin-bottom: 10px;
}

.ep-text {
  font-size: 14px;
  color: #374151;
  line-height: 1.5;
  margin-bottom: 16px;
}

.ep-btn {
  display: inline-block;
  padding: 9px 20px;
  background: #6366f1;
  color: white;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
}

.ep-footer {
  padding: 14px 20px;
  background: #f8fafc;
}

.ep-footer-name {
  font-size: 13px;
  font-weight: 700;
  color: #374151;
  margin-bottom: 4px;
}

.ep-footer-detail, .ep-footer-addr {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
}

.preview-note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 14px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.preview-note svg { flex-shrink: 0; margin-top: 1px; }

@media (max-width: 1024px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
  .preview-col {
    position: static;
    order: -1;
  }
}
</style>
