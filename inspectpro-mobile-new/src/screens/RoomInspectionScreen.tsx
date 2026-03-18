import React, { useEffect, useState, useCallback } from 'react'
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  TextInput, Alert, Image, Modal, ActivityIndicator,
  KeyboardAvoidingView, Platform,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native'
import type { StackNavigationProp, RouteProp } from '@react-navigation/stack'
import * as ImagePicker from 'expo-image-picker'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import { useAuthStore } from '../stores/authStore'
import { saveAudioRecording, getAudioRecordingsForItem, getLocalInspection } from '../services/database'
import AudioRecorderWidget from '../components/AudioRecorderWidget'
import Header from '../components/Header'
import { colors, font, radius, spacing } from '../utils/theme'
import { api } from '../services/api'
import SwipeableRow from '../components/SwipeableRow'
import HumanTypistRecorder, { HumanRecording } from '../components/HumanTypistRecorder'

type Nav   = StackNavigationProp<RootStackParamList, 'RoomInspection'>
type Route = RouteProp<RootStackParamList, 'RoomInspection'>

const ANSWER_OPTIONS      = ['Yes', 'No', 'N/A']
const CLEANLINESS_OPTIONS = [
  'Professionally Cleaned',
  'Professionally Cleaned — Receipt Seen',
  'Professionally Cleaned with Omissions',
  'Domestically Cleaned',
  'Domestically Cleaned with Omissions',
  'Not Clean',
]

function OptionPicker({ options, value, onSelect }: { options: string[]; value: string; onSelect: (v: string) => void }) {
  return (
    <View style={optStyles.row}>
      {options.map(opt => (
        <TouchableOpacity key={opt} style={[optStyles.btn, value === opt && optStyles.btnActive]} onPress={() => onSelect(opt === value ? '' : opt)}>
          <Text style={[optStyles.text, value === opt && optStyles.textActive]}>{opt}</Text>
        </TouchableOpacity>
      ))}
    </View>
  )
}

export default function RoomInspectionScreen() {
  const navigation = useNavigation<Nav>()
  const route      = useRoute<Route>()
  const insets     = useSafeAreaInsets()
  const { inspectionId, sectionKey, sectionName, sectionType, templateSectionId, fixedSectionData } = route.params
  const { activeInspection, loadInspection, setReportData, humanRecordings, addHumanRecording, removeHumanRecording } = useInspectionStore()
  const { user } = useAuthStore()

  const [items, setItems]               = useState<any[]>([])
  const [sectionType_, setSectionType_] = useState<string>('room')
  const [recordings, setRecordings]     = useState<Record<string, any[]>>({})
  const [addItemModal, setAddItemModal] = useState(false)
  const [newItemName, setNewItemName]   = useState('')
  const [loading, setLoading]           = useState(true)
  const [renameItemModal, setRenameItemModal] = useState(false)
  const [renameItemId, setRenameItemId]       = useState('')
  const [renameItemName, setRenameItemName]   = useState('')

  // Sub-item state — tracks which items have been expanded to show sub-items
  // Sub-items stored in report_data[sectionKey][itemId]._subs matching web app format

  // AI typist state
  const [hasAiTypist, setHasAiTypist]           = useState(false)
  const [aiProcessingItem, setAiProcessingItem] = useState<string | null>(null)
  const [aiError, setAiError]                   = useState('')

  // Cleanliness dropdown state
  const [cleanlinessOpen, setCleanlinessOpen]   = useState(false)
  const [cleanlinessItemId, setCleanlinessItemId] = useState('')

  // Human typist state
  const [isHumanTypist, setIsHumanTypist]   = useState(false)
  const [activeItemKey, setActiveItemKey]     = useState<string | undefined>(undefined)
  const [activeItemName, setActiveItemName]   = useState<string | undefined>(undefined)

  useFocusEffect(useCallback(() => { loadInspection(inspectionId) }, [inspectionId]))

  useEffect(() => { buildItems() }, [sectionKey])

  async function buildItems() {
    setLoading(true)
    try {
      // Read fresh from DB — avoids store race condition
      const fresh = await getLocalInspection(inspectionId)

      // Determine typist mode
      if (fresh) {
        const role = user?.role
        const typistMode = user?.typist_mode   // clerk's own typist_mode setting
        const typistName = (fresh.typist_name || fresh.typist?.name || '').toLowerCase()
        const typistIsAi = fresh.typist_is_ai === true ||
                           fresh.typist?.is_ai === true ||
                           typistName === 'ai typist' ||
                           typistName.startsWith('ai ')

        // Debug — remove once confirmed working
        console.log('[TypistMode] role:', role, 'typistMode:', typistMode,
                    'typistName:', typistName, 'typistIsAi:', typistIsAi,
                    'typist_id:', fresh.typist_id)

        // AI mode: clerk explicitly set to ai_instant or ai_processing,
        //          OR the assigned typist is flagged as AI
        const aiMode = typistIsAi ||
                       typistMode === 'ai_instant' ||
                       typistMode === 'ai_processing'

        // Human mode: anyone who isn't in AI mode
        // This includes: clerks with typist_mode='human', clerks with no typist assigned,
        // clerks with a human typist assigned, and users with role='typist'
        const humanMode = !aiMode

        setHasAiTypist(aiMode)
        setIsHumanTypist(humanMode)
      }

      if (sectionType === 'fixed' && fixedSectionData) {
        const section = JSON.parse(fixedSectionData)
        setSectionType_(section.type || 'condition_summary')
        const mapped = (section.items || []).map((item: any, i: number) => adaptItem(item, section.type, i, section.secIdx))
        setItems(mapped)
      } else if (sectionType === 'room') {
        setSectionType_('room')
        let templateItems: any[] = []

        if (templateSectionId && fresh?.template_id) {
          const tmplRes = await api.getTemplate(fresh.template_id)
          const tmplSection = (tmplRes.data.sections ?? []).find((s: any) => s.id === templateSectionId)
          if (tmplSection) {
            templateItems = tmplSection.items.map((item: any) => ({
              id: String(item.id),
              label: item.name || item.label || '',
              hasDescription: true,
              hasCondition: item.requires_condition !== false,
              hasPhotos: item.requires_photo !== false,
            }))
          }
        }

        // Also load any extra items saved in report_data._extra
        const savedRd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
        const extras: any[] = (savedRd[sectionKey]?._extra || []).map((e: any) => ({
          id: e._eid,
          label: e.name || '',
          hasDescription: true,
          hasCondition: true,
          hasPhotos: true,
          custom: true,
        }))

        setItems([...templateItems, ...extras])
        setLoading(false)
        return
      }
    } catch (err) {
      console.error('buildItems error', err)
      Alert.alert('Error', 'Could not load section items. Check your connection.')
    } finally {
      setLoading(false)
    }
  }

  // Matches _adaptItem in InspectionReportView.vue
  function adaptItem(item: any, type: string, idx: number, secIdx: number) {
    const id = `fs_${secIdx}_${idx}`
    switch (type) {
      case 'meter_readings':
        return { id, name: item.name || '', type, hasReading: true, hasLocationSerial: true, hasPhotos: true }
      case 'cleaning_summary':
        return { id, name: item.name || '', type, hasCleanliness: true, hasCleanlinessNotes: true, hasPhotos: true }
      case 'fire_door_safety':
        return { id, name: item.name || '', question: item.question || '', type, hasAnswer: true, hasNotes: true, hasPhotos: true }
      case 'smoke_alarms':
      case 'health_safety':
        return { id, question: item.name || item.question || '', name: item.name || '', type, hasAnswer: true, hasNotes: true, hasPhotos: true }
      case 'keys':
        return { id, name: item.name || '', type, hasDescription: true, hasPhotos: true }
      case 'condition_summary':
      default:
        return { id, name: item.name || '', type, hasConditionText: true, hasPhotos: true }
    }
  }

  function getReportData() {
    // Always read from activeInspection store — store is updated synchronously
    // by setReportData so this is always current within a session
    if (!activeInspection?.report_data) return {}
    try { return JSON.parse(activeInspection.report_data) } catch { return {} }
  }

  function getField(itemId: string, field: string) {
    const rd = getReportData()
    return rd[sectionKey]?.[String(itemId)]?.[field] ?? ''
  }

  async function setField(itemId: string, field: string, value: any) {
    // Read fresh from DB to prevent concurrent write races
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][String(itemId)]) rd[sectionKey][String(itemId)] = {}
    rd[sectionKey][String(itemId)][field] = value
    await setReportData(inspectionId, rd)
  }

  async function addPhoto(itemId: string, base64: string) {
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][String(itemId)]) rd[sectionKey][String(itemId)] = {}
    const existing: string[] = rd[sectionKey][String(itemId)]._photos || []
    rd[sectionKey][String(itemId)]._photos = [...existing, `data:image/jpeg;base64,${base64}`]
    await setReportData(inspectionId, rd)
  }

  async function removePhoto(itemId: string, idx: number) {
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    const photos: string[] = rd[sectionKey]?.[String(itemId)]?._photos || []
    photos.splice(idx, 1)
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][String(itemId)]) rd[sectionKey][String(itemId)] = {}
    rd[sectionKey][String(itemId)]._photos = [...photos]
    await setReportData(inspectionId, rd)
  }

  async function handleTakePhoto(itemId: string) {
    const { status } = await ImagePicker.requestCameraPermissionsAsync()
    if (status !== 'granted') { Alert.alert('Permission required', 'Camera access is needed.'); return }
    const result = await ImagePicker.launchCameraAsync({ quality: 0.75, base64: true })
    if (!result.canceled && result.assets[0].base64) await addPhoto(itemId, result.assets[0].base64)
  }

  async function handlePickPhoto(itemId: string) {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync()
    if (status !== 'granted') { Alert.alert('Permission required', 'Photo library access is needed.'); return }
    const result = await ImagePicker.launchImageLibraryAsync({ quality: 0.75, base64: true, mediaTypes: ImagePicker.MediaTypeOptions.Images })
    if (!result.canceled && result.assets[0].base64) await addPhoto(itemId, result.assets[0].base64)
  }

  // ── AI Transcription ──────────────────────────────────────────────────────
  async function transcribeItem(
    itemId: string,
    itemLabel: string,
    uri: string,
    durationMs: number
  ) {
    setAiProcessingItem(itemId)
    setAiError('')
    try {
      // Read file as base64
      const { readAsStringAsync, EncodingType } = await import('expo-file-system') as any
      const audioB64 = await readAsStringAsync(uri, { encoding: EncodingType.Base64 })

      const response = await api.transcribeItem({
        audio:       audioB64,
        mimeType:    'audio/m4a',
        itemLabel,
        roomName:    sectionName,
        sectionId:   sectionKey,
        rowId:       itemId,
        sectionType: sectionType_,
      })

      const result = response.data
      const rd = getReportData()
      if (!rd[sectionKey]) rd[sectionKey] = {}
      if (!rd[sectionKey][String(itemId)]) rd[sectionKey][String(itemId)] = {}
      const row = rd[sectionKey][String(itemId)]

      // Fill fields — only if empty (matches web app behaviour)
      let changed = false
      if (sectionType_ === 'room') {
        if (result.description && !row.description) { row.description = result.description; changed = true }
        if (result.condition   && !row.condition)   { row.condition   = result.condition;   changed = true }
      } else if (sectionType_ === 'meter_readings') {
        if (result.locationSerial && !row.locationSerial) { row.locationSerial = result.locationSerial; changed = true }
        if (result.reading        && !row.reading)        { row.reading        = result.reading;        changed = true }
      } else if (sectionType_ === 'keys') {
        if (result.description && !row.description) { row.description = result.description; changed = true }
      } else if (sectionType_ === 'condition_summary') {
        if (result.condition && !row.condition) { row.condition = result.condition; changed = true }
      } else if (sectionType_ === 'cleaning_summary') {
        const cn = result.cleanlinessNotes || result.notes
        if (cn && !row.cleanlinessNotes) { row.cleanlinessNotes = cn; changed = true }
      } else {
        if (result.notes && !row.notes) { row.notes = result.notes; changed = true }
      }

      if (changed) {
        await setReportData(inspectionId, rd)
        Alert.alert('✨ AI filled', `Fields updated for: ${itemLabel}`)
      } else if (result.transcript) {
        Alert.alert('Transcribed', `No new fields to fill for: ${itemLabel}`)
      }
    } catch (err: any) {
      console.error('transcribeItem error', err)
      const msg = err.response?.data?.error || err.message || 'Transcription failed'
      setAiError(msg)
      Alert.alert('AI Error', msg)
    } finally {
      setAiProcessingItem(null)
    }
  }

  async function handleRecordingComplete(item: any, uri: string, durationMs: number) {
    await saveAudioRecording(inspectionId, sectionKey, item.id, uri, durationMs)
    const recs = await getAudioRecordingsForItem(inspectionId, sectionKey, item.id)
    setRecordings(prev => ({ ...prev, [item.id]: recs }))

    // Trigger AI transcription if AI typist assigned
    if (hasAiTypist) {
      const label = item.label || item.name || ''
      transcribeItem(item.id, label, uri, durationMs)
    }
  }

  async function handleSubItemRecordingComplete(
    parentItemId: string,
    sid: string,
    subLabel: string,
    uri: string,
    durationMs: number
  ) {
    // Save audio under the sid key
    await saveAudioRecording(inspectionId, sectionKey, sid, uri, durationMs)
    const recs = await getAudioRecordingsForItem(inspectionId, sectionKey, sid)
    setRecordings(prev => ({ ...prev, [sid]: recs }))

    if (!hasAiTypist) return

    // Transcribe and fill this sub-item's description + condition
    setAiProcessingItem(sid)
    setAiError('')
    try {
      const { readAsStringAsync, EncodingType } = await import('expo-file-system') as any
      const audioB64 = await readAsStringAsync(uri, { encoding: EncodingType.Base64 })
      const response = await api.transcribeItem({
        audio:       audioB64,
        mimeType:    'audio/m4a',
        itemLabel:   subLabel,
        roomName:    sectionName,
        sectionId:   sectionKey,
        rowId:       sid,
        sectionType: 'room',
      })
      const result = response.data
      const fresh = await getLocalInspection(inspectionId)
      const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
      const subs: any[] = rd[sectionKey]?.[String(parentItemId)]?._subs || []
      const sub = subs.find((s: any) => s._sid === sid)
      if (sub) {
        let changed = false
        if (result.description && !sub.description) { sub.description = result.description; changed = true }
        if (result.condition   && !sub.condition)   { sub.condition   = result.condition;   changed = true }
        if (changed) {
          await setReportData(inspectionId, rd)
          Alert.alert('✨ AI filled', `Sub-item updated: ${subLabel}`)
        }
      }
    } catch (err: any) {
      const msg = err.response?.data?.error || err.message || 'Transcription failed'
      setAiError(msg)
    } finally {
      setAiProcessingItem(null)
    }
  }

  async function handleAddItem() {
    if (!newItemName.trim()) return
    const key = `extra_${Date.now()}`
    const newItem = sectionType_ === 'room'
      ? { id: key, label: newItemName.trim(), hasDescription: true, hasCondition: true, hasPhotos: true, custom: true }
      : { id: key, name: newItemName.trim(), type: sectionType_, hasConditionText: true, hasPhotos: true, custom: true }
    // Read fresh to avoid overwriting concurrent writes
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey]['_extra']) rd[sectionKey]['_extra'] = []
    rd[sectionKey]['_extra'].push({ _eid: key, name: newItemName.trim() })
    await setReportData(inspectionId, rd)
    // Add to items state AFTER writing so it's consistent
    setItems(prev => [...prev, newItem])
    setNewItemName('')
    setAddItemModal(false)
  }

  async function deleteItemImmediate(itemId: string) {
    setItems(prev => prev.filter(i => i.id !== itemId))
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (rd[sectionKey]) {
      delete rd[sectionKey][String(itemId)]
      if (rd[sectionKey]['_extra']) rd[sectionKey]['_extra'] = rd[sectionKey]['_extra'].filter((e: any) => e._eid !== itemId)
    }
    await setReportData(inspectionId, rd)
  }

  async function deleteItemConfirmed(itemId: string, itemName: string) {
    Alert.alert(`Delete "${itemName}"?`, 'This cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => deleteItemImmediate(itemId) },
    ])
  }

  async function duplicateItem(itemId: string, item: any) {
    const newId = `extra_${Date.now()}`
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    const existing = rd[sectionKey]?.[String(itemId)] || {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    rd[sectionKey][newId] = JSON.parse(JSON.stringify(existing))
    if (!rd[sectionKey]['_extra']) rd[sectionKey]['_extra'] = []
    const label = item.label || item.name || ''
    rd[sectionKey]['_extra'].push({ _eid: newId, name: `${label} (Copy)` })
    await setReportData(inspectionId, rd)
    const newItem = { ...item, id: newId, label: `${label} (Copy)`, custom: true }
    setItems(prev => [...prev, newItem])
  }

  async function handleRenameItem() {
    if (!renameItemName.trim()) return
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey]['_extra']) rd[sectionKey]['_extra'] = []
    const extraIdx = rd[sectionKey]['_extra'].findIndex((e: any) => e._eid === renameItemId)
    if (extraIdx >= 0) {
      rd[sectionKey]['_extra'][extraIdx].name = renameItemName.trim()
    }
    await setReportData(inspectionId, rd)
    setItems(prev => prev.map(i => i.id === renameItemId
      ? { ...i, label: renameItemName.trim(), name: renameItemName.trim() }
      : i
    ))
    setRenameItemModal(false)
  }

  // ── Sub-items — stored as report_data[sectionKey][itemId]._subs
  // Matches web app: { _sid, description, condition }
  function getSubs(itemId: string): any[] {
    return getReportData()[sectionKey]?.[String(itemId)]?._subs ?? []
  }

  async function addSubItem(itemId: string) {
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][String(itemId)]) rd[sectionKey][String(itemId)] = {}
    if (!rd[sectionKey][String(itemId)]._subs) rd[sectionKey][String(itemId)]._subs = []
    const sid = `sub_${Date.now()}`
    rd[sectionKey][String(itemId)]._subs.push({ _sid: sid, description: '', condition: '' })
    await setReportData(inspectionId, rd)
  }

  async function removeSubItem(itemId: string, sid: string) {
    Alert.alert('Remove sub-item?', '', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: async () => {
        const fresh = await getLocalInspection(inspectionId)
        const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
        if (rd[sectionKey]?.[String(itemId)]?._subs) {
          rd[sectionKey][String(itemId)]._subs = rd[sectionKey][String(itemId)]._subs.filter((s: any) => s._sid !== sid)
          await setReportData(inspectionId, rd)
        }
      }},
    ])
  }

  async function setSubField(itemId: string, sid: string, field: string, value: string) {
    const fresh = await getLocalInspection(inspectionId)
    const rd = fresh?.report_data ? JSON.parse(fresh.report_data) : {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][String(itemId)]) rd[sectionKey][String(itemId)] = {}
    if (!rd[sectionKey][String(itemId)]._subs) rd[sectionKey][String(itemId)]._subs = []
    const sub = rd[sectionKey][String(itemId)]._subs.find((s: any) => s._sid === sid)
    if (sub) sub[field] = value
    await setReportData(inspectionId, rd)
  }

  function isItemDone(item: any) {
    const id = item.id
    return !!(
      getField(id, 'condition') || getField(id, 'answer') || getField(id, 'cleanliness') ||
      getField(id, 'reading') || getField(id, 'description') || getField(id, 'notes')
    )
  }

  function renderPhotos(item: any) {
    const photos: string[] = getReportData()[sectionKey]?.[String(item.id)]?._photos || []
    const count = photos.length
    return (
      <View style={styles.photoBlock}>
        {/* Top row: label + icon buttons */}
        <View style={styles.photosHeader}>
          <Text style={styles.fieldLabel}>
            Photos{count > 0 ? ` (${count})` : ''}
          </Text>
          <View style={styles.photoIconBtns}>
            <TouchableOpacity style={styles.photoIconBtn} onPress={() => handleTakePhoto(item.id)}>
              <Text style={styles.photoIconEmoji}>📷</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.photoIconBtn} onPress={() => handlePickPhoto(item.id)}>
              <Text style={styles.photoIconEmoji}>🖼</Text>
            </TouchableOpacity>
          </View>
        </View>
        {/* Thumbnail strip */}
        {count > 0 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.photoStrip}>
            {photos.map((uri: string, idx: number) => (
              <TouchableOpacity key={idx}
                onPress={() => navigation.navigate('ItemGallery', {
                  inspectionId, sectionKey, itemKey: String(item.id), itemName: item.label || item.name,
                })}
                onLongPress={() => Alert.alert('Remove photo?', '', [
                  { text: 'Cancel', style: 'cancel' },
                  { text: 'Remove', style: 'destructive', onPress: () => removePhoto(item.id, idx) },
                ])}>
                <Image source={{ uri }} style={styles.photoThumb} />
              </TouchableOpacity>
            ))}
          </ScrollView>
        )}
      </View>
    )
  }

  function renderVoiceNotes(item: any) {
    // Human typist: no per-item recorder — the floating bar handles all recording
    if (isHumanTypist) return null

    const isProcessing = aiProcessingItem === item.id

    // AI typist or no typist assigned: per-item recorder widget
    return (
      <View style={styles.voiceBlock}>
        {isProcessing && (
          <View style={styles.aiProcessingBadge}>
            <ActivityIndicator size="small" color={colors.accent} />
            <Text style={styles.aiProcessingText}>AI transcribing…</Text>
          </View>
        )}
        <AudioRecorderWidget
          recordings={recordings[item.id] || []}
          onRecordingComplete={async (uri, dur) => handleRecordingComplete(item, uri, dur)}
          onDeleteRecording={async (uri) => {
            setRecordings(prev => ({ ...prev, [item.id]: (prev[item.id] || []).filter((r: any) => r.file_uri !== uri) }))
          }}
          compact
        />
      </View>
    )
  }

  function renderItem(item: any) {
    const label = item.label || item.name || ''

    const baseActions = [
      {
        icon: '✏️',
        label: 'Rename',
        bg: colors.primaryLight,
        onPress: () => { setRenameItemId(item.id); setRenameItemName(label); setRenameItemModal(true) },
      },
      {
        icon: '⧉',
        label: 'Copy',
        bg: '#e0f2fe',
        onPress: () => duplicateItem(item.id, item),
      },
      {
        icon: '🗑',
        label: 'Delete',
        bg: colors.dangerLight,
        onPress: () => deleteItemConfirmed(item.id, label),
      },
    ]
    // Add sub-item action for room items (hasDescription = room items)
    const itemActions = (item.hasDescription && sectionType_ === 'room')
      ? [{ icon: '⊕', label: 'Sub-item', bg: '#f0fdf4', onPress: () => addSubItem(item.id) }, ...baseActions]
      : baseActions

    return (
      <SwipeableRow
        key={item.id}
        actions={itemActions}
      >
      <View style={styles.itemCard}>
        {/* Header */}
        <View style={styles.itemHeader}>
          <View style={styles.itemHeaderLeft}>
            <Text style={styles.itemName}>{label}</Text>
          </View>
        </View>

        {/* Question label for smoke/health/fire */}
        {item.question ? <Text style={styles.questionText}>{item.question}</Text> : null}

        {/* ── ROOM ITEMS: Description textarea then Condition textarea ── */}
        {sectionType_ === 'room' && (
          <>
            <View style={styles.fieldGroup}>
              <Text style={styles.fieldLabel}>Description</Text>
              <TextInput
                style={styles.notesInput}
                value={getField(item.id, 'description')}
                onChangeText={v => setField(item.id, 'description', v)}
                placeholder="Describe item appearance, state, notes…"
                placeholderTextColor={colors.textLight}
                multiline numberOfLines={3} textAlignVertical="top"
              />
            </View>
            {item.hasCondition !== false && (
              <View style={styles.fieldGroup}>
                <Text style={styles.fieldLabel}>Condition</Text>
                <TextInput
                  style={styles.notesInput}
                  value={getField(item.id, 'condition')}
                  onChangeText={v => setField(item.id, 'condition', v)}
                  placeholder="e.g. Good, Fair, Worn, Damaged…"
                  placeholderTextColor={colors.textLight}
                  multiline numberOfLines={2} textAlignVertical="top"
                />
              </View>
            )}
          </>
        )}

        {/* ── FIXED: condition_summary — condition text box ── */}
        {item.hasConditionText && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Condition</Text>
            <TextInput
              style={styles.notesInput}
              value={getField(item.id, 'condition')}
              onChangeText={v => setField(item.id, 'condition', v)}
              placeholder="Describe condition…"
              placeholderTextColor={colors.textLight}
              multiline numberOfLines={2} textAlignVertical="top"
            />
          </View>
        )}

        {/* Answer — smoke alarms, health & safety, fire door */}
        {item.hasAnswer && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Answer</Text>
            <OptionPicker options={ANSWER_OPTIONS} value={getField(item.id, 'answer')} onSelect={v => setField(item.id, 'answer', v)} />
          </View>
        )}

        {/* Notes — smoke/health/fire door */}
        {item.hasNotes && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Notes</Text>
            <TextInput
              style={styles.notesInput}
              value={getField(item.id, 'notes')}
              onChangeText={v => setField(item.id, 'notes', v)}
              placeholder="Notes…" placeholderTextColor={colors.textLight}
              multiline numberOfLines={2} textAlignVertical="top"
            />
          </View>
        )}

        {/* Cleanliness — cleaning summary — dropdown */}
        {item.hasCleanliness && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Cleanliness</Text>
            <TouchableOpacity
              style={styles.dropdownBtn}
              onPress={() => { setCleanlinessItemId(item.id); setCleanlinessOpen(true) }}
            >
              <Text style={[styles.dropdownBtnText, !getField(item.id, 'cleanliness') && styles.dropdownBtnPlaceholder]}>
                {getField(item.id, 'cleanliness') || 'Select cleanliness…'}
              </Text>
              <Text style={styles.dropdownChevron}>▾</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Cleanliness notes */}
        {item.hasCleanlinessNotes && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Additional Notes</Text>
            <TextInput
              style={styles.notesInput}
              value={getField(item.id, 'cleanlinessNotes')}
              onChangeText={v => setField(item.id, 'cleanlinessNotes', v)}
              placeholder="Additional notes…" placeholderTextColor={colors.textLight}
              multiline numberOfLines={2} textAlignVertical="top"
            />
          </View>
        )}

        {/* Keys — description */}
        {item.hasDescription && sectionType_ !== 'room' && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Description</Text>
            <TextInput
              style={styles.notesInput}
              value={getField(item.id, 'description')}
              onChangeText={v => setField(item.id, 'description', v)}
              placeholder="e.g. 2 × Yale keys…"
              placeholderTextColor={colors.textLight}
              multiline numberOfLines={2} textAlignVertical="top"
            />
          </View>
        )}

        {/* Meter reading */}
        {item.hasReading && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Reading</Text>
            <TextInput
              style={[styles.notesInput, styles.inlineInput]}
              value={getField(item.id, 'reading')}
              onChangeText={v => setField(item.id, 'reading', v)}
              placeholder="e.g. 12345.6" placeholderTextColor={colors.textLight}
              keyboardType="decimal-pad"
            />
          </View>
        )}

        {/* Location / serial */}
        {item.hasLocationSerial && (
          <View style={styles.fieldGroup}>
            <Text style={styles.fieldLabel}>Location / Serial</Text>
            <TextInput
              style={[styles.notesInput, styles.inlineInput]}
              value={getField(item.id, 'locationSerial')}
              onChangeText={v => setField(item.id, 'locationSerial', v)}
              placeholder="e.g. Hallway / SN123456" placeholderTextColor={colors.textLight}
            />
          </View>
        )}

        {/* Photos */}
        {renderPhotos(item)}

        {/* Voice notes for main item — always above sub-items */}
        {renderVoiceNotes(item)}

        {/* Sub-items — only for room items */}
        {sectionType_ === 'room' && getSubs(item.id).length > 0 && (
          <View style={styles.subsContainer}>
            <View style={styles.subsDivider} />
            {getSubs(item.id).map((sub: any, idx: number) => (
              <View key={sub._sid} style={styles.subItem}>
                <View style={styles.subItemHeader}>
                  <Text style={styles.subItemTitle}>—</Text>
                  <TouchableOpacity onPress={() => removeSubItem(item.id, sub._sid)}>
                    <Text style={styles.subItemDelete}>✕</Text>
                  </TouchableOpacity>
                </View>
                <View style={styles.fieldGroup}>
                  <Text style={styles.fieldLabel}>Description</Text>
                  <TextInput
                    style={styles.notesInput}
                    value={sub.description}
                    onChangeText={v => setSubField(item.id, sub._sid, 'description', v)}
                    placeholder="Describe sub-item…"
                    placeholderTextColor={colors.textLight}
                    multiline numberOfLines={2} textAlignVertical="top"
                  />
                </View>
                <View style={styles.fieldGroup}>
                  <Text style={styles.fieldLabel}>Condition</Text>
                  <TextInput
                    style={styles.notesInput}
                    value={sub.condition}
                    onChangeText={v => setSubField(item.id, sub._sid, 'condition', v)}
                    placeholder="e.g. Good, Fair, Worn…"
                    placeholderTextColor={colors.textLight}
                    multiline numberOfLines={2} textAlignVertical="top"
                  />
                </View>
                {/* Per-sub-item recorder — AI typist only */}
                {hasAiTypist && (
                  <View style={[styles.voiceBlock, { marginTop: 8 }]}>
                    {aiProcessingItem === sub._sid && (
                      <View style={styles.aiProcessingBadge}>
                        <ActivityIndicator size="small" color={colors.accent} />
                        <Text style={styles.aiProcessingText}>AI transcribing…</Text>
                      </View>
                    )}
                    <AudioRecorderWidget
                      recordings={recordings[sub._sid] || []}
                      onRecordingComplete={async (uri, dur) =>
                        handleSubItemRecordingComplete(
                          item.id, sub._sid,
                          `${item.label || item.name} — Sub-item ${idx + 1}`,
                          uri, dur
                        )
                      }
                      onDeleteRecording={async (uri) => {
                        setRecordings(prev => ({ ...prev, [sub._sid]: (prev[sub._sid] || []).filter((r: any) => r.file_uri !== uri) }))
                      }}
                      compact
                    />
                  </View>
                )}
              </View>
            ))}
          </View>
        )}

      </View>
      </SwipeableRow>
    )
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={[styles.screen, { paddingTop: insets.top }]}>
        <Header title={sectionName} subtitle={activeInspection?.property_address} onBack={() => navigation.goBack()} />

        {/* AI Typist banner */}
        {hasAiTypist && (
          <View style={styles.aiBanner}>
            <Text style={styles.aiBannerIcon}>✨</Text>
            <Text style={styles.aiBannerText}>AI Typist active — recordings fill fields automatically</Text>
          </View>
        )}


        {/* AI error banner */}
        {aiError ? (
          <View style={styles.aiErrorBanner}>
            <Text style={styles.aiErrorText}>⚠️ {aiError}</Text>
            <TouchableOpacity onPress={() => setAiError('')}><Text style={styles.aiErrorDismiss}>✕</Text></TouchableOpacity>
          </View>
        ) : null}

        {loading ? (
          <View style={styles.loading}><ActivityIndicator color={colors.primary} size="large" /></View>
        ) : (
          <ScrollView
            contentContainerStyle={[styles.scroll, isHumanTypist && { paddingBottom: 120 }]}
            keyboardShouldPersistTaps="handled"
          >
            {items.length > 0 && (
              <Text style={styles.swipeHint}>Swipe left or right for options</Text>
            )}
            {items.length === 0 && (
              <View style={styles.emptyNote}>
                <Text style={styles.emptyNoteText}>No items yet. Tap "+ Add Item" to add one.</Text>
              </View>
            )}
            {items.map(renderItem)}
            <TouchableOpacity style={styles.addItemBtn} onPress={() => setAddItemModal(true)}>
              <Text style={styles.addItemText}>+ Add Item</Text>
            </TouchableOpacity>
            <View style={{ height: 20 }} />
          </ScrollView>
        )}

        {/* Human typist recorder — fixed at bottom */}
        {isHumanTypist && (
          <HumanTypistRecorder
            inspectionId={inspectionId}
            currentSectionKey={sectionKey}
            currentSectionName={sectionName}
            currentItemKey={activeItemKey}
            currentItemName={activeItemName}
            recordings={humanRecordings[inspectionId] || []}
            onRecordingAdded={(rec) => addHumanRecording(inspectionId, rec)}
            onRecordingDeleted={(id) => removeHumanRecording(inspectionId, id)}
          />
        )}

        {/* Cleanliness dropdown modal */}
        <Modal visible={cleanlinessOpen} transparent animationType="fade">
          <View style={mStyles.overlay}>
            <View style={mStyles.box}>
              <Text style={mStyles.title}>Cleanliness</Text>
              <View style={styles.dropdownList}>
                <TouchableOpacity
                  style={styles.dropdownListItem}
                  onPress={() => { setField(cleanlinessItemId, 'cleanliness', ''); setCleanlinessOpen(false) }}
                >
                  <Text style={[styles.dropdownListItemText, styles.dropdownListItemPlaceholder]}>Clear selection</Text>
                </TouchableOpacity>
                {CLEANLINESS_OPTIONS.map(opt => {
                  const isSelected = getField(cleanlinessItemId, 'cleanliness') === opt
                  return (
                    <TouchableOpacity
                      key={opt}
                      style={[styles.dropdownListItem, isSelected && styles.dropdownListItemActive]}
                      onPress={() => { setField(cleanlinessItemId, 'cleanliness', opt); setCleanlinessOpen(false) }}
                    >
                      <Text style={[styles.dropdownListItemText, isSelected && styles.dropdownListItemTextActive]}>
                        {opt}
                      </Text>
                      {isSelected && <Text style={styles.dropdownCheck}>✓</Text>}
                    </TouchableOpacity>
                  )
                })}
              </View>
              <TouchableOpacity style={[mStyles.cancel, { marginTop: spacing.sm }]} onPress={() => setCleanlinessOpen(false)}>
                <Text style={mStyles.cancelText}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>

        {/* Rename item modal */}
        <Modal visible={renameItemModal} transparent animationType="fade">
          <View style={mStyles.overlay}><View style={mStyles.box}>
            <Text style={mStyles.title}>Rename Item</Text>
            <TextInput style={mStyles.input} value={renameItemName} onChangeText={setRenameItemName} autoFocus />
            <View style={mStyles.actions}>
              <TouchableOpacity style={mStyles.cancel} onPress={() => setRenameItemModal(false)}>
                <Text style={mStyles.cancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={mStyles.confirm} onPress={handleRenameItem}>
                <Text style={mStyles.confirmText}>Save</Text>
              </TouchableOpacity>
            </View>
          </View></View>
        </Modal>

        <Modal visible={addItemModal} transparent animationType="fade">
          <View style={mStyles.overlay}><View style={mStyles.box}>
            <Text style={mStyles.title}>Add Item</Text>
            <TextInput style={mStyles.input} value={newItemName} onChangeText={setNewItemName}
              placeholder="Item name…" placeholderTextColor={colors.textLight} autoFocus />
            <View style={mStyles.actions}>
              <TouchableOpacity style={mStyles.cancel} onPress={() => { setAddItemModal(false); setNewItemName('') }}>
                <Text style={mStyles.cancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={mStyles.confirm} onPress={handleAddItem}>
                <Text style={mStyles.confirmText}>Add</Text>
              </TouchableOpacity>
            </View>
          </View></View>
        </Modal>
      </View>
    </KeyboardAvoidingView>
  )
}

const optStyles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 4 },
  btn: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.sm, backgroundColor: colors.muted, borderWidth: 1.5, borderColor: colors.border },
  btnActive: { backgroundColor: colors.primaryLight, borderColor: colors.primary },
  text: { fontSize: font.sm, color: colors.textMid, fontWeight: '500' },
  textActive: { color: colors.primary, fontWeight: '700' },
})
const mStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', alignItems: 'center', justifyContent: 'center' },
  box: { backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.lg, width: '80%' },
  title: { fontSize: font.lg, fontWeight: '700', color: colors.text, marginBottom: spacing.md },
  input: { borderWidth: 2, borderColor: colors.border, borderRadius: radius.md, padding: spacing.sm, fontSize: font.md, color: colors.text, marginBottom: spacing.md },
  actions: { flexDirection: 'row', gap: spacing.sm },
  cancel: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.muted, alignItems: 'center' },
  cancelText: { color: colors.textMid, fontWeight: '600' },
  confirm: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.primary, alignItems: 'center' },
  confirmText: { color: '#fff', fontWeight: '700' },
})
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  aiBanner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: '#eef2ff', borderBottomWidth: 1, borderBottomColor: '#c7d2fe', paddingHorizontal: spacing.md, paddingVertical: 10 },
  aiBannerIcon: { fontSize: 16 },
  aiBannerText: { fontSize: font.sm, color: '#3730a3', fontWeight: '600', flex: 1 },
  aiErrorBanner: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: colors.dangerLight, paddingHorizontal: spacing.md, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#fca5a5' },
  aiErrorText: { fontSize: font.sm, color: colors.danger, flex: 1 },
  aiErrorDismiss: { fontSize: font.md, color: colors.danger, fontWeight: '700', paddingLeft: spacing.sm },
  scroll: { paddingHorizontal: spacing.sm, paddingTop: spacing.sm },
  itemCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  itemHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 },
  itemHeaderLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flex: 1 },
  itemName: { fontSize: font.sm, fontWeight: '700', color: colors.text, flex: 1 },
  deleteBtn: { fontSize: font.md, color: colors.danger, padding: 4 },
  questionText: { fontSize: font.sm, color: colors.textMid, fontStyle: 'italic', marginBottom: spacing.xs },
  fieldGroup: { marginTop: 8 },
  fieldLabel: { fontSize: font.xs, fontWeight: '700', color: colors.textLight, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 },
  notesInput: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: 8, fontSize: font.sm, color: colors.text, backgroundColor: colors.surface, minHeight: 60 },
  inlineInput: { minHeight: 0, height: 42 },
  photoBlock: { marginTop: 8 },
  photosHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  photoIconBtns: { flexDirection: 'row', gap: spacing.xs },
  photoIconBtn: {
    width: 44, height: 44,
    backgroundColor: colors.muted,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    alignItems: 'center', justifyContent: 'center',
  },
  photoIconEmoji: { fontSize: 22 },
  photoStrip: { marginTop: 4 },
  photoThumb: { width: 80, height: 80, borderRadius: radius.md, marginRight: 6 },
  voiceBlock: { marginTop: 8, gap: 4 },
  aiProcessingBadge: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#eef2ff', paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.sm, alignSelf: 'flex-start' },
  aiProcessingText: { fontSize: font.xs, color: '#3730a3', fontWeight: '600' },
  addItemBtn: { borderWidth: 1, borderColor: colors.border, borderStyle: 'dashed', borderRadius: radius.md, padding: spacing.sm, alignItems: 'center', marginTop: spacing.xs },
  addItemText: { fontSize: font.sm, color: colors.textMid, fontWeight: '600' },
  emptyNote: { backgroundColor: colors.muted, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  subsContainer: { marginTop: spacing.sm },
  subsDivider: { height: 1, backgroundColor: colors.border, marginBottom: spacing.sm, borderStyle: 'dashed' },
  subItem: { backgroundColor: '#fafafa', borderRadius: radius.sm, padding: spacing.sm, marginBottom: spacing.sm, borderLeftWidth: 3, borderLeftColor: colors.primaryLight, borderWidth: 1, borderColor: colors.border },
  subItemHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  subItemTitle: { fontSize: font.md, fontWeight: '400', color: colors.textLight },
  subItemDelete: { fontSize: font.sm, color: colors.danger, padding: 4 },
  dropdownList: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: 'hidden', marginBottom: 4 },
  dropdownListItem: { paddingVertical: 13, paddingHorizontal: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  dropdownListItemActive: { backgroundColor: colors.primaryLight },
  dropdownListItemText: { fontSize: font.sm, color: colors.text, flex: 1 },
  dropdownListItemPlaceholder: { color: colors.textLight, fontStyle: 'italic' },
  dropdownListItemTextActive: { color: colors.primary, fontWeight: '700' },
  dropdownCheck: { fontSize: font.sm, color: colors.primary, fontWeight: '700' },
  dropdownBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: 10, backgroundColor: colors.surface },
  dropdownBtnText: { fontSize: font.sm, color: colors.text, flex: 1 },
  dropdownBtnPlaceholder: { color: colors.textLight },
  dropdownChevron: { fontSize: font.sm, color: colors.textLight, marginLeft: spacing.xs },
  swipeHint: { fontSize: 10, color: colors.textLight, textAlign: 'center', marginBottom: spacing.xs, fontStyle: 'italic' },
  emptyNoteText: { fontSize: font.sm, color: colors.textLight, textAlign: 'center' },
})
