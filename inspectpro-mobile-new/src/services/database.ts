import * as SQLite from 'expo-sqlite'

const db = SQLite.openDatabase('inspectpro.db')

export async function initDatabase(): Promise<void> {
  return new Promise((resolve, reject) => {
    db.transaction(tx => {
      tx.executeSql(`
        CREATE TABLE IF NOT EXISTS inspections (
          id INTEGER PRIMARY KEY,
          data TEXT NOT NULL,
          report_data TEXT,
          status TEXT NOT NULL DEFAULT 'assigned',
          local_status TEXT NOT NULL DEFAULT 'downloaded',
          downloaded_at TEXT NOT NULL,
          updated_at TEXT,
          synced INTEGER NOT NULL DEFAULT 0
        )
      `)
      tx.executeSql(`
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
        )
      `)
      // Migrations — safe to run repeatedly (ALTER TABLE IF NOT EXISTS not supported,
      // so we catch errors silently)
      tx.executeSql("ALTER TABLE audio_recordings ADD COLUMN section_name TEXT NOT NULL DEFAULT ''", [], () => {}, () => false)
      tx.executeSql("ALTER TABLE audio_recordings ADD COLUMN item_name TEXT", [], () => {}, () => false)
      tx.executeSql("ALTER TABLE audio_recordings ADD COLUMN label TEXT NOT NULL DEFAULT ''", [], () => {}, () => false)
    }, reject, resolve)
  })
}

function query<T>(sql: string, args: any[] = []): Promise<T[]> {
  return new Promise((resolve, reject) => {
    db.transaction(tx => {
      tx.executeSql(
        sql, args,
        (_, result) => {
          const rows: T[] = []
          for (let i = 0; i < result.rows.length; i++) rows.push(result.rows.item(i))
          resolve(rows)
        },
        (_, err) => { reject(err); return false }
      )
    })
  })
}

function run(sql: string, args: any[] = []): Promise<void> {
  return new Promise((resolve, reject) => {
    db.transaction(tx => {
      tx.executeSql(
        sql, args,
        () => resolve(),
        (_, err) => { reject(err); return false }
      )
    })
  })
}

export async function saveInspection(inspection: any) {
  const existing = await query<{ id: number }>('SELECT id FROM inspections WHERE id = ?', [inspection.id])
  const now = new Date().toISOString()
  if (existing.length > 0) {
    await run(
      `UPDATE inspections SET data = ?, report_data = ?, status = ?, updated_at = ? WHERE id = ?`,
      [JSON.stringify(inspection), inspection.report_data || null, inspection.status, now, inspection.id]
    )
  } else {
    await run(
      `INSERT INTO inspections (id, data, report_data, status, local_status, downloaded_at, updated_at, synced) VALUES (?, ?, ?, ?, 'downloaded', ?, ?, 0)`,
      [inspection.id, JSON.stringify(inspection), inspection.report_data || null, inspection.status, now, now]
    )
  }
}

export async function getLocalInspections(): Promise<any[]> {
  const rows = await query<{ data: string; report_data: string | null; local_status: string; synced: number }>(
    'SELECT data, report_data, local_status, synced FROM inspections ORDER BY downloaded_at DESC'
  )
  return rows.map(r => ({
    ...JSON.parse(r.data),
    report_data: r.report_data,
    local_status: r.local_status,
    synced: r.synced === 1,
  }))
}

export async function getLocalInspection(id: number): Promise<any | null> {
  const rows = await query<{ data: string; report_data: string | null; local_status: string; synced: number }>(
    'SELECT data, report_data, local_status, synced FROM inspections WHERE id = ?', [id]
  )
  if (rows.length === 0) return null
  const r = rows[0]
  return { ...JSON.parse(r.data), report_data: r.report_data, local_status: r.local_status, synced: r.synced === 1 }
}

export async function updateReportData(inspectionId: number, reportData: string) {
  await run(`UPDATE inspections SET report_data = ?, updated_at = ?, synced = 0 WHERE id = ?`,
    [reportData, new Date().toISOString(), inspectionId])
}

export async function updateLocalStatus(inspectionId: number, localStatus: string) {
  await run(`UPDATE inspections SET local_status = ?, updated_at = ? WHERE id = ?`,
    [localStatus, new Date().toISOString(), inspectionId])
}

export async function markSynced(inspectionId: number) {
  await run(`UPDATE inspections SET synced = 1, updated_at = ? WHERE id = ?`,
    [new Date().toISOString(), inspectionId])
}

export async function deleteLocalInspection(inspectionId: number) {
  await run('DELETE FROM inspections WHERE id = ?', [inspectionId])
  await run('DELETE FROM audio_recordings WHERE inspection_id = ?', [inspectionId])
}

export async function saveAudioRecording(
  inspectionId: number,
  sectionKey: string,
  sectionName: string,
  itemKey: string | undefined,
  itemName: string | undefined,
  label: string,
  fileUri: string,
  durationMs: number,
  transcription?: string
) {
  await run(
    `INSERT INTO audio_recordings (inspection_id, section_key, section_name, item_key, item_name, label, file_uri, duration_ms, transcription, created_at, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
    [inspectionId, sectionKey, sectionName, itemKey || null, itemName || null, label, fileUri, durationMs, transcription || null, new Date().toISOString()]
  )
}

export async function deleteAudioRecording(id: number, fileUri: string) {
  await run('DELETE FROM audio_recordings WHERE id = ?', [id])
  try {
    const { deleteAsync } = await import('expo-file-system') as any
    await deleteAsync(fileUri, { idempotent: true })
  } catch {}
}

export async function getAudioRecordings(inspectionId: number): Promise<any[]> {
  return query('SELECT * FROM audio_recordings WHERE inspection_id = ? ORDER BY created_at DESC', [inspectionId])
}

export async function getAudioRecordingsForItem(inspectionId: number, sectionKey: string, itemKey: string): Promise<any[]> {
  return query(
    `SELECT * FROM audio_recordings WHERE inspection_id = ? AND section_key = ? AND item_key = ? ORDER BY created_at DESC`,
    [inspectionId, sectionKey, itemKey]
  )
}

export async function updateTranscription(recordingId: number, transcription: string) {
  await run('UPDATE audio_recordings SET transcription = ?, synced = 0 WHERE id = ?', [transcription, recordingId])
}
