import React, { useEffect, useState, useCallback } from 'react'
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  Alert, TextInput, Modal, ActivityIndicator, FlatList,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native'
import type { StackNavigationProp, RouteProp } from '@react-navigation/stack'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import { getLocalInspection } from '../services/database'
import { api } from '../services/api'
import Header from '../components/Header'
import SwipeableRow from '../components/SwipeableRow'
import { colors, font, radius, spacing } from '../utils/theme'

type Nav   = StackNavigationProp<RootStackParamList, 'RoomSelection'>
type Route = RouteProp<RootStackParamList, 'RoomSelection'>

function inferType(cols: string[]): string {
  const c = cols || []
  if (c.includes('reading'))                                                 return 'meter_readings'
  if (c.includes('cleanliness'))                                             return 'cleaning_summary'
  if (c.includes('name') && c.includes('answer') && c.includes('question')) return 'fire_door_safety'
  if (c.includes('answer') && c.includes('question'))                       return 'smoke_alarms'
  if (c.includes('answer') && c.includes('name'))                           return 'smoke_alarms'
  if (c.includes('condition'))                                               return 'condition_summary'
  if (c.includes('description'))                                             return 'keys'
  return 'condition_summary'
}



export default function RoomSelectionScreen() {
  const navigation = useNavigation<Nav>()
  const route      = useRoute<Route>()
  const insets     = useSafeAreaInsets()
  const { inspectionId } = route.params
  const { activeInspection, loadInspection, setReportData } = useInspectionStore()

  const [fixedSections, setFixedSections]       = useState<any[]>([])
  const [templateSections, setTemplateSections] = useState<any[]>([])
  const [loadingTemplate, setLoadingTemplate]   = useState(true)

  // Modals
  const [renameModal, setRenameModal]   = useState(false)
  const [addModal, setAddModal]         = useState(false)
  const [targetRoomId, setTargetRoomId] = useState('')
  const [targetName, setTargetName]     = useState('')

  // Add room modal state
  const [presets, setPresets]             = useState<any[]>([])
  const [presetsLoading, setPresetsLoading] = useState(false)
  const [addMode, setAddMode]             = useState<'choose' | 'custom' | 'preset'>('choose')
  const [newRoomName, setNewRoomName]     = useState('')
  const [selectedPreset, setSelectedPreset] = useState<any | null>(null)
  const [presetRoomName, setPresetRoomName] = useState('')

  useFocusEffect(useCallback(() => { loadInspection(inspectionId) }, [inspectionId]))
  useEffect(() => { loadResources() }, [inspectionId])

  async function loadResources() {
    setLoadingTemplate(true)
    try {
      const inspection = await getLocalInspection(inspectionId)

      // Use the template embedded at download time (works offline).
      // Fall back to a live API call only when the cached template is absent
      // (e.g. inspection was downloaded before this feature was added).
      let tmplData: any = inspection?.template ?? null
      if (!tmplData && inspection?.template_id) {
        try {
          const tmplRes = await api.getTemplate(inspection.template_id)
          tmplData = tmplRes.data
        } catch {
          Alert.alert('No connection', 'Could not load template. Please connect to the internet to load this inspection for the first time.')
        }
      }

      const fixedRes = await api.getFixedSections().catch(() => ({ data: [] }))
      const fixed = (fixedRes.data as any[])
        .filter((s: any) => s.enabled !== false)
        .map((s: any, secIdx: number) => ({
          ...s,
          sectionKey: `fs_${secIdx}_${s.name.toLowerCase().replace(/[^a-z0-9]/g, '_')}`,
          type: inferType(s.columns || []),
          secIdx,
        }))
      setFixedSections(fixed)

      if (tmplData) {
        setTemplateSections(
          (tmplData.sections ?? []).filter((s: any) => s.section_type === 'room')
        )
      }
    } catch {
      Alert.alert('Error', 'Could not load template. Check your connection.')
    } finally {
      setLoadingTemplate(false)
    }
  }

  async function openAddModal() {
    setAddMode('choose')
    setNewRoomName('')
    setSelectedPreset(null)
    setPresetRoomName('')
    setAddModal(true)
    // Load presets in background
    setPresetsLoading(true)
    try {
      const res = await api.getSectionPresets()
      setPresets(res.data || [])
    } catch {
      setPresets([])
    } finally {
      setPresetsLoading(false)
    }
  }

  function getReportData() {
    if (!activeInspection?.report_data) return {}
    try { return JSON.parse(activeInspection.report_data) } catch { return {} }
  }

  async function handleAddCustomRoom() {
    if (!newRoomName.trim()) return
    const key = `custom_${Date.now()}`
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd['_customRooms']) rd['_customRooms'] = []
    rd['_customRooms'].push({ key, name: newRoomName.trim() })
    await setReportData(inspectionId, rd)
    await loadInspection(inspectionId)
    setNewRoomName('')
    setAddModal(false)
  }

  async function handleAddPresetRoom() {
    if (!selectedPreset) return
    const name = presetRoomName.trim() || selectedPreset.name
    const key = `custom_${Date.now()}`
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}

    // Add to custom rooms list
    if (!rd['_customRooms']) rd['_customRooms'] = []
    rd['_customRooms'].push({ key, name })

    // Pre-populate _extra items from the preset's items
    if (selectedPreset.items?.length) {
      if (!rd[key]) rd[key] = {}
      if (!rd[key]['_extra']) rd[key]['_extra'] = []
      selectedPreset.items.forEach((item: any, i: number) => {
        const eid = `preset_${Date.now()}_${i}`
        rd[key]['_extra'].push({
          _eid: eid,
          name: item.name || '',
        })
      })
    }

    await setReportData(inspectionId, rd)
    await loadInspection(inspectionId)
    setAddModal(false)
  }

  async function handleRename() {
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd['_roomNames']) rd['_roomNames'] = {}
    rd['_roomNames'][targetRoomId] = targetName
    await setReportData(inspectionId, rd)
    await loadInspection(inspectionId)
    setRenameModal(false)
  }

  async function deleteRoomConfirmed(key: string, name: string) {
    Alert.alert(`Delete "${name}"?`, 'This removes the room and all its data.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete', style: 'destructive',
        onPress: async () => {
          const fresh = await getLocalInspection(inspectionId)
          const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
          delete rd[key]
          if (rd['_roomNames']) delete rd['_roomNames'][key]
          if (rd['_customRooms']) rd['_customRooms'] = rd['_customRooms'].filter((r: any) => r.key !== key)
          await setReportData(inspectionId, rd)
          await loadInspection(inspectionId)
        },
      },
    ])
  }

  async function handleDuplicateRoom(key: string, name: string) {
    const newKey = `custom_${Date.now()}`
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    rd[newKey] = JSON.parse(JSON.stringify(rd[key] || {}))
    if (!rd['_customRooms']) rd['_customRooms'] = []
    rd['_customRooms'].push({ key: newKey, name: `${name} (Copy)` })
    await setReportData(inspectionId, rd)
    await loadInspection(inspectionId)
  }

  function openRename(key: string, name: string) {
    setTargetRoomId(key); setTargetName(name); setRenameModal(true)
  }

  function navigateToRoom(key: string, name: string, templateSectionId?: number, sectionIndex?: number) {
    navigation.navigate('RoomInspection', {
      inspectionId, sectionKey: key, sectionName: name,
      sectionType: 'room', templateSectionId,
      sectionIndex,
    })
  }

  function roomActions(key: string, name: string) {
    return [
      { icon: '✏️', label: 'Rename', bg: colors.primaryLight, onPress: () => openRename(key, name) },
      { icon: '⧉',  label: 'Copy',   bg: '#e0f2fe',            onPress: () => handleDuplicateRoom(key, name) },
      { icon: '🗑',  label: 'Delete', bg: colors.dangerLight,   onPress: () => deleteRoomConfirmed(key, name) },
    ]
  }

  const rd = getReportData()
  const customRooms: { key: string; name: string }[] = rd['_customRooms'] || []
  const roomNames: Record<string, string> = rd['_roomNames'] || {}

  // ── Add Room Modal content ─────────────────────────────────────────────────
  function renderAddModal() {
    if (addMode === 'choose') {
      return (
        <>
          <Text style={mStyles.title}>Add Room</Text>
          <Text style={mStyles.subtitle}>Choose how to add a room</Text>

          <TouchableOpacity style={mStyles.choiceBtn} onPress={() => setAddMode('custom')}>
            <View style={mStyles.choiceText}>
              <Text style={mStyles.choiceTitle}>Custom Room</Text>
              <Text style={mStyles.choiceSub}>Start with a blank room</Text>
            </View>
            <Text style={mStyles.choiceArrow}>›</Text>
          </TouchableOpacity>

          <TouchableOpacity style={mStyles.choiceBtn} onPress={() => setAddMode('preset')}>
            <View style={mStyles.choiceText}>
              <Text style={mStyles.choiceTitle}>From Preset</Text>
              <Text style={mStyles.choiceSub}>Use a saved room template</Text>
            </View>
            <Text style={mStyles.choiceArrow}>›</Text>
          </TouchableOpacity>

          <TouchableOpacity style={mStyles.cancel} onPress={() => setAddModal(false)}>
            <Text style={mStyles.cancelText}>Cancel</Text>
          </TouchableOpacity>
        </>
      )
    }

    if (addMode === 'custom') {
      return (
        <>
          <Text style={mStyles.title}>Custom Room</Text>
          <TextInput
            style={mStyles.input}
            value={newRoomName}
            onChangeText={setNewRoomName}
            placeholder="e.g. Bedroom 3"
            placeholderTextColor={colors.textLight}
            autoFocus
          />
          <View style={mStyles.actions}>
            <TouchableOpacity style={mStyles.cancelBtn} onPress={() => setAddMode('choose')}>
              <Text style={mStyles.cancelText}>← Back</Text>
            </TouchableOpacity>
            <TouchableOpacity style={mStyles.confirm} onPress={handleAddCustomRoom}>
              <Text style={mStyles.confirmText}>Add Room</Text>
            </TouchableOpacity>
          </View>
        </>
      )
    }

    if (addMode === 'preset') {
      if (selectedPreset) {
        return (
          <>
            <Text style={mStyles.title}>{selectedPreset.name}</Text>
            <Text style={mStyles.subtitle}>{selectedPreset.item_count} item{selectedPreset.item_count !== 1 ? 's' : ''}</Text>
            <TextInput
              style={mStyles.input}
              value={presetRoomName}
              onChangeText={setPresetRoomName}
              placeholder={selectedPreset.name}
              placeholderTextColor={colors.textLight}
            />
            <Text style={mStyles.fieldLabel}>Room name (leave blank to use preset name)</Text>
            <View style={mStyles.actions}>
              <TouchableOpacity style={mStyles.cancelBtn} onPress={() => setSelectedPreset(null)}>
                <Text style={mStyles.cancelText}>← Back</Text>
              </TouchableOpacity>
              <TouchableOpacity style={mStyles.confirm} onPress={handleAddPresetRoom}>
                <Text style={mStyles.confirmText}>Add Room</Text>
              </TouchableOpacity>
            </View>
          </>
        )
      }

      return (
        <>
          <Text style={mStyles.title}>Choose Preset</Text>
          {presetsLoading ? (
            <ActivityIndicator color={colors.primary} style={{ marginVertical: spacing.lg }} />
          ) : presets.length === 0 ? (
            <View style={mStyles.emptyPresets}>
              <Text style={mStyles.emptyPresetsText}>No presets saved yet. Create room presets in the web app under Templates → Section Library.</Text>
            </View>
          ) : (
            <FlatList
              data={presets}
              keyExtractor={p => String(p.id)}
              style={mStyles.presetList}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={mStyles.presetRow}
                  onPress={() => { setSelectedPreset(item); setPresetRoomName('') }}
                >
                  <View style={mStyles.presetRowLeft}>
                    <Text style={mStyles.presetName}>{item.name}</Text>
                    <Text style={mStyles.presetMeta}>{item.item_count} item{item.item_count !== 1 ? 's' : ''}</Text>
                  </View>
                  <Text style={mStyles.choiceArrow}>›</Text>
                </TouchableOpacity>
              )}
              ItemSeparatorComponent={() => <View style={{ height: 1, backgroundColor: colors.border }} />}
            />
          )}
          <TouchableOpacity style={mStyles.backBtn} onPress={() => setAddMode('choose')}>
            <Text style={mStyles.backBtnText}>← Back to Options</Text>
          </TouchableOpacity>
        </>
      )
    }

    return null
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <Header title="Select Area" subtitle={activeInspection?.property_address} onBack={() => navigation.goBack()} />

      {loadingTemplate ? (
        <View style={styles.loading}><ActivityIndicator color={colors.primary} size="large" /></View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>

          {/* Fixed sections */}
          <Text style={styles.groupLabel}>Fixed Sections</Text>
          {fixedSections.map((section: any) => (
            <TouchableOpacity key={section.sectionKey} style={[styles.row, styles.rowMb]}
              onPress={() => navigation.navigate('RoomInspection', {
                inspectionId, sectionKey: section.sectionKey, sectionName: section.name,
                sectionType: 'fixed', fixedSectionData: JSON.stringify(section),
              })}>
              <View style={styles.rowContent}>
                <Text style={styles.rowName}>{section.name}</Text>
              </View>
              <Text style={styles.chevron}>›</Text>
            </TouchableOpacity>
          ))}

          {/* Rooms header */}
          <View style={styles.roomsHeader}>
            <Text style={styles.groupLabel}>Rooms</Text>
            <TouchableOpacity style={styles.addRoomBtn} onPress={openAddModal}>
              <Text style={styles.addRoomText}>+ Add Room</Text>
            </TouchableOpacity>
          </View>

          {templateSections.length === 0 && customRooms.length === 0 && (
            <View style={styles.noTemplate}>
              <Text style={styles.noTemplateText}>No template rooms found. Assign a template to this inspection on the web app.</Text>
            </View>
          )}

          {(templateSections.length > 0 || customRooms.length > 0) && (
            <Text style={styles.swipeHint}>Swipe left or right for options</Text>
          )}

          {/* Template rooms */}
          {templateSections.map((section: any, sectionIdx: number) => {
            const key = String(section.id)
            const displayName = roomNames[key] || section.name
            // sectionIndex is 1-based for display labels (1.1, 2.3, …)
            const sectionIndex = sectionIdx + 1
            return (
              <SwipeableRow key={key} actions={roomActions(key, displayName)}>
                <TouchableOpacity style={[styles.row, styles.rowMb]}
                  onPress={() => navigateToRoom(key, displayName, section.id, sectionIndex)}>
                  <View style={styles.rowContent}>
                    <Text style={styles.rowName}>{displayName}</Text>
                  </View>
                  <Text style={styles.chevron}>›</Text>
                </TouchableOpacity>
              </SwipeableRow>
            )
          })}

          {/* Custom rooms */}
          {customRooms.map(({ key, name }) => (
            <SwipeableRow key={key} actions={roomActions(key, name)}>
              <TouchableOpacity style={[styles.row, styles.rowMb]}
                onPress={() => navigateToRoom(key, name)}>
                <View style={styles.rowContent}>
                  <Text style={styles.rowName}>{name}</Text>
                </View>
                <Text style={styles.chevron}>›</Text>
              </TouchableOpacity>
            </SwipeableRow>
          ))}

          <TouchableOpacity style={styles.syncBtn} onPress={() => navigation.navigate('Sync')}>
            <Text style={styles.syncBtnText}>⇅ Sync Inspection</Text>
          </TouchableOpacity>
        </ScrollView>
      )}

      {/* Rename modal */}
      <Modal visible={renameModal} transparent animationType="fade">
        <View style={mStyles.overlay}><View style={mStyles.box}>
          <Text style={mStyles.title}>Rename Room</Text>
          <TextInput style={mStyles.input} value={targetName} onChangeText={setTargetName} autoFocus />
          <View style={mStyles.actions}>
            <TouchableOpacity style={mStyles.cancelBtn} onPress={() => setRenameModal(false)}>
              <Text style={mStyles.cancelText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={mStyles.confirm} onPress={handleRename}>
              <Text style={mStyles.confirmText}>Save</Text>
            </TouchableOpacity>
          </View>
        </View></View>
      </Modal>

      {/* Add room modal */}
      <Modal visible={addModal} transparent animationType="fade">
        <View style={mStyles.overlay}>
          <View style={[mStyles.box, addMode === 'preset' && !selectedPreset && mStyles.boxTall]}>
            {renderAddModal()}
          </View>
        </View>
      </Modal>
    </View>
  )
}

const mStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', alignItems: 'center', justifyContent: 'center', padding: spacing.lg },
  box: { backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.lg, width: '100%' },
  boxTall: { maxHeight: '80%' },
  title: { fontSize: font.lg, fontWeight: '700', color: colors.text, marginBottom: 4 },
  subtitle: { fontSize: font.sm, color: colors.textMid, marginBottom: spacing.md },
  fieldLabel: { fontSize: font.xs, color: colors.textLight, marginTop: 4, marginBottom: spacing.sm },
  input: { borderWidth: 2, borderColor: colors.border, borderRadius: radius.md, padding: spacing.sm, fontSize: font.md, color: colors.text, marginBottom: spacing.sm },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  cancelBtn: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.muted, alignItems: 'center' },
  cancel: { padding: 12, borderRadius: radius.md, backgroundColor: colors.muted, alignItems: 'center', marginTop: spacing.sm },
  cancelText: { color: colors.textMid, fontWeight: '600' },
  confirm: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.primary, alignItems: 'center' },
  confirmText: { color: '#fff', fontWeight: '700' },
  choiceBtn: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    backgroundColor: colors.muted, borderRadius: radius.md,
    padding: spacing.md, marginBottom: spacing.sm,
    borderWidth: 1, borderColor: colors.border,
  },
  choiceText: { flex: 1 },
  choiceTitle: { fontSize: font.md, fontWeight: '700', color: colors.text },
  choiceSub: { fontSize: font.xs, color: colors.textMid, marginTop: 1 },
  choiceArrow: { fontSize: font.xl, color: colors.textLight },
  presetList: { maxHeight: 280, marginBottom: spacing.sm },
  presetRow: {
    flexDirection: 'row', alignItems: 'center',
    paddingVertical: spacing.sm, paddingHorizontal: spacing.xs,
  },
  presetRowLeft: { flex: 1 },
  presetName: { fontSize: font.md, fontWeight: '600', color: colors.text },
  presetMeta: { fontSize: font.xs, color: colors.textLight, marginTop: 2 },
  backBtn: { padding: 14, borderRadius: radius.md, backgroundColor: colors.muted, alignItems: 'center', marginTop: spacing.md, borderWidth: 1, borderColor: colors.border },
  backBtnText: { color: colors.text, fontWeight: '700', fontSize: font.sm },
  emptyPresets: { backgroundColor: colors.muted, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  emptyPresetsText: { fontSize: font.sm, color: colors.textMid, lineHeight: 20 },
})

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { paddingHorizontal: spacing.md, paddingTop: spacing.sm, paddingBottom: 40 },
  groupLabel: { fontSize: font.xs, fontWeight: '700', color: colors.textLight, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: spacing.md, marginBottom: spacing.xs },
  swipeHint: { fontSize: 10, color: colors.textLight, textAlign: 'center', marginBottom: spacing.xs, fontStyle: 'italic' },
  roomsHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: spacing.md },
  addRoomBtn: { backgroundColor: colors.primaryLight, paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.sm },
  addRoomText: { fontSize: font.sm, color: colors.primary, fontWeight: '700' },
  noTemplate: { backgroundColor: colors.warningLight, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm },
  noTemplateText: { fontSize: font.sm, color: colors.warning, lineHeight: 18 },
  rowMb: { marginBottom: 4 },
  row: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 13, borderWidth: 1, borderColor: colors.border },
  rowContent: { flex: 1 },
  rowName: { fontSize: font.md, fontWeight: '600', color: colors.text, flex: 1 },
  chevron: { fontSize: font.xl, color: colors.textLight, marginLeft: spacing.sm },
  syncBtn: { marginTop: spacing.xl, backgroundColor: colors.accent, borderRadius: radius.md, padding: 14, alignItems: 'center' },
  syncBtnText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
})
