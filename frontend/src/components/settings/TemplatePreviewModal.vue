<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  template: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['close'])

// Demo branding values — these will come from Settings > Reports > Client config at runtime
const demoBranding = {
  primaryColor: '#1E3A8A',
  clientName: 'Yellands Estates',
  logoText: 'YE', // initials fallback when no logo uploaded
  hasLogo: false
}

// Parse template content
const content = computed(() => {
  try {
    return JSON.parse(props.template.content)
  } catch {
    return { fixedSections: [], rooms: [] }
  }
})

const fixedSections = computed(() => content.value.fixedSections || [])
const rooms = computed(() => content.value.rooms || [])
const enabledFixedSections = computed(() => fixedSections.value.filter(s => s.enabled))
const enabledRooms = computed(() => rooms.value.filter(r => r.enabled))

// Table of contents items
const tocItems = computed(() => {
  const items = []
  let pageNum = 3 // cover=1, contents=2, disclaimer=3 (if exists), then sections

  // Fixed sections
  enabledFixedSections.value.forEach(section => {
    items.push({ title: section.name, page: pageNum++ })
  })

  // Room sections
  enabledRooms.value.forEach(room => {
    items.push({ title: room.name, page: pageNum++ })
  })

  return items
})

const inspectionTypeLabel = computed(() => {
  const map = {
    check_in: 'Check In Report',
    check_out: 'Check Out Report',
    interim: 'Interim Inspection Report',
    inventory: 'Inventory Report'
  }
  return map[props.template.inspection_type] || props.template.inspection_type
})

const today = new Date().toLocaleDateString('en-GB', {
  day: '2-digit', month: 'long', year: 'numeric'
})

// Active page for scrolling/navigation
const previewContainer = ref(null)

function close() {
  emit('close')
}

function handleKeydown(e) {
  if (e.key === 'Escape') close()
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
  document.body.style.overflow = 'hidden'
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  document.body.style.overflow = ''
})

const cleanlinessOptions = [
  'Professionally Cleaned',
  'Professionally Cleaned - Receipt Seen',
  'Professionally Cleaned with Omissions',
  'Domestically Cleaned',
  'Domestically Cleaned with Omissions',
  'Not Clean'
]
</script>

<template>
  <div class="preview-overlay" @click.self="close">
    <!-- Top bar -->
    <div class="preview-topbar">
      <div class="topbar-left">
        <div class="preview-label">
          <span class="preview-dot"></span>
          Report Preview
        </div>
        <span class="template-title-pill">{{ template.name }}</span>
        <span class="type-pill">{{ inspectionTypeLabel }}</span>
      </div>
      <div class="topbar-right">
        <div class="branding-note">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Branding uses demo values — configure per client in Settings › Reports
        </div>
        <button class="btn-close" @click="close">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          Close Preview
        </button>
      </div>
    </div>

    <!-- Pages scroll area -->
    <div class="preview-scroll" ref="previewContainer">
      <div class="pages-wrapper">

        <!-- ═══════════════════════════════════════════ -->
        <!-- PAGE 1: COVER PAGE                          -->
        <!-- ═══════════════════════════════════════════ -->
        <div class="page-label">Cover Page</div>
        <div class="a4-page cover-page" :style="{ '--brand': demoBranding.primaryColor }">
          <!-- Full bleed colour top section -->
          <div class="cover-top">
            <!-- Centred logo — 600px wide, no border, auto height -->
            <div class="cover-logo-centered">
              <img v-if="demoBranding.hasLogo" :src="demoBranding.logoUrl" alt="Client logo" class="cover-logo-img" />
              <div v-else class="cover-logo-fallback">
                <span class="logo-initials">{{ demoBranding.logoText }}</span>
              </div>
            </div>

            <!-- Inspection type badge -->
            <div class="cover-type-badge">{{ inspectionTypeLabel }}</div>
          </div>

          <!-- Property overview photo — 600px wide, auto height, object-fit cover -->
          <div class="cover-photo-area">
            <img v-if="demoBranding.hasPhoto" :src="demoBranding.photoUrl" alt="Property overview" class="cover-photo-img" />
            <div v-else class="photo-placeholder">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              <span>Property Overview Photo</span>
            </div>
          </div>

          <!-- Cover bottom info strip -->
          <div class="cover-bottom">
            <div class="cover-info-grid">
              <div class="cover-info-item">
                <div class="cover-info-label">Property Address</div>
                <div class="cover-info-value">12 Example Street, London, SW1A 1AA</div>
              </div>
              <div class="cover-info-item">
                <div class="cover-info-label">Inspection Date</div>
                <div class="cover-info-value">{{ today }}</div>
              </div>
              <div class="cover-info-item">
                <div class="cover-info-label">Inspector / Clerk</div>
                <div class="cover-info-value">Robyn Lee</div>
              </div>
              <div class="cover-info-item">
                <div class="cover-info-label">Report Reference</div>
                <div class="cover-info-value">CHK-2026-0001</div>
              </div>
            </div>
            <div class="cover-footer-strip" :style="{ background: demoBranding.primaryColor }">
              <span>Prepared by L&amp;M Inventories</span>
              <span>Confidential</span>
            </div>
          </div>
        </div>

        <!-- ═══════════════════════════════════════════ -->
        <!-- PAGE 2: TABLE OF CONTENTS                   -->
        <!-- ═══════════════════════════════════════════ -->
        <div class="page-label">Contents</div>
        <div class="a4-page" :style="{ '--brand': demoBranding.primaryColor }">
          <div class="page-header-bar" :style="{ background: demoBranding.primaryColor }">
            <span class="page-header-title">Table of Contents</span>
            <span class="page-header-logo">{{ demoBranding.logoText }}</span>
          </div>

          <div class="toc-body">
            <!-- Standard front matter entries -->
            <div class="toc-section-group">
              <div class="toc-group-label">Report Overview</div>
              <div class="toc-entry toc-entry--fixed">
                <span class="toc-dot-line"></span>
                <span class="toc-title">Cover Page</span>
                <span class="toc-dots"></span>
                <span class="toc-page">1</span>
              </div>
              <div class="toc-entry toc-entry--fixed">
                <span class="toc-dot-line"></span>
                <span class="toc-title">Table of Contents</span>
                <span class="toc-dots"></span>
                <span class="toc-page">2</span>
              </div>
              <div class="toc-entry toc-entry--fixed">
                <span class="toc-dot-line"></span>
                <span class="toc-title">Disclaimer & Terms</span>
                <span class="toc-dots"></span>
                <span class="toc-page">3</span>
              </div>
            </div>

            <!-- Template sections -->
            <div class="toc-section-group" v-if="enabledFixedSections.length > 0">
              <div class="toc-group-label">Report Sections</div>
              <div 
                v-for="(item, i) in tocItems.filter((_, idx) => idx < enabledFixedSections.length)" 
                :key="'fixed-' + i"
                class="toc-entry"
              >
                <span class="toc-number">{{ i + 1 }}</span>
                <span class="toc-title">{{ item.title }}</span>
                <span class="toc-dots"></span>
                <span class="toc-page">{{ item.page }}</span>
              </div>
            </div>

            <!-- Rooms -->
            <div class="toc-section-group" v-if="enabledRooms.length > 0">
              <div class="toc-group-label">Property Rooms</div>
              <div 
                v-for="(item, i) in tocItems.filter((_, idx) => idx >= enabledFixedSections.length)" 
                :key="'room-' + i"
                class="toc-entry"
              >
                <span class="toc-number">{{ enabledFixedSections.length + i + 1 }}</span>
                <span class="toc-title">{{ item.title }}</span>
                <span class="toc-dots"></span>
                <span class="toc-page">{{ item.page }}</span>
              </div>
            </div>
          </div>

          <div class="page-footer">
            <span>{{ demoBranding.clientName }} · {{ inspectionTypeLabel }}</span>
            <span>Page 2</span>
          </div>
        </div>

        <!-- ═══════════════════════════════════════════ -->
        <!-- PAGE 3: DISCLAIMER                          -->
        <!-- ═══════════════════════════════════════════ -->
        <div class="page-label">Disclaimer</div>
        <div class="a4-page" :style="{ '--brand': demoBranding.primaryColor }">
          <div class="page-header-bar" :style="{ background: demoBranding.primaryColor }">
            <span class="page-header-title">Disclaimer & Terms</span>
            <span class="page-header-logo">{{ demoBranding.logoText }}</span>
          </div>

          <div class="disclaimer-body">
            <div class="disclaimer-placeholder">
              <div class="disclaimer-icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--brand)" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
              </div>
              <h3>Disclaimer Text</h3>
              <p>Your disclaimer content will appear here. Configure it in <strong>Settings › Reports</strong> — you can set different disclaimer text per client.</p>
            </div>

            <!-- Placeholder lines to simulate text -->
            <div class="placeholder-text-block">
              <div class="placeholder-line placeholder-line--full"></div>
              <div class="placeholder-line placeholder-line--full"></div>
              <div class="placeholder-line placeholder-line--80"></div>
              <div class="placeholder-line"></div>
              <div class="placeholder-line placeholder-line--full"></div>
              <div class="placeholder-line placeholder-line--full"></div>
              <div class="placeholder-line placeholder-line--60"></div>
              <div class="placeholder-line"></div>
              <div class="placeholder-line placeholder-line--full"></div>
              <div class="placeholder-line placeholder-line--70"></div>
            </div>
          </div>

          <div class="page-footer">
            <span>{{ demoBranding.clientName }} · {{ inspectionTypeLabel }}</span>
            <span>Page 3</span>
          </div>
        </div>

        <!-- ═══════════════════════════════════════════ -->
        <!-- FIXED SECTIONS                              -->
        <!-- ═══════════════════════════════════════════ -->
        <template v-for="(section, sIdx) in enabledFixedSections" :key="'fs-' + sIdx">
          <div class="page-label">{{ section.name }}</div>
          <div class="a4-page" :style="{ '--brand': demoBranding.primaryColor }">
            <div class="page-header-bar" :style="{ background: demoBranding.primaryColor }">
              <span class="page-header-title">{{ section.name }}</span>
              <span class="page-header-logo">{{ demoBranding.logoText }}</span>
            </div>

            <div class="section-body">

              <!-- CONDITION SUMMARY -->
              <template v-if="section.type === 'condition_summary'">
                <table class="report-table">
                  <thead>
                    <tr>
                      <th class="col-name">Item</th>
                      <th class="col-condition">Condition</th>
                      <th class="col-photo">Photos</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rIdx) in section.rows" :key="rIdx" :class="{ 'row-alt': rIdx % 2 === 1 }">
                      <td>{{ row.name || '—' }}</td>
                      <td>
                        <span v-if="row.condition" class="condition-badge">{{ row.condition }}</span>
                        <span v-else class="empty-cell">—</span>
                      </td>
                      <td class="photo-cell"><span class="photo-stub">📷</span></td>
                    </tr>
                  </tbody>
                </table>
              </template>

              <!-- CLEANING SUMMARY -->
              <template v-else-if="section.type === 'cleaning_summary'">
                <table class="report-table">
                  <thead>
                    <tr>
                      <th class="col-name">Area</th>
                      <th>Cleanliness</th>
                      <th>Notes</th>
                      <th class="col-photo">Photos</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rIdx) in section.rows" :key="rIdx" :class="{ 'row-alt': rIdx % 2 === 1 }">
                      <td>{{ row.name || '—' }}</td>
                      <td>
                        <span v-if="row.cleanliness" class="cleanliness-badge" :class="{ 'clean': row.cleanliness.startsWith('Prof'), 'domestic': row.cleanliness.startsWith('Dom'), 'notclean': row.cleanliness === 'Not Clean' }">
                          {{ row.cleanliness }}
                        </span>
                        <span v-else class="empty-cell">—</span>
                      </td>
                      <td class="notes-cell">{{ row.cleanlinessNotes || '—' }}</td>
                      <td class="photo-cell"><span class="photo-stub">📷</span></td>
                    </tr>
                  </tbody>
                </table>
              </template>

              <!-- SMOKE ALARMS / HEALTH & SAFETY -->
              <template v-else-if="section.type === 'smoke_alarms' || section.type === 'health_safety'">
                <table class="report-table">
                  <thead>
                    <tr>
                      <th>Question</th>
                      <th class="col-answer">Answer</th>
                      <th>Notes</th>
                      <th class="col-photo">Photos</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rIdx) in section.rows" :key="rIdx" :class="{ 'row-alt': rIdx % 2 === 1 }">
                      <td>{{ row.question || '—' }}</td>
                      <td class="answer-cell">
                        <span v-if="row.answer" class="answer-badge" :class="{ 'yes': row.answer === 'Yes', 'no': row.answer === 'No', 'na': row.answer === 'N/A' }">
                          {{ row.answer }}
                        </span>
                        <span v-else class="empty-cell">—</span>
                      </td>
                      <td>{{ row.notes || '—' }}</td>
                      <td class="photo-cell"><span class="photo-stub">📷</span></td>
                    </tr>
                  </tbody>
                </table>
              </template>

              <!-- FIRE DOOR SAFETY -->
              <template v-else-if="section.type === 'fire_door_safety'">
                <table class="report-table">
                  <thead>
                    <tr>
                      <th class="col-name">Location</th>
                      <th>Question</th>
                      <th class="col-answer">Answer</th>
                      <th>Notes</th>
                      <th class="col-photo">Photos</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rIdx) in section.rows" :key="rIdx" :class="{ 'row-alt': rIdx % 2 === 1 }">
                      <td>{{ row.name || '—' }}</td>
                      <td>{{ row.question || '—' }}</td>
                      <td class="answer-cell">
                        <span v-if="row.answer" class="answer-badge" :class="{ 'yes': row.answer === 'Yes', 'no': row.answer === 'No', 'na': row.answer === 'N/A' }">
                          {{ row.answer }}
                        </span>
                        <span v-else class="empty-cell">—</span>
                      </td>
                      <td>{{ row.notes || '—' }}</td>
                      <td class="photo-cell"><span class="photo-stub">📷</span></td>
                    </tr>
                  </tbody>
                </table>
              </template>

              <!-- KEYS & ACCESS -->
              <template v-else-if="section.type === 'keys'">
                <table class="report-table">
                  <thead>
                    <tr>
                      <th class="col-name">Key / Access Item</th>
                      <th>Description / Notes</th>
                      <th class="col-photo">Photos</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rIdx) in section.rows" :key="rIdx" :class="{ 'row-alt': rIdx % 2 === 1 }">
                      <td>{{ row.name || '—' }}</td>
                      <td>{{ row.description || '—' }}</td>
                      <td class="photo-cell"><span class="photo-stub">📷</span></td>
                    </tr>
                  </tbody>
                </table>
              </template>

              <!-- METER READINGS -->
              <template v-else-if="section.type === 'meter_readings'">
                <table class="report-table">
                  <thead>
                    <tr>
                      <th class="col-name">Meter</th>
                      <th>Location & Serial No.</th>
                      <th class="col-reading">Reading</th>
                      <th class="col-photo">Photos</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rIdx) in section.rows" :key="rIdx" :class="{ 'row-alt': rIdx % 2 === 1 }">
                      <td>{{ row.name || '—' }}</td>
                      <td>{{ row.locationSerial || '—' }}</td>
                      <td class="reading-cell">{{ row.reading || '—' }}</td>
                      <td class="photo-cell"><span class="photo-stub">📷</span></td>
                    </tr>
                  </tbody>
                </table>
              </template>

            </div>

            <div class="page-footer">
              <span>{{ demoBranding.clientName }} · {{ inspectionTypeLabel }}</span>
              <span>Page {{ sIdx + 4 }}</span>
            </div>
          </div>
        </template>

        <!-- ═══════════════════════════════════════════ -->
        <!-- ROOM SECTIONS                               -->
        <!-- ═══════════════════════════════════════════ -->
        <template v-for="(room, rIdx) in enabledRooms" :key="'room-' + rIdx">
          <div class="page-label">Room: {{ room.name }}</div>
          <div class="a4-page" :style="{ '--brand': demoBranding.primaryColor }">
            <div class="page-header-bar" :style="{ background: demoBranding.primaryColor }">
              <span class="page-header-title">{{ room.name }}</span>
              <span class="page-header-logo">{{ demoBranding.logoText }}</span>
            </div>

            <div class="section-body">
              <!-- Room photo strip -->
              <div class="room-photo-strip">
                <div class="room-photo-thumb">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                </div>
                <div class="room-photo-thumb">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                </div>
                <div class="room-photo-thumb">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                </div>
                <div class="room-photo-label">Room overview photos</div>
              </div>

              <table class="report-table">
                <thead>
                  <tr>
                    <th class="col-room-item">Item</th>
                    <th>Description</th>
                    <th class="col-condition">Condition</th>
                    <th class="col-photo">Photos</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(section, sIdx) in room.sections" :key="sIdx" :class="{ 'row-alt': sIdx % 2 === 1 }">
                    <td class="item-label">{{ section.label }}</td>
                    <td>
                      <span v-if="section.hasDescription" class="field-placeholder">Description / notes</span>
                      <span v-else class="empty-cell">N/A</span>
                    </td>
                    <td>
                      <span v-if="section.hasCondition" class="field-placeholder condition-placeholder">Condition</span>
                      <span v-else class="empty-cell">N/A</span>
                    </td>
                    <td class="photo-cell"><span class="photo-stub">📷</span></td>
                  </tr>
                </tbody>
              </table>

              <div class="room-notes-area">
                <div class="room-notes-label">General Notes for {{ room.name }}</div>
                <div class="room-notes-box"></div>
              </div>
            </div>

            <div class="page-footer">
              <span>{{ demoBranding.clientName }} · {{ inspectionTypeLabel }}</span>
              <span>Page {{ enabledFixedSections.length + rIdx + 4 }}</span>
            </div>
          </div>
        </template>

        <!-- Empty state if template has nothing -->
        <div v-if="enabledFixedSections.length === 0 && enabledRooms.length === 0" class="empty-template-notice">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <p>This template has no enabled sections or rooms yet.<br>Edit the template to add content.</p>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
/* ─── OVERLAY ──────────────────────────────────────── */
.preview-overlay {
  position: fixed;
  inset: 0;
  background: #0f172a;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  font-family: 'Georgia', 'Times New Roman', serif;
}

/* ─── TOP BAR ──────────────────────────────────────── */
.preview-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 52px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  flex-shrink: 0;
  gap: 16px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.preview-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 1px;
  white-space: nowrap;
}

.preview-dot {
  width: 8px;
  height: 8px;
  background: #ef4444;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.template-title-pill {
  padding: 4px 10px;
  background: #334155;
  color: #e2e8f0;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}

.type-pill {
  padding: 4px 10px;
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.branding-note {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.branding-note svg {
  flex-shrink: 0;
  color: #f59e0b;
}

.btn-close {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: #334155;
  color: #e2e8f0;
  border: 1px solid #475569;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn-close:hover {
  background: #475569;
}

/* ─── SCROLL AREA ──────────────────────────────────── */
.preview-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: auto;
  padding: 32px 24px 60px;
  background: #0f172a;
}

.pages-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.page-label {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  align-self: flex-start;
  margin-left: calc(50% - 396px);
  margin-top: 20px;
  margin-bottom: 4px;
}

/* ─── A4 PAGE ──────────────────────────────────────── */
.a4-page {
  width: 794px; /* A4 at 96dpi */
  min-height: 1123px;
  background: white;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4), 0 1px 4px rgba(0, 0, 0, 0.3);
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ─── COVER PAGE ───────────────────────────────────── */
.cover-page {
  font-family: 'Georgia', 'Times New Roman', serif;
}

.cover-top {
  background: var(--brand);
  padding: 48px 56px 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.cover-logo-centered {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
}

/* Real logo — 600px wide, no border, height auto */
.cover-logo-img {
  width: 600px;
  max-width: 100%;
  height: auto;
  display: block;
}

/* Fallback initials box when no logo uploaded */
.cover-logo-fallback {
  width: 600px;
  max-width: 100%;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.12);
}

.logo-initials {
  font-size: 32px;
  font-weight: 700;
  color: white;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  letter-spacing: -1px;
  opacity: 0.6;
}

.cover-type-badge {
  display: inline-block;
  padding: 10px 20px;
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 6px;
  color: white;
  font-size: 18px;
  font-weight: 400;
  font-family: 'Georgia', serif;
  letter-spacing: 0.5px;
  align-self: flex-start;
}

.cover-photo-area {
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

/* Real photo — 600px wide, height auto, never distorted */
.cover-photo-img {
  width: 600px;
  max-width: 100%;
  height: auto;
  display: block;
  object-fit: cover;
}

.photo-placeholder {
  width: 600px;
  max-width: 100%;
  min-height: 340px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #94a3b8;
  font-size: 14px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.cover-bottom {
  background: white;
}

.cover-info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border-top: 2px solid var(--brand);
}

.cover-info-item {
  padding: 20px 28px;
  border-right: 1px solid #e5e7eb;
  border-bottom: 1px solid #e5e7eb;
}

.cover-info-item:nth-child(even) {
  border-right: none;
}

.cover-info-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #94a3b8;
  margin-bottom: 4px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.cover-info-value {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.cover-footer-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 28px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-weight: 500;
}

/* ─── PAGE HEADER BAR ──────────────────────────────── */
.page-header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 32px;
  flex-shrink: 0;
}

.page-header-title {
  font-size: 15px;
  font-weight: 700;
  color: white;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  letter-spacing: 0.3px;
}

.page-header-logo {
  font-size: 13px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.7);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* ─── TABLE OF CONTENTS ────────────────────────────── */
.toc-body {
  flex: 1;
  padding: 40px 56px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.toc-section-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.toc-group-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #94a3b8;
  margin-bottom: 8px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  padding-bottom: 6px;
  border-bottom: 1px solid #e5e7eb;
}

.toc-entry {
  display: grid;
  grid-template-columns: 24px 1fr auto 32px;
  align-items: baseline;
  gap: 8px;
  padding: 6px 0;
  font-size: 14px;
  color: #334155;
}

.toc-entry--fixed .toc-number,
.toc-entry--fixed .toc-dot-line {
  display: block;
}

.toc-number {
  font-size: 11px;
  color: var(--brand);
  font-weight: 700;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  text-align: center;
}

.toc-dot-line {
  display: block;
}

.toc-title {
  font-family: 'Georgia', serif;
  font-size: 14px;
}

.toc-dots {
  border-bottom: 1.5px dotted #cbd5e1;
  flex: 1;
  align-self: center;
}

.toc-page {
  font-size: 13px;
  font-weight: 700;
  color: var(--brand);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  text-align: right;
  min-width: 24px;
}

/* ─── DISCLAIMER ───────────────────────────────────── */
.disclaimer-body {
  flex: 1;
  padding: 40px 56px;
}

.disclaimer-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 32px;
  background: #f8fafc;
  border: 2px dashed #e2e8f0;
  border-radius: 12px;
  margin-bottom: 32px;
  gap: 12px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.disclaimer-icon {
  padding: 12px;
  background: white;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.disclaimer-placeholder h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.disclaimer-placeholder p {
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
}

.placeholder-text-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.placeholder-line {
  height: 10px;
  background: #f1f5f9;
  border-radius: 4px;
  width: 90%;
}

.placeholder-line--full { width: 100%; }
.placeholder-line--80 { width: 80%; }
.placeholder-line--70 { width: 70%; }
.placeholder-line--60 { width: 60%; }

/* ─── SECTION BODY ─────────────────────────────────── */
.section-body {
  flex: 1;
  padding: 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ─── REPORT TABLE ─────────────────────────────────── */
.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.report-table thead {
  background: var(--brand);
}

.report-table th {
  padding: 10px 14px;
  text-align: left;
  font-size: 11px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border: none;
}

.report-table td {
  padding: 10px 14px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
  vertical-align: middle;
  line-height: 1.5;
}

.row-alt td {
  background: #f8fafc;
}

.col-name { width: 22%; }
.col-room-item { width: 20%; }
.col-condition { width: 20%; }
.col-answer { width: 100px; }
.col-photo { width: 72px; text-align: center; }
.col-reading { width: 100px; }

.photo-cell { text-align: center; }
.photo-stub { font-size: 14px; opacity: 0.4; }
.answer-cell { text-align: center; }
.reading-cell { font-family: 'Courier New', monospace; font-weight: 600; }
.notes-cell { font-size: 11px; color: #64748b; }
.item-label { font-weight: 600; color: #1e293b; }
.empty-cell { color: #cbd5e1; font-size: 11px; }

/* Badges */
.condition-badge {
  display: inline-block;
  padding: 2px 8px;
  background: #dbeafe;
  color: #1e40af;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.cleanliness-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}
.cleanliness-badge.clean { background: #dcfce7; color: #166534; }
.cleanliness-badge.domestic { background: #fef9c3; color: #854d0e; }
.cleanliness-badge.notclean { background: #fee2e2; color: #991b1b; }

.answer-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
}
.answer-badge.yes { background: #dcfce7; color: #166534; }
.answer-badge.no { background: #fee2e2; color: #991b1b; }
.answer-badge.na { background: #f1f5f9; color: #64748b; }

.field-placeholder {
  color: #cbd5e1;
  font-style: italic;
  font-size: 11px;
}

.condition-placeholder {
  display: inline-block;
  padding: 2px 8px;
  background: #f1f5f9;
  border-radius: 4px;
}

/* ─── ROOM PHOTO STRIP ─────────────────────────────── */
.room-photo-strip {
  display: flex;
  gap: 8px;
  align-items: center;
  background: #f8fafc;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.room-photo-thumb {
  width: 80px;
  height: 60px;
  background: #e2e8f0;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.room-photo-label {
  font-size: 11px;
  color: #94a3b8;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  margin-left: 4px;
}

/* ─── ROOM NOTES ───────────────────────────────────── */
.room-notes-area {
  margin-top: 8px;
}

.room-notes-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #94a3b8;
  margin-bottom: 6px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.room-notes-box {
  height: 60px;
  border: 1px dashed #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
}

/* ─── PAGE FOOTER ──────────────────────────────────── */
.page-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 32px;
  border-top: 1px solid #f1f5f9;
  font-size: 10px;
  color: #94a3b8;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  flex-shrink: 0;
}

/* ─── EMPTY STATE ──────────────────────────────────── */
.empty-template-notice {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 80px;
  color: #64748b;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  text-align: center;
  line-height: 1.6;
}
</style>
