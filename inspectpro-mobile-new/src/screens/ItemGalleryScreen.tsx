import React, { useState, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  Image, Modal, Dimensions, Alert, ActivityIndicator,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useNavigation, useRoute, useFocusEffect } from '@react-navigation/native'
import type { StackNavigationProp, RouteProp } from '@react-navigation/stack'
import * as ImageManipulator from 'expo-image-manipulator'
import * as FileSystem from 'expo-file-system'
import * as ImagePicker from 'expo-image-picker'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import Header from '../components/Header'
import { colors, font, radius, spacing } from '../utils/theme'

type Nav   = StackNavigationProp<RootStackParamList, 'ItemGallery'>
type Route = RouteProp<RootStackParamList, 'ItemGallery'>

const { width: SW, height: SH } = Dimensions.get('window')
const THUMB = (SW - spacing.md * 2 - spacing.sm * 2) / 3

export default function ItemGalleryScreen() {
  const navigation = useNavigation<Nav>()
  const route      = useRoute<Route>()
  const insets     = useSafeAreaInsets()
  const { inspectionId, sectionKey, itemKey, itemName } = route.params
  const { activeInspection, setReportData } = useInspectionStore()

  const [lightboxUri, setLightboxUri]     = useState<string | null>(null)
  const [lightboxIndex, setLightboxIndex] = useState(0)
  const [rotating, setRotating]           = useState(false)

  function getPhotos(): string[] {
    if (!activeInspection?.report_data) return []
    try {
      const rd = JSON.parse(activeInspection.report_data)
      return rd[sectionKey]?.[itemKey]?._photos || []
    } catch { return [] }
  }

  async function updatePhotos(newPhotos: string[]) {
    if (!activeInspection?.report_data) return
    const rd = JSON.parse(activeInspection.report_data)
    if (!rd[sectionKey]) rd[sectionKey] = {}
    if (!rd[sectionKey][itemKey]) rd[sectionKey][itemKey] = {}
    rd[sectionKey][itemKey]._photos = newPhotos
    await setReportData(inspectionId, rd)
  }

  async function handleRotate(uri: string, direction: 'cw' | 'ccw') {
    setRotating(true)
    try {
      const deg = direction === 'cw' ? 90 : 270
      const result = await ImageManipulator.manipulateAsync(
        uri,
        [{ rotate: deg }],
        { compress: 0.85, format: ImageManipulator.SaveFormat.JPEG }
      )
      const photos = getPhotos()
      const idx = photos.indexOf(uri)
      if (idx >= 0) {
        const newPhotos = [...photos]
        // Delete old file if it was a local cache file
        try { await FileSystem.deleteAsync(uri, { idempotent: true }) } catch {}
        newPhotos[idx] = result.uri
        await updatePhotos(newPhotos)
        setLightboxUri(result.uri)
      }
    } catch (err) {
      Alert.alert('Error', 'Could not rotate photo.')
    } finally {
      setRotating(false)
    }
  }

  async function handleDelete(uri: string) {
    Alert.alert('Delete photo?', 'This cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete', style: 'destructive',
        onPress: async () => {
          const photos = getPhotos().filter(u => u !== uri)
          await updatePhotos(photos)
          setLightboxUri(null)
        },
      },
    ])
  }

  async function handleAddMore() {
    const { status } = await ImagePicker.requestCameraPermissionsAsync()
    if (status !== 'granted') { Alert.alert('Permission required', 'Camera permission is needed.'); return }
    const result = await ImagePicker.launchCameraAsync({ quality: 0.75, base64: true })
    if (!result.canceled && result.assets[0].base64) {
      const photos = [...getPhotos(), `data:image/jpeg;base64,${result.assets[0].base64}`]
      await updatePhotos(photos)
    }
  }

  function openLightbox(uri: string, index: number) {
    setLightboxUri(uri)
    setLightboxIndex(index)
  }

  const photos = getPhotos()

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <Header
        title={itemName}
        subtitle={`${photos.length} photo${photos.length !== 1 ? 's' : ''}`}
        onBack={() => navigation.goBack()}
        right={
          <TouchableOpacity style={styles.addBtn} onPress={handleAddMore}>
            <Text style={styles.addBtnText}>+</Text>
          </TouchableOpacity>
        }
      />

      {photos.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyIcon}>🖼️</Text>
          <Text style={styles.emptyTitle}>No photos yet</Text>
          <TouchableOpacity style={styles.btnPrimary} onPress={handleAddMore}>
            <Text style={styles.btnPrimaryText}>📷 Take Photo</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={photos}
          keyExtractor={(uri, i) => `${uri}_${i}`}
          numColumns={3}
          contentContainerStyle={styles.grid}
          columnWrapperStyle={styles.row}
          renderItem={({ item: uri, index }) => (
            <TouchableOpacity onPress={() => openLightbox(uri, index)}>
              <Image source={{ uri }} style={styles.thumb} />
              <View style={styles.thumbIndex}>
                <Text style={styles.thumbIndexText}>{index + 1}</Text>
              </View>
            </TouchableOpacity>
          )}
        />
      )}

      {/* Lightbox */}
      <Modal visible={!!lightboxUri} animationType="fade" statusBarTranslucent>
        <View style={lbStyles.screen}>
          {lightboxUri && (
            <>
              {/* Close */}
              <TouchableOpacity
                style={[lbStyles.closeBtn, { top: insets.top + 12 }]}
                onPress={() => setLightboxUri(null)}
              >
                <Text style={lbStyles.closeBtnText}>✕</Text>
              </TouchableOpacity>

              {/* Photo counter */}
              <View style={[lbStyles.counter, { top: insets.top + 16 }]}>
                <Text style={lbStyles.counterText}>
                  {photos.indexOf(lightboxUri) + 1} / {photos.length}
                </Text>
              </View>

              {/* Image */}
              <Image
                source={{ uri: lightboxUri }}
                style={lbStyles.image}
                resizeMode="contain"
              />

              {rotating && (
                <View style={lbStyles.rotatingOverlay}>
                  <ActivityIndicator color="#fff" size="large" />
                  <Text style={lbStyles.rotatingText}>Rotating…</Text>
                </View>
              )}

              {/* Actions */}
              <View style={[lbStyles.actions, { paddingBottom: insets.bottom + spacing.md }]}>
                <TouchableOpacity style={lbStyles.actionBtn} onPress={() => handleRotate(lightboxUri, 'ccw')} disabled={rotating}>
                  <Text style={lbStyles.actionIcon}>↺</Text>
                  <Text style={lbStyles.actionLabel}>Rotate Left</Text>
                </TouchableOpacity>

                <TouchableOpacity style={lbStyles.actionBtn} onPress={() => handleRotate(lightboxUri, 'cw')} disabled={rotating}>
                  <Text style={lbStyles.actionIcon}>↻</Text>
                  <Text style={lbStyles.actionLabel}>Rotate Right</Text>
                </TouchableOpacity>

                <TouchableOpacity style={[lbStyles.actionBtn, lbStyles.actionDanger]} onPress={() => handleDelete(lightboxUri)}>
                  <Text style={lbStyles.actionIcon}>🗑</Text>
                  <Text style={[lbStyles.actionLabel, { color: colors.danger }]}>Delete</Text>
                </TouchableOpacity>
              </View>

              {/* Prev / Next */}
              {photos.length > 1 && (
                <>
                  {photos.indexOf(lightboxUri) > 0 && (
                    <TouchableOpacity
                      style={[lbStyles.navBtn, lbStyles.navLeft]}
                      onPress={() => {
                        const idx = photos.indexOf(lightboxUri) - 1
                        setLightboxUri(photos[idx])
                        setLightboxIndex(idx)
                      }}
                    >
                      <Text style={lbStyles.navText}>‹</Text>
                    </TouchableOpacity>
                  )}
                  {photos.indexOf(lightboxUri) < photos.length - 1 && (
                    <TouchableOpacity
                      style={[lbStyles.navBtn, lbStyles.navRight]}
                      onPress={() => {
                        const idx = photos.indexOf(lightboxUri) + 1
                        setLightboxUri(photos[idx])
                        setLightboxIndex(idx)
                      }}
                    >
                      <Text style={lbStyles.navText}>›</Text>
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

const lbStyles = StyleSheet.create({
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
    paddingHorizontal: spacing.sm, paddingVertical: 4,
    borderRadius: radius.sm,
  },
  counterText: { color: '#fff', fontSize: font.sm },
  image: { width: SW, height: SH * 0.65, alignSelf: 'center' },
  rotatingOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.6)',
    alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
  },
  rotatingText: { color: '#fff', fontSize: font.md },
  actions: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: spacing.lg,
    paddingTop: spacing.md,
    backgroundColor: 'rgba(0,0,0,0.7)',
    position: 'absolute', bottom: 0, left: 0, right: 0,
  },
  actionBtn: { alignItems: 'center', gap: 4, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  actionDanger: {},
  actionIcon: { fontSize: 26, color: '#fff' },
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

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  grid: { padding: spacing.md, paddingBottom: 40 },
  row: { gap: spacing.sm, marginBottom: spacing.sm },
  thumb: { width: THUMB, height: THUMB, borderRadius: radius.md },
  thumbIndex: {
    position: 'absolute', bottom: 4, right: 4,
    backgroundColor: 'rgba(0,0,0,0.55)',
    paddingHorizontal: 5, paddingVertical: 1,
    borderRadius: 4,
  },
  thumbIndexText: { color: '#fff', fontSize: 10, fontWeight: '600' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  emptyIcon: { fontSize: 48 },
  emptyTitle: { fontSize: font.lg, fontWeight: '700', color: colors.textMid },
  addBtn: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: colors.primary,
    alignItems: 'center', justifyContent: 'center',
  },
  addBtnText: { color: '#fff', fontSize: font.xl, fontWeight: '300', marginTop: -2 },
  btnPrimary: {
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: 12,
  },
  btnPrimaryText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
})
