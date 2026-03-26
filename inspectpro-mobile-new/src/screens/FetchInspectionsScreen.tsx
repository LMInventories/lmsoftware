import React, { useState, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, Modal,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useNavigation, useFocusEffect } from '@react-navigation/native'
import type { StackNavigationProp } from '@react-navigation/stack'

import * as FileSystem from 'expo-file-system/legacy'

import type { RootStackParamList } from '../../App'
import { api } from '../services/api'
import { saveInspection, getLocalInspections } from '../services/database'
import { colors, font, radius, spacing, TYPE_LABELS, STATUS_COLORS } from '../utils/theme'
import Header from '../components/Header'
import StatusBadge from '../components/StatusBadge'

/**
 * When the server returns report_data with photos as base64 data URIs, write each
 * one to a local file and replace the data URI with a file:// path.
 * This prevents massive inline strings in SQLite and ensures Image components
 * can render photos reliably.
 *
 * Works for any itemKey including '_overview' (the room overview key).
 */
async function extractBase64PhotosToFiles(inspectionId: number, rd: any): Promise<any> {
  const dir = `${FileSystem.documentDirectory}photos/${inspectionId}/`
  let dirReady = false

  const ensureDir = async () => {
    if (!dirReady) {
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true })
      dirReady = true
    }
  }

  for (const sectionKey of Object.keys(rd)) {
    const section = rd[sectionKey]
    if (!section || typeof section !== 'object' || Array.isArray(section)) continue

    for (const itemKey of Object.keys(section)) {
      const item = section[itemKey]
      if (!item || typeof item !== 'object' || Array.isArray(item)) continue
      if (!Array.isArray(item._photos)) continue

      const hasBase64 = item._photos.some((u: string) => typeof u === 'string' && u.startsWith('data:'))
      if (!hasBase64) continue

      await ensureDir()
      item._photos = await Promise.all(
        item._photos.map(async (uri: string) => {
          if (!uri.startsWith('data:image')) return uri
          try {
            const b64 = uri.split(',')[1]
            // Unique filename — timestamp + short random suffix avoids collisions
            const dest = `${dir}${Date.now()}_${Math.random().toString(36).slice(2, 7)}.jpg`
            await FileSystem.writeAsStringAsync(dest, b64, {
              encoding: FileSystem.EncodingType.Base64,
            })
            return dest
          } catch (e) {
            console.warn('[FetchInspections] could not extract photo to file:', e)
            return uri  // keep data URI as fallback — better than losing the photo
          }
        })
      )
    }
  }
  return rd
}

type Nav = StackNavigationProp<RootStackParamList, 'FetchInspections'>

export default function FetchInspectionsScreen() {
  const navigation = useNavigation<Nav>()
  const insets = useSafeAreaInsets()

  const [serverList, setServerList]   = useState<any[]>([])
  const [localIds, setLocalIds]       = useState<Set<number>>(new Set())
  const [selected, setSelected]       = useState<Set<number>>(new Set())
  const [loading, setLoading]         = useState(false)
  const [fetching, setFetching]       = useState(false)
  const [results, setResults]         = useState<{ id: number; address: string; success: boolean; error?: string }[] | null>(null)
  const [confirmModal, setConfirmModal] = useState(false)

  useFocusEffect(useCallback(() => {
    loadServer()
  }, []))

  async function loadServer() {
    setLoading(true)
    setResults(null)
    try {
      const [serverRes, local] = await Promise.all([
        api.getInspections(),
        getLocalInspections(),
      ])
      const assigned = (serverRes.data as any[]).filter((i: any) =>
        ['assigned', 'active', 'processing'].includes(i.status)
      )
      setServerList(assigned)
      setLocalIds(new Set(local.map((i: any) => i.id)))
    } catch {
      Alert.alert('Error', 'Could not load inspections. Check your connection.')
    } finally {
      setLoading(false)
    }
  }

  function toggleSelect(id: number) {
    setSelected(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  function toggleAll() {
    if (selected.size === serverList.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(serverList.map(i => i.id)))
    }
  }

  async function runFetch() {
    setConfirmModal(false)
    setFetching(true)
    const res: { id: number; address: string; success: boolean; error?: string }[] = []

    // Fetch fixed sections once before the loop — they're global, not per-inspection.
    // We embed a copy in every downloaded inspection so the app works fully offline.
    let fixedSectionsData: any[] = []
    try {
      const fsRes = await api.getFixedSections()
      fixedSectionsData = Array.isArray(fsRes.data) ? fsRes.data : []
    } catch (fsErr) {
      console.warn('[FetchInspections] Could not pre-fetch fixed sections:', fsErr)
      // Non-fatal: app will attempt a live fetch when rooms are opened
    }

    for (const id of Array.from(selected)) {
      const inspection = serverList.find(i => i.id === id)
      if (!inspection) continue
      try {
        // Fetch full inspection detail (includes property.overview_photo)
        const detail = await api.getInspection(id)
        // Normalise detail response: add flat fields the app reads everywhere
        // Detail has nested property/client/inspector/typist objects;
        // the list endpoint has flat fields. We need both.
        const d = detail.data
        const normalised: any = {
          ...d,
          property_address:  d.property?.address   ?? inspection.property_address ?? 'Unknown address',
          client_name:       d.client?.name         ?? inspection.client_name      ?? '',
          client_id:         d.client?.id           ?? d.property?.client_id       ?? null,
          inspector_name:    d.inspector?.name      ?? inspection.inspector_name   ?? '',
          typist_name:       d.typist?.name         ?? inspection.typist_name      ?? '',
          typist_is_ai:      d.typist_is_ai         ?? d.typist?.is_ai              ?? false,
        }

        // Always fetch the full template and overwrite whatever the inspection
        // detail API returned. The detail endpoint may include a partial template
        // object (e.g. {id, name} without sections), which is truthy but useless.
        // We need the full object with sections[].items[] for rooms to work offline.
        if (d.template_id) {
          try {
            const tmplRes = await api.getTemplate(d.template_id)
            normalised.template = tmplRes.data
          } catch (tmplErr) {
            console.warn('[FetchInspections] Could not pre-fetch template:', tmplErr)
            // Non-fatal: app will attempt a live fetch when rooms are opened
          }
        }

        // Embed fixed sections so the app works fully offline.
        // Fixed sections are global (not inspection-specific) but we embed a copy
        // in each inspection record so they're available without a connection.
        if (fixedSectionsData.length > 0) {
          normalised.fixedSections = fixedSectionsData
        }

        // Normalise report_data from the server response:
        //  - Server may return it as a parsed object or as a JSON string — handle both.
        //  - Extract any base64 data URIs to local files so Image renders them reliably
        //    and SQLite doesn't store huge inline strings.
        if (normalised.report_data) {
          try {
            const rdObj = typeof normalised.report_data === 'string'
              ? JSON.parse(normalised.report_data)
              : normalised.report_data
            const extracted = await extractBase64PhotosToFiles(id, rdObj)
            normalised.report_data = JSON.stringify(extracted)
          } catch (e) {
            console.warn('[FetchInspections] report_data processing failed:', e)
            // Ensure it's stored as a string at minimum
            if (typeof normalised.report_data !== 'string') {
              normalised.report_data = JSON.stringify(normalised.report_data)
            }
          }
        }

        await saveInspection(normalised)
        res.push({ id, address: normalised.property_address, success: true })
      } catch (err: any) {
        res.push({ id, address: inspection.property_address, success: false, error: err.message || 'Network error' })
      }
    }

    // Refresh local IDs
    const local = await getLocalInspections()
    setLocalIds(new Set(local.map((i: any) => i.id)))
    setSelected(new Set())
    setFetching(false)
    setResults(res)
  }

  function formatDate(str: string | null) {
    if (!str) return '—'
    return new Date(str).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  }

  function renderItem({ item }: { item: any }) {
    const isLocal = localIds.has(item.id)
    const isSel   = selected.has(item.id)
    return (
      <TouchableOpacity
        style={[styles.card, isSel && styles.cardSelected]}
        onPress={() => toggleSelect(item.id)}
        activeOpacity={0.75}
      >
        <View style={styles.cardCheck}>
          <View style={[styles.checkbox, isSel && styles.checkboxChecked]}>
            {isSel && <Text style={styles.checkmark}>✓</Text>}
          </View>
        </View>
        <View style={styles.cardBody}>
          <Text style={styles.address} numberOfLines={2}>{item.property_address}</Text>
          <Text style={styles.client}>{item.client_name || '—'}</Text>
          <View style={styles.metaRow}>
            <Text style={styles.meta}>{TYPE_LABELS[item.inspection_type] ?? item.inspection_type}</Text>
            <Text style={styles.metaDot}>·</Text>
            <Text style={styles.meta}>{formatDate(item.conduct_date)}</Text>
          </View>
          <View style={styles.badges}>
            <StatusBadge status={item.status} small />
            {isLocal && (
              <View style={styles.localBadge}>
                <Text style={styles.localBadgeText}>✓ Downloaded</Text>
              </View>
            )}
          </View>
        </View>
      </TouchableOpacity>
    )
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <Header
        title="Fetch Inspections"
        subtitle="Select inspections to download"
        onBack={() => navigation.goBack()}
      />

      {/* Results banner */}
      {results && (
        <View style={styles.resultsBanner}>
          <Text style={styles.resultsTitle}>
            {results.filter(r => r.success).length}/{results.length} downloaded
          </Text>
          {results.map(r => (
            <Text key={r.id} style={r.success ? styles.resultOk : styles.resultFail}>
              {r.success ? '✓' : '✕'} {r.address}{!r.success && ` — ${r.error}`}
            </Text>
          ))}
        </View>
      )}

      {loading ? (
        <View style={styles.loading}><ActivityIndicator color={colors.primary} size="large" /></View>
      ) : serverList.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyIcon}>📋</Text>
          <Text style={styles.emptyTitle}>No assigned inspections</Text>
          <Text style={styles.emptySub}>There are no inspections assigned to you on the server.</Text>
          <TouchableOpacity style={styles.refreshBtn} onPress={loadServer}>
            <Text style={styles.refreshBtnText}>↺ Refresh</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <>
          <View style={styles.listHeader}>
            <Text style={styles.listCount}>{serverList.length} inspection{serverList.length !== 1 ? 's' : ''} assigned</Text>
            <TouchableOpacity onPress={toggleAll}>
              <Text style={styles.toggleAll}>
                {selected.size === serverList.length ? 'Deselect All' : 'Select All'}
              </Text>
            </TouchableOpacity>
          </View>

          <FlatList
            data={serverList}
            keyExtractor={i => String(i.id)}
            renderItem={renderItem}
            contentContainerStyle={styles.list}
            refreshing={loading}
            onRefresh={loadServer}
          />

          <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
            <TouchableOpacity
              style={[styles.fetchBtn, (selected.size === 0 || fetching) && styles.fetchBtnDisabled]}
              onPress={() => { if (selected.size > 0) setConfirmModal(true) }}
              disabled={selected.size === 0 || fetching}
            >
              {fetching ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.fetchBtnText}>
                  ↓ Download {selected.size > 0 ? `${selected.size} Inspection${selected.size !== 1 ? 's' : ''}` : ''}
                </Text>
              )}
            </TouchableOpacity>
          </View>
        </>
      )}

      <Modal visible={confirmModal} transparent animationType="fade">
        <View style={modalStyles.overlay}>
          <View style={modalStyles.box}>
            <Text style={modalStyles.title}>Download {selected.size} Inspection{selected.size !== 1 ? 's' : ''}?</Text>
            <Text style={modalStyles.body}>
              This will download all inspection data to your device, including property photos and templates. Make sure you have a good connection.
            </Text>
            {Array.from(selected).map(id => {
              const insp = serverList.find(i => i.id === id)
              return (
                <Text key={id} style={modalStyles.listItem}>
                  • {insp?.property_address}
                </Text>
              )
            })}
            <View style={modalStyles.actions}>
              <TouchableOpacity style={modalStyles.cancel} onPress={() => setConfirmModal(false)}>
                <Text style={modalStyles.cancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={modalStyles.confirm} onPress={runFetch}>
                <Text style={modalStyles.confirmText}>Download</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  )
}

const modalStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', alignItems: 'center', justifyContent: 'center' },
  box: { backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.lg, width: '88%' },
  title: { fontSize: font.lg, fontWeight: '700', color: colors.text, marginBottom: spacing.sm },
  body: { fontSize: font.sm, color: colors.textMid, marginBottom: spacing.sm, lineHeight: 20 },
  listItem: { fontSize: font.sm, color: colors.text, marginBottom: 4, paddingLeft: spacing.sm },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  cancel: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.muted, alignItems: 'center' },
  cancelText: { color: colors.textMid, fontWeight: '600' },
  confirm: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.primary, alignItems: 'center' },
  confirmText: { color: '#fff', fontWeight: '700' },
})

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  resultsBanner: { backgroundColor: colors.surface, padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  resultsTitle: { fontSize: font.md, fontWeight: '700', color: colors.text, marginBottom: 4 },
  resultOk: { fontSize: font.sm, color: colors.success, fontWeight: '600' },
  resultFail: { fontSize: font.sm, color: colors.danger },
  listHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: spacing.md, paddingVertical: spacing.sm, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  listCount: { fontSize: font.sm, color: colors.textMid, fontWeight: '600' },
  toggleAll: { fontSize: font.sm, color: colors.accent, fontWeight: '600' },
  list: { padding: spacing.md, gap: spacing.sm },
  card: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, borderWidth: 1.5, borderColor: colors.border },
  cardSelected: { borderColor: colors.primary, backgroundColor: colors.primaryLight },
  cardCheck: { marginRight: spacing.sm },
  checkbox: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: colors.borderDark, alignItems: 'center', justifyContent: 'center' },
  checkboxChecked: { backgroundColor: colors.primary, borderColor: colors.primary },
  checkmark: { color: '#fff', fontSize: 14, fontWeight: '800' },
  cardBody: { flex: 1, gap: 2 },
  address: { fontSize: font.md, fontWeight: '700', color: colors.text, lineHeight: 20 },
  client: { fontSize: font.sm, color: colors.textMid },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  meta: { fontSize: font.xs, color: colors.textLight },
  metaDot: { fontSize: font.xs, color: colors.textLight },
  badges: { flexDirection: 'row', gap: spacing.xs, marginTop: 4, flexWrap: 'wrap' },
  localBadge: { backgroundColor: colors.successLight, paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.sm },
  localBadgeText: { fontSize: 10, color: colors.success, fontWeight: '700' },
  footer: { padding: spacing.md, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  fetchBtn: { backgroundColor: colors.primary, borderRadius: radius.md, padding: 14, alignItems: 'center' },
  fetchBtnDisabled: { backgroundColor: colors.borderDark },
  fetchBtnText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.md, padding: spacing.xl },
  emptyIcon: { fontSize: 48 },
  emptyTitle: { fontSize: font.lg, fontWeight: '700', color: colors.textMid },
  emptySub: { fontSize: font.sm, color: colors.textLight, textAlign: 'center' },
  refreshBtn: { backgroundColor: colors.primary, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: 12 },
  refreshBtnText: { color: '#fff', fontWeight: '700' },
})
