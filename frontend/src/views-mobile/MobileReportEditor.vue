<script setup>
/**
 * MobileReportEditor.vue
 *
 * Tab-based report editor. Each fixed section and each room gets its own
 * tab. Tabs scroll horizontally. Swipe gesture switches between them.
 * Each tab renders a MobileSectionTab which contains all the item rows.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../services/api'
import {
  getInspection,
  getReportData,
  saveReportData,
} from '../services/offline'
import MobileSectionTab from './MobileSectionTab.vue'

const route  = useRoute()
const router = useRouter()

const id          = Number(route.params.id)
const inspection  = ref(null)
const template    = ref(null)
const reportData  = ref({})
const activeTab   = ref(0)
const saving      = ref(false)
const saved       = ref(false)

// Touch/swipe state
let touchStartX = 0

// ── Load ──────────────────────────────────────────────────────────────
onMounted(async () => {
  inspection.value = await getInspection(id)
  reportData.value = await getReportData(id)

  // Load template
  try {
    const iRes = await api.getInspection(id)
    inspection.value = iRes.data
    if (iRes.data.template_id) {
      const tRes = await api.getTemplate(iRes.data.template_id)
      template.value = tRes.data
    }
  } catch { /* offline — no template update */ }

  // Default to first tab
  if (tabs.value.length) activeTab.value = 0
})

// ── Tabs ──────────────────────────────────────────────────────────────
const fixedSections = computed(() =>
  (template.value?.sections || []).filter(s => !s.is_room)
)
const rooms = computed(() =>
  (template.value?.sections || []).filter(s => s.is_room)
)

const tabs = computed(() => [
  ...fixedSections.value.map(s => ({ type: 'fixed', section: s, id: s.id, label: s.name })),
  ...rooms.value.map(r      => ({ type: 'room',  section: r, id: r.id, label: r.name })),
  { type: 'add', id: '__add__', label: '+ Add' },
])

// Short display label for tabs (truncate)
function tabShortLabel(label) {
  if (label.length <= 10) return label
  return label.slice(0, 9) + '…'
}

// ── Report data helpers ───────────────────────────────────────────────
function get(sectionId, rowId, field) {
  return reportData.value[sectionId]?.[String(rowId)]?.[field] ?? ''
}

function set(sectionId, rowId, field, value) {
  if (!reportData.value[sectionId]) reportData.value[sectionId] = {}
  if (!reportData.value[sectionId][String(rowId)]) reportData.value[sectionId][String(rowId)] = {}
  reportData.value[sectionId][String(rowId)][field] = value
  scheduleSave()
}

// ── Auto-save ─────────────────────────────────────────────────────────
let saveTimer = null
function scheduleSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(doSave, 2000)
}

async function doSave() {
  saving.value = true
  await saveReportData(id, reportData.value)
  // Also attempt server push if online
  try { await api.updateInspection(id, { report_data: JSON.stringify(reportData.value) }) }
  catch { /* offline — sync queue handles it */ }
  saving.value = false
  saved.value  = true
  setTimeout(() => { saved.value = false }, 2000)
}

// ── Add room / section ────────────────────────────────────────────────
function handleAddTab() {
  // For now show an action sheet (native) or a simple prompt
  // Full implementation: show a bottom sheet with options:
  // "Add Room" | "Add Fixed Section"
  // These would add extra items to reportData and refresh tabs
  alert('Add Room / Section — bottom sheet coming in next build')
}

// ── Swipe between tabs ────────────────────────────────────────────────
function onTouchStart(e) { touchStartX = e.touches[0].clientX }
function onTouchEnd(e) {
  const dx = e.changedTouches[0].clientX - touchStartX
  if (Math.abs(dx) < 60) return
  if (dx < 0 && activeTab.value < tabs.value.length - 1) activeTab.value++
  if (dx > 0 && activeTab.value > 0) activeTab.value--
}
</script>

<template>
  <div class="mre-shell" @touchstart.passive="onTouchStart" @touchend.passive="onTouchEnd">

    <!-- Nav bar -->
    <header class="mre-nav">
      <button class="mre-back" @click="router.push(`/mobile/inspection/${id}`)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <div class="mre-nav-center">
        <span class="mre-nav-addr">{{ inspection?.property_address?.split(',')[0] }}</span>
      </div>
      <div class="mre-save-indicator">
        <svg v-if="saving" class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
        <svg v-else-if="saved" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
      </div>
    </header>

    <!-- Tab strip -->
    <div class="mre-tabs-wrap">
      <div class="mre-tabs" role="tablist">
        <button
          v-for="(tab, idx) in tabs"
          :key="tab.id"
          class="mre-tab"
          :class="{ active: activeTab === idx, 'tab-add': tab.type === 'add' }"
          @click="tab.type === 'add' ? handleAddTab() : (activeTab = idx)"
          role="tab"
        >
          {{ tabShortLabel(tab.label) }}
        </button>
      </div>
    </div>

    <!-- Active section content -->
    <div class="mre-content" v-if="tabs[activeTab] && tabs[activeTab].type !== 'add'">
      <MobileSectionTab
        :key="tabs[activeTab].id"
        :tab="tabs[activeTab]"
        :inspection-id="id"
        :inspection="inspection"
        :report-data="reportData"
        :template="template"
        @set="(sid, rid, field, val) => set(sid, rid, field, val)"
        @save="doSave"
      />
    </div>

    <!-- No template -->
    <div v-else-if="!template" class="mre-no-template">
      <p>Loading template…</p>
    </div>

  </div>
</template>

<style scoped>
.mre-shell {
  height: 100vh;
  background: #0f172a;
  color: #f1f5f9;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Nav */
.mre-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 50px 14px 10px;
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
  flex-shrink: 0;
}
.mre-back {
  background: none; border: none; color: #94a3b8; cursor: pointer; padding: 4px;
}
.mre-nav-center { flex: 1; text-align: center; }
.mre-nav-addr { font-size: 14px; font-weight: 700; color: #f1f5f9; }
.mre-save-indicator {
  width: 24px; height: 24px; display: flex; align-items: center; justify-content: center;
}

/* Tab strip */
.mre-tabs-wrap {
  background: #0f172a;
  border-bottom: 2px solid #1e293b;
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
}
.mre-tabs-wrap::-webkit-scrollbar { display: none; }
.mre-tabs {
  display: flex;
  gap: 0;
  padding: 0 6px;
  width: max-content;
  min-width: 100%;
}
.mre-tab {
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  background: none;
  border: none;
  border-bottom: 3px solid transparent;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s, border-color 0.15s;
  font-family: inherit;
  margin-bottom: -2px;
}
.mre-tab.active {
  color: #a5b4fc;
  border-bottom-color: #6366f1;
}
.mre-tab.tab-add {
  color: #4ade80;
  font-weight: 700;
}
.mre-tab.tab-add:active { color: #22c55e; }

/* Content */
.mre-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
}

.mre-no-template {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  font-size: 14px;
}

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }
</style>
