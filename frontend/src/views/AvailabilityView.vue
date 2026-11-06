<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import api from '../services/api'

// ── Constants ────────────────────────────────────────────────────────────────
const SNAP = 30                     // minutes
const PX_PER_MIN = 0.8              // 48px per hour
const GRID_HEIGHT = 1440 * PX_PER_MIN
const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const hours = Array.from({ length: 24 }, (_, i) => i)

// ── State ────────────────────────────────────────────────────────────────────
const mode = ref('repeating')        // 'repeating' | 'holiday'
const view = ref('month')            // holiday: 'month' | 'week' | 'day'
const anchor = ref(startOfDay(new Date()))
const blocks = ref([])
const error = ref('')
const scroller = ref(null)
const bodyEl = ref(null)

// ── Date helpers ─────────────────────────────────────────────────────────────
function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()) }
function addDays(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n) }
function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function fromIso(s) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }
function mondayOf(d) { return addDays(d, -((d.getDay() + 6) % 7)) }
function ordinal(n) {
  const v = n % 100
  return n + (['th', 'st', 'nd', 'rd'][(v - 20) % 10] || ['th', 'st', 'nd', 'rd'][v] || 'th')
}
function hhmm(min) {
  const m = Math.min(min, 1439)
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}
function endLabel(min) { return min >= 1440 ? '24:00' : hhmm(min) }
const todayIso = iso(new Date())

// ── Load ─────────────────────────────────────────────────────────────────────
async function load() {
  try {
    const res = await api.http.get('/api/availability/me')
    blocks.value = res.data
  } catch (e) {
    error.value = e.response?.data?.error || 'Failed to load availability'
  }
}
onMounted(async () => {
  await load()
  scrollToMorning()
})

function scrollToMorning() {
  nextTick(() => { if (scroller.value) scroller.value.scrollTop = 8 * 60 * PX_PER_MIN })
}

// ── Columns for the time grid ────────────────────────────────────────────────
const columns = computed(() => {
  if (mode.value === 'repeating') {
    return DAY_NAMES.map((name, i) => ({ key: i, label: name, weekday: i }))
  }
  if (view.value === 'day') {
    const d = anchor.value
    return [{ key: iso(d), label: `${d.toLocaleDateString('en-GB', { weekday: 'long' })} ${ordinal(d.getDate())}`, date: iso(d) }]
  }
  const mon = mondayOf(anchor.value)
  return DAY_NAMES.map((name, i) => {
    const d = addDays(mon, i)
    return { key: iso(d), label: `${name.slice(0, 3)} ${ordinal(d.getDate())}`, date: iso(d) }
  })
})

function covers(b, col) {
  if (mode.value === 'repeating') return b.kind === 'repeating' && b.weekday === col.weekday
  return b.kind === 'holiday' && b.start_date <= col.date && col.date <= (b.end_date || b.start_date)
}
const modeBlocks = computed(() => blocks.value.filter(b => b.kind === mode.value))
function allDayFor(col) { return modeBlocks.value.filter(b => b.start_min == null && covers(b, col)) }
function timedFor(col) { return modeBlocks.value.filter(b => b.start_min != null && covers(b, col)) }

// ── Persistence (optimistic) ─────────────────────────────────────────────────
function payloadFor(col, startMin, endMin) {
  const p = { kind: mode.value, start_min: startMin, end_min: endMin }
  if (mode.value === 'repeating') p.weekday = col.weekday
  else { p.start_date = col.date; p.end_date = col.date }
  return p
}

async function createBlock(payload) {
  error.value = ''
  try {
    const res = await api.http.post('/api/availability/me', payload)
    blocks.value.push(res.data)
  } catch (e) {
    error.value = e.response?.data?.error || 'Failed to save'
  }
}

async function updateBlock(id, payload) {
  error.value = ''
  try {
    const res = await api.http.put(`/api/availability/me/${id}`, payload)
    const i = blocks.value.findIndex(b => b.id === id)
    if (i >= 0) blocks.value[i] = res.data
  } catch (e) {
    error.value = e.response?.data?.error || 'Failed to save'
    await load()
  }
}

async function removeBlock(id) {
  error.value = ''
  const prev = blocks.value
  blocks.value = prev.filter(b => b.id !== id)
  try {
    await api.http.delete(`/api/availability/me/${id}`)
  } catch (e) {
    blocks.value = prev
    error.value = e.response?.data?.error || 'Failed to remove'
  }
}

async function removeAll() {
  const what = mode.value === 'repeating' ? 'repeating' : 'holiday'
  if (!confirm(`Remove all ${what} unavailability?`)) return
  error.value = ''
  try {
    await api.http.delete('/api/availability/me', { params: { kind: mode.value } })
    blocks.value = blocks.value.filter(b => b.kind !== mode.value)
  } catch (e) {
    error.value = e.response?.data?.error || 'Failed to remove'
  }
}

// ── Time-grid dragging ───────────────────────────────────────────────────────
// drag: { type: 'create'|'move'|'top'|'bottom', colIdx, block?, anchor, startY, startX, moved, offset }
const drag = ref(null)
const draft = ref(null)   // { colIdx, start, end, id? } while dragging

function snap(min) { return Math.round(min / SNAP) * SNAP }
function minuteAt(clientY) {
  const rect = bodyEl.value.getBoundingClientRect()
  return Math.max(0, Math.min(1440, (clientY - rect.top) / PX_PER_MIN))
}
function colAt(clientX) {
  const rect = bodyEl.value.getBoundingClientRect()
  const gutter = 56
  const w = (rect.width - gutter) / columns.value.length
  return Math.max(0, Math.min(columns.value.length - 1, Math.floor((clientX - rect.left - gutter) / w)))
}

function startCreate(e, colIdx) {
  if (e.button !== undefined && e.button !== 0) return
  const slotStart = Math.min(1440 - SNAP, Math.floor(minuteAt(e.clientY) / SNAP) * SNAP)
  drag.value = { type: 'create', colIdx, anchor: slotStart, startY: e.clientY, moved: false }
  draft.value = { colIdx, start: slotStart, end: slotStart + SNAP }
  bindWindow()
}

function startBlock(e, block, colIdx, type) {
  if (e.button !== undefined && e.button !== 0) return
  e.stopPropagation()
  drag.value = {
    type, colIdx, block, startY: e.clientY, moved: false,
    offset: minuteAt(e.clientY) - block.start_min,
  }
  draft.value = { colIdx, start: block.start_min, end: block.end_min, id: block.id }
  bindWindow()
}

function onMove(e) {
  const d = drag.value
  if (!d) return
  if (Math.abs(e.clientY - d.startY) > 4) d.moved = true
  const m = minuteAt(e.clientY)
  if (d.type === 'create') {
    const cur = Math.floor(m / SNAP) * SNAP
    const lo = Math.min(d.anchor, cur), hi = Math.max(d.anchor, cur) + SNAP
    draft.value = { colIdx: d.colIdx, start: lo, end: Math.min(1440, hi) }
  } else if (d.type === 'move') {
    const len = d.block.end_min - d.block.start_min
    let s = snap(m - d.offset)
    s = Math.max(0, Math.min(1440 - len, s))
    const colIdx = mode.value === 'repeating' || columns.value.length > 1 ? colAt(e.clientX) : d.colIdx
    draft.value = { colIdx, start: s, end: s + len, id: d.block.id }
  } else if (d.type === 'top') {
    const s = Math.max(0, Math.min(d.block.end_min - SNAP, snap(m)))
    draft.value = { colIdx: d.colIdx, start: s, end: d.block.end_min, id: d.block.id }
  } else if (d.type === 'bottom') {
    const en = Math.min(1440, Math.max(d.block.start_min + SNAP, snap(m)))
    draft.value = { colIdx: d.colIdx, start: d.block.start_min, end: en, id: d.block.id }
  }
}

async function onUp() {
  unbindWindow()
  const d = drag.value, dr = draft.value
  drag.value = null
  draft.value = null
  if (!d || !dr) return
  const col = columns.value[dr.colIdx]
  if (d.type === 'create') {
    // A plain click makes a one-hour block; a drag makes exactly what was swept.
    const end = d.moved ? dr.end : Math.min(1440, dr.start + 60)
    await createBlock(payloadFor(col, dr.start, end))
  } else if (!d.moved) {
    if (d.type === 'move') await removeBlock(d.block.id)    // click removes
  } else {
    await updateBlock(d.block.id, payloadFor(col, dr.start, dr.end))
  }
}

function bindWindow() {
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onCancel)
}
function unbindWindow() {
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onCancel)
}
function onCancel() { unbindWindow(); drag.value = null; draft.value = null }
onUnmounted(unbindWindow)

function blockStyle(b, colIdx) {
  const live = draft.value && draft.value.id === b.id ? draft.value : null
  const s = live ? live.start : b.start_min
  const e = live ? live.end : b.end_min
  return { top: `${s * PX_PER_MIN}px`, height: `${Math.max(12, (e - s) * PX_PER_MIN)}px` }
}
function blockLabel(b, colIdx) {
  const live = draft.value && draft.value.id === b.id ? draft.value : null
  const s = live ? live.start : b.start_min
  const e = live ? live.end : b.end_min
  return `${hhmm(s)}–${endLabel(e)}`
}
const draftStyle = computed(() => draft.value && !draft.value.id
  ? { top: `${draft.value.start * PX_PER_MIN}px`, height: `${(draft.value.end - draft.value.start) * PX_PER_MIN}px` }
  : null)
// While moving a block into another column, render it there.
function isMovedAway(b, colIdx) {
  return draft.value && draft.value.id === b.id && draft.value.colIdx !== colIdx
}
function draftBlockHere(colIdx) {
  if (!draft.value || !draft.value.id || draft.value.colIdx !== colIdx) return null
  const b = blocks.value.find(x => x.id === draft.value.id)
  return b || null
}

// All-day cell click
async function addAllDay(col) {
  if (mode.value === 'repeating') {
    await createBlock({ kind: 'repeating', weekday: col.weekday, start_min: null, end_min: null })
  } else {
    await createBlock({ kind: 'holiday', start_date: col.date, end_date: col.date, start_min: null, end_min: null })
  }
}

// ── Holiday navigation ───────────────────────────────────────────────────────
function shift(dir) {
  const a = anchor.value
  if (view.value === 'month') anchor.value = new Date(a.getFullYear(), a.getMonth() + dir, 1)
  else if (view.value === 'week') anchor.value = addDays(a, 7 * dir)
  else anchor.value = addDays(a, dir)
}
function goToday() { anchor.value = startOfDay(new Date()) }
function setView(v) { view.value = v; if (v !== 'month') scrollToMorning() }
function openDay(dateStr) { anchor.value = fromIso(dateStr); setView('day') }
function setMode(m) { mode.value = m; if (m === 'repeating' || view.value !== 'month') scrollToMorning() }

const title = computed(() => {
  const a = anchor.value
  if (view.value === 'month') return a.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
  if (view.value === 'day') return `${a.toLocaleDateString('en-GB', { weekday: 'long' })} ${a.toLocaleDateString('en-GB', { month: 'long' })} ${ordinal(a.getDate())}`
  const mon = mondayOf(a), sun = addDays(mon, 6)
  const f = d => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  return `${f(mon)} – ${f(sun)} ${sun.getFullYear()}`
})

// ── Month view ───────────────────────────────────────────────────────────────
const monthCells = computed(() => {
  const first = new Date(anchor.value.getFullYear(), anchor.value.getMonth(), 1)
  const start = mondayOf(first)
  const cells = []
  for (let i = 0; i < 42; i++) {
    const d = addDays(start, i)
    cells.push({ date: iso(d), day: d.getDate(), other: d.getMonth() !== first.getMonth() })
  }
  const rows = []
  for (let i = 0; i < 42; i += 7) rows.push(cells.slice(i, i + 7))
  // Drop a trailing row that is entirely the next month.
  return rows.filter((r, i) => i < 5 || r.some(c => !c.other))
})

function blocksOnDate(dateStr) {
  return blocks.value.filter(b => b.kind === 'holiday' && b.start_date <= dateStr && dateStr <= (b.end_date || b.start_date))
}
function chipLabel(b) {
  return b.start_min == null ? 'Unavailable' : `${hhmm(b.start_min)}–${endLabel(b.end_min)} Unavailable`
}

const monthDrag = ref(null)   // { from, to }
function monthDown(e, cell) {
  if (e.button !== undefined && e.button !== 0) return
  monthDrag.value = { from: cell.date, to: cell.date }
  window.addEventListener('pointermove', monthMove)
  window.addEventListener('pointerup', monthUp)
  window.addEventListener('pointercancel', monthCancel)
}
function monthCancel() {
  window.removeEventListener('pointermove', monthMove)
  window.removeEventListener('pointerup', monthUp)
  window.removeEventListener('pointercancel', monthCancel)
  monthDrag.value = null   // browser took over (e.g. the page started scrolling) — don't create anything
}
function monthMove(e) {
  const el = document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-date]')
  if (el && monthDrag.value) monthDrag.value.to = el.dataset.date
}
async function monthUp() {
  window.removeEventListener('pointermove', monthMove)
  window.removeEventListener('pointerup', monthUp)
  window.removeEventListener('pointercancel', monthCancel)
  const d = monthDrag.value
  monthDrag.value = null
  if (!d) return
  const [s, e] = d.from <= d.to ? [d.from, d.to] : [d.to, d.from]
  await createBlock({ kind: 'holiday', start_date: s, end_date: e, start_min: null, end_min: null })
}
function inMonthDrag(dateStr) {
  const d = monthDrag.value
  if (!d) return false
  const [s, e] = d.from <= d.to ? [d.from, d.to] : [d.to, d.from]
  return dateStr >= s && dateStr <= e
}
onUnmounted(monthCancel)

// ── Add holiday by dates (works without dragging — handy on touch screens) ──
const hf = ref({ start: '', end: '', allDay: true, from: '09:00', to: '17:00' })
const hfSaving = ref(false)
function syncHolidayEnd() { if (!hf.value.end || hf.value.end < hf.value.start) hf.value.end = hf.value.start }
function toMin(t) { const [h, m] = t.split(':').map(Number); return h * 60 + m }

async function addHoliday() {
  error.value = ''
  const { start, end, allDay, from, to } = hf.value
  if (!start) { error.value = 'Choose a start date'; return }
  const last = end || start
  if (last < start) { error.value = 'End date must be on or after the start date'; return }
  let sm = null, em = null
  if (!allDay) {
    if (last !== start) { error.value = 'Specific hours can only be set for a single day — use all day for a range'; return }
    sm = toMin(from); em = toMin(to)
    if (!from || !to || sm >= em) { error.value = 'End time must be after the start time'; return }
  }
  hfSaving.value = true
  await createBlock({ kind: 'holiday', start_date: start, end_date: last, start_min: sm, end_min: em })
  hfSaving.value = false
  if (!error.value) {
    anchor.value = fromIso(start)
    hf.value.start = ''; hf.value.end = ''
  }
}

const showTimeGrid = computed(() => mode.value === 'repeating' || view.value !== 'month')
</script>

<template>
  <div class="av-page">
    <h1 class="av-title">Availability</h1>

    <div class="av-toolbar">
      <p class="av-hint">
        Drag and resize blocks to change availability. Click a block to remove it.
        You won't appear as a clerk option, and will show as Unavailable in Telegram, while blocked.
      </p>
      <div class="av-actions">
        <button class="btn-remove-all" @click="removeAll">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
          Remove all unavailability
        </button>
        <div class="seg">
          <button :class="{ on: mode === 'repeating' }" @click="setMode('repeating')">Repeating</button>
          <button :class="{ on: mode === 'holiday' }" @click="setMode('holiday')">Holiday</button>
        </div>
      </div>
    </div>

    <div v-if="error" class="av-error">{{ error }}</div>

    <div v-if="mode === 'holiday'" class="nav-row">
      <div class="nav-left">
        <div class="seg small">
          <button @click="shift(-1)" aria-label="Previous">‹</button>
          <button @click="shift(1)" aria-label="Next">›</button>
        </div>
        <button class="btn-today" @click="goToday">Today</button>
      </div>
      <div class="nav-title">{{ title }}</div>
      <div class="seg small">
        <button :class="{ on: view === 'month' }" @click="setView('month')">Month</button>
        <button :class="{ on: view === 'week' }" @click="setView('week')">Week</button>
        <button :class="{ on: view === 'day' }" @click="setView('day')">Day</button>
      </div>
    </div>

    <form v-if="mode === 'holiday'" class="hol-form" @submit.prevent="addHoliday">
      <label>From <input type="date" v-model="hf.start" @change="syncHolidayEnd" /></label>
      <label>To <input type="date" v-model="hf.end" :min="hf.start || undefined" /></label>
      <label class="chk"><input type="checkbox" v-model="hf.allDay" /> All day</label>
      <template v-if="!hf.allDay">
        <label>Start time <input type="time" step="900" v-model="hf.from" /></label>
        <label>End time <input type="time" step="900" v-model="hf.to" /></label>
      </template>
      <button type="submit" class="btn-add" :disabled="hfSaving">Add unavailability</button>
    </form>

    <!-- ── Time grid (repeating / holiday week + day) ─────────────────── -->
    <div v-if="showTimeGrid" class="grid-scroll-x">
      <div class="grid">
        <div class="grid-head" :style="{ gridTemplateColumns: `56px repeat(${columns.length}, 1fr)` }">
          <div class="gh-corner"></div>
          <div v-for="c in columns" :key="c.key" class="gh-day" :class="{ today: c.date === todayIso }">{{ c.label }}</div>
        </div>
        <div class="grid-head allday" :style="{ gridTemplateColumns: `56px repeat(${columns.length}, 1fr)` }">
          <div class="gh-corner small">all-day</div>
          <div v-for="c in columns" :key="c.key" class="allday-cell" :class="{ today: c.date === todayIso }" @click="addAllDay(c)">
            <button v-for="b in allDayFor(c)" :key="b.id" class="chip" @click.stop="removeBlock(b.id)" title="Click to remove">Unavailable</button>
          </div>
        </div>

        <div ref="scroller" class="grid-scroll">
          <div ref="bodyEl" class="grid-body" :style="{ height: GRID_HEIGHT + 'px' }">
            <div class="gutter">
              <div v-for="h in hours" :key="h" class="hour-label" :style="{ top: h * 60 * PX_PER_MIN + 'px' }">{{ String(h).padStart(2, '0') }}:00</div>
            </div>
            <div
              v-for="(c, ci) in columns" :key="c.key"
              class="day-col" :class="{ today: c.date === todayIso }"
              :style="{ left: `calc(56px + (100% - 56px) * ${ci} / ${columns.length})`, width: `calc((100% - 56px) / ${columns.length})` }"
              @pointerdown="startCreate($event, ci)"
            >
              <div v-for="h in hours" :key="h" class="hour-line" :style="{ top: h * 60 * PX_PER_MIN + 'px' }"></div>
              <div v-for="h in hours" :key="'h' + h" class="half-line" :style="{ top: (h * 60 + 30) * PX_PER_MIN + 'px' }"></div>

              <template v-for="b in timedFor(c)" :key="b.id">
                <div
                  v-if="!isMovedAway(b, ci)"
                  class="block" :class="{ dragging: draft && draft.id === b.id }"
                  :style="blockStyle(b, ci)"
                  @pointerdown="startBlock($event, b, ci, 'move')"
                >
                  <div class="handle top" @pointerdown="startBlock($event, b, ci, 'top')"></div>
                  <span class="block-text">{{ blockLabel(b, ci) }} Unavailable</span>
                  <div class="handle bottom" @pointerdown="startBlock($event, b, ci, 'bottom')"></div>
                </div>
              </template>

              <div v-if="draftBlockHere(ci) && !timedFor(c).includes(draftBlockHere(ci))" class="block dragging"
                   :style="{ top: draft.start * PX_PER_MIN + 'px', height: (draft.end - draft.start) * PX_PER_MIN + 'px' }">
                <span class="block-text">{{ hhmm(draft.start) }}–{{ endLabel(draft.end) }} Unavailable</span>
              </div>

              <div v-if="draftStyle && draft.colIdx === ci" class="block draft" :style="draftStyle">
                <span class="block-text">{{ hhmm(draft.start) }}–{{ endLabel(draft.end) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Month view (holiday) ───────────────────────────────────────── -->
    <div v-else class="month">
      <div class="month-head">
        <div v-for="n in DAY_NAMES" :key="n">{{ n }}</div>
      </div>
      <div v-for="(row, ri) in monthCells" :key="ri" class="month-row">
        <div
          v-for="cell in row" :key="cell.date"
          class="month-cell" :class="{ other: cell.other, today: cell.date === todayIso, sweep: inMonthDrag(cell.date) }"
          :data-date="cell.date"
          @pointerdown="monthDown($event, cell)"
        >
          <div class="mc-day">
            <button class="day-link" title="Open Day view" @pointerdown.stop @click.stop="openDay(cell.date)">{{ ordinal(cell.day) }}</button>
          </div>
          <button
            v-for="b in blocksOnDate(cell.date)" :key="b.id"
            class="chip wide" @pointerdown.stop @click.stop="removeBlock(b.id)" title="Click to remove"
          >{{ chipLabel(b) }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.av-page { padding: 24px 28px 48px; max-width: 1400px; }
.av-title { font-size: 26px; font-weight: 600; color: #334155; margin: 0 0 14px; }
.av-toolbar { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.av-hint { font-size: 13px; font-style: italic; color: #64748b; margin: 0; max-width: 560px; }
.av-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.btn-remove-all { display: inline-flex; align-items: center; gap: 8px; background: #9f2b36; color: #fff; border: none; border-radius: 6px; padding: 10px 18px; font-size: 13px; font-weight: 700; cursor: pointer; }
.btn-remove-all:hover { background: #861f29; }
.av-error { background: #fef2f2; border: 1px solid #fca5a5; color: #dc2626; padding: 10px 14px; border-radius: 7px; font-size: 13px; margin-bottom: 12px; }

.seg { display: inline-flex; border: 1px solid #cbd5e1; border-radius: 5px; overflow: hidden; }
.seg button { background: #e5e7eb; border: none; padding: 9px 16px; font-size: 13px; color: #475569; cursor: pointer; font-family: inherit; }
.seg button + button { border-left: 1px solid #cbd5e1; }
.seg button.on { background: #4f86e6; color: #fff; }
.seg.small button { padding: 6px 12px; background: #f8fafc; }
.seg.small button.on { background: #e5e7eb; color: #1e293b; box-shadow: inset 0 1px 3px rgba(0,0,0,.15); }

.nav-row { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; margin-bottom: 14px; }
.nav-left { display: flex; gap: 10px; align-items: center; }
.nav-row > .seg:last-child { justify-self: end; }
.nav-title { font-weight: 600; color: #334155; text-align: center; }
.btn-today { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 5px; padding: 6px 12px; font-size: 13px; color: #475569; cursor: pointer; }

.hol-form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; margin-bottom: 14px; padding: 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }
.hol-form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 600; color: #475569; }
.hol-form label.chk { flex-direction: row; align-items: center; gap: 6px; padding-bottom: 9px; }
.hol-form input[type="date"], .hol-form input[type="time"] { padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font: inherit; font-size: 14px; }
.btn-add { background: #4f86e6; color: #fff; border: none; border-radius: 6px; padding: 10px 18px; font-size: 13px; font-weight: 700; cursor: pointer; }
.btn-add:disabled { background: #94a3b8; }
@media (max-width: 768px) {
  .hol-form label { flex: 1 1 140px; }
  .hol-form input { width: 100%; box-sizing: border-box; }
  .btn-add { width: 100%; min-height: 44px; }
}

.grid-scroll-x { overflow-x: auto; }
.grid { min-width: 720px; border: 1px solid #d5dae1; background: #fff; }
.grid-head { display: grid; border-bottom: 1px solid #d5dae1; }
.gh-corner { border-right: 1px solid #e2e8f0; font-size: 10px; color: #94a3b8; display: flex; align-items: center; justify-content: center; }
.gh-day { text-align: center; font-size: 13px; font-weight: 700; color: #334155; padding: 2px 0; border-right: 1px solid #e2e8f0; }
.gh-day:last-child, .allday-cell:last-child { border-right: none; }
.grid-head.allday { border-bottom: 3px double #d5dae1; }
.allday-cell { min-height: 46px; border-right: 1px solid #e2e8f0; padding: 3px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.gh-day.today, .allday-cell.today, .day-col.today { background: #fff8dc; }

.grid-scroll { height: clamp(320px, 62vh, 540px); overflow-y: auto; position: relative; }
.grid-body { position: relative; }
.gutter { position: absolute; left: 0; top: 0; bottom: 0; width: 56px; border-right: 1px solid #e2e8f0; background: #fff; z-index: 2; }
.hour-label { position: absolute; left: 0; width: 52px; text-align: right; font-size: 13px; color: #334155; transform: translateY(-1px); padding-top: 2px; }
.day-col { position: absolute; top: 0; bottom: 0; border-right: 1px solid #e2e8f0; touch-action: pan-x pan-y; cursor: cell; }
.day-col:last-child { border-right: none; }
.hour-line { position: absolute; left: 0; right: 0; border-top: 1px solid #d5dae1; pointer-events: none; }
.half-line { position: absolute; left: 0; right: 0; border-top: 1px dotted #e2e8f0; pointer-events: none; }

.block { position: absolute; left: 2px; right: 2px; background: #d4d4d8; border: 1px solid #8e8e96; border-radius: 3px; font-size: 12px; color: #27272a; cursor: grab; touch-action: none; user-select: none; z-index: 1; }
.block.draft { background: rgba(79,134,230,.35); border-color: #4f86e6; pointer-events: none; }
.block.dragging { cursor: grabbing; box-shadow: 0 2px 8px rgba(0,0,0,.25); z-index: 3; }
.block-text { padding: 2px 5px; display: block; pointer-events: none; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.handle { position: absolute; left: 0; right: 0; height: 7px; cursor: ns-resize; touch-action: none; }
.handle.top { top: 0; }
.handle.bottom { bottom: 0; }
@media (pointer: coarse) {
  /* Finger-sized resize grips that straddle the block edge */
  .handle { height: 22px; }
  .handle.top { top: -11px; }
  .handle.bottom { bottom: -11px; }
  .day-link { padding: 6px 8px; }
  .btn-remove-all, .seg button, .btn-today { min-height: 40px; }
}

.chip { background: #d4d4d8; border: 1px solid #8e8e96; border-radius: 3px; font-size: 12px; color: #27272a; text-align: left; padding: 1px 5px; cursor: pointer; font-family: inherit; }
.chip:hover { background: #fecaca; border-color: #dc2626; }
.chip.wide { display: block; width: 100%; margin-top: 2px; box-sizing: border-box; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.month-cell { touch-action: pan-x pan-y; }

.month { border: 1px solid #d5dae1; background: #fff; user-select: none; }
.month-head { display: grid; grid-template-columns: repeat(7, 1fr); border-bottom: 1px solid #d5dae1; }
.month-head div { text-align: center; font-size: 13px; font-weight: 700; color: #334155; padding: 3px 0; border-right: 1px solid #e2e8f0; }
.month-row { display: grid; grid-template-columns: repeat(7, 1fr); border-bottom: 1px solid #e2e8f0; }
.month-row:last-child { border-bottom: none; }
.month-cell { min-height: 86px; border-right: 1px solid #e2e8f0; padding: 3px; cursor: pointer; min-width: 0; }
.month-cell:last-child { border-right: none; }
.month-cell.other { background: #e5e7eb; color: #94a3b8; }
.month-cell.today { background: #fff8dc; }
.month-cell.sweep { background: #dbeafe; }
.mc-day { text-align: right; font-size: 14px; color: #334155; }
.month-cell.other .mc-day { color: #94a3b8; }
.day-link { background: none; border: none; padding: 0 2px; font: inherit; color: inherit; cursor: pointer; text-decoration: underline; text-decoration-color: transparent; }
.day-link:hover { color: #2563eb; text-decoration-color: currentColor; }

@media (max-width: 768px) {
  .av-page { padding: 16px 12px 40px; }
  .nav-row { grid-template-columns: 1fr; justify-items: center; }
  .nav-row > .seg:last-child { justify-self: center; }
  .month-cell { min-height: 64px; padding: 2px; }
  .chip.wide { font-size: 10px; padding: 1px 2px; }
  .mc-day { font-size: 12px; }
  .grid { min-width: 600px; }
  .btn-remove-all { width: 100%; justify-content: center; }
  .av-actions { width: 100%; }
  .av-actions .seg { width: 100%; }
  .av-actions .seg button { flex: 1; }
}
</style>
