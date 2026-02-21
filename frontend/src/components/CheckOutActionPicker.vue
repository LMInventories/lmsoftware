<script setup>
/**
 * CheckOutActionPicker
 * 
 * Renders a small warning-triangle (⚠) button next to a room item.
 * On click, opens a popover to add/remove Actions with Responsibility assignment.
 * 
 * Props:
 *   actions     - Array of current actions on this item
 *   roomId      - ID of the room
 *   itemId      - ID of the item (template id or extra eid)
 *
 * Emits:
 *   update:actions - new actions array when changed
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  actions:    { type: Array,  default: () => [] },
  roomId:     { required: true },
  itemId:     { required: true },
})
const emit = defineEmits(['update:actions'])

// These should match your Settings → Actions configuration.
// Hardcoded here for now; wire to API when ActionsSettings is fully built.
const AVAILABLE_ACTIONS = [
  { id: 'needs_cleaning',       name: 'Needs Cleaning',       color: '#d97706' },
  { id: 'needs_maintenance',    name: 'Needs Maintenance',    color: '#dc2626' },
  { id: 'needs_investigation',  name: 'Needs Investigation',  color: '#7c3aed' },
  { id: 'needs_replacement',    name: 'Needs Replacement',    color: '#be123c' },
  { id: 'fair_wear_tear',       name: 'Fair Wear & Tear',     color: '#4b5563' },
]

const RESPONSIBILITIES = ['Tenant', 'Landlord', 'Agent', 'Contractor', 'Investigate']

const open   = ref(false)
const adding = ref(false)

const newAction = ref({ actionId: '', responsibility: 'Tenant', note: '' })

const hasActions = computed(() => props.actions.length > 0)

function toggleOpen() { open.value = !open.value; adding.value = false }

function startAdd() { newAction.value = { actionId: '', responsibility: 'Tenant', note: '' }; adding.value = true }

function confirmAdd() {
  if (!newAction.value.actionId) return
  const def = AVAILABLE_ACTIONS.find(a => a.id === newAction.value.actionId)
  const updated = [
    ...props.actions,
    {
      id:             `act_${Date.now()}_${Math.random().toString(36).slice(2,6)}`,
      actionId:       newAction.value.actionId,
      actionName:     def?.name || newAction.value.actionId,
      actionColor:    def?.color || '#64748b',
      responsibility: newAction.value.responsibility,
      note:           newAction.value.note,
    }
  ]
  emit('update:actions', updated)
  adding.value = false
}

function removeAction(id) {
  emit('update:actions', props.actions.filter(a => a.id !== id))
}

// Close on outside click
const containerRef = ref(null)
function onDocClick(e) {
  if (open.value && containerRef.value && !containerRef.value.contains(e.target)) {
    open.value = false
    adding.value = false
  }
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onUnmounted(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <div class="co-action-wrap" ref="containerRef">
    <!-- Warning triangle trigger button -->
    <button
      class="warning-btn"
      :class="{ 'has-actions': hasActions }"
      @click="toggleOpen"
      :title="hasActions ? `${actions.length} action(s) assigned` : 'Add action'"
      type="button"
    >
      <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
        <path d="M12 2L1 21h22L12 2zm0 3.5L20.5 19h-17L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
      </svg>
      <span v-if="hasActions" class="action-count">{{ actions.length }}</span>
    </button>

    <!-- Popover panel -->
    <div v-if="open" class="action-popover">
      <div class="popover-header">
        <span class="popover-title">Actions</span>
        <button class="popover-close" @click="open = false" type="button">✕</button>
      </div>

      <!-- Existing actions list -->
      <div v-if="actions.length" class="existing-actions">
        <div v-for="act in actions" :key="act.id" class="action-pill">
          <span class="pill-dot" :style="{ background: act.actionColor }"></span>
          <span class="pill-name">{{ act.actionName }}</span>
          <span class="pill-resp">{{ act.responsibility }}</span>
          <span v-if="act.note" class="pill-note">{{ act.note }}</span>
          <button class="pill-remove" @click="removeAction(act.id)" type="button" title="Remove">✕</button>
        </div>
      </div>
      <p v-else class="no-actions-msg">No actions assigned.</p>

      <!-- Add new action form -->
      <div v-if="adding" class="add-form">
        <div class="form-row">
          <label>Action</label>
          <select v-model="newAction.actionId" class="form-select">
            <option value="" disabled>Select action…</option>
            <option v-for="a in AVAILABLE_ACTIONS" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>Responsibility</label>
          <select v-model="newAction.responsibility" class="form-select">
            <option v-for="r in RESPONSIBILITIES" :key="r" :value="r">{{ r }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>Note (optional)</label>
          <input v-model="newAction.note" class="form-input" type="text" placeholder="Additional detail…" />
        </div>
        <div class="form-actions">
          <button type="button" class="btn-cancel-add" @click="adding = false">Cancel</button>
          <button type="button" class="btn-confirm-add" @click="confirmAdd" :disabled="!newAction.actionId">Add</button>
        </div>
      </div>

      <button v-if="!adding" class="btn-add-action" type="button" @click="startAdd">
        ＋ Add Action
      </button>
    </div>
  </div>
</template>

<style scoped>
.co-action-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

/* The triangle button */
.warning-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 7px;
  border-radius: 6px;
  border: 1.5px solid #e5e7eb;
  background: #fafafa;
  color: #94a3b8;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s;
  position: relative;
  white-space: nowrap;
}
.warning-btn:hover {
  border-color: #f59e0b;
  background: #fffbeb;
  color: #d97706;
}
.warning-btn.has-actions {
  border-color: #f59e0b;
  background: #fffbeb;
  color: #d97706;
}
.action-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  background: #d97706;
  color: white;
  border-radius: 50%;
  font-size: 10px;
  font-weight: 700;
}

/* Popover */
.action-popover {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 500;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.12);
  width: 320px;
  padding: 0;
  overflow: hidden;
}

.popover-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
  background: #fafafa;
}
.popover-title { font-size: 13px; font-weight: 700; color: #1e293b; }
.popover-close {
  background: none; border: none; cursor: pointer; color: #94a3b8;
  font-size: 14px; padding: 2px 6px; border-radius: 4px;
}
.popover-close:hover { background: #f1f5f9; color: #475569; }

.existing-actions {
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 180px;
  overflow-y: auto;
}
.no-actions-msg {
  padding: 12px 16px;
  font-size: 12px;
  color: #94a3b8;
  text-align: center;
}

.action-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
}
.pill-dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.pill-name { font-weight: 600; color: #374151; flex: 1; min-width: 0; }
.pill-resp {
  padding: 1px 7px;
  background: #e0e7ff; color: #4338ca;
  border-radius: 8px; font-size: 10px; font-weight: 600; flex-shrink: 0;
}
.pill-note { color: #6b7280; font-size: 11px; flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pill-remove {
  background: none; border: none; color: #94a3b8; cursor: pointer;
  padding: 1px 4px; border-radius: 4px; font-size: 12px; flex-shrink: 0;
}
.pill-remove:hover { background: #fee2e2; color: #dc2626; }

/* Add form */
.add-form {
  padding: 12px 14px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-row { display: flex; flex-direction: column; gap: 4px; }
.form-row label { font-size: 11px; font-weight: 600; color: #64748b; }
.form-select, .form-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
  font-family: inherit;
  color: #1e293b;
  background: white;
}
.form-select:focus, .form-input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99,102,241,0.1);
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}
.btn-cancel-add {
  padding: 5px 12px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
}
.btn-confirm-add {
  padding: 5px 14px;
  background: #6366f1;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  color: white;
  cursor: pointer;
}
.btn-confirm-add:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-confirm-add:not(:disabled):hover { background: #4f46e5; }

.btn-add-action {
  width: 100%;
  padding: 10px 14px;
  background: none;
  border: none;
  border-top: 1px solid #f1f5f9;
  font-size: 13px;
  font-weight: 600;
  color: #6366f1;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}
.btn-add-action:hover { background: #f5f3ff; }
</style>
