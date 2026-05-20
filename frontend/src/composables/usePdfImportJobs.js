/**
 * usePdfImportJobs — background PDF import tracker.
 *
 * Singleton state: persists across navigation, survives component unmount.
 * Polls every 5 s for active jobs; emits toasts on completion.
 * Completed results stored by inspection_id for the InspectionReportView to pick up.
 */
import { ref, computed } from 'vue'
import { useToast } from './useToast'
import api from '../services/api'

const _activeJobs    = ref([])   // [{job_id, inspection_id, filename, started_at}]
const _completedJobs = ref({})   // {inspection_id: {job_id, result, filename, completed_at}}
const _pollTimer     = ref(null)
const _initialized   = ref(false)
const LS_KEY = 'pdf_import_active_jobs'

function _load() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) _activeJobs.value = JSON.parse(raw)
  } catch { /* ignore */ }
}

function _save() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(_activeJobs.value)) } catch { /* ignore */ }
}

async function _poll() {
  if (!_activeJobs.value.length) return
  const toast = useToast()
  const done  = []

  for (const job of _activeJobs.value) {
    try {
      const res = await api.pdfImportStatus(job.job_id)
      const { status, result, error } = res.data

      if (status === 'done') {
        const rooms = (result?.rooms || []).length
        const items = (result?.rooms || []).reduce((s, r) => s + (r.items || []).length, 0)
        toast.success(`PDF ready — ${rooms} rooms, ${items} items. Open the inspection to review.`, 9000)
        _completedJobs.value = {
          ..._completedJobs.value,
          [String(job.inspection_id)]: { job_id: job.job_id, result, filename: job.filename, completed_at: Date.now() },
        }
        done.push(job.job_id)
      } else if (status === 'error') {
        toast.error(`PDF import failed (${job.filename}): ${error}`, 8000)
        done.push(job.job_id)
      }
      // status === 'processing' or 'not_found' → keep polling
    } catch { /* network error — retry next tick */ }
  }

  if (done.length) {
    _activeJobs.value = _activeJobs.value.filter(j => !done.includes(j.job_id))
    _save()
  }
  if (!_activeJobs.value.length && _pollTimer.value) {
    clearInterval(_pollTimer.value)
    _pollTimer.value = null
  }
}

function _startPolling() {
  if (!_pollTimer.value) _pollTimer.value = setInterval(_poll, 5000)
}

export function usePdfImportJobs() {
  if (!_initialized.value) {
    _load()
    _initialized.value = true
    if (_activeJobs.value.length) _startPolling()
  }

  function registerJob(jobId, inspectionId, filename) {
    // Replace any previous job for the same inspection
    _activeJobs.value = [
      ..._activeJobs.value.filter(j => j.inspection_id !== String(inspectionId)),
      { job_id: jobId, inspection_id: String(inspectionId), filename, started_at: Date.now() },
    ]
    _save()
    _startPolling()
  }

  function getCompletedJob(inspectionId) {
    return _completedJobs.value[String(inspectionId)] || null
  }

  function clearCompletedJob(inspectionId) {
    const next = { ..._completedJobs.value }
    delete next[String(inspectionId)]
    _completedJobs.value = next
  }

  function isJobPending(inspectionId) {
    return _activeJobs.value.some(j => j.inspection_id === String(inspectionId))
  }

  return {
    activeJobs:      computed(() => _activeJobs.value),
    registerJob,
    getCompletedJob,
    clearCompletedJob,
    isJobPending,
  }
}
