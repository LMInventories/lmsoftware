<script setup>
/**
 * MobileSectionTab.vue
 *
 * Renders the items for one tab (a fixed section or a room).
 * Handles:
 *   - All field types (condition, description, cleanliness, QA, meter, keys)
 *   - Per-item camera (via Capacitor Camera)
 *   - Per-item mic recording (Web Audio API — works in Capacitor WebView)
 *   - Photo thumbnails with lightbox
 *   - Delete / hide rows
 *   - Add extra rows
 *   - Rearrange (long-press drag — simplified for mobile)
 */
import { ref, computed, watch } from 'vue'
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera'
import { Capacitor } from '@capacitor/core'
import {
  savePhoto,
  getPhotos,
  saveRecording,
} from '../services/offline'
import { saveAudioToFilesystem, savePhotoToFilesystem } from '../services/sync'

const props = defineProps({
  tab:           { type: Object, required: true },
  inspectionId:  { type: Number, required: true },
  inspection:    { type: Object, default: null },
  reportData:    { type: Object, required: true },
  template:      { type: Object, default: null },
})

const emit = defineEmits(['set', 'save'])

const sec         = computed(() => props.tab.section)
const isRoom      = computed(() => props.tab.type === 'room')
const isFixed     = computed(() => props.tab.type === 'fixed')

// ── Report data helpers ───────────────────────────────────────────────
function get(sectionId, rowId, field) {
  return props.reportData[sectionId]?.[String(rowId)]?.[field] ?? ''
}
function set(sectionId, rowId, field, value) {
  emit('set', sectionId, rowId, field, value)
}

// ── Extra rows ────────────────────────────────────────────────────────
const extras = computed(() => props.reportData[sec.value?.id]?._extra ?? [])

function addExtraRow() {
  const eid = `mex_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
  const blank = { _eid: eid }
  const type  = sec.value?.type
  if (type === 'condition_summary')     { blank.name = ''; blank.condition = '' }
  else if (type === 'cleaning_summary') { blank.name = ''; blank.cleanliness = ''; blank.cleanlinessNotes = '' }
  else if (type === 'keys')             { blank.name = ''; blank.description = '' }
  else if (type === 'meter_readings')   { blank.name = ''; blank.locationSerial = ''; blank.reading = '' }
  else if (isRoom.value)                { blank.label = ''; blank.description = ''; blank.condition = '' }

  if (!props.reportData[sec.value.id]) props.reportData[sec.value.id] = {}
  if (!props.reportData[sec.value.id]._extra) props.reportData[sec.value.id]._extra = []
  props.reportData[sec.value.id]._extra.push(blank)
  emit('save')
}

function removeExtra(eid) {
  if (!props.reportData[sec.value.id]?._extra) return
  props.reportData[sec.value.id]._extra = props.reportData[sec.value.id]._extra.filter(e => e._eid !== eid)
  emit('save')
}

// ── Hidden rows ───────────────────────────────────────────────────────
function isHidden(sectionId, rowId) {
  return (props.reportData[sectionId]?._hidden || []).includes(String(rowId))
}
function hideRow(sectionId, rowId) {
  if (!props.reportData[sectionId]) props.reportData[sectionId] = {}
  if (!props.reportData[sectionId]._hidden) props.reportData[sectionId]._hidden = []
  props.reportData[sectionId]._hidden.push(String(rowId))
  emit('save')
}

// ── Photos ────────────────────────────────────────────────────────────
const photoCache = ref({}) // key = "sectionId:rowId" → array of base64/url

function photoKey(sid, rid) { return `${sid}:${rid}` }

function getPhotoArr(sid, rid) {
  const k = photoKey(sid, rid)
  if (!photoCache.value[k]) {
    // Load from reportData _photos
    const stored = props.reportData[sid]?.[String(rid)]?._photos || []
    photoCache.value[k] = [...stored]
  }
  return photoCache.value[k]
}

async function takePhoto(sectionId, rowId) {
  try {
    const photo = await Camera.getPhoto({
      quality:      85,
      allowEditing: false,
      resultType:   CameraResultType.Base64,
      source:       CameraSource.Prompt, // Camera or Gallery
    })

    const base64 = `data:image/${photo.format};base64,${photo.base64String}`
    const k      = photoKey(sectionId, rowId)

    if (!photoCache.value[k]) photoCache.value[k] = []
    photoCache.value[k].push(base64)

    // Persist into reportData _photos array
    if (!props.reportData[sectionId]) props.reportData[sectionId] = {}
    if (!props.reportData[sectionId][String(rowId)]) props.reportData[sectionId][String(rowId)] = {}
    if (!props.reportData[sectionId][String(rowId)]._photos) props.reportData[sectionId][String(rowId)]._photos = []
    props.reportData[sectionId][String(rowId)]._photos.push(base64)

    // Save to filesystem + offline DB
    const filename = `${props.inspectionId}_${sectionId}_${rowId}_${Date.now()}.jpg`
    const filePath = await savePhotoToFilesystem(photo.base64String, filename)
    await savePhoto({
      id:            `ph_${Date.now()}`,
      inspection_id: props.inspectionId,
      section_id:    String(sectionId),
      item_id:       String(rowId),
      file_path:     filePath,
    })

    emit('save')
  } catch (err) {
    if (!err.message?.includes('cancelled')) console.error('Camera error:', err)
  }
}

function removePhoto(sectionId, rowId, idx) {
  const k = photoKey(sectionId, rowId)
  if (photoCache.value[k]) photoCache.value[k].splice(idx, 1)
  if (props.reportData[sectionId]?.[String(rowId)]?._photos) {
    props.reportData[sectionId][String(rowId)]._photos.splice(idx, 1)
  }
  emit('save')
}

// Lightbox
const lightbox = ref({ open: false, photos: [], idx: 0 })
function openLightbox(photos, idx) { lightbox.value = { open: true, photos, idx } }
function closeLightbox() { lightbox.value.open = false }

// ── Audio recording ───────────────────────────────────────────────────
const activeRecorder   = ref(null)
const recordingKey     = ref(null) // "sectionId:rowId" while recording
const recordingSeconds = ref(0)
let   recordingTimer   = null
const recordingChunks  = ref([])

function recKey(sid, rid) { return `${sid}:${rid}` }
function isRecording(sid, rid) { return recordingKey.value === recKey(sid, rid) }

async function toggleRecording(sid, rid, label) {
  const k = recKey(sid, rid)
  if (recordingKey.value === k) {
    // Stop
    clearInterval(recordingTimer)
    if (activeRecorder.value?.state !== 'inactive') activeRecorder.value.stop()
    recordingKey.value = null
    return
  }

  // Stop any current recording first
  if (activeRecorder.value && activeRecorder.value.state !== 'inactive') {
    activeRecorder.value.stop()
    await new Promise(r => setTimeout(r, 120))
  }

  let stream = null
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch {
    alert('Microphone access denied — please allow microphone permission in settings')
    return
  }

  const mr = new MediaRecorder(stream)
  activeRecorder.value  = mr
  recordingChunks.value = []
  recordingSeconds.value = 0
  recordingKey.value    = k

  mr.ondataavailable = e => { if (e.data.size > 0) recordingChunks.value.push(e.data) }
  mr.onstop = async () => {
    stream.getTracks().forEach(t => t.stop())
    if (recordingChunks.value.length === 0) return

    const blob     = new Blob(recordingChunks.value, { type: mr.mimeType || 'audio/webm' })
    const recId    = `rec_${Date.now()}`
    const filename = `${props.inspectionId}_${sid}_${rid}_${Date.now()}.webm`
    const filePath = await saveAudioToFilesystem(blob, filename)

    await saveRecording({
      id:            recId,
      inspection_id: props.inspectionId,
      item_key:      k,
      label,
      file_path:     filePath,
      mime_type:     mr.mimeType,
      duration:      recordingSeconds.value,
    })
  }

  mr.start(250)
  clearInterval(recordingTimer)
  recordingTimer = setInterval(() => recordingSeconds.value++, 1000)
}

// ── Cleanliness options ───────────────────────────────────────────────
const cleanlinessOpts = [
  'Professionally Cleaned',
  'Professionally Cleaned — Receipt Seen',
  'Professionally Cleaned with Omissions',
  'Domestically Cleaned',
  'Domestically Cleaned with Omissions',
  'Not Clean',
]
</script>

<template>
  <div class="mst-shell">

    <!-- ROOM TAB ─────────────────────────────────────────────────── -->
    <template v-if="isRoom && sec">
      <div class="mst-section-header">
        <h2 class="mst-section-title">{{ sec.name }}</h2>
      </div>

      <!-- Room overview photo -->
      <div class="mst-overview-photo-row">
        <button class="mst-cam-row-btn" @click="takePhoto(sec.id, '_overview')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          Room Overview Photo
          <span v-if="getPhotoArr(sec.id,'_overview').length" class="mst-cam-count">{{ getPhotoArr(sec.id,'_overview').length }}</span>
        </button>
      </div>
      <div v-if="getPhotoArr(sec.id,'_overview').length" class="mst-thumbs">
        <div v-for="(ph,pi) in getPhotoArr(sec.id,'_overview')" :key="pi" class="mst-thumb" @click="openLightbox(getPhotoArr(sec.id,'_overview'),pi)">
          <img :src="ph" />
          <button class="mst-thumb-del" @click.stop="removePhoto(sec.id,'_overview',pi)">×</button>
        </div>
      </div>

      <!-- Room items -->
      <div
        v-for="item in (sec.sections || sec.items || [])"
        :key="item.id"
        class="mst-item"
      >
        <div class="mst-item-header">
          <span class="mst-item-label">{{ item.label }}</span>
          <div class="mst-item-btns">
            <button
              class="mst-icon-btn"
              :class="{ 'mst-rec-active': isRecording(sec.id, item.id) }"
              @click="toggleRecording(sec.id, item.id, sec.name + ' — ' + item.label)"
            >
              <svg v-if="!isRecording(sec.id, item.id)" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
              <span v-else class="mst-rec-dot">● {{ recordingSeconds }}s</span>
            </button>
            <button class="mst-icon-btn mst-cam-btn" @click="takePhoto(sec.id, item.id)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              <span v-if="getPhotoArr(sec.id,item.id).length" class="mst-cam-count-sm">{{ getPhotoArr(sec.id,item.id).length }}</span>
            </button>
          </div>
        </div>

        <!-- Photo strip -->
        <div v-if="getPhotoArr(sec.id,item.id).length" class="mst-thumbs">
          <div v-for="(ph,pi) in getPhotoArr(sec.id,item.id)" :key="pi" class="mst-thumb" @click="openLightbox(getPhotoArr(sec.id,item.id),pi)">
            <img :src="ph" />
            <button class="mst-thumb-del" @click.stop="removePhoto(sec.id,item.id,pi)">×</button>
          </div>
        </div>

        <!-- Fields -->
        <div class="mst-fields">
          <div v-if="item.hasDescription" class="mst-field">
            <label class="mst-label">Description</label>
            <textarea class="mst-textarea" rows="3" :placeholder="`Describe ${item.label.toLowerCase()}…`"
              :value="get(sec.id, item.id, 'description')"
              @input="set(sec.id, item.id, 'description', $event.target.value)" />
          </div>
          <div v-if="item.hasCondition" class="mst-field">
            <label class="mst-label">Condition</label>
            <textarea class="mst-textarea" rows="3" :placeholder="`Condition of ${item.label.toLowerCase()}…`"
              :value="get(sec.id, item.id, 'condition')"
              @input="set(sec.id, item.id, 'condition', $event.target.value)" />
          </div>
          <div v-if="item.hasNotes" class="mst-field">
            <label class="mst-label">Notes</label>
            <input class="mst-input" type="text" placeholder="Notes…"
              :value="get(sec.id, item.id, 'notes')"
              @input="set(sec.id, item.id, 'notes', $event.target.value)" />
          </div>
        </div>
      </div>

      <!-- Extra rows (added on device) -->
      <div v-for="ex in extras" :key="ex._eid" class="mst-item mst-extra-item">
        <div class="mst-item-header">
          <input class="mst-input mst-extra-label-input" type="text" placeholder="Item name…"
            :value="ex.label"
            @input="ex.label = $event.target.value; emit('save')" />
          <div class="mst-item-btns">
            <button class="mst-icon-btn mst-cam-btn" @click="takePhoto(sec.id, ex._eid)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            </button>
            <button class="mst-icon-btn mst-del-btn" @click="removeExtra(ex._eid)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
            </button>
          </div>
        </div>
        <div class="mst-fields">
          <div class="mst-field">
            <label class="mst-label">Description</label>
            <textarea class="mst-textarea" rows="2" placeholder="Describe…"
              :value="ex.description"
              @input="ex.description = $event.target.value; emit('save')" />
          </div>
          <div class="mst-field">
            <label class="mst-label">Condition</label>
            <textarea class="mst-textarea" rows="2" placeholder="Condition…"
              :value="ex.condition"
              @input="ex.condition = $event.target.value; emit('save')" />
          </div>
        </div>
      </div>
    </template>

    <!-- FIXED SECTION TABS ───────────────────────────────────────── -->
    <template v-else-if="isFixed && sec">
      <div class="mst-section-header">
        <h2 class="mst-section-title">{{ sec.name }}</h2>
      </div>

      <!-- Condition Summary / Keys / Meters: row-per-item -->
      <template v-if="['condition_summary','keys','meter_readings'].includes(sec.type)">
        <div v-for="row in (sec.rows || [])" :key="row.id" v-show="!isHidden(sec.id, row.id)" class="mst-item">
          <div class="mst-item-header">
            <span class="mst-item-label">{{ row.name }}</span>
            <div class="mst-item-btns">
              <button class="mst-icon-btn" :class="{ 'mst-rec-active': isRecording(sec.id, row.id) }"
                @click="toggleRecording(sec.id, row.id, sec.name + ' — ' + row.name)">
                <svg v-if="!isRecording(sec.id, row.id)" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                <span v-else class="mst-rec-dot">● {{ recordingSeconds }}s</span>
              </button>
              <button class="mst-icon-btn mst-cam-btn" @click="takePhoto(sec.id, row.id)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                <span v-if="getPhotoArr(sec.id,row.id).length" class="mst-cam-count-sm">{{ getPhotoArr(sec.id,row.id).length }}</span>
              </button>
              <button class="mst-icon-btn mst-del-btn" @click="hideRow(sec.id, row.id)">×</button>
            </div>
          </div>
          <div class="mst-fields">
            <!-- Condition summary -->
            <div v-if="sec.type === 'condition_summary'" class="mst-field">
              <label class="mst-label">Condition</label>
              <input class="mst-input" type="text" placeholder="Describe condition…"
                :value="get(sec.id, row.id, 'condition')"
                @input="set(sec.id, row.id, 'condition', $event.target.value)" />
            </div>
            <!-- Keys -->
            <div v-if="sec.type === 'keys'" class="mst-field">
              <label class="mst-label">Description / Quantity</label>
              <input class="mst-input" type="text" placeholder="e.g. 2x Yale, 1x Deadlock"
                :value="get(sec.id, row.id, 'description')"
                @input="set(sec.id, row.id, 'description', $event.target.value)" />
            </div>
            <!-- Meter readings -->
            <template v-if="sec.type === 'meter_readings'">
              <div class="mst-field">
                <label class="mst-label">Location & Serial</label>
                <input class="mst-input" type="text" placeholder="e.g. Under stairs SN123456"
                  :value="get(sec.id, row.id, 'locationSerial')"
                  @input="set(sec.id, row.id, 'locationSerial', $event.target.value)" />
              </div>
              <div class="mst-field">
                <label class="mst-label">Reading</label>
                <input class="mst-input" type="text" placeholder="12345.6"
                  :value="get(sec.id, row.id, 'reading')"
                  @input="set(sec.id, row.id, 'reading', $event.target.value)" />
              </div>
            </template>
          </div>
        </div>
      </template>

      <!-- Cleaning Summary -->
      <template v-else-if="sec.type === 'cleaning_summary'">
        <div v-for="row in (sec.rows || [])" :key="row.id" v-show="!isHidden(sec.id, row.id)" class="mst-item">
          <div class="mst-item-header">
            <span class="mst-item-label">{{ row.name }}</span>
            <div class="mst-item-btns">
              <button class="mst-icon-btn" :class="{ 'mst-rec-active': isRecording(sec.id, row.id) }"
                @click="toggleRecording(sec.id, row.id, sec.name + ' — ' + row.name)">
                <svg v-if="!isRecording(sec.id, row.id)" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                <span v-else class="mst-rec-dot">● {{ recordingSeconds }}s</span>
              </button>
              <button class="mst-icon-btn mst-cam-btn" @click="takePhoto(sec.id, row.id)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              </button>
              <button class="mst-icon-btn mst-del-btn" @click="hideRow(sec.id, row.id)">×</button>
            </div>
          </div>
          <div class="mst-fields">
            <div class="mst-field">
              <label class="mst-label">Cleanliness</label>
              <select class="mst-input" :value="get(sec.id, row.id, 'cleanliness')"
                @change="set(sec.id, row.id, 'cleanliness', $event.target.value)">
                <option value="">Select…</option>
                <option v-for="o in cleanlinessOpts" :key="o" :value="o">{{ o }}</option>
              </select>
            </div>
            <div class="mst-field">
              <label class="mst-label">Notes</label>
              <input class="mst-input" type="text" placeholder="Additional notes…"
                :value="get(sec.id, row.id, 'cleanlinessNotes')"
                @input="set(sec.id, row.id, 'cleanlinessNotes', $event.target.value)" />
            </div>
          </div>
        </div>
      </template>

      <!-- QA sections (smoke alarms, health & safety, fire door) -->
      <template v-else-if="['smoke_alarms','health_safety','fire_door_safety'].includes(sec.type)">
        <div v-for="row in (sec.rows || [])" :key="row.id" v-show="!isHidden(sec.id, row.id)" class="mst-item">
          <div class="mst-item-header">
            <span class="mst-item-label">{{ row.question || row.name }}</span>
            <div class="mst-item-btns">
              <button class="mst-icon-btn" :class="{ 'mst-rec-active': isRecording(sec.id, row.id) }"
                @click="toggleRecording(sec.id, row.id, sec.name + ' — ' + (row.question || row.name))">
                <svg v-if="!isRecording(sec.id, row.id)" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                <span v-else class="mst-rec-dot">● {{ recordingSeconds }}s</span>
              </button>
              <button class="mst-icon-btn mst-cam-btn" @click="takePhoto(sec.id, row.id)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              </button>
              <button class="mst-icon-btn mst-del-btn" @click="hideRow(sec.id, row.id)">×</button>
            </div>
          </div>
          <div class="mst-fields">
            <div class="mst-field">
              <label class="mst-label">Answer</label>
              <select class="mst-input" :value="get(sec.id, row.id, 'answer')"
                @change="set(sec.id, row.id, 'answer', $event.target.value)">
                <option value="">Select…</option>
                <option>Yes</option><option>No</option><option>N/A</option>
                <option>Investigate</option><option>Pass</option><option>Fail</option>
              </select>
            </div>
            <div class="mst-field">
              <label class="mst-label">Notes</label>
              <input class="mst-input" type="text" placeholder="Notes…"
                :value="get(sec.id, row.id, 'notes')"
                @input="set(sec.id, row.id, 'notes', $event.target.value)" />
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- Add row button -->
    <div class="mst-add-row">
      <button class="mst-add-btn" @click="addExtraRow">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Add item
      </button>
    </div>

    <!-- Lightbox -->
    <div v-if="lightbox.open" class="mst-lightbox" @click.self="closeLightbox">
      <button class="mst-lb-close" @click="closeLightbox">✕</button>
      <img :src="lightbox.photos[lightbox.idx]" class="mst-lb-img" />
      <div class="mst-lb-nav">
        <button v-if="lightbox.idx > 0" @click="lightbox.idx--" class="mst-lb-arrow">‹</button>
        <span class="mst-lb-counter">{{ lightbox.idx + 1 }} / {{ lightbox.photos.length }}</span>
        <button v-if="lightbox.idx < lightbox.photos.length - 1" @click="lightbox.idx++" class="mst-lb-arrow">›</button>
      </div>
    </div>

  </div>
</template>

<style scoped>
.mst-shell {
  background: #0f172a;
  min-height: 100%;
  padding-bottom: 40px;
}

.mst-section-header {
  padding: 16px 20px 8px;
  border-bottom: 1px solid #1e293b;
}
.mst-section-title { font-size: 16px; font-weight: 800; color: #f1f5f9; margin: 0; }

.mst-overview-photo-row {
  padding: 12px 16px;
  border-bottom: 1px solid #1e293b;
}
.mst-cam-row-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
  padding: 10px 14px;
  cursor: pointer;
  width: 100%;
  font-family: inherit;
}
.mst-cam-count {
  margin-left: auto;
  background: #6366f1;
  color: white;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 10px;
}

/* Items */
.mst-item {
  border-bottom: 1px solid #1e293b;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mst-extra-item { background: #0a1628; }

.mst-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.mst-item-label {
  font-size: 14px;
  font-weight: 700;
  color: #e2e8f0;
  flex: 1;
  line-height: 1.3;
}
.mst-extra-label-input {
  flex: 1;
  font-weight: 700;
  font-size: 14px;
}

.mst-item-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.mst-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.12s;
  font-size: 12px;
  font-weight: 700;
  position: relative;
}
.mst-icon-btn:active { background: #334155; }
.mst-cam-btn { color: #64748b; }
.mst-del-btn { color: #f87171; border-color: #7f1d1d; }
.mst-rec-active {
  background: #dc2626 !important;
  border-color: #dc2626 !important;
  color: white !important;
}
.mst-rec-dot { font-size: 10px; white-space: nowrap; }
.mst-cam-count-sm {
  position: absolute;
  top: -4px;
  right: -4px;
  background: #6366f1;
  color: white;
  font-size: 9px;
  font-weight: 800;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Fields */
.mst-fields { display: flex; flex-direction: column; gap: 10px; }
.mst-field  { display: flex; flex-direction: column; gap: 4px; }
.mst-label  {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
}
.mst-input, .mst-textarea {
  width: 100%;
  padding: 10px 12px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  font-size: 14px;
  color: #f1f5f9;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s;
}
.mst-input:focus, .mst-textarea:focus { border-color: #6366f1; }
.mst-textarea { resize: none; line-height: 1.5; }

/* Photo thumbnails */
.mst-thumbs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.mst-thumb {
  width: 72px;
  height: 72px;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
}
.mst-thumb img { width: 100%; height: 100%; object-fit: cover; }
.mst-thumb-del {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  background: rgba(0,0,0,0.7);
  color: white;
  border: none;
  border-radius: 50%;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

/* Add row */
.mst-add-row { padding: 14px 16px; }
.mst-add-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  background: none;
  border: 1.5px dashed #334155;
  border-radius: 8px;
  color: #6366f1;
  font-size: 13px;
  font-weight: 700;
  padding: 10px 16px;
  cursor: pointer;
  width: 100%;
  font-family: inherit;
}

/* Lightbox */
.mst-lightbox {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.95);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.mst-lb-close {
  position: absolute;
  top: 20px;
  right: 20px;
  background: rgba(255,255,255,0.15);
  border: none;
  color: white;
  font-size: 20px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mst-lb-img {
  max-width: 95%;
  max-height: 75vh;
  border-radius: 8px;
  object-fit: contain;
}
.mst-lb-nav {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-top: 16px;
}
.mst-lb-arrow {
  background: rgba(255,255,255,0.15);
  border: none;
  color: white;
  font-size: 28px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mst-lb-counter { color: rgba(255,255,255,0.6); font-size: 14px; }
</style>
