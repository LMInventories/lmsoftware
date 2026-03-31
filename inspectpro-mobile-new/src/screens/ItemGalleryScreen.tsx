import React, { useState, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  Image, Modal, Dimensions, Alert, ActivityIndicator,
  ScrollView,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native'
import type { StackNavigationProp, RouteProp } from '@react-navigation/stack'
import * as ImageManipulator from 'expo-image-manipulator'
import * as FileSystem from 'expo-file-system/legacy'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import { getLocalInspection } from '../services/database'
import { setCameraTarget, processPendingPhotos } from '../services/cameraStore'
import Header from '../components/Header'
import { colors, font, radius, spacing } from '../utils/theme'
import { api } from '../services/api'

type Nav   = StackNavigationProp<RootStackParamList, 'ItemGallery'>
type Route = RouteProp<RootStackParamList, 'ItemGallery'>

const { width: SW, height: SH } = Dimensions.get('window')
const THUMB = (SW - spacing.md * 2 - spacing.sm * 2) / 3

interface RoomOption { key: string; name: string; items: ItemOption[] }
interface ItemOption { key: string; name: string }
interface AiSuggestion {
  photoUri:    string
  sectionKey:  string
  sectionName: string
  itemKey:     string
  itemName:    string
  confidence:  number
}

export default function ItemGalleryScreen() {
  const navigation = useNavigation<Nav>()
  const route      = useRoute<Route>()
  const insets     = useSafeAreaInsets()
  const { inspectionId, sectionKey, sectionName, itemKey, itemName, itemPosition } = route.params
  const { activeInspection, setReportData } = useInspectionStore()

  // Lightbox
  const [lightboxUri, setLightboxUri]     = useState<string | null>(null)
  const [rotating, setRotating]           = useState(false)

  // Multi-select
  const [selecting, setSelecting]   = useState(false)
  const [selected, setSelected]     = useState<Set<string>>(new Set())

  // Reassign modal
  const [showReassign, setShowReassign]     = useState(false)
  const [currentRoomItems, setCurrentRoomItems] = useState<ItemOption[]>([])
  const [targetItem, setTargetItem]         = useState<ItemOption | null>(null)
  const [roomsLoading, setRoomsLoading]     = useState(false)
  const [itemPickerOpen, setItemPickerOpen] = useState(false)

  // AI reassign
  const [aiLoading, setAiLoading]         = useState(false)
  const [aiSuggestions, setAiSuggestions] = useState<AiSuggestion[]>([])
  const [showAiReview, setShowAiReview]   = useState(false)
  const [autoAssigned, setAutoAssigned]   = useState<string[]>([])

  // Pick up any photo parked in cameraStore (fallback if handler was GC'd)
  useFocusEffect(useCallback(() => {
    const pending = processPendingPhotos()
    if (pending) updatePhotos([...getPhotos(), pending])
  }, []))

  // ── Helpers ────────────────────────────────────────────────────────────────
  function getPhotos(): string[] {
    if (!activeInspection?.report_data) return []
    try {
      const rd = JSON.parse(activeInspection.report_data)
      return rd[sectionKey]?.[itemKey]?._photos || []
    } catch { return [] }
  }

  async function updatePhotos(newPhotos: string[]) {
    const rdStr = activeInspection?.report_data
    const rd = rdStr ? JSON.parse(rdStr) : {}
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][itemKey]) rd[sectionKey][itemKey] = {}
    rd[sectionKey][itemKey]._photos = newPhotos
    await setReportData(inspectionId, rd)
  }

  function toggleSelect(uri: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(uri) ? next.delete(uri) : next.add(uri)
      return next
    })
  }

  function exitSelect() {
    setSelecting(false)
    setSelected(new Set())
  }

  // ── Lightbox actions ───────────────────────────────────────────────────────
  async function handleRotate(uri: string, direction: 'cw' | 'ccw') {
    setRotating(true)
    try {
      const result = await ImageManipulator.manipulateAsync(
        uri,
        [{ rotate: direction === 'cw' ? 90 : 270 }],
        { compress: 0.85, format: ImageManipulator.SaveFormat.JPEG }
      )
      // Save rotated version to a new file; do NOT delete the original
      const dir = `${FileSystem.documentDirectory}photos/${inspectionId}/`
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true })
      const dest = `${dir}${Date.now()}_rot.jpg`
      await FileSystem.copyAsync({ from: result.uri, to: dest })

      const photos = getPhotos()
      const idx = photos.indexOf(uri)
      if (idx >= 0) {
        const next = [...photos]
        next[idx] = dest
        await updatePhotos(next)
        setLightboxUri(dest)
      }
    } catch { Alert.alert('Error', 'Could not rotate photo.') }
    finally { setRotating(false) }
  }

  async function handleDeleteSingle(uri: string) {
    Alert.alert('Delete photo?', 'This cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
        await updatePhotos(getPhotos().filter(u => u !== uri))
        setLightboxUri(null)
      }},
    ])
  }

  function handleAddMore() {
    setCameraTarget((uri) => updatePhotos([...getPhotos(), uri]))
    navigation.navigate('Camera', { inspectionId })
  }

  // ── Multi-select delete ────────────────────────────────────────────────────
  async function handleDeleteSelected() {
    Alert.alert(`Delete ${selected.size} photo${selected.size !== 1 ? 's' : ''}?`, 'This cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
        await updatePhotos(getPhotos().filter(u => !selected.has(u)))
        exitSelect()
      }},
    ])
  }

  // ── Reassign ───────────────────────────────────────────────────────────────
  async function openReassign() {
    setRoomsLoading(true)
    setShowReassign(true)
    try {
      if (!activeInspection?.template_id) {
        Alert.alert('No template', 'This inspection has no template assigned.')
        setShowReassign(false); return
      }
      // Use cached template (embedded at download time) — fallback to live API
      let tmplData: any = null
      const localInsp = await getLocalInspection(inspectionId)
      if (localInsp?.template) {
        tmplData = localInsp.template
      } else {
        const tmplRes = await api.getTemplate(activeInspection.template_id)
        tmplData = tmplRes.data
      }
      const sections: any[] = tmplData.sections || []
      // Find only this room's section and its items
      const thisSection = sections.find((s: any) => String(s.id) === sectionKey)
      const items: ItemOption[] = (thisSection?.items || []).map((it: any) => ({
        key:  String(it.id),
        name: it.name,
      }))
      setCurrentRoomItems(items)
      setTargetItem(items[0] || null)
    } catch { Alert.alert('Error', 'Could not load room items.'); setShowReassign(false) }
    finally { setRoomsLoading(false) }
  }

  async function confirmReassign() {
    if (!targetItem) return
    if (targetItem.key === itemKey) {
      Alert.alert('Same item', 'Photos are already assigned here.'); return
    }
    const rd = JSON.parse(activeInspection?.report_data || '{}')
    const photosToMove = getPhotos().filter(u => selected.has(u))
    // Remove from source item
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][itemKey]) rd[sectionKey][itemKey] = {}
    rd[sectionKey][itemKey]._photos = getPhotos().filter(u => !selected.has(u))
    // Add to target item (same room)
    if (!rd[sectionKey][targetItem.key]) rd[sectionKey][targetItem.key] = {}
    rd[sectionKey][targetItem.key]._photos = [
      ...(rd[sectionKey][targetItem.key]._photos || []),
      ...photosToMove,
    ]
    await setReportData(inspectionId, rd)
    setShowReassign(false)
    exitSelect()
    Alert.alert('Done', `${photosToMove.length} photo${photosToMove.length !== 1 ? 's' : ''} moved to ${targetItem.name}`)
  }

  // ── AI Reassign ────────────────────────────────────────────────────────────
  async function handleAiReassign() {
    if (!selected.size || aiLoading) return
    setAiLoading(true)
    try {
      if (!activeInspection?.template_id) {
        Alert.alert('No template', 'This inspection has no template assigned.'); return
      }
      // Use cached template; AI reassign does need network for the classify call itself
      let tmplData: any = null
      const localInsp2 = await getLocalInspection(inspectionId)
      if (localInsp2?.template) {
        tmplData = localInsp2.template
      } else {
        const tmplRes = await api.getTemplate(activeInspection.template_id)
        tmplData = tmplRes.data
      }
      const sections: any[] = tmplData.sections || []
      // Constrain to current room only — photos should only move within the same room
      const thisSection = sections.find((s: any) => String(s.id) === sectionKey)
      // Include any filled-in description text so AI has both item names and textual context
      const roomContextStr = thisSection
        ? `Room: "${thisSection.name}" (key: ${sectionKey})\n` +
          (thisSection.items || []).map((it: any) => {
            const itemRd = rd[sectionKey]?.[String(it.id)]
            const desc = itemRd?.description ? ` — described as: "${itemRd.description}"` : ''
            const cond = itemRd?.condition ? ` — condition: "${itemRd.condition}"` : ''
            return `  - "${it.name}" (key: ${it.id})${desc}${cond}`
          }).join('\n')
        : ''

      const selectedPhotos = getPhotos().filter(u => selected.has(u))
      const suggestions: AiSuggestion[] = []
      const autoMoved: string[] = []
      const rd = JSON.parse(activeInspection?.report_data || '{}')

      for (const photoUri of selectedPhotos) {
        // Support both legacy data: URIs and new file:// URIs
        let base64: string | null = null
        if (photoUri.startsWith('data:')) {
          base64 = photoUri.split(',')[1]
        } else if (photoUri.startsWith('file://') || photoUri.startsWith('/')) {
          try {
            base64 = await FileSystem.readAsStringAsync(photoUri, { encoding: FileSystem.EncodingType.Base64 })
          } catch { base64 = null }
        }
        if (!base64) continue

        try {
          const res = await api.classifyPhoto({
            imageBase64:  base64,
            mimeType:     'image/jpeg',
            roomContext:  roomContextStr,
            inspectionId: inspectionId,
          })
          const parsed = res.data
          const suggestion: AiSuggestion = {
            photoUri,
            sectionKey:  String(parsed.sectionKey),
            sectionName: parsed.sectionName || '',
            itemKey:     String(parsed.itemKey),
            itemName:    parsed.itemName || '',
            confidence:  Number(parsed.confidence) || 0,
          }
          suggestions.push(suggestion)

          if (suggestion.confidence >= 0.8 &&
              (suggestion.sectionKey !== sectionKey || suggestion.itemKey !== itemKey)) {
            if (!rd[suggestion.sectionKey]) rd[suggestion.sectionKey] = {}
            if (!rd[suggestion.sectionKey][suggestion.itemKey]) rd[suggestion.sectionKey][suggestion.itemKey] = {}
            rd[suggestion.sectionKey][suggestion.itemKey]._photos = [
              ...(rd[suggestion.sectionKey][suggestion.itemKey]._photos || []),
              photoUri,
            ]
            autoMoved.push(photoUri)
          }
        } catch {
          suggestions.push({ photoUri, sectionKey, sectionName, itemKey, itemName, confidence: 0 })
        }
      }

      if (autoMoved.length > 0) {
        if (!rd[sectionKey]) rd[sectionKey] = {}
        if (!rd[sectionKey][itemKey]) rd[sectionKey][itemKey] = {}
        rd[sectionKey][itemKey]._photos = getPhotos().filter((u: string) => !autoMoved.includes(u))
        await setReportData(inspectionId, rd)
        setAutoAssigned(autoMoved)
      }

      const needsReview = suggestions.filter(s => s.confidence < 0.8)
      if (needsReview.length > 0) {
        setAiSuggestions(needsReview)
        setShowAiReview(true)
      } else {
        exitSelect()
        Alert.alert('AI Reassign Complete',
          `${autoMoved.length} photo${autoMoved.length !== 1 ? 's' : ''} automatically moved within ${sectionName}.`)
      }
    } catch { Alert.alert('Error', 'AI analysis failed. Please try again.') }
    finally { setAiLoading(false) }
  }

  async function acceptAiSuggestion(s: AiSuggestion) {
    const rd = JSON.parse(activeInspection?.report_data || '{}')
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][itemKey]) rd[sectionKey][itemKey] = {}
    rd[sectionKey][itemKey]._photos = (rd[sectionKey][itemKey]._photos || []).filter((u: string) => u !== s.photoUri)
    if (!rd[s.sectionKey]) rd[s.sectionKey] = {}
    if (!rd[s.sectionKey][s.itemKey]) rd[s.sectionKey][s.itemKey] = {}
    rd[s.sectionKey][s.itemKey]._photos = [...(rd[s.sectionKey][s.itemKey]._photos || []), s.photoUri]
    await setReportData(inspectionId, rd)
    const remaining = aiSuggestions.filter(x => x.photoUri !== s.photoUri)
    setAiSuggestions(remaining)
    if (remaining.length === 0) { setShowAiReview(false); exitSelect() }
  }

  function dismissAiSuggestion(photoUri: string) {
    const remaining = aiSuggestions.filter(s => s.photoUri !== photoUri)
    setAiSuggestions(remaining)
    if (remaining.length === 0) { setShowAiReview(false); exitSelect() }
  }

  const photos = getPhotos()

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <Header
        title={itemPosition ? `${itemPosition} — ${itemName}` : itemName}
        subtitle={selecting ? `${selected.size} selected` : `${photos.length} photo${photos.length !== 1 ? 's' : ''} · ${sectionName}`}
        onBack={selecting ? exitSelect : () => navigation.goBack()}
        right={!selecting
          ? <TouchableOpacity style={styles.addBtn} onPress={handleAddMore}>
              <Text style={styles.addBtnText}>+</Text>
            </TouchableOpacity>
          : undefined
        }
      />

      {photos.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyIcon}>🖼️</Text>
          <Text style={styles.emptyTitle}>No photos yet</Text>
          <TouchableOpacity style={styles.btnPrimary} onPress={handleAddMore}>
            <Text style={styles.btnPrimaryText}>Take Photo</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={photos}
          keyExtractor={(_, i) => String(i)}
          numColumns={3}
          contentContainerStyle={[styles.grid, selecting && { paddingBottom: 96 }]}
          columnWrapperStyle={styles.row}
          renderItem={({ item: uri, index }) => (
            <TouchableOpacity
              onPress={() => selecting ? toggleSelect(uri) : (setLightboxUri(uri))}
              onLongPress={() => { if (!selecting) { setSelecting(true); setSelected(new Set([uri])) } }}
              activeOpacity={0.8}
            >
              <Image source={{ uri }} style={[styles.thumb, selecting && selected.has(uri) && styles.thumbSelected]} />
              {selecting
                ? <View style={[styles.checkbox, selected.has(uri) && styles.checkboxChecked]}>
                    {selected.has(uri) && <Text style={styles.checkmark}>✓</Text>}
                  </View>
                : <View style={styles.thumbIndex}>
                    <Text style={styles.thumbIndexText}>{index + 1}</Text>
                  </View>
              }
            </TouchableOpacity>
          )}
        />
      )}

      {/* Multi-select action bar */}
      {selecting && (
        <View style={[styles.actionBar, { paddingBottom: insets.bottom + spacing.xs }]}>
          <TouchableOpacity
            style={[styles.barBtn, styles.barBtnOutline]}
            onPress={() => selected.size === photos.length ? setSelected(new Set()) : setSelected(new Set(photos))}
          >
            <Text style={styles.barBtnOutlineText}>
              {selected.size === photos.length ? 'None' : 'All'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.barBtn, styles.barBtnPrimary, !selected.size && styles.barBtnDisabled]}
            onPress={selected.size > 0 ? openReassign : undefined}
          >
            <Text style={styles.barBtnText}>Reassign</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.barBtn, styles.barBtnAccent, (!selected.size || aiLoading) && styles.barBtnDisabled]}
            onPress={selected.size > 0 && !aiLoading ? handleAiReassign : undefined}
          >
            {aiLoading
              ? <ActivityIndicator color="#fff" size="small" />
              : <Text style={styles.barBtnText}>✦ AI</Text>
            }
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.barBtn, styles.barBtnDanger, !selected.size && styles.barBtnDisabled]}
            onPress={selected.size > 0 ? handleDeleteSelected : undefined}
          >
            <Text style={styles.barBtnText}>Delete</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* ── Reassign Modal ──────────────────────────────────────────────────── */}
      <Modal visible={showReassign} animationType="slide" presentationStyle="pageSheet">
        <View style={[mStyles.screen, { paddingTop: insets.top }]}>
          <View style={mStyles.header}>
            <TouchableOpacity onPress={() => setShowReassign(false)}>
              <Text style={mStyles.cancel}>Cancel</Text>
            </TouchableOpacity>
            <Text style={mStyles.title}>Reassign Photos</Text>
            <TouchableOpacity onPress={confirmReassign}>
              <Text style={[mStyles.confirm, !targetItem && mStyles.confirmDisabled]}>Move</Text>
            </TouchableOpacity>
          </View>
          {roomsLoading ? (
            <View style={mStyles.loadingWrap}>
              <ActivityIndicator color={colors.primary} size="large" />
              <Text style={mStyles.loadingText}>Loading rooms…</Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={mStyles.body} keyboardShouldPersistTaps="handled">
              <Text style={mStyles.desc}>
                Moving <Text style={mStyles.bold}>{selected.size}</Text> photo{selected.size !== 1 ? 's' : ''} from{' '}
                <Text style={mStyles.bold}>{itemName}</Text> to another item in this room
              </Text>

              {/* Room — locked to current, shown as info only */}
              <Text style={mStyles.label}>Room</Text>
              <View style={mStyles.lockedRoom}>
                <Text style={mStyles.lockedRoomText}>{sectionName}</Text>
                <Text style={mStyles.lockedRoomBadge}>Current room</Text>
              </View>

              {/* Item picker */}
              <Text style={[mStyles.label, { marginTop: spacing.md }]}>Item</Text>
              <TouchableOpacity
                style={[mStyles.picker, itemPickerOpen && mStyles.pickerOpen]}
                onPress={() => setItemPickerOpen(v => !v)}
              >
                <Text style={mStyles.pickerVal}>{targetItem?.name || 'Select item…'}</Text>
                <Text style={mStyles.chevron}>{itemPickerOpen ? '▲' : '▼'}</Text>
              </TouchableOpacity>
              {itemPickerOpen && (
                <View style={mStyles.dropdown}>
                  {currentRoomItems.length === 0
                    ? <Text style={mStyles.emptyOpts}>No items in this room</Text>
                    : currentRoomItems.map(item => (
                        <TouchableOpacity key={item.key}
                          style={[mStyles.option, targetItem?.key === item.key && mStyles.optionActive]}
                          onPress={() => { setTargetItem(item); setItemPickerOpen(false) }}
                        >
                          <Text style={[mStyles.optionText, targetItem?.key === item.key && mStyles.optionTextActive]}>
                            {item.name}
                          </Text>
                          {targetItem?.key === item.key && <Text style={mStyles.tick}>✓</Text>}
                        </TouchableOpacity>
                      ))
                  }
                </View>
              )}

              {/* Preview strip */}
              <Text style={[mStyles.label, { marginTop: spacing.lg }]}>
                Photos being moved ({selected.size})
              </Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                {photos.filter(u => selected.has(u)).map((uri, i) => (
                  <Image key={i} source={{ uri }} style={mStyles.previewThumb} />
                ))}
              </ScrollView>
            </ScrollView>
          )}
        </View>
      </Modal>

      {/* ── AI Review Modal ─────────────────────────────────────────────────── */}
      <Modal visible={showAiReview} animationType="slide" presentationStyle="pageSheet">
        <View style={[mStyles.screen, { paddingTop: insets.top }]}>
          <View style={mStyles.header}>
            <TouchableOpacity onPress={() => { setShowAiReview(false); exitSelect() }}>
              <Text style={mStyles.cancel}>Done</Text>
            </TouchableOpacity>
            <Text style={mStyles.title}>AI Review</Text>
            <View style={{ width: 50 }} />
          </View>
          <ScrollView contentContainerStyle={mStyles.body}>
            {autoAssigned.length > 0 && (
              <View style={aiS.autoNote}>
                <Text style={aiS.autoNoteText}>
                  ✦ {autoAssigned.length} photo{autoAssigned.length !== 1 ? 's' : ''} auto-assigned with high confidence
                </Text>
              </View>
            )}
            <Text style={mStyles.desc}>
              {aiSuggestions.length} photo{aiSuggestions.length !== 1 ? 's' : ''} need your review — confidence below 80%.
            </Text>
            {aiSuggestions.map((s, i) => (
              <View key={i} style={aiS.card}>
                <Image source={{ uri: s.photoUri }} style={aiS.thumb} />
                <View style={aiS.body}>
                  <View style={[aiS.confPill, { backgroundColor: confColor(s.confidence) + '22' }]}>
                    <Text style={[aiS.confText, { color: confColor(s.confidence) }]}>
                      {Math.round(s.confidence * 100)}% confidence
                    </Text>
                  </View>
                  <Text style={aiS.suggestLabel}>Suggested location</Text>
                  <Text style={aiS.suggestRoom}>{s.sectionName}</Text>
                  <Text style={aiS.suggestItem}>› {s.itemName}</Text>
                  <View style={aiS.actions}>
                    <TouchableOpacity style={[aiS.btn, aiS.btnAccept]} onPress={() => acceptAiSuggestion(s)}>
                      <Text style={aiS.btnText}>Move Here</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={[aiS.btn, aiS.btnKeep]} onPress={() => dismissAiSuggestion(s.photoUri)}>
                      <Text style={aiS.btnKeepText}>Keep Here</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
            ))}
          </ScrollView>
        </View>
      </Modal>

      {/* ── Lightbox ──────────────────────────────────────────────────────────── */}
      <Modal visible={!!lightboxUri} animationType="fade" statusBarTranslucent>
        <View style={lbS.screen}>
          {lightboxUri && (
            <>
              <TouchableOpacity style={[lbS.closeBtn, { top: insets.top + 12 }]} onPress={() => setLightboxUri(null)}>
                <Text style={lbS.closeBtnText}>✕</Text>
              </TouchableOpacity>
              <View style={[lbS.counter, { top: insets.top + 16 }]}>
                <Text style={lbS.counterText}>{photos.indexOf(lightboxUri) + 1} / {photos.length}</Text>
              </View>
              <Image source={{ uri: lightboxUri }} style={lbS.image} resizeMode="contain" />
              {rotating && (
                <View style={lbS.overlay}>
                  <ActivityIndicator color="#fff" size="large" />
                  <Text style={lbS.overlayText}>Rotating…</Text>
                </View>
              )}
              <View style={[lbS.actions, { paddingBottom: insets.bottom + spacing.md }]}>
                <TouchableOpacity style={lbS.actionBtn} onPress={() => handleRotate(lightboxUri, 'ccw')} disabled={rotating}>
                  <Text style={lbS.actionIcon}>↺</Text>
                  <Text style={lbS.actionLabel}>Rotate Left</Text>
                </TouchableOpacity>
                <TouchableOpacity style={lbS.actionBtn} onPress={() => handleRotate(lightboxUri, 'cw')} disabled={rotating}>
                  <Text style={lbS.actionIcon}>↻</Text>
                  <Text style={lbS.actionLabel}>Rotate Right</Text>
                </TouchableOpacity>
                <TouchableOpacity style={lbS.actionBtn} onPress={() => handleDeleteSingle(lightboxUri)}>
                  <Text style={lbS.actionIcon}>🗑</Text>
                  <Text style={[lbS.actionLabel, { color: colors.danger }]}>Delete</Text>
                </TouchableOpacity>
              </View>
              {photos.length > 1 && (
                <>
                  {photos.indexOf(lightboxUri) > 0 && (
                    <TouchableOpacity style={[lbS.navBtn, lbS.navLeft]}
                      onPress={() => { const i = photos.indexOf(lightboxUri) - 1; setLightboxUri(photos[i]) }}>
                      <Text style={lbS.navText}>‹</Text>
                    </TouchableOpacity>
                  )}
                  {photos.indexOf(lightboxUri) < photos.length - 1 && (
                    <TouchableOpacity style={[lbS.navBtn, lbS.navRight]}
                      onPress={() => { const i = photos.indexOf(lightboxUri) + 1; setLightboxUri(photos[i]) }}>
                      <Text style={lbS.navText}>›</Text>
                    </TouchableOpacity>
                  )}
                </>
              )}
            </>
          )}
        </View>
      </Modal>
    </View>
  )
}

function confColor(c: number) { return c >= 0.65 ? colors.warning : colors.danger }

// ─────────────────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  screen:  { flex: 1, backgroundColor: colors.background },
  grid:    { padding: spacing.md, paddingBottom: 40 },
  row:     { gap: spacing.sm, marginBottom: spacing.sm },
  thumb:   { width: THUMB, height: THUMB, borderRadius: radius.md },
  thumbSelected: { opacity: 0.55, borderWidth: 3, borderColor: colors.primary, borderRadius: radius.md },
  checkbox: {
    position: 'absolute', top: 5, right: 5,
    width: 22, height: 22, borderRadius: 11,
    backgroundColor: 'rgba(255,255,255,0.92)',
    borderWidth: 2, borderColor: colors.borderDark,
    alignItems: 'center', justifyContent: 'center',
  },
  checkboxChecked: { backgroundColor: colors.primary, borderColor: colors.primary },
  checkmark: { color: '#fff', fontSize: 12, fontWeight: '800' },
  thumbIndex: {
    position: 'absolute', bottom: 4, right: 4,
    backgroundColor: 'rgba(0,0,0,0.55)',
    paddingHorizontal: 5, paddingVertical: 1, borderRadius: 4,
  },
  thumbIndexText: { color: '#fff', fontSize: 10, fontWeight: '600' },
  empty:     { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  emptyIcon: { fontSize: 48 },
  emptyTitle: { fontSize: font.lg, fontWeight: '700', color: colors.textMid },
  addBtn: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: colors.primary,
    alignItems: 'center', justifyContent: 'center',
  },
  addBtnText: { color: '#fff', fontSize: font.xl, fontWeight: '300', marginTop: -2 },
  btnPrimary: { backgroundColor: colors.primary, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: 12 },
  btnPrimaryText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
  // Action bar
  actionBar: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    backgroundColor: colors.surface,
    borderTopWidth: 1, borderTopColor: colors.border,
    flexDirection: 'row', gap: spacing.sm,
    paddingTop: spacing.sm, paddingHorizontal: spacing.md,
  },
  barBtn:          { flex: 1, paddingVertical: 11, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  barBtnOutline:   { borderWidth: 1.5, borderColor: colors.borderDark },
  barBtnOutlineText: { fontSize: font.sm, fontWeight: '600', color: colors.textMid },
  barBtnPrimary:   { backgroundColor: colors.primary },
  barBtnAccent:    { backgroundColor: colors.accent },
  barBtnDanger:    { backgroundColor: colors.danger },
  barBtnDisabled:  { opacity: 0.38 },
  barBtnText:      { color: '#fff', fontSize: font.sm, fontWeight: '700' },
})

const lbS = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#000', justifyContent: 'center' },
  closeBtn: {
    position: 'absolute', left: spacing.md, zIndex: 10,
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignItems: 'center', justifyContent: 'center',
  },
  closeBtnText: { color: '#fff', fontSize: font.lg, fontWeight: '700' },
  counter: {
    position: 'absolute', alignSelf: 'center', zIndex: 10,
    backgroundColor: 'rgba(0,0,0,0.5)',
    paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.sm,
  },
  counterText: { color: '#fff', fontSize: font.sm },
  image: { width: SW, height: SH * 0.65, alignSelf: 'center' },
  overlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
  },
  overlayText: { color: '#fff', fontSize: font.md },
  actions: {
    flexDirection: 'row', justifyContent: 'center', gap: spacing.lg,
    paddingTop: spacing.md, backgroundColor: 'rgba(0,0,0,0.7)',
    position: 'absolute', bottom: 0, left: 0, right: 0,
  },
  actionBtn:   { alignItems: 'center', gap: 4, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  actionIcon:  { fontSize: 26, color: '#fff' },
  actionLabel: { fontSize: font.xs, color: '#ccc' },
  navBtn: {
    position: 'absolute', top: '40%',
    backgroundColor: 'rgba(255,255,255,0.15)',
    width: 44, height: 44, borderRadius: 22,
    alignItems: 'center', justifyContent: 'center',
  },
  navLeft:  { left: spacing.md },
  navRight: { right: spacing.md },
  navText:  { color: '#fff', fontSize: 28, fontWeight: '300' },
})

const mStyles = StyleSheet.create({
  screen:  { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.md, paddingVertical: 14,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  cancel:          { fontSize: font.md, color: colors.textMid, fontWeight: '500' },
  title:           { fontSize: font.md, fontWeight: '700', color: colors.text },
  confirm:         { fontSize: font.md, color: colors.primary, fontWeight: '700' },
  confirmDisabled: { opacity: 0.35 },
  loadingWrap:     { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  loadingText:     { fontSize: font.md, color: colors.textMid },
  body:            { padding: spacing.md },
  desc:            { fontSize: font.sm, color: colors.textMid, marginBottom: spacing.md, lineHeight: 20 },
  bold:            { fontWeight: '700', color: colors.text },
  label:           { fontSize: font.xs, fontWeight: '700', color: colors.textLight, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
  lockedRoom: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: colors.muted,
    borderWidth: 1.5, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 13,
  },
  lockedRoomText:  { fontSize: font.md, color: colors.textMid, fontWeight: '500' },
  lockedRoomBadge: { fontSize: font.xs, color: colors.textLight, fontStyle: 'italic' },
  picker: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: colors.surface,
    borderWidth: 1.5, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 13,
  },
  pickerOpen:      { borderColor: colors.primary, borderBottomLeftRadius: 0, borderBottomRightRadius: 0 },
  pickerVal:       { fontSize: font.md, color: colors.text, flex: 1 },
  chevron:         { fontSize: font.sm, color: colors.textLight, marginLeft: spacing.sm },
  dropdown: {
    backgroundColor: colors.surface,
    borderWidth: 1.5, borderColor: colors.primary, borderTopWidth: 0,
    borderBottomLeftRadius: radius.md, borderBottomRightRadius: radius.md,
    marginBottom: spacing.sm, overflow: 'hidden',
  },
  option: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.md, paddingVertical: 13,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  optionActive:     { backgroundColor: colors.primaryLight },
  optionText:       { fontSize: font.md, color: colors.text },
  optionTextActive: { color: colors.primary, fontWeight: '600' },
  tick:             { fontSize: font.md, color: colors.primary, fontWeight: '700' },
  emptyOpts:        { padding: spacing.md, fontSize: font.sm, color: colors.textLight, fontStyle: 'italic' },
  previewThumb:     { width: 68, height: 68, borderRadius: radius.sm, marginRight: spacing.sm },
})

const aiS = StyleSheet.create({
  autoNote: {
    backgroundColor: colors.successLight, borderRadius: radius.md,
    padding: 12, marginBottom: spacing.md,
  },
  autoNoteText: { fontSize: font.sm, color: colors.success, fontWeight: '600' },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
    flexDirection: 'row', padding: spacing.sm, marginBottom: spacing.md, gap: spacing.sm,
  },
  thumb:        { width: 84, height: 84, borderRadius: radius.md, flexShrink: 0 },
  body:         { flex: 1, gap: 3 },
  confPill:     { alignSelf: 'flex-start', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10, marginBottom: 4 },
  confText:     { fontSize: font.xs, fontWeight: '700' },
  suggestLabel: { fontSize: font.xs, color: colors.textLight },
  suggestRoom:  { fontSize: font.sm, fontWeight: '700', color: colors.text },
  suggestItem:  { fontSize: font.sm, color: colors.textMid },
  actions:      { flexDirection: 'row', gap: spacing.sm, marginTop: 6 },
  btn:          { flex: 1, paddingVertical: 8, borderRadius: radius.md, alignItems: 'center' },
  btnAccept:    { backgroundColor: colors.primary },
  btnKeep:      { backgroundColor: colors.muted, borderWidth: 1, borderColor: colors.border },
  btnText:      { color: '#fff', fontSize: font.xs, fontWeight: '700' },
  btnKeepText:  { color: colors.textMid, fontSize: font.xs, fontWeight: '600' },
})
