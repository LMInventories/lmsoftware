<script setup>
/**
 * CheckOutActionPicker
 *
 * Used on each room item in the Check Out report editor.
 * Shows assigned action tags as coloured pills; clicking opens an inline
 * dropdown to add/remove tags and set a responsibility party.
 *
 * Props:
 *   actions  — array of assigned action objects: [{ actionId, responsibility, conditions }]
 *   roomId   — string (for keying)
 *   itemId   — string (for keying)
 *
 * Emits:
 *   update:actions — new array of action objects
 *
 * Action object shape (stored in reportData):
 *   { actionId: string, responsibility: string, conditions: string[] }
 *   (backward compat: legacy `condition: string` is read as `[condition]`)
 */

import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import api from '../services/api'

const props = defineProps({
  actions:        { type: Array,  default: () => [] },
  roomId:         { type: String, default: '' },
  itemId:         { type: String, default: '' },
  conditionText:  { type: String, default: '' },
})

// ── Condition lines — split the checkOutCondition textarea by newline ─────
const conditionLines = computed(() => {
  if (!props.conditionText) return []
  return props.conditionText
    .split('\n')
    .map(l => l.trim())
    .filter(Boolean)
})
const emit = defineEmits(['update:actions'])

// ── Global action catalogue (loaded once per page) ────────────────────────
// Shared across all picker instances via module-level cache
const _catalogueCache = { loaded: false, actions: [], responsibilities: [] }

const catalogue      = ref([])
const responsibilities = ref([])

onMounted(async () => {
  if (_catalogueCache.loaded) {
    catalogue.value       = _catalogueCache.actions
    responsibilities.value = _catalogueCache.responsibilities
    return
  }
  try {
    const res = await api.getActions()
    catalogue.value       = res.data.actions         || []
    responsibilities.value = res.data.responsibilities || []
    _catalogueCache.actions          = catalogue.value
    _catalogueCache.responsibilities = responsibilities.value
    _catalogueCache.loaded           = true
  } catch {
    // fail silently — picker just won't show options
  }
})

// ── Picker open/close ─────────────────────────────────────────────────────
const open      = ref(false)
const pickerEl  = ref(null)
const toggleBtn = ref(null)

const dropdownStyle = ref({})

function positionDropdown() {
  if (!toggleBtn.value) return
  const rect = toggleBtn.value.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom
  const dropH = 480

  if (spaceBelow >= dropH || spaceBelow >= 200) {
    // Open downward
    dropdownStyle.value = {
      top:  rect.bottom + 6 + 'px',
      left: rect.left + 'px',
    }
  } else {
    // Flip upward
    dropdownStyle.value = {
      top:  rect.top - 6 + 'px',
      left: rect.left + 'px',
      transform: 'translateY(-100%)',
    }
  }
}

function toggle() {
  open.value = !open.value
  if (open.value) {
    nextTick(positionDropdown)
  }
}

function onClickOutside(e) {
  if (pickerEl.value && !pickerEl.value.contains(e.target)) open.value = false
}
onMounted(() => {
  document.addEventListener('mousedown', onClickOutside)
  window.addEventListener('scroll', positionDropdown, true)
  window.addEventListener('resize', positionDropdown)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onClickOutside)
  window.removeEventListener('scroll', positionDropdown, true)
  window.removeEventListener('resize', positionDropdown)
})

// ── Assigned actions ──────────────────────────────────────────────────────
// Internal copy — we emit on every change
const assigned = computed(() => props.actions || [])

function isAssigned(actionId) {
  return assigned.value.some(a => a.actionId === actionId)
}

function getAssigned(actionId) {
  return assigned.value.find(a => a.actionId === actionId)
}

// Normalise an action object: ensure it has conditions[] (migrate legacy condition string)
function normaliseAction(a) {
  if (a.conditions) return a
  return { ...a, conditions: a.condition ? [a.condition] : [] }
}

function getConditions(a) {
  return (normaliseAction(a)).conditions
}

function toggleAction(actionId) {
  if (isAssigned(actionId)) {
    emit('update:actions', assigned.value.filter(a => a.actionId !== actionId))
  } else {
    emit('update:actions', [
      ...assigned.value,
      { actionId, responsibility: responsibilities.value[0] || '', conditions: [] }
    ])
  }
}

function setResponsibility(actionId, value) {
  emit('update:actions', assigned.value.map(a =>
    a.actionId === actionId ? { ...normaliseAction(a), responsibility: value } : a
  ))
}

function toggleCondition(actionId, line) {
  emit('update:actions', assigned.value.map(a => {
    if (a.actionId !== actionId) return a
    const norm = normaliseAction(a)
    const has = norm.conditions.includes(line)
    return { ...norm, conditions: has ? norm.conditions.filter(c => c !== line) : [...norm.conditions, line] }
  }))
}

// ── Helpers ───────────────────────────────────────────────────────────────
function getCatalogueItem(actionId) {
  return catalogue.value.find(c => c.id === actionId)
}
</script>

<template>
  <div class="cap-wrap" ref="pickerEl">

    <!-- ── Assigned pills row ─────────────────────────────────────────── -->
    <div class="cap-pills" :class="{ 'cap-pills-empty': !assigned.length }">
      <template v-if="assigned.length">
        <div
          v-for="a in assigned"
          :key="a.actionId"
          class="cap-pill"
          :style="{
            background: (getCatalogueItem(a.actionId)?.color || '#64748b') + '20',
            color:       getCatalogueItem(a.actionId)?.color || '#64748b',
            borderColor: (getCatalogueItem(a.actionId)?.color || '#64748b') + '60',
          }"
        >
          <span class="cap-pill-dot" :style="{ background: getCatalogueItem(a.actionId)?.color || '#64748b' }"></span>
          <span class="cap-pill-name">{{ getCatalogueItem(a.actionId)?.name || a.actionId }}</span>
          <span v-if="a.responsibility" class="cap-pill-resp">· {{ a.responsibility }}</span>
          <span v-if="getConditions(a).length" class="cap-pill-resp">· {{ getConditions(a).length > 1 ? getConditions(a).length + ' conditions' : getConditions(a)[0] }}</span>
          <button class="cap-pill-x" @click.stop="toggleAction(a.actionId)">×</button>
        </div>
      </template>

      <!-- Toggle button -->
      <button
        ref="toggleBtn"
        class="cap-toggle-btn"
        :class="{ 'cap-toggle-has': assigned.length }"
        @click="toggle"
        title="Assign actions"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path v-if="!open" d="M12 5v14M5 12h14"/>
          <path v-else d="M5 12h14"/>
        </svg>
        <span>{{ assigned.length ? 'Edit' : 'Add action' }}</span>
      </button>
    </div>

    <!-- ── Dropdown ───────────────────────────────────────────────────── -->
    <transition name="cap-fade">
      <div v-if="open" class="cap-dropdown" :style="dropdownStyle">

        <div v-if="!catalogue.length" class="cap-empty">
          No actions configured — add them in Settings → Actions.
        </div>

        <template v-else>
          <!-- Action toggle list -->
          <div class="cap-section-lbl">Select actions</div>
          <div class="cap-action-list">
            <button
              v-for="cat in catalogue"
              :key="cat.id"
              class="cap-action-btn"
              :class="{ active: isAssigned(cat.id) }"
              :style="isAssigned(cat.id) ? {
                background:   cat.color + '18',
                borderColor:  cat.color + '80',
                color:        cat.color,
              } : {}"
              @click="toggleAction(cat.id)"
            >
              <span class="cap-action-dot" :style="{ background: cat.color }"></span>
              {{ cat.name }}
              <svg v-if="isAssigned(cat.id)" class="cap-check" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
            </button>
          </div>

          <!-- Per-action details (shown for assigned ones) -->
          <template v-if="assigned.length">
            <div class="cap-divider"></div>
            <div class="cap-section-lbl">Details</div>

            <div
              v-for="a in assigned"
              :key="a.actionId"
              class="cap-detail-row"
            >
              <div
                class="cap-detail-label"
                :style="{ color: getCatalogueItem(a.actionId)?.color || '#64748b' }"
              >
                <span class="cap-action-dot" :style="{ background: getCatalogueItem(a.actionId)?.color || '#64748b' }"></span>
                {{ getCatalogueItem(a.actionId)?.name || a.actionId }}
              </div>

              <!-- Responsibility -->
              <div class="cap-detail-field" v-if="responsibilities.length">
                <label class="cap-field-lbl">Responsibility</label>
                <select
                  class="cap-select"
                  :value="a.responsibility"
                  @change="setResponsibility(a.actionId, $event.target.value)"
                >
                  <option value="">— Select —</option>
                  <option v-for="r in responsibilities" :key="r" :value="r">{{ r }}</option>
                </select>
              </div>

              <!-- Condition — multi-select checkboxes from checkOutCondition lines -->
              <div class="cap-detail-field">
                <label class="cap-field-lbl">Condition <span class="cap-opt">(select all that apply)</span></label>

                <!-- Lines available: multi-select checkbox list -->
                <template v-if="conditionLines.length">
                  <div class="cap-cond-list">
                    <label
                      v-for="line in conditionLines"
                      :key="line"
                      class="cap-cond-item"
                      :class="{ 'cap-cond-checked': getConditions(a).includes(line) }"
                    >
                      <input
                        type="checkbox"
                        class="cap-cond-cb"
                        :checked="getConditions(a).includes(line)"
                        @change="toggleCondition(a.actionId, line)"
                      />
                      <span class="cap-cond-text">{{ line }}</span>
                    </label>
                  </div>
                </template>

                <!-- No lines yet: plain text input (each line = one condition) -->
                <template v-else>
                  <input
                    class="cap-note-input"
                    type="text"
                    placeholder="e.g. Heavy marks to low level door…"
                    :value="getConditions(a).join(', ')"
                    @change="toggleCondition(a.actionId, $event.target.value.trim())"
                    maxlength="200"
                  />
                </template>
              </div>
            </div>
          </template>

          <!-- Done button -->
          <div class="cap-footer">
            <button class="cap-done-btn" @click="open = false">Done</button>
          </div>
        </template>
      </div>
    </transition>

  </div>
</template>

<style scoped>
.cap-wrap {
  position: relative;
}

/* ── Pills row ─────────────────────────────────────────────────────────── */
.cap-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 32px;
}

.cap-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 7px;
  border-radius: 999px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
}
.cap-pill-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.cap-pill-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cap-pill-resp {
  opacity: 0.75;
  font-weight: 500;
  font-size: 11px;
}
.cap-pill-x {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 0 0 2px;
  color: inherit;
  opacity: 0.6;
  margin-left: 2px;
}
.cap-pill-x:hover { opacity: 1; }

/* Toggle button */
.cap-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.cap-toggle-btn:hover {
  background: #e0e7ff;
  color: #4f46e5;
  border-color: #c7d2fe;
}
.cap-toggle-btn.cap-toggle-has {
  background: #eff6ff;
  color: #3b82f6;
  border-color: #bfdbfe;
}

/* ── Dropdown ──────────────────────────────────────────────────────────── */
.cap-dropdown {
  position: fixed;
  z-index: 9999;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  padding: 14px;
  width: 300px;
  max-height: 480px;
  overflow-y: auto;
}

.cap-fade-enter-active,
.cap-fade-leave-active {
  transition: opacity 0.12s, transform 0.12s;
}
.cap-fade-enter-from,
.cap-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.cap-empty {
  font-size: 13px;
  color: #94a3b8;
  font-style: italic;
  text-align: center;
  padding: 8px 0;
}

.cap-section-lbl {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #94a3b8;
  margin-bottom: 8px;
}

/* Action toggle buttons */
.cap-action-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 2px;
}
.cap-action-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  background: #f8fafc;
  color: #475569;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.12s;
  text-align: left;
}
.cap-action-btn:hover:not(.active) {
  background: #f1f5f9;
  border-color: #cbd5e1;
}
.cap-action-btn.active {
  font-weight: 700;
}
.cap-action-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
}
.cap-check {
  margin-left: auto;
  flex-shrink: 0;
}

/* Detail rows */
.cap-divider {
  height: 1px;
  background: #f1f5f9;
  margin: 12px 0;
}
.cap-detail-row {
  padding: 10px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  margin-bottom: 8px;
}
.cap-detail-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 10px;
}
.cap-detail-field {
  margin-bottom: 8px;
}
.cap-detail-field:last-child { margin-bottom: 0; }
.cap-field-lbl {
  display: block;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: #94a3b8;
  margin-bottom: 4px;
}
.cap-opt {
  font-weight: 400;
  text-transform: none;
  font-style: italic;
  letter-spacing: 0;
}
.cap-select,
.cap-note-input {
  width: 100%;
  padding: 6px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  background: white;
  font-family: inherit;
}
.cap-select:focus,
.cap-note-input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99,102,241,0.1);
}

/* Condition multi-select checkboxes */
.cap-cond-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cap-cond-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: white;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s;
  font-size: 13px;
  line-height: 1.4;
  user-select: none;
}
.cap-cond-item:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}
.cap-cond-item.cap-cond-checked {
  background: #eff6ff;
  border-color: #93c5fd;
}
.cap-cond-cb {
  flex-shrink: 0;
  margin-top: 2px;
  accent-color: #6366f1;
  cursor: pointer;
}
.cap-cond-text {
  color: #374151;
}
.cap-cond-checked .cap-cond-text {
  color: #1d4ed8;
  font-weight: 600;
}

/* Footer */
.cap-footer {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.cap-done-btn {
  padding: 7px 20px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.cap-done-btn:hover { background: #4f46e5; }
</style>
