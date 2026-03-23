import * as SQLite from 'expo-sqlite'
import * as FileSystem from 'expo-file-system'

const db = SQLite.openDatabaseSync('inspectpro.db')

export function initDatabase(): void {
  db.execSync(`
    CREATE TABLE IF NOT EXISTS inspections (
      id INTEGER PRIMARY KEY,
      data TEXT NOT NULL,
      report_data TEXT,
      status TEXT NOT NULL DEFAULT 'assigned',
      local_status TEXT NOT NULL DEFAULT 'downloaded',
      downloaded_at TEXT NOT NULL,
      updated_at TEXT,
      synced INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS audio_recordings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      inspection_id INTEGER NOT NULL,
      section_key TEXT NOT NULL,
      section_name TEXT NOT NULL DEFAULT '',
      item_key TEXT,
      item_name TEXT,
      label TEXT NOT NULL DEFAULT '',
      file_uri TEXT NOT NULL,
      duration_ms INTEGER,
      transcription TEXT,
      created_at TEXT NOT NULL,
      synced INTEGER NOT NULL DEFAULT 0
    );
  `)

  // Migrations — safe to run repeatedly (errors silently ignored)
  try { db.runSync("ALTER TABLE audio_recordings ADD COLUMN section_name TEXT NOT NULL DEFAULT ''") } catch {}
  try { db.runSync('ALTER TABLE audio_recordings ADD COLUMN item_name TEXT') } catch {}
  try { db.runSync("ALTER TABLE audio_recordings ADD COLUMN label TEXT NOT NULL DEFAULT ''") } catch {}
}

export function saveInspection(inspection: any): void {
  const existing = db.getFirstSync<{ id: number }>(
    'SELECT id FROM inspections WHERE id = ?', [inspection.id]
  )
  const now = new Date().toISOString()
  if (existing) {
    db.runSync(
      'UPDATE inspections SET data = ?, report_data = ?, status = ?, updated_at = ? WHERE id = ?',
      [JSON.stringify(inspection), inspection.report_data || null, inspection.status, now, inspection.id]
    )
  } else {
    db.runSync(
      `INSERT INTO inspections (id, data, report_data, status, local_status, downloaded_at, updated_at, synced)
       VALUES (?, ?, ?, ?, 'downloaded', ?, ?, 0)`,
      [inspection.id, JSON.stringify(inspection), inspection.report_data || null, inspection.status, now, now]
    )
  }
}

export function getLocalInspections(): any[] {
  const rows = db.getAllSync<{ data: string; report_data: string | null; local_status: string; synced: number }>(
    'SELECT data, report_data, local_status, synced FROM inspections ORDER BY downloaded_at DESC'
  )
  return rows.map(r => ({
    ...JSON.parse(r.data),
    report_data: r.report_data,
    local_status: r.local_status,
    synced: r.synced === 1,
  }))
}

export function getLocalInspection(id: number): any | null {
  const r = db.getFirstSync<{ data: string; report_data: string | null; local_status: string; synced: number }>(
    'SELECT data, report_data, local_status, synced FROM inspections WHERE id = ?', [id]
  )
  if (!r) return null
  return { ...JSON.parse(r.data), report_data: r.report_data, local_status: r.local_status, synced: r.synced === 1 }
}

export function updateReportData(inspectionId: number, reportData: string): void {
  db.runSync(
    'UPDATE inspections SET report_data = ?, updated_at = ?, synced = 0 WHERE id = ?',
    [reportData, new Date().toISOString(), inspectionId]
  )
}

export function updateLocalStatus(inspectionId: number, localStatus: string): void {
  db.runSync(
    'UPDATE inspections SET local_status = ?, updated_at = ? WHERE id = ?',
    [localStatus, new Date().toISOString(), inspectionId]
  )
}

export function markSynced(inspectionId: number): void {
  db.runSync(
    'UPDATE inspections SET synced = 1, updated_at = ? WHERE id = ?',
    [new Date().toISOString(), inspectionId]
  )
}

export function deleteLocalInspection(inspectionId: number): void {
  db.runSync('DELETE FROM inspections WHERE id = ?', [inspectionId])
  db.runSync('DELETE FROM audio_recordings WHERE inspection_id = ?', [inspectionId])
}

export function saveAudioRecording(
  inspectionId: number,
  sectionKey: string,
  sectionName: string,
  itemKey: string | undefined,
  itemName: string | undefined,
  label: string,
  fileUri: string,
  durationMs: number,
  transcription?: string
): void {
  db.runSync(
    `INSERT INTO audio_recordings
       (inspection_id, section_key, section_name, item_key, item_name, label, file_uri, duration_ms, transcription, created_at, synced)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
    [inspectionId, sectionKey, sectionName, itemKey || null, itemName || null, label, fileUri, durationMs, transcription || null, new Date().toISOString()]
  )
}

export async function deleteAudioRecording(id: number, fileUri: string): Promise<void> {
  db.runSync('DELETE FROM audio_recordings WHERE id = ?', [id])
  try {
    await FileSystem.deleteAsync(fileUri, { idempotent: true })
  } catch {}
}

export function getAudioRecordings(inspectionId: number): any[] {
  return db.getAllSync(
    'SELECT * FROM audio_recordings WHERE inspection_id = ? ORDER BY created_at DESC',
    [inspectionId]
  )
}

export function getAudioRecordingsForItem(inspectionId: number, sectionKey: string, itemKey: string): any[] {
  return db.getAllSync(
    'SELECT * FROM audio_recordings WHERE inspection_id = ? AND section_key = ? AND item_key = ? ORDER BY created_at DESC',
    [inspectionId, sectionKey, itemKey]
  )
}

export function updateTranscription(recordingId: number, transcription: string): void {
  db.runSync(
    'UPDATE audio_recordings SET transcription = ?, synced = 0 WHERE id = ?',
    [transcription, recordingId]
  )
}
