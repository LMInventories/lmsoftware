import React, { useState, useCallback } from 'react'
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  Alert, ActivityIndicator, Modal,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useNavigation, useFocusEffect } from '@react-navigation/native'
import type { StackNavigationProp } from '@react-navigation/stack'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import { useAuthStore } from '../stores/authStore'
import { markSynced, deleteLocalInspection, getLocalInspection, getAudioRecordings } from '../services/database'
import { api } from '../services/api'
import * as FileSystem from 'expo-file-system/legacy'
import Header from '../components/Header'
import StatusBadge from '../components/StatusBadge'
import { colors, font, radius, spacing, TYPE_LABELS } from '../utils/theme'

type Nav = StackNavigationProp<RootStackParamList, 'Sync'>
type SyncResult = { id: number; address: string; success: boolean; error?: string }

export default function SyncScreen() {
  const navigation = useNavigation<Nav>()
  const insets     = useSafeAreaInsets()
  const { inspections, loadInspections } = useInspectionStore()
  const { user } = useAuthStore()

  const [selected, setSelected]       = useState<Set<number>>(new Set())
  const [syncing, setSyncing]         = useState(false)
  const [results, setResults]         = useState<SyncResult[] | null>(null)
  const [confirmModal, setConfirmModal] = useState(false)
  const [progressMsg, setProgressMsg] = useState('')

  useFocusEffect(useCallback(() => {
    loadInspections()
    setResults(null)
  }, []))

  const syncable = inspections.filter(i => !i.synced)
  const done     = inspections.filter(i => i.synced)

  function toggleSelect(id: number) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  function toggleAll() {
    setSelected(selected.size === syncable.length ? new Set() : new Set(syncable.map(i => i.id)))
  }

  // Walk all _photos and _overviewPhotos arrays in report_data.
  // For each entry that is a file URI, read and encode to base64 data URI.
  // Legacy data: URIs are passed through unchanged.
  // Returns the mutated (deep-copied) object — does NOT touch the stored data.
  async function convertPhotoUrisToBase64(rd: any): Promise<any> {
    for (const sectionKey of Object.keys(rd)) {
      const section = rd[sectionKey]
      if (!section || typeof section !== 'object') continue

      // Walk all item keys — this covers template items, fixed section items,
      // AND '_overview' (the room overview key, stored as _overview._photos).
      // The old flat '_overviewPhotos' key is no longer used.
      for (const itemKey of Object.keys(section)) {
        const item = section[itemKey]
        if (!item || typeof item !== 'object' || Array.isArray(item)) continue
        if (Array.isArray(item._photos)) {
          item._photos = await encodePhotoArray(item._photos)
        }
      }
    }
    return rd
  }

  async function encodePhotoArray(photos: string[]): Promise<string[]> {
    return Promise.all(photos.map(async (uri) => {
      // Already a data URI — nothing to do
      if (uri.startsWith('data:')) return uri
      // File URI — read and encode
      try {
        const b64 = await FileSystem.readAsStringAsync(uri, {
          encoding: FileSystem.EncodingType.Base64,
        })
        return `data:image/jpeg;base64,${b64}`
      } catch (e) {
        console.warn('[Sync] could not encode photo:', uri, e)
        return uri  // keep original so the field isn't silently dropped
      }
    }))
  }

  async function runSync() {
    setConfirmModal(false)
    setSyncing(true)
    setResults(null)
    const res: SyncResult[] = []

    for (const id of Array.from(selected)) {
      const inspection = inspections.find(i => i.id === id)
      if (!inspection) continue
      setProgressMsg(`Syncing ${inspection.property_address}…`)

      try {
        // Read fresh from DB to guarantee latest report_data
        const fresh = getLocalInspection(id)
        const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}

        // Read audio recordings from SQLite — persists across app restarts
        // unlike the in-memory Zustand store
        const sqliteRecs = getAudioRecordings(id)
        console.log(`[Sync] found ${sqliteRecs.length} audio recordings in SQLite for inspection ${id}`)

        if (sqliteRecs.length > 0) {
          const serialised = await Promise.all(
            sqliteRecs.map(async (rec: any) => {
              let audioB64 = ''
              try {
                const info = await FileSystem.getInfoAsync(rec.file_uri)
                if (info.exists) {
                  audioB64 = await FileSystem.readAsStringAsync(rec.file_uri, {
                    encoding: FileSystem.EncodingType.Base64,
                  })
                  console.log(`[Sync] encoded clip ${rec.id}: ${audioB64.length} chars`)
                } else {
                  console.warn(`[Sync] file missing for recording ${rec.id}:`, rec.file_uri)
                }
              } catch (e) {
                console.warn(`[Sync] could not read audio ${rec.id}:`, e)
              }
              return {
                id:         String(rec.id),
                audioB64,
                mimeType:   'audio/m4a',
                duration:   (rec.duration_ms || 0) / 1000,  // web app expects seconds
                createdAt:  rec.created_at,
                label:      rec.label || rec.section_name || '',
                itemKey:    rec.item_key
                              ? `${rec.section_key}:${rec.item_key}`
                              : null,
                transcript: rec.transcription || null,
                gptResult:  null,
              }
            })
          )
          const withAudio = serialised.filter(r => r.audioB64.length > 0)
          if (withAudio.length > 0) {
            rd._recordings = withAudio
            console.log(`[Sync] ${withAudio.length}/${sqliteRecs.length} clips serialised successfully`)
          } else {
            console.warn('[Sync] all clips failed to encode — check file paths')
          }
        }

        // Convert any file:// photo URIs → base64 data URIs for the server payload.
        // We deep-copy rd first so on-device storage always keeps file URIs.
        const rdForSync = await convertPhotoUrisToBase64(JSON.parse(JSON.stringify(rd)))
        const payload: any = { report_data: JSON.stringify(rdForSync) }

        // Status transitions:
        //
        // Clerk + AI typist (ai_instant / ai_room) or typist flagged as AI:
        //   Fields already filled on-device → skip Processing → go straight to Review
        //
        // Clerk + human typist (human) or no typist assigned:
        //   Human needs to type from audio → move to Processing so typist can access it
        //
        // Role = typist:
        //   Typist has finished typing → move to Review
        //
        // Admin/manager: no auto-transition
        const role = user?.role
        const typistMode = user?.typist_mode
        // fresh.status is now reliable: updateInspectionServerStatus() patches the
        // data blob when Start Inspection is tapped, so it no longer freezes at the
        // value from download time.
        // local_status === 'active' is kept as a secondary check to cover the
        // offline-start edge case where the server couldn't be reached and the blob
        // was therefore not updated.
        const freshStatus = fresh?.status || inspection.status
        const localStatus = fresh?.local_status || inspection.local_status
        const isActive    = freshStatus === 'active' || localStatus === 'active'
        const typistName = (fresh?.typist_name || fresh?.typist?.name || '').toLowerCase()
        const typistIsAi = fresh?.typist_is_ai === true ||
                           fresh?.typist?.is_ai === true ||
                           typistName === 'ai typist' ||
                           typistName.startsWith('ai ')
        const isAiMode = typistIsAi ||
                         typistMode === 'ai_instant' ||
                         typistMode === 'ai_room'

        const isFinalised = !!(fresh as any)?.is_finalised

        if (role === 'clerk' && isActive) {
          if (isFinalised) {
            // Finalised on device: move to processing (human typist) or review (AI typist)
            payload.status = isAiMode ? 'review' : 'processing'
          }
          // Not finalised: upload report data but leave inspection Active on server
        } else if (role === 'typist' && freshStatus === 'processing') {
          // Typist finished typing → Review
          payload.status = 'review'
        }
        // Admins/managers: no auto-transition

        await api.syncInspection(id, payload)
        await markSynced(id)
        res.push({ id, address: inspection.property_address, success: true })
      } catch (err: any) {
        let msg = 'Network error'
        if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
          msg = 'Upload timed out — the payload may be too large or the server is slow. Try again on Wi-Fi.'
        } else if (err.response?.status === 413) {
          msg = 'Payload too large — try syncing with fewer photos or shorter audio.'
        } else if (err.response?.status === 401 || err.response?.status === 403) {
          msg = 'Authentication error — please log out and back in.'
        } else if (err.response?.status >= 500) {
          msg = `Server error (${err.response.status}) — please try again shortly.`
        } else if (err.response?.data?.error) {
          msg = err.response.data.error
        } else if (err.message && err.message !== 'Network Error') {
          msg = err.message
        } else if (!err.response) {
          msg = 'No internet connection — check your network and try again.'
        }
        res.push({ id, address: inspection.property_address, success: false, error: msg })
      }
    }

    await loadInspections()
    setSyncing(false)
    setProgressMsg('')
    setResults(res)
    setSelected(new Set())
  }

  async function handleRemove(id: number, address: string) {
    Alert.alert(`Remove "${address}"?`, 'Removes the local copy. Only remove synced inspections.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: async () => { await deleteLocalInspection(id); await loadInspections() } },
    ])
  }

  function formatDate(str: string | null) {
    if (!str) return '—'
    return new Date(str).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  }

  // Explain what status transition will happen for this user
  function syncNote() {
    const typistMode = user?.typist_mode
    const isAiMode = typistMode === 'ai_instant' || typistMode === 'ai_room'
    const selectedList = syncable.filter(i => selected.has(i.id))
    const anyFinalised = selectedList.some(i => (i as any).is_finalised)
    const allFinalised = selectedList.length > 0 && selectedList.every(i => (i as any).is_finalised)

    if (user?.role === 'clerk') {
      if (allFinalised) {
        return isAiMode
          ? 'All selected inspections are finalised. Syncing will upload and move to Review.'
          : 'All selected inspections are finalised. Syncing will upload and move to Processing for the typist.'
      }
      if (anyFinalised) {
        return isAiMode
          ? 'Finalised inspections will move to Review. Unfinalised inspections will stay Active.'
          : 'Finalised inspections will move to Processing. Unfinalised inspections will stay Active.'
      }
      return 'None of the selected inspections are finalised. Syncing will upload data but leave them Active.'
    }
    if (user?.role === 'typist')
      return 'Syncing will upload your report and move the inspection to Review.'
    return 'Syncing will upload report data to the server.'
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <Header title="Sync" subtitle="Upload completed inspections" onBack={() => navigation.goBack()} />

      <ScrollView contentContainerStyle={styles.scroll}>
        {results && (
          <View style={styles.resultsBox}>
            <Text style={styles.resultsTitle}>{results.filter(r => r.success).length}/{results.length} synced successfully</Text>
            {results.map(r => (
              <View key={r.id} style={styles.resultRow}>
                <Text style={r.success ? styles.resultOk : styles.resultFail}>{r.success ? '✓' : '✕'} {r.address}</Text>
                {!r.success && <Text style={styles.resultError}>{r.error}</Text>}
              </View>
            ))}
          </View>
        )}

        {syncable.length > 0 && (
          <>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionLabel}>Ready to Sync ({syncable.length})</Text>
              <TouchableOpacity onPress={toggleAll}>
                <Text style={styles.toggleAllText}>{selected.size === syncable.length ? 'Deselect All' : 'Select All'}</Text>
              </TouchableOpacity>
            </View>

            {syncable.map(inspection => {
              const isSel = selected.has(inspection.id)
              return (
                <TouchableOpacity key={inspection.id} style={[styles.card, isSel && styles.cardSelected]} onPress={() => toggleSelect(inspection.id)}>
                  <View style={styles.cardCheck}>
                    <View style={[styles.checkbox, isSel && styles.checkboxChecked]}>
                      {isSel && <Text style={styles.checkboxMark}>✓</Text>}
                    </View>
                  </View>
                  <View style={styles.cardContent}>
                    <Text style={styles.cardAddress} numberOfLines={2}>{inspection.property_address}</Text>
                    <Text style={styles.cardMeta}>{TYPE_LABELS[inspection.inspection_type] ?? inspection.inspection_type} · {formatDate(inspection.conduct_date)}</Text>
                    <View style={styles.badgeRow}>
                      <StatusBadge status={inspection.status} small />
                      {(inspection as any).is_finalised && (
                        <View style={styles.finalisedBadge}>
                          <Text style={styles.finalisedBadgeText}>✓ Finalised</Text>
                        </View>
                      )}
                    </View>
                  </View>
                </TouchableOpacity>
              )
            })}

            <TouchableOpacity
              style={[styles.syncBtn, (selected.size === 0 || syncing) && styles.syncBtnDisabled]}
              onPress={() => { if (selected.size > 0) setConfirmModal(true) }}
              disabled={syncing || selected.size === 0}
            >
              {syncing ? (
                <View style={styles.syncingRow}>
                  <ActivityIndicator color="#fff" size="small" />
                  <Text style={styles.syncBtnText}>{progressMsg || 'Syncing…'}</Text>
                </View>
              ) : (
                <Text style={styles.syncBtnText}>
                  ⇅ Sync {selected.size > 0 ? `${selected.size} Inspection${selected.size !== 1 ? 's' : ''}` : ''}
                </Text>
              )}
            </TouchableOpacity>
          </>
        )}

        {done.length > 0 && (
          <>
            <View style={[styles.sectionHeader, { marginTop: spacing.lg }]}>
              <Text style={styles.sectionLabel}>Synced — Awaiting Removal ({done.length})</Text>
            </View>
            {done.map(inspection => (
              <View key={inspection.id} style={[styles.card, styles.cardDone]}>
                <View style={styles.cardContent}>
                  <Text style={[styles.cardAddress, styles.cardAddressDone]} numberOfLines={2}>{inspection.property_address}</Text>
                  <Text style={styles.cardMeta}>{TYPE_LABELS[inspection.inspection_type] ?? inspection.inspection_type} · {formatDate(inspection.conduct_date)}</Text>
                </View>
                <TouchableOpacity style={styles.removeBtn} onPress={() => handleRemove(inspection.id, inspection.property_address)}>
                  <Text style={styles.removeBtnText}>Remove</Text>
                </TouchableOpacity>
              </View>
            ))}
          </>
        )}

        {syncable.length === 0 && done.length === 0 && (
          <View style={styles.empty}>
            <Text style={styles.emptyIcon}>☁️</Text>
            <Text style={styles.emptyTitle}>Nothing to sync</Text>
            <Text style={styles.emptySub}>Download inspections from the Fetch screen first.</Text>
          </View>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>

      <Modal visible={confirmModal} transparent animationType="fade">
        <View style={mStyles.overlay}><View style={mStyles.box}>
          <Text style={mStyles.title}>Sync {selected.size} Inspection{selected.size !== 1 ? 's' : ''}?</Text>
          <View style={mStyles.warning}>
            <Text style={mStyles.warningIcon}>ℹ️</Text>
            <Text style={mStyles.warningText}>{syncNote()}</Text>
          </View>
          <View style={mStyles.warning}>
            <Text style={mStyles.warningIcon}>⚠️</Text>
            <Text style={mStyles.warningText}>Make sure you have a working internet connection before syncing.</Text>
          </View>
          <View style={mStyles.actions}>
            <TouchableOpacity style={mStyles.cancel} onPress={() => setConfirmModal(false)}>
              <Text style={mStyles.cancelText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={mStyles.confirm} onPress={runSync}>
              <Text style={mStyles.confirmText}>Sync Now</Text>
            </TouchableOpacity>
          </View>
        </View></View>
      </Modal>
    </View>
  )
}

const mStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', alignItems: 'center', justifyContent: 'center' },
  box: { backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.lg, width: '85%' },
  title: { fontSize: font.lg, fontWeight: '700', color: colors.text, marginBottom: spacing.md },
  warning: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start', backgroundColor: colors.warningLight, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm },
  warningIcon: { fontSize: 16 },
  warningText: { flex: 1, fontSize: font.sm, color: colors.warning, lineHeight: 18 },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  cancel: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.muted, alignItems: 'center' },
  cancelText: { color: colors.textMid, fontWeight: '600' },
  confirm: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.primary, alignItems: 'center' },
  confirmText: { color: '#fff', fontWeight: '700' },
})
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: spacing.md },
  resultsBox: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  resultsTitle: { fontSize: font.md, fontWeight: '700', color: colors.text, marginBottom: spacing.sm },
  resultRow: { marginBottom: 4 },
  resultOk: { fontSize: font.sm, color: colors.success, fontWeight: '600' },
  resultFail: { fontSize: font.sm, color: colors.danger, fontWeight: '600' },
  resultError: { fontSize: font.xs, color: colors.danger, marginLeft: 18, marginTop: 2 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xs },
  sectionLabel: { fontSize: font.xs, fontWeight: '700', color: colors.textLight, textTransform: 'uppercase', letterSpacing: 0.6 },
  toggleAllText: { fontSize: font.sm, color: colors.accent, fontWeight: '600' },
  card: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.sm, borderWidth: 1.5, borderColor: colors.border },
  cardSelected: { borderColor: colors.primary, backgroundColor: colors.primaryLight },
  cardDone: { opacity: 0.7 },
  cardCheck: { marginRight: spacing.sm },
  checkbox: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: colors.borderDark, alignItems: 'center', justifyContent: 'center' },
  checkboxChecked: { backgroundColor: colors.primary, borderColor: colors.primary },
  checkboxMark: { color: '#fff', fontSize: 14, fontWeight: '800' },
  cardContent: { flex: 1, gap: 2 },
  badgeRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, flexWrap: 'wrap', marginTop: 2 },
  finalisedBadge: { backgroundColor: colors.successLight, borderRadius: radius.sm, paddingHorizontal: 6, paddingVertical: 2 },
  finalisedBadgeText: { fontSize: font.xs, color: colors.success, fontWeight: '700' },
  cardAddress: { fontSize: font.md, fontWeight: '700', color: colors.text, lineHeight: 20 },
  cardAddressDone: { color: colors.textMid },
  cardMeta: { fontSize: font.xs, color: colors.textLight },
  removeBtn: { backgroundColor: colors.dangerLight, paddingHorizontal: spacing.sm, paddingVertical: 5, borderRadius: radius.sm },
  removeBtnText: { fontSize: font.xs, color: colors.danger, fontWeight: '700' },
  syncBtn: { backgroundColor: colors.primary, borderRadius: radius.md, padding: 14, alignItems: 'center', marginTop: spacing.md },
  syncBtnDisabled: { backgroundColor: colors.borderDark },
  syncBtnText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
  syncingRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  empty: { alignItems: 'center', justifyContent: 'center', paddingTop: 80, gap: spacing.md },
  emptyIcon: { fontSize: 48 },
  emptyTitle: { fontSize: font.lg, fontWeight: '700', color: colors.textMid },
  emptySub: { fontSize: font.sm, color: colors.textLight, textAlign: 'center' },
})
