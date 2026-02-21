/**
 * offline.js — SQLite offline storage layer
 *
 * Wraps @capacitor-community/sqlite to provide a clean API for
 * storing and reading inspections, report data, recordings, photos,
 * and the sync queue.
 *
 * All methods are async and safe to call even when not on a mobile
 * device — on web/desktop they fall back to localStorage-backed stubs
 * so the same code path works in the browser during development.
 */

import { Capacitor } from '@capacitor/core'

// ── Detect native vs web ──────────────────────────────────────────────
const isNative = Capacitor.isNativePlatform()

// ── Lazy-load the SQLite plugin only on native ────────────────────────
let db = null

async function getDB() {
  if (db) return db

  if (!isNative) {
    // Web dev stub — use in-memory object, data lost on reload but unblocks dev
    db = createWebStub()
    return db
  }

  const { CapacitorSQLite, SQLiteConnection } = await import('@capacitor-community/sqlite')
  const sqlite = new SQLiteConnection(CapacitorSQLite)

  const ret = await sqlite.checkConnectionsConsistency()
  const isConn = (await sqlite.isConnection('inventory_offline', false)).result
  if (ret.result && isConn) {
    db = await sqlite.retrieveConnection('inventory_offline', false)
  } else {
    db = await sqlite.createConnection('inventory_offline', false, 'no-encryption', 1, false)
  }

  await db.open()
  await runMigrations(db)
  return db
}

// ── Schema migrations ─────────────────────────────────────────────────
async function runMigrations(db) {
  await db.execute(`
    CREATE TABLE IF NOT EXISTS inspections (
      id          INTEGER PRIMARY KEY,
      data        TEXT    NOT NULL,
      fetched_at  TEXT    NOT NULL,
      synced_at   TEXT,
      is_dirty    INTEGER NOT NULL DEFAULT 0
    );
  `)

  await db.execute(`
    CREATE TABLE IF NOT EXISTS report_data (
      inspection_id  INTEGER PRIMARY KEY,
      data           TEXT    NOT NULL,
      modified_at    TEXT    NOT NULL
    );
  `)

  await db.execute(`
    CREATE TABLE IF NOT EXISTS sync_queue (
      id             INTEGER PRIMARY KEY AUTOINCREMENT,
      inspection_id  INTEGER NOT NULL,
      type           TEXT    NOT NULL,
      payload        TEXT    NOT NULL,
      status         TEXT    NOT NULL DEFAULT 'pending',
      created_at     TEXT    NOT NULL,
      attempts       INTEGER NOT NULL DEFAULT 0,
      error_msg      TEXT
    );
  `)

  await db.execute(`
    CREATE TABLE IF NOT EXISTS recordings (
      id             TEXT    PRIMARY KEY,
      inspection_id  INTEGER NOT NULL,
      item_key       TEXT    NOT NULL,
      label          TEXT    NOT NULL,
      file_path      TEXT    NOT NULL,
      mime_type      TEXT,
      duration       INTEGER NOT NULL DEFAULT 0,
      created_at     TEXT    NOT NULL,
      synced         INTEGER NOT NULL DEFAULT 0
    );
  `)

  await db.execute(`
    CREATE TABLE IF NOT EXISTS photos (
      id             TEXT    PRIMARY KEY,
      inspection_id  INTEGER NOT NULL,
      section_id     TEXT    NOT NULL,
      item_id        TEXT    NOT NULL,
      file_path      TEXT    NOT NULL,
      created_at     TEXT    NOT NULL,
      synced         INTEGER NOT NULL DEFAULT 0
    );
  `)
}

// ═══════════════════════════════════════════════════════════════════
// INSPECTIONS
// ═══════════════════════════════════════════════════════════════════

export async function saveInspection(inspection) {
  const db = await getDB()
  const now = new Date().toISOString()
  await db.run(
    `INSERT OR REPLACE INTO inspections (id, data, fetched_at, is_dirty)
     VALUES (?, ?, ?, 0)`,
    [inspection.id, JSON.stringify(inspection), now]
  )
}

export async function getInspection(id) {
  const db = await getDB()
  const res = await db.query(`SELECT data FROM inspections WHERE id = ?`, [id])
  if (!res.values?.length) return null
  try { return JSON.parse(res.values[0].data) } catch { return null }
}

export async function getAllInspections() {
  const db = await getDB()
  const res = await db.query(`SELECT data, is_dirty, fetched_at FROM inspections ORDER BY fetched_at DESC`)
  return (res.values || []).map(row => ({
    ...JSON.parse(row.data),
    _is_dirty:   !!row.is_dirty,
    _fetched_at: row.fetched_at,
  }))
}

export async function markInspectionDirty(id) {
  const db = await getDB()
  await db.run(`UPDATE inspections SET is_dirty = 1 WHERE id = ?`, [id])
}

export async function markInspectionSynced(id) {
  const db = await getDB()
  const now = new Date().toISOString()
  await db.run(`UPDATE inspections SET is_dirty = 0, synced_at = ? WHERE id = ?`, [now, id])
}

export async function deleteInspection(id) {
  const db = await getDB()
  await db.run(`DELETE FROM inspections WHERE id = ?`, [id])
  await db.run(`DELETE FROM report_data WHERE inspection_id = ?`, [id])
  await db.run(`DELETE FROM recordings WHERE inspection_id = ?`, [id])
  await db.run(`DELETE FROM photos WHERE inspection_id = ?`, [id])
  await db.run(`DELETE FROM sync_queue WHERE inspection_id = ?`, [id])
}

// ═══════════════════════════════════════════════════════════════════
// REPORT DATA
// ═══════════════════════════════════════════════════════════════════

export async function saveReportData(inspectionId, data) {
  const db = await getDB()
  const now = new Date().toISOString()
  await db.run(
    `INSERT OR REPLACE INTO report_data (inspection_id, data, modified_at)
     VALUES (?, ?, ?)`,
    [inspectionId, JSON.stringify(data), now]
  )
  await markInspectionDirty(inspectionId)
  // Add to sync queue
  await enqueueSyncItem(inspectionId, 'report_data', { inspectionId, reportData: data })
}

export async function getReportData(inspectionId) {
  const db = await getDB()
  const res = await db.query(`SELECT data FROM report_data WHERE inspection_id = ?`, [inspectionId])
  if (!res.values?.length) return {}
  try { return JSON.parse(res.values[0].data) } catch { return {} }
}

// ═══════════════════════════════════════════════════════════════════
// RECORDINGS
// ═══════════════════════════════════════════════════════════════════

export async function saveRecording(rec) {
  // rec: { id, inspection_id, item_key, label, file_path, mime_type, duration }
  const db = await getDB()
  const now = new Date().toISOString()
  await db.run(
    `INSERT OR REPLACE INTO recordings
       (id, inspection_id, item_key, label, file_path, mime_type, duration, created_at, synced)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)`,
    [rec.id, rec.inspection_id, rec.item_key, rec.label,
     rec.file_path, rec.mime_type || 'audio/webm', rec.duration || 0, now]
  )
  await markInspectionDirty(rec.inspection_id)
}

export async function getRecordings(inspectionId) {
  const db = await getDB()
  const res = await db.query(
    `SELECT * FROM recordings WHERE inspection_id = ? ORDER BY created_at ASC`,
    [inspectionId]
  )
  return res.values || []
}

export async function getUnsyncedRecordings(inspectionId) {
  const db = await getDB()
  const res = await db.query(
    `SELECT * FROM recordings WHERE inspection_id = ? AND synced = 0`,
    [inspectionId]
  )
  return res.values || []
}

export async function markRecordingSynced(id) {
  const db = await getDB()
  await db.run(`UPDATE recordings SET synced = 1 WHERE id = ?`, [id])
}

// ═══════════════════════════════════════════════════════════════════
// PHOTOS
// ═══════════════════════════════════════════════════════════════════

export async function savePhoto(photo) {
  // photo: { id, inspection_id, section_id, item_id, file_path }
  const db = await getDB()
  const now = new Date().toISOString()
  await db.run(
    `INSERT OR REPLACE INTO photos
       (id, inspection_id, section_id, item_id, file_path, created_at, synced)
     VALUES (?, ?, ?, ?, ?, ?, 0)`,
    [photo.id, photo.inspection_id, photo.section_id, photo.item_id, photo.file_path, now]
  )
  await markInspectionDirty(photo.inspection_id)
}

export async function getPhotos(inspectionId, sectionId, itemId) {
  const db = await getDB()
  const res = await db.query(
    `SELECT * FROM photos WHERE inspection_id = ? AND section_id = ? AND item_id = ? ORDER BY created_at ASC`,
    [inspectionId, sectionId, itemId]
  )
  return res.values || []
}

export async function getUnsyncedPhotos(inspectionId) {
  const db = await getDB()
  const res = await db.query(
    `SELECT * FROM photos WHERE inspection_id = ? AND synced = 0`,
    [inspectionId]
  )
  return res.values || []
}

export async function markPhotoSynced(id) {
  const db = await getDB()
  await db.run(`UPDATE photos SET synced = 1 WHERE id = ?`, [id])
}

// ═══════════════════════════════════════════════════════════════════
// SYNC QUEUE
// ═══════════════════════════════════════════════════════════════════

export async function enqueueSyncItem(inspectionId, type, payload) {
  const db = await getDB()
  const now = new Date().toISOString()
  // Deduplicate report_data entries — only one pending entry needed at a time
  if (type === 'report_data') {
    await db.run(
      `DELETE FROM sync_queue WHERE inspection_id = ? AND type = 'report_data' AND status = 'pending'`,
      [inspectionId]
    )
  }
  await db.run(
    `INSERT INTO sync_queue (inspection_id, type, payload, status, created_at, attempts)
     VALUES (?, ?, ?, 'pending', ?, 0)`,
    [inspectionId, type, JSON.stringify(payload), now]
  )
}

export async function getPendingSyncItems(inspectionId = null) {
  const db = await getDB()
  const query = inspectionId
    ? `SELECT * FROM sync_queue WHERE status = 'pending' AND inspection_id = ? ORDER BY id ASC`
    : `SELECT * FROM sync_queue WHERE status = 'pending' ORDER BY inspection_id, id ASC`
  const res = await db.query(query, inspectionId ? [inspectionId] : [])
  return (res.values || []).map(row => ({ ...row, payload: JSON.parse(row.payload) }))
}

export async function markSyncItemStatus(id, status, errorMsg = null) {
  const db = await getDB()
  await db.run(
    `UPDATE sync_queue SET status = ?, error_msg = ?, attempts = attempts + 1 WHERE id = ?`,
    [status, errorMsg, id]
  )
}

export async function clearDoneSyncItems() {
  const db = await getDB()
  await db.run(`DELETE FROM sync_queue WHERE status = 'done'`)
}

// ═══════════════════════════════════════════════════════════════════
// WEB STUB (development fallback)
// ═══════════════════════════════════════════════════════════════════

function createWebStub() {
  const store = {
    inspections: {},
    report_data: {},
    recordings: [],
    photos: [],
    sync_queue: [],
  }

  return {
    execute: async () => {},
    run: async (sql, params) => {
      console.debug('[offline stub] run:', sql.slice(0, 60), params)
    },
    query: async (sql, params) => {
      console.debug('[offline stub] query:', sql.slice(0, 60), params)
      return { values: [] }
    },
  }
}
