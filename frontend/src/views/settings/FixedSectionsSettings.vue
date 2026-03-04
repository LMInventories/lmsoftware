<script setup>
import { ref, onMounted } from 'vue'
import api from '../../services/api'

const sections  = ref([])
const loading   = ref(true)
const saving    = ref(false)
const newName   = ref('')

async function load() {
  loading.value = true
  try {
    const res = await api.getFixedSections()
    sections.value = res.data
  } catch (e) {
    console.error(e)
    alert('Failed to load fixed sections')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res = await api.updateFixedSections(sections.value)
    sections.value = res.data
  } catch (e) {
    console.error(e)
    alert('Failed to save')
  } finally {
    saving.value = false
  }
}

function addSection() {
  const name = newName.value.trim()
  if (!name) return
  sections.value.push({ name, enabled: true })
  newName.value = ''
}

function remove(index) {
  sections.value.splice(index, 1)
}

function moveUp(index) {
  if (index === 0) return
  const arr = sections.value
  ;[arr[index - 1], arr[index]] = [arr[index], arr[index - 1]]
}

function moveDown(index) {
  if (index === sections.value.length - 1) return
  const arr = sections.value
  ;[arr[index], arr[index + 1]] = [arr[index + 1], arr[index]]
}

onMounted(load)
</script>

<template>
  <div class="fs-wrap">
    <div class="fs-header">
      <div>
        <h2 class="fs-title">Fixed Sections</h2>
        <p class="fs-subtitle">
          These sections appear on <strong>every</strong> inspection report, regardless of template.
          Manage the list below — order and visibility apply system-wide.
        </p>
      </div>
      <button @click="save" :disabled="saving" class="btn-save">
        {{ saving ? 'Saving…' : 'Save Changes' }}
      </button>
    </div>

    <div v-if="loading" class="fs-loading">Loading…</div>

    <div v-else>
      <!-- Section list -->
      <div class="fs-list">
        <div
          v-for="(section, index) in sections"
          :key="index"
          class="fs-row"
          :class="{ disabled: !section.enabled }"
        >
          <!-- Enabled toggle -->
          <label class="toggle" :title="section.enabled ? 'Enabled' : 'Disabled'">
            <input type="checkbox" v-model="section.enabled" />
            <span class="toggle-track"></span>
          </label>

          <!-- Name (editable inline) -->
          <input
            v-model="section.name"
            class="fs-name-input"
            :class="{ muted: !section.enabled }"
            placeholder="Section name"
          />

          <!-- Order + remove -->
          <div class="fs-actions">
            <button @click="moveUp(index)"   :disabled="index === 0"                    class="btn-icon" title="Move Up">↑</button>
            <button @click="moveDown(index)" :disabled="index === sections.length - 1"  class="btn-icon" title="Move Down">↓</button>
            <button @click="remove(index)"                                               class="btn-icon danger" title="Remove">✕</button>
          </div>
        </div>

        <div v-if="sections.length === 0" class="fs-empty">
          No fixed sections yet. Add one below.
        </div>
      </div>

      <!-- Add new -->
      <div class="fs-add-row">
        <input
          v-model="newName"
          class="fs-add-input"
          placeholder="New section name, e.g. Carbon Monoxide Alarms"
          @keyup.enter="addSection"
        />
        <button @click="addSection" class="btn-add">＋ Add</button>
      </div>

      <p class="fs-hint">
        Changes take effect for all new and existing inspections once saved.
        Disabled sections are hidden from reports but not deleted.
      </p>
    </div>
  </div>
</template>

<style scoped>
.fs-wrap { max-width: 680px; }

.fs-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 28px;
  gap: 20px;
}

.fs-title    { font-size: 20px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.fs-subtitle { font-size: 13px; color: #64748b; line-height: 1.5; max-width: 480px; }

.btn-save {
  padding: 10px 22px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background 0.15s;
}
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

.fs-loading { color: #94a3b8; padding: 20px 0; }

/* ── List ─────────────────────────────────────────────────────────────────── */
.fs-list {
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 16px;
}

.fs-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: white;
  border-bottom: 1px solid #f1f5f9;
  transition: background 0.15s;
}
.fs-row:last-child { border-bottom: none; }
.fs-row:hover      { background: #fafafa; }
.fs-row.disabled   { background: #f8fafc; }

/* Toggle */
.toggle { position: relative; flex-shrink: 0; cursor: pointer; }
.toggle input { display: none; }

.toggle-track {
  display: block;
  width: 36px; height: 20px;
  background: #d1d5db;
  border-radius: 10px;
  position: relative;
  transition: background 0.2s;
}
.toggle-track::after {
  content: '';
  position: absolute;
  top: 2px; left: 2px;
  width: 16px; height: 16px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.toggle input:checked ~ .toggle-track              { background: #6366f1; }
.toggle input:checked ~ .toggle-track::after       { transform: translateX(16px); }

/* Name input */
.fs-name-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 14px;
  font-weight: 500;
  color: #1e293b;
  padding: 4px 6px;
  border-radius: 4px;
  font-family: inherit;
  transition: background 0.15s;
}
.fs-name-input:focus  { outline: none; background: #f1f5f9; }
.fs-name-input.muted  { color: #94a3b8; }

/* Action buttons */
.fs-actions { display: flex; gap: 4px; flex-shrink: 0; }

.btn-icon {
  width: 28px; height: 28px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 12px; font-weight: 700;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  color: #374151;
  transition: all 0.15s;
}
.btn-icon:hover:not(:disabled) { background: #f1f5f9; border-color: #c7d2fe; color: #6366f1; }
.btn-icon:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-icon.danger:hover { background: #fee2e2; border-color: #fecaca; color: #dc2626; }

.fs-empty {
  padding: 32px;
  text-align: center;
  color: #94a3b8;
  font-size: 14px;
}

/* ── Add row ──────────────────────────────────────────────────────────────── */
.fs-add-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.fs-add-input {
  flex: 1;
  padding: 10px 14px;
  border: 1.5px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  transition: border-color 0.15s;
}
.fs-add-input:focus { outline: none; border-color: #6366f1; }

.btn-add {
  padding: 10px 20px;
  background: #f1f5f9;
  color: #374151;
  border: 1.5px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
.btn-add:hover { background: #e2e8f0; border-color: #cbd5e1; }

.fs-hint {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}
</style>
