/**
 * sync.js — Sync engine
 *
 * Processes the local sync queue and uploads everything to the server.
 * Order of operations:
 *   1. report_data  (JSON, tiny, must go first)
 *   2. photos       (base64 encoded, medium)
 *   3. audio        (file path → binary upload, largest)
 *
 * After a successful full sync, optionally advances the inspection status
 * if the inspector marked it as finished on mobile.
 */

import { Capacitor } from '@capacitor/core'
import { Filesystem, Directory } from '@capacitor/filesystem'
import api from './api'
import {
  getPendingSyncItems,
  markSyncItemStatus,
  markInspectionSynced,
  markRecordingSynced,
  markPhotoSynced,
  getUnsyncedRecordings,
  getUnsyncedPhotos,
  clearDoneSyncItems,
} from './offline'

const isNative = Capacitor.isNativePlatform()

// ── Public API ────────────────────────────────────────────────────────

/**
 * Sync a single inspection to the server.
 * Emits progress via the optional `onProgress(step, total, message)` callback.
 *
 * Returns { success, errors[] }
 */
export async function syncInspection(inspectionId, { onProgress, markFinished = false } = {}) {
  const errors = []
  let step = 0

  const emit = (msg) => {
    step++
    onProgress?.(step, msg)
  }

  try {
    // ── 1. Report data ──────────────────────────────────────────────
    emit('Uploading report data…')
    const rdItems = await getPendingSyncItems(inspectionId)
    const rdItem  = rdItems.find(i => i.type === 'report_data')

    if (rdItem) {
      try {
        await api.updateInspection(inspectionId, {
          report_data: JSON.stringify(rdItem.payload.reportData)
        })
        await markSyncItemStatus(rdItem.id, 'done')
      } catch (err) {
        await markSyncItemStatus(rdItem.id, 'error', err.message)
        errors.push(`Report data: ${err.message}`)
      }
    }

    // ── 2. Photos ───────────────────────────────────────────────────
    const unsyncedPhotos = await getUnsyncedPhotos(inspectionId)
    emit(`Uploading ${unsyncedPhotos.length} photo(s)…`)

    for (const photo of unsyncedPhotos) {
      try {
        const base64 = await readFileAsBase64(photo.file_path)
        // The existing report_data photo array is already updated locally.
        // Here we POST the raw file to a dedicated upload endpoint if your
        // backend supports it, otherwise the base64 is already in report_data.
        // For now: photos are embedded in report_data JSON (current architecture).
        // When a dedicated photo endpoint exists, POST here instead.
        await markPhotoSynced(photo.id)
      } catch (err) {
        errors.push(`Photo ${photo.id}: ${err.message}`)
      }
    }

    // ── 3. Audio recordings ─────────────────────────────────────────
    const unsyncedRecs = await getUnsyncedRecordings(inspectionId)
    emit(`Uploading ${unsyncedRecs.length} recording(s)…`)

    for (const rec of unsyncedRecs) {
      try {
        const base64 = await readFileAsBase64(rec.file_path)
        // POST to a recordings endpoint — add this route to your Flask backend:
        // POST /api/inspections/:id/recordings  { item_key, label, duration, audio_data (base64), mime_type }
        await api.createRecording(inspectionId, {
          item_key:   rec.item_key,
          label:      rec.label,
          duration:   rec.duration,
          audio_data: base64,
          mime_type:  rec.mime_type || 'audio/webm',
        })
        await markRecordingSynced(rec.id)
      } catch (err) {
        errors.push(`Recording ${rec.id}: ${err.message}`)
      }
    }

    // ── 4. Advance status if marked finished ────────────────────────
    if (markFinished && errors.length === 0) {
      emit('Finalising…')
      try {
        // Fetch the inspection to check typist assignment
        const res = await api.getInspection(inspectionId)
        const insp = res.data
        const nextStatus = insp.typist_id ? 'processing' : 'review'
        await api.updateInspection(inspectionId, { status: nextStatus })
      } catch (err) {
        errors.push(`Status advance: ${err.message}`)
      }
    }

    // ── 5. Mark inspection as synced locally ────────────────────────
    if (errors.length === 0) {
      await markInspectionSynced(inspectionId)
      await clearDoneSyncItems()
      emit('Sync complete ✓')
    } else {
      emit(`Sync finished with ${errors.length} error(s)`)
    }

    return { success: errors.length === 0, errors }

  } catch (err) {
    return { success: false, errors: [`Sync failed: ${err.message}`] }
  }
}

/**
 * Sync all dirty inspections — called from a background check or "Sync all" button.
 */
export async function syncAll(onProgress) {
  const items = await getPendingSyncItems()
  const ids   = [...new Set(items.map(i => i.inspection_id))]
  const results = []

  for (const id of ids) {
    const result = await syncInspection(id, { onProgress })
    results.push({ inspectionId: id, ...result })
  }

  return results
}

// ── Helpers ───────────────────────────────────────────────────────────

async function readFileAsBase64(filePath) {
  if (!isNative) {
    // On web, filePath is already a blob URL or base64 string
    if (filePath.startsWith('data:') || filePath.startsWith('blob:')) {
      return filePath.split(',')[1] || filePath
    }
    return filePath
  }

  // On native, read from filesystem
  const result = await Filesystem.readFile({
    path:      filePath,
    directory: Directory.Data,
  })
  return result.data // already base64
}

/**
 * Save a recorded audio blob to the local filesystem.
 * Returns the file path for storage in the recordings table.
 */
export async function saveAudioToFilesystem(blob, filename) {
  if (!isNative) {
    // On web/dev, return a blob URL instead
    return URL.createObjectURL(blob)
  }

  const base64 = await blobToBase64(blob)
  const path    = `recordings/${filename}`

  await Filesystem.writeFile({
    path,
    data:      base64,
    directory: Directory.Data,
    recursive: true,
  })

  return path
}

/**
 * Save a photo (base64 string) to the local filesystem.
 * Returns the file path.
 */
export async function savePhotoToFilesystem(base64Data, filename) {
  if (!isNative) return base64Data

  const path = `photos/${filename}`
  await Filesystem.writeFile({
    path,
    data:      base64Data,
    directory: Directory.Data,
    recursive: true,
  })
  return path
}

/**
 * Read a file from the local filesystem and return a usable src URL.
 * Used to display locally-stored photos in the report editor.
 */
export async function getLocalFileUrl(filePath) {
  if (!isNative) return filePath
  if (!filePath || filePath.startsWith('http') || filePath.startsWith('data:')) return filePath

  try {
    const result = await Filesystem.readFile({
      path:      filePath,
      directory: Directory.Data,
    })
    return `data:image/jpeg;base64,${result.data}`
  } catch {
    return filePath
  }
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload  = () => resolve(reader.result.split(',')[1])
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}
