<script setup>
import { ref, computed, watchEffect } from 'vue'
import { useToast } from '../composables/useToast'
import { usePdfImportJobs } from '../composables/usePdfImportJobs'
import api from '../services/api'

const props = defineProps({
  inspection: { type: Object, required: true },
  templates:  { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'saved'])

const toast         = useToast()
const pdfImportJobs = usePdfImportJobs()

// ── State ────────────────────────────────────────────────────────────────────
const step        = ref(1)   // 1 = upload PDF · 2 = review & save
const file        = ref(null)
const fileName    = ref('')
const parsed      = ref(null)
const error       = ref('')
const saving      = ref(false)
const parsing     = ref(false)
const jobKey      = ref('')
const roomMapping = ref({})
const keepLayout  = ref(false)
const includePhotos = ref(true)
const allCheckInTemplates = ref([])

// Cloud-picker OAuth token
let _gdriveToken = null

// ── Computed ─────────────────────────────────────────────────────────────────
const allTemplateSections = computed(() => {
  const out = []
  for (const tpl of allCheckInTemplates.value) {
    for (const sec of (tpl.sections || [])) {
      if (sec.section_type === 'room') out.push({ ...sec, templateId: tpl.id, templateName: tpl.name })
    }
  }
  return out
})

const totalImportedPhotos = computed(() => {
  if (!parsed.value) return 0
  return (parsed.value.rooms || []).reduce((n, r) => n + (r._photos?.length || 0), 0)
    + (parsed.value._overviewPhotos?.length || 0)
    + (parsed.value._coverPhoto ? 1 : 0)
})

const mergedSections = computed(() => {
  const counts = {}
  for (const v of Object.values(roomMapping.value)) {
    if (v && v !== 'new') counts[v] = (counts[v] || 0) + 1
  }
  return counts
})

// ── File handling ────────────────────────────────────────────────────────────
function onFileSelected(e) {
  const f = e.target?.files?.[0] || e.dataTransfer?.files?.[0]
  if (!f) return
  if (f.type !== 'application/pdf') { toast.error('Please choose a PDF file'); return }
  file.value     = f
  fileName.value = f.name
  error.value    = ''
}

// ── Cloud pickers ─────────────────────────────────────────────────────────────
const DROPBOX_KEY    = import.meta.env.VITE_DROPBOX_APP_KEY   || ''
const GDRIVE_CLIENT  = import.meta.env.VITE_GOOGLE_CLIENT_ID  || ''

function _loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return }
    const s = document.createElement('script')
    s.src = src; s.onload = resolve; s.onerror = reject
    document.head.appendChild(s)
  })
}

async function openDropboxPicker() {
  if (!DROPBOX_KEY) { toast.error('Dropbox is not configured'); return }
  try {
    await _loadScript('https://www.dropbox.com/static/api/2/dropins.js')
    window.Dropbox.choose({
      appKey: DROPBOX_KEY, linkType: 'direct', multiselect: false, extensions: ['.pdf'],
      success: async (files) => {
        try {
          const blob = await (await fetch(files[0].link)).blob()
          file.value     = new File([blob], files[0].name, { type: 'application/pdf' })
          fileName.value = files[0].name
          toast.success('PDF loaded from Dropbox')
        } catch (e) { toast.error('Failed to download from Dropbox: ' + e.message) }
      },
      cancel: () => {},
    })
  } catch (e) { toast.error('Could not load Dropbox picker') }
}

async function openGoogleDrivePicker() {
  if (!GDRIVE_CLIENT) { toast.error('Google Drive is not configured'); return }
  try {
    if (!_gdriveToken) {
      await _loadScript('https://accounts.google.com/gsi/client')
      _gdriveToken = await new Promise((resolve, reject) => {
        const client = google.accounts.oauth2.initTokenClient({
          client_id: GDRIVE_CLIENT,
          scope: 'https://www.googleapis.com/auth/drive.readonly',
          callback: (r) => r.error ? reject(new Error(r.error)) : resolve(r.access_token),
        })
        client.requestAccessToken()
      })
    }
    await _loadScript('https://apis.google.com/js/api.js')
    await new Promise(r => gapi.load('picker', r))
    const view = new google.picker.DocsView().setMimeTypes('application/pdf')
    new google.picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(_gdriveToken)
      .setCallback(async (d) => {
        if (d.action !== google.picker.Action.PICKED) return
        const doc = d.docs[0]
        try {
          const resp = await fetch(
            `https://www.googleapis.com/drive/v3/files/${doc.id}?alt=media`,
            { headers: { Authorization: `Bearer ${_gdriveToken}` } }
          )
          const blob = await resp.blob()
          file.value     = new File([blob], doc.name + '.pdf', { type: 'application/pdf' })
          fileName.value = doc.name + '.pdf'
          toast.success('PDF loaded from Google Drive')
        } catch (e) { toast.error('Failed to download from Google Drive') }
      })
      .build().setVisible(true)
  } catch (e) { toast.error('Could not open Google Drive picker') }
}

// ── Parse ────────────────────────────────────────────────────────────────────
async function runParse() {
  if (!file.value) { toast.warning('Please select a PDF file'); return }
  parsing.value = true
  error.value   = ''
  jobKey.value  = Date.now().toString(36) + Math.random().toString(36).slice(2)
  try {
    const startRes = await api.pdfImport(file.value)
    const jobId    = startRes.data?.job_id
    if (!jobId) throw new Error('No job ID returned from server')
    pdfImportJobs.registerJob(jobId, jobKey.value, fileName.value)
    toast.info("PDF is being analysed — we'll update this screen when it's ready.", 6000)
  } catch (e) {
    error.value   = 'Failed to start PDF analysis: ' + (e.message || 'unknown error')
    parsing.value = false
  }
}

watchEffect(() => {
  if (!jobKey.value) return
  const completed = pdfImportJobs.getCompletedJob(jobKey.value)
  if (!completed) return
  pdfImportJobs.clearCompletedJob(jobKey.value)
  parsed.value = completed.result
  if (parsed.value) parsed.value._fileName = completed.filename
  _loadTemplatesAndAdvance()
})

async function _loadTemplatesAndAdvance() {
  try {
    const checkInTpls = props.templates.filter(t => t.inspection_type === 'check_in')
    const fetched     = await Promise.all(checkInTpls.map(t => api.getTemplate(t.id)))
    allCheckInTemplates.value = fetched.map(r => r.data)
  } catch { allCheckInTemplates.value = [] }
  parsing.value = false
  _buildInitialRoomMapping()
  step.value = 2
}

function _buildInitialRoomMapping() {
  if (!parsed.value) return
  const sections  = allTemplateSections.value
  const normalise = s => s.toLowerCase().replace(/[^a-z0-9]/g, '')
  const mapping   = {}
  for (const pdfRoom of (parsed.value.rooms || [])) {
    const pdfNorm = normalise(pdfRoom.name)
    let best = sections.find(s => normalise(s.name) === pdfNorm)
    if (!best) best = sections.find(s => { const tn = normalise(s.name); return tn.includes(pdfNorm) || pdfNorm.includes(tn) })
    mapping[pdfRoom.name] = best ? String(best.id) : 'new'
  }
  roomMapping.value = mapping
}

// ── Save ─────────────────────────────────────────────────────────────────────
function _buildParsedPayload() {
  if (includePhotos.value) return parsed.value
  const rooms = (parsed.value.rooms || []).map(r => { const out = { ...r }; delete out._photos; delete out._photoRefs; return out })
  const out = { ...parsed.value, rooms }
  delete out._overviewPhotos; delete out._coverPhoto
  return out
}

function _pollRedistributionJob(jobId) {
  return new Promise((resolve, reject) => {
    const MAX = 5 * 60 * 1000
    const INTERVAL = 4000
    const started = Date.now()
    const tick = async () => {
      try {
        if (Date.now() - started > MAX) { reject(new Error('AI redistribution timed out')); return }
        const res    = await api.applyPdfImportStatus(props.inspection.id, jobId)
        const status = res.data?.status
        if (status === 'done')  { resolve(res.data); return }
        if (status === 'error') { reject(new Error(res.data?.error || 'AI redistribution failed')); return }
        setTimeout(tick, INTERVAL)
      } catch (e) { reject(e) }
    }
    setTimeout(tick, INTERVAL)
  })
}

async function save() {
  saving.value = true
  try {
    const roomMappings = Object.entries(roomMapping.value).map(([pdfRoomName, templateSectionId]) => ({
      pdfRoomName,
      templateSectionId: templateSectionId === 'new' ? null : parseInt(templateSectionId, 10),
    }))
    const parsedPayload = _buildParsedPayload()
    const applyRes = await api.applyPdfImport(
      props.inspection.id,
      { ...parsedPayload, roomMappings, redistributeItems: !keepLayout.value },
      { timeout: keepLayout.value ? 30_000 : 60_000 },
    )
    if (applyRes.status === 202) {
      const jobId = applyRes.data?.job_id
      if (!jobId) throw new Error('Server returned 202 but no job_id')
      await _pollRedistributionJob(jobId)
    }
    toast.success('Check In PDF applied successfully')
    emit('saved')
  } catch (e) {
    toast.error(e?.response?.data?.error || e.message || 'Failed to apply PDF')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="pi-overlay" @click.self="emit('close')">
    <div class="pi-modal">
      <div class="pi-header">
        <h2>Upload Check In PDF</h2>
        <button @click="emit('close')" class="pi-close">✕</button>
      </div>

      <!-- Step indicators -->
      <div class="pi-steps">
        <div class="pi-step" :class="{ active: step >= 1, done: step > 1 }">
          <span class="pi-step-num">1</span><span class="pi-step-label">Upload PDF</span>
        </div>
        <div class="pi-step-line"></div>
        <div class="pi-step" :class="{ active: step >= 2 }">
          <span class="pi-step-num">2</span><span class="pi-step-label">Review &amp; Save</span>
        </div>
      </div>

      <div class="pi-body">

        <!-- ── Step 1: Upload + parse ─────────────────────────────────── -->
        <div v-if="step === 1">
          <p class="pi-step2-intro">Upload the Check In PDF for this inspection. Claude will extract all rooms, items, descriptions and conditions automatically.</p>

          <label
            class="pi-dropzone"
            :class="{ 'pi-dropzone-has': fileName }"
            @dragover.prevent
            @drop.prevent="onFileSelected"
          >
            <template v-if="!fileName">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              <span class="pi-dz-title">Drop PDF here or <u>browse</u></span>
              <span class="pi-dz-hint">Check In or Inventory report in PDF format</span>
            </template>
            <template v-else>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <span class="pi-dz-filename">{{ fileName }}</span>
              <span class="pi-dz-hint">Click to change</span>
            </template>
            <input type="file" accept="application/pdf" style="display:none" @change="onFileSelected" />
          </label>

          <div class="pi-cloud-row">
            <span class="pi-cloud-or">or import from</span>
            <button type="button" class="pi-btn-cloud" @click="openGoogleDrivePicker">
              <svg width="18" height="18" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
                <path d="M6.6 66.85l3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3L27.5 53H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
                <path d="M43.65 25L29.9 1.2C28.55 2 27.4 3.1 26.6 4.5L1.2 48.5A9.06 9.06 0 000 53h27.5z" fill="#00ac47"/>
                <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8L73.55 76.8z" fill="#ea4335"/>
                <path d="M43.65 25L57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>
                <path d="M59.8 53H27.5L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.4 4.5-1.2z" fill="#2684fc"/>
                <path d="M73.4 26.5L60.7 4.5C59.9 3.1 58.75 2 57.4 1.2L43.65 25 59.8 53h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/>
              </svg>
              Google Drive
            </button>
            <button type="button" class="pi-btn-cloud" @click="openDropboxPicker">
              <svg width="18" height="18" viewBox="0 0 215 205" xmlns="http://www.w3.org/2000/svg" fill="#0061FF">
                <path d="M67.5 0L0 43.8l47.7 38.2L67.5 71l19.8 11L107.5 71l19.8 11 19.8-11 47.7-38.2L127.5 0 107.5 22.5zM107.5 82L87.7 71 47.7 97.8 0 63.8l67.5 43.8 40-27L127.5 108l40-27.2L215 63.8l-47.7 34L127.5 71zM67.5 108.8L0 152.5 67.5 196 107.5 171l40 25L215 152.5l-67.5-43.7-40 27-40-27z"/>
              </svg>
              Dropbox
            </button>
          </div>

          <div v-if="error" class="pi-error">{{ error }}</div>
          <div v-if="parsing" class="pi-parsing">
            <span class="pi-spinner"></span> Analysing PDF with AI — this may take 30–60 seconds…
          </div>

          <div class="pi-footer">
            <button type="button" @click="emit('close')" class="pi-btn-secondary" :disabled="parsing">Cancel</button>
            <button type="button" @click="runParse" :disabled="!fileName || parsing" class="pi-btn-primary">
              {{ parsing ? 'Analysing…' : 'Analyse PDF →' }}
            </button>
          </div>
        </div>

        <!-- ── Step 2: Mode picker + room mapping ─────────────────────── -->
        <div v-if="step === 2 && parsed">

          <div class="pi-map-stats">
            <span class="pi-map-stat-badge">{{ parsed.rooms?.length || 0 }} rooms found</span>
            <span class="pi-map-stat-badge">{{ parsed.rooms?.reduce((n, r) => n + (r.items?.length || 0), 0) || 0 }} items extracted</span>
            <span v-if="totalImportedPhotos > 0" class="pi-map-stat-badge" :class="includePhotos ? 'pi-map-stat-badge-photo' : 'pi-map-stat-badge-photo-skip'">
              {{ totalImportedPhotos }} photo{{ totalImportedPhotos === 1 ? '' : 's' }} {{ includePhotos ? 'extracted' : 'found (not importing)' }}
            </span>
          </div>

          <div class="pi-mode-row">
            <button type="button" class="pi-mode-card" :class="{ 'pi-mode-card-active': !keepLayout }" @click="keepLayout = false">
              <div class="pi-mode-icon">✦</div>
              <div class="pi-mode-text">
                <span class="pi-mode-title">Smart redistribution</span>
                <span class="pi-mode-hint">AI reads all content and places each item into the correct template section. Takes ~30 s.</span>
              </div>
            </button>
            <button type="button" class="pi-mode-card" :class="{ 'pi-mode-card-active': keepLayout }" @click="keepLayout = true">
              <div class="pi-mode-icon">▤</div>
              <div class="pi-mode-text">
                <span class="pi-mode-title">Keep PDF layout</span>
                <span class="pi-mode-hint">Items stay exactly as extracted — no AI redistribution. Fastest option.</span>
              </div>
            </button>
          </div>

          <template v-if="!keepLayout">
            <p class="pi-map-intro">
              Match each room from the PDF to a room in one of your templates.
              <em v-if="!allTemplateSections.length" class="pi-map-warn"> No check-in templates found — rooms will be imported as-is.</em>
            </p>
            <div class="pi-room-list">
              <div
                v-for="room in (parsed.rooms || [])"
                :key="room.name"
                class="pi-room-row"
                :class="{ 'pi-room-merging': mergedSections[roomMapping[room.name]] > 1 }"
              >
                <div class="pi-room-left">
                  <div class="pi-room-name">{{ room.name }}</div>
                  <div class="pi-room-count">
                    {{ room.items?.length || 0 }} item{{ room.items?.length === 1 ? '' : 's' }}<template v-if="room._photos?.length"> · {{ room._photos.length }} photo{{ room._photos.length === 1 ? '' : 's' }}</template>
                  </div>
                </div>
                <div class="pi-room-arrow">→</div>
                <div class="pi-room-right">
                  <select v-model="roomMapping[room.name]" class="pi-room-select">
                    <option value="new">＋ Import as new room</option>
                    <optgroup v-for="tpl in allCheckInTemplates" :key="tpl.id" :label="tpl.name">
                      <option v-for="sec in (tpl.sections || []).filter(s => s.section_type === 'room')" :key="sec.id" :value="String(sec.id)">{{ sec.name }}</option>
                    </optgroup>
                  </select>
                  <span v-if="mergedSections[roomMapping[room.name]] > 1" class="pi-merge-badge" :title="`${mergedSections[roomMapping[room.name]]} rooms will be merged`">⟺ Merge</span>
                </div>
              </div>
            </div>
          </template>

          <div v-else class="pi-layout-summary">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="9 12 11 14 15 10"/></svg>
            {{ parsed.rooms?.length || 0 }} rooms will be imported exactly as extracted, with no AI redistribution.
          </div>

          <div class="pi-footer">
            <button type="button" @click="step = 1" class="pi-btn-secondary" :disabled="saving">← Re-upload</button>
            <button type="button" @click="save" :disabled="saving" class="pi-btn-primary">
              <template v-if="saving">
                <span class="pi-spinner" style="width:14px;height:14px;border-width:2px;margin-right:6px"></span>
                {{ keepLayout ? 'Saving…' : 'Redistributing with AI…' }}
              </template>
              <template v-else>
                {{ keepLayout ? 'Apply Check In' : 'Redistribute &amp; Apply' }}
              </template>
            </button>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.pi-overlay {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.6);
  z-index: 9000;
  display: flex; align-items: center; justify-content: center;
  padding: 16px;
}
.pi-modal {
  background: #fff; border-radius: 14px;
  width: 820px; max-width: 100%; max-height: 90vh;
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: 0 20px 60px rgba(0,0,0,0.25);
}
.pi-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 24px; border-bottom: 1px solid #e2e8f0; flex-shrink: 0;
}
.pi-header h2 { font-size: 17px; font-weight: 700; color: #0f172a; margin: 0; }
.pi-close {
  width: 28px; height: 28px; border: none; background: #f1f5f9;
  border-radius: 6px; cursor: pointer; font-size: 14px; color: #64748b;
  display: flex; align-items: center; justify-content: center; transition: background 0.15s;
}
.pi-close:hover { background: #e2e8f0; color: #1e293b; }

.pi-steps {
  display: flex; align-items: center;
  padding: 16px 24px 0; gap: 0; flex-shrink: 0;
}
.pi-step { display: flex; align-items: center; gap: 7px; opacity: 0.4; transition: opacity 0.2s; }
.pi-step.active { opacity: 1; }
.pi-step-num {
  width: 24px; height: 24px; border-radius: 50%; background: #e2e8f0; color: #64748b;
  font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: background 0.2s, color 0.2s;
}
.pi-step.active .pi-step-num { background: #6366f1; color: #fff; }
.pi-step.done   .pi-step-num { background: #10b981; color: #fff; }
.pi-step-label  { font-size: 12px; font-weight: 600; color: #64748b; white-space: nowrap; }
.pi-step.active .pi-step-label { color: #1e293b; }
.pi-step-line   { flex: 1; height: 2px; background: #e2e8f0; margin: 0 8px; min-width: 20px; }

.pi-body { padding: 20px 24px 24px; overflow-y: auto; flex: 1; }

.pi-step2-intro { font-size: 13px; color: #64748b; margin: 0 0 16px; line-height: 1.5; }

.pi-dropzone {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; border: 2px dashed #cbd5e1; border-radius: 10px;
  padding: 40px 24px; cursor: pointer; transition: all 0.15s;
  background: #f8fafc; text-align: center; color: #64748b; min-height: 160px;
}
.pi-dropzone:hover, .pi-dropzone-has { border-color: #6366f1; background: #eef2ff; }
.pi-dz-title    { font-size: 15px; font-weight: 600; color: #475569; }
.pi-dz-hint     { font-size: 12px; color: #94a3b8; }
.pi-dz-filename { font-size: 14px; font-weight: 700; color: #4338ca; }

.pi-cloud-row { display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.pi-cloud-or  { font-size: 12px; color: #94a3b8; white-space: nowrap; }
.pi-btn-cloud {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 7px 14px; border-radius: 8px; border: 1.5px solid #e2e8f0;
  background: #fff; font-size: 13px; font-weight: 600; color: #334155;
  cursor: pointer; transition: border-color 0.15s, background 0.15s;
}
.pi-btn-cloud:hover { border-color: #6366f1; background: #f5f3ff; }

.pi-error {
  background: #fef2f2; color: #dc2626;
  border: 1px solid #fecaca; border-radius: 8px;
  padding: 10px 14px; font-size: 13px; margin-top: 10px;
}
.pi-parsing {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: #6366f1; padding: 12px 0 4px; font-weight: 600;
}

.pi-map-stats { display: flex; gap: 8px; margin-bottom: 8px; }
.pi-map-stat-badge {
  background: #ede9fe; color: #4f46e5;
  font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 20px;
}
.pi-map-stat-badge-photo       { background: #fef3c7; color: #92400e; }
.pi-map-stat-badge-photo-skip  { background: #f1f5f9; color: #64748b; }

.pi-mode-row { display: flex; gap: 10px; margin: 12px 0 16px; }
.pi-mode-card {
  flex: 1; display: flex; align-items: flex-start; gap: 12px;
  padding: 14px 16px; border-radius: 10px; border: 2px solid #e2e8f0;
  background: #f8fafc; cursor: pointer; text-align: left; transition: all 0.15s;
}
.pi-mode-card:hover        { border-color: #a5b4fc; background: #eef2ff; }
.pi-mode-card-active       { border-color: #6366f1; background: #eef2ff; }
.pi-mode-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
.pi-mode-text { display: flex; flex-direction: column; gap: 4px; }
.pi-mode-title { font-size: 13px; font-weight: 700; color: #1e293b; }
.pi-mode-hint  { font-size: 11px; color: #64748b; line-height: 1.4; }

.pi-map-intro { font-size: 12px; color: #64748b; margin: 0 0 12px; line-height: 1.5; }
.pi-map-warn  { color: #b45309; font-style: normal; font-weight: 600; }

.pi-room-list {
  display: flex; flex-direction: column; gap: 8px;
  max-height: 320px; overflow-y: auto; padding-right: 4px;
}
.pi-room-row {
  display: flex; align-items: center; gap: 10px;
  background: #f8fafc; border: 1px solid #e2e8f0;
  border-radius: 8px; padding: 8px 12px;
}
.pi-room-merging { border-color: #fbbf24; background: #fffbeb; }
.pi-room-left  { flex: 0 0 180px; min-width: 0; }
.pi-room-name  { font-size: 13px; font-weight: 600; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pi-room-count { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.pi-room-arrow { color: #94a3b8; font-size: 16px; flex-shrink: 0; }
.pi-room-right { flex: 1; display: flex; align-items: center; gap: 8px; min-width: 0; }
.pi-room-select {
  flex: 1; padding: 6px 8px; border: 1px solid #e2e8f0;
  border-radius: 6px; font-size: 12px; color: #1e293b; background: #fff;
  min-width: 0;
}
.pi-merge-badge {
  flex-shrink: 0; background: #fef3c7; color: #92400e;
  font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 20px;
  white-space: nowrap; cursor: help;
}

.pi-layout-summary {
  display: flex; align-items: center; gap: 8px;
  background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px;
  padding: 12px 14px; font-size: 13px; color: #166534; margin: 12px 0 16px;
}

.pi-footer {
  display: flex; justify-content: flex-end; gap: 10px;
  margin-top: 20px; padding-top: 16px; border-top: 1px solid #f1f5f9;
}
.pi-btn-primary {
  display: inline-flex; align-items: center;
  padding: 9px 20px; background: #6366f1; color: #fff;
  border: none; border-radius: 8px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.pi-btn-primary:hover:not(:disabled) { background: #4f46e5; }
.pi-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.pi-btn-secondary {
  padding: 9px 18px; background: #f1f5f9; color: #475569;
  border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.pi-btn-secondary:hover:not(:disabled) { background: #e2e8f0; }
.pi-btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }

@keyframes pi-spin { to { transform: rotate(360deg); } }
.pi-spinner {
  display: inline-block; width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff;
  border-radius: 50%; animation: pi-spin 0.7s linear infinite;
}
</style>
