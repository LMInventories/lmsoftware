import React, { useEffect, useState, useCallback, useRef } from 'react'
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  Alert, TextInput, Modal, ActivityIndicator, FlatList, Animated,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native'
import type { StackNavigationProp, RouteProp } from '@react-navigation/stack'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import { getLocalInspection } from '../services/database'
import { api } from '../services/api'
import Header from '../components/Header'
import { GestureDetector, Gesture, GestureHandlerRootView } from 'react-native-gesture-handler'
import SwipeableRow from '../components/SwipeableRow'
import { colors, font, radius, spacing } from '../utils/theme'

type Nav   = StackNavigationProp<RootStackParamList, 'RoomSelection'>
type Route = RouteProp<RootStackParamList, 'RoomSelection'>

function inferType(cols: string[]): string {
  const c = cols || []
  if (c.includes('reading'))                                                   return 'meter_readings'
  if (c.includes('cleanliness'))                                               return 'cleaning_summary'
  // answer-based checks must come before condition/description
  if (c.includes('name') && c.includes('answer') && c.includes('question'))   return 'fire_door_safety'
  if (c.includes('answer') && c.includes('question'))                         return 'smoke_alarms'
  if (c.includes('answer') && c.includes('description'))                      return 'health_safety'
  if (c.includes('answer') && c.includes('name'))                             return 'smoke_alarms'
  if (c.includes('condition'))                                                 return 'condition_summary'
  if (c.includes('description'))                                               return 'keys'
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
      // Guard against partial template objects (e.g. {id, name} without sections)
      // that the inspection detail API may have included before we overwrite with
      // the full template in FetchInspectionsScreen.
      const cachedHasSections = Array.isArray(inspection?.template?.sections) &&
                                inspection.template.sections.length > 0
      let tmplData: any = cachedHasSections ? inspection.template : null
      if (!tmplData && inspection?.template_id) {
        try {
          const tmplRes = await api.getTemplate(inspection.template_id)
          tmplData = tmplRes.data
        } catch {
          Alert.alert('No connection', 'Could not load template. Please connect to the internet to load this inspection for the first time.')
        }
      }

      // Use fixed sections embedded at download time (works fully offline).
      // Fall back to a live API call only if not cached (e.g. older downloaded inspection).
      const cachedFixedOk = Array.isArray(inspection?.fixedSections) &&
                            inspection.fixedSections.length > 0
      let rawFixed: any[] = []
      if (cachedFixedOk) {
        rawFixed = inspection.fixedSections
      } else {
        try {
          const fsRes = await api.getFixedSections()
          rawFixed = Array.isArray(fsRes.data) ? fsRes.data : []
        } catch {
          // No connection and no cache — fixed sections will be empty
          console.warn('[RoomSelection] No cached fixed sections and no connection.')
        }
      }
      const fixed = rawFixed
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
          try {
            const fresh = getLocalInspection(inspectionId)
            const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}

            // Clear data for this room key
            delete rd[key]
            if (rd['_roomNames']) delete rd['_roomNames'][key]

            // Remove from custom rooms list (if it was a custom room)
            if (rd['_customRooms']) rd['_customRooms'] = rd['_customRooms'].filter((r: any) => r.key !== key)

            // Remove from ordering list
            if (rd['_roomOrder']) rd['_roomOrder'] = rd['_roomOrder'].filter((k: string) => k !== key)

            // For template rooms the key comes from the template and won't be in
            // _customRooms — track it in _hiddenRooms so buildOrderedRooms() filters it out.
            if (!rd['_hiddenRooms']) rd['_hiddenRooms'] = []
            if (!rd['_hiddenRooms'].includes(key)) rd['_hiddenRooms'].push(key)

            setReportData(inspectionId, rd)
            loadInspection(inspectionId)
          } catch (e) {
            Alert.alert('Delete failed', 'Could not delete the room. Please try again.')
          }
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

  // ── Room ordering ──────────────────────────────────────────────────────────
  // Build a unified ordered list of all rooms (template + custom) so they can
  // be reordered freely across both groups. _roomOrder in report_data stores
  // an array of room keys; rooms not yet in it appear at the end in default order.
  interface RoomEntry {
    key: string
    name: string
    templateSectionId?: number
    sectionIndex?: number
  }

  function buildOrderedRooms(): RoomEntry[] {
    const hidden: string[] = rd['_hiddenRooms'] || []
    const all: RoomEntry[] = [
      ...templateSections
        .filter((s: any) => !hidden.includes(String(s.id)))
        .map((s: any, i: number) => ({
          key: String(s.id),
          name: roomNames[String(s.id)] || s.name,
          templateSectionId: s.id,
          sectionIndex: i + 1,
        })),
      ...customRooms
        .filter(r => !hidden.includes(r.key))
        .map(r => ({ key: r.key, name: r.name })),
    ]
    const order: string[] = rd['_roomOrder'] || []
    if (!order.length) return all
    const orderMap = new Map(order.map((k: string, i: number) => [k, i]))
    return [...all].sort((a, b) => {
      const ai = orderMap.has(a.key) ? orderMap.get(a.key)! : Infinity
      const bi = orderMap.has(b.key) ? orderMap.get(b.key)! : Infinity
      return ai - bi
    })
  }

  // ── Drag-to-reorder state ──────────────────────────────────────────────────
  // ROW_H: approximate row height (paddingVertical 13×2 + text ~20 + marginBottom 4)
  const ROW_H = 54

  // dragFrom / dragTo tracked in refs (not state) so gesture callbacks always
  // see the latest values without stale closures.
  const dragFromRef = useRef<number | null>(null)
  const dragToRef   = useRef<number | null>(null)
  // dragFrom/To as state drives the "gap" visual (items shifting to make room).
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragTo,   setDragTo]   = useState<number | null>(null)
  // Single Animated.Value drives the dragged row's y position.
  const dragYAnim = useRef(new Animated.Value(0)).current

  async function commitReorderByIndex(from: number, to: number) {
    const ordered = buildOrderedRooms()
    const keys = ordered.map(r => r.key)
    const [moved] = keys.splice(from, 1)
    keys.splice(to, 0, moved)
    const fresh = await getLocalInspection(inspectionId)
    const freshRd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    freshRd['_roomOrder'] = keys
    await setReportData(inspectionId, freshRd)
    await loadInspection(inspectionId)
  }

  function makeDragGesture(idx: number) {
    return Gesture.Pan()
      .runOnJS(true)
      .minDistance(4)
      .onStart(() => {
        dragYAnim.setValue(0)
        dragFromRef.current = idx
        dragToRef.current   = idx
        setDragFrom(idx)
        setDragTo(idx)
      })
      .onUpdate((e) => {
        dragYAnim.setValue(e.translationY)
        const rooms = buildOrderedRooms()
        const newTo = Math.max(0, Math.min(rooms.length - 1, Math.round(idx + e.translationY / ROW_H)))
        if (newTo !== dragToRef.current) {
          dragToRef.current = newTo
          setDragTo(newTo)
        }
      })
      .onEnd(() => {
        const from = dragFromRef.current
        const to   = dragToRef.current
        dragYAnim.setValue(0)
        dragFromRef.current = null
        dragToRef.current   = null
        setDragFrom(null)
        setDragTo(null)
        if (from !== null && to !== null && from !== to) {
          commitReorderByIndex(from, to)
        }
      })
      .onFinalize(() => {
        dragYAnim.setValue(0)
        dragFromRef.current = null
        dragToRef.current   = null
        setDragFrom(null)
        setDragTo(null)
      })
  }

  // Returns how far a non-dragged item should shift (in px) to show the gap.
  function getShift(idx: number, from: number, to: number): number {
    if (from < to) {
      // Dragging down: items between from+1..to shift up
      if (idx > from && idx <= to) return -ROW_H
    } else if (from > to) {
      // Dragging up: items between to..from-1 shift down
      if (idx >= to && idx < from) return ROW_H
    }
    return 0
  }

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
    <GestureHandlerRootView style={[styles.screen, { paddingTop: insets.top }]}>
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
            <Text style={styles.swipeHint}>Swipe for options · Drag  ≡  to reorder</Text>
          )}

          {/* All rooms — template + custom — in user-defined order.
              Each row wraps in an Animated.View so the dragged item follows
              the finger (dragYAnim) while others shift to show the drop gap. */}
          {buildOrderedRooms().map((room, idx) => {
            const isDragging = dragFrom === idx
            const shift      = (dragFrom !== null && dragTo !== null && !isDragging)
              ? getShift(idx, dragFrom, dragTo)
              : 0

            return (
              <Animated.View
                key={room.key}
                style={[
                  styles.rowMb,
                  isDragging
                    ? { transform: [{ translateY: dragYAnim }], zIndex: 20, elevation: 8 }
                    : shift !== 0
                      ? { transform: [{ translateY: shift }] }
                      : {},
                ]}
              >
                <SwipeableRow
                  actions={roomActions(room.key, room.name)}
                  disabled={dragFrom !== null}
                >
                  <View style={[styles.row, isDragging && styles.rowDragging]}>
                    <TouchableOpacity
                      style={styles.rowContent}
                      onPress={() => dragFrom === null && navigateToRoom(room.key, room.name, room.templateSectionId, room.sectionIndex)}
                      activeOpacity={0.7}
                    >
                      <Text style={styles.rowName}>{room.name}</Text>
                    </TouchableOpacity>
                    <GestureDetector gesture={makeDragGesture(idx)}>
                      <View style={styles.dragHandle} hitSlop={{ top: 10, bottom: 10, left: 10, right: 4 }}>
                        <Text style={styles.dragHandleIcon}>≡</Text>
                      </View>
                    </GestureDetector>
                  </View>
                </SwipeableRow>
              </Animated.View>
            )
          })}

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
    </GestureHandlerRootView>
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
  rowDragging: { backgroundColor: '#f0f7ff', borderColor: colors.primary, shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.15, shadowRadius: 8 },
  rowContent: { flex: 1 },
  rowName: { fontSize: font.md, fontWeight: '600', color: colors.text, flex: 1 },
  chevron: { fontSize: font.xl, color: colors.textLight, marginLeft: spacing.sm },
  dragHandle: { paddingHorizontal: 10, paddingVertical: 6, alignItems: 'center', justifyContent: 'center' },
  dragHandleIcon: { fontSize: 20, color: colors.textLight, letterSpacing: 1 },
  syncBtn: { marginTop: spacing.xl, backgroundColor: colors.accent, borderRadius: radius.md, padding: 14, alignItems: 'center' },
  syncBtnText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
})
