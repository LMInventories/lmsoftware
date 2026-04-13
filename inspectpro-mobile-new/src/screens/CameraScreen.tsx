/**
 * CameraScreen — powered by react-native-vision-camera v4
 *
 * Key behaviours
 * ──────────────
 * • Proper lens detection: shows a wide/ultra-wide button only when the
 *   device physically supports it (minZoom < neutralZoom), not a guess.
 * • Photos saved to BOTH device gallery (expo-media-library) AND
 *   app-private documentDirectory for the in-app gallery.
 * • Shutter sound disabled (enableShutterSound: false).
 * • Pinch-to-zoom via GestureHandler (no Reanimated required).
 * • Tap-to-focus: tap anywhere on the viewfinder to pre-lock AF.
 * • Focus mode toggle (AF / 🔒): lock focus at a point for fast rapid-fire
 *   shooting — no AF re-run before each capture.
 * • Front/back flip supported with separate device lookup.
 * • Camera paused when screen loses focus (navigation push/pop).
 * • Landscape support: controls column shifts to the right side; button labels
 *   rotate 90° so they face the user when holding the device sideways.
 * • outputOrientation="device" bakes rotation into pixel data so thumbnails
 *   always display upright regardless of per-device EXIF support.
 * • Capture gate released immediately after takePhoto() resolves — file copy
 *   runs async so the next shot can start without waiting for I/O.
 */

import React, { useRef, useState, useCallback, useEffect } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Dimensions,
  Animated,
  Image,
  BackHandler,
} from 'react-native'
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera'
import type { CameraDevice } from 'react-native-vision-camera'
import * as MediaLibrary from 'expo-media-library'
// expo-file-system/legacy preserves the makeDirectoryAsync / copyAsync API
import * as FileSystem from 'expo-file-system/legacy'
import {
  GestureHandlerRootView,
  GestureDetector,
  Gesture,
} from 'react-native-gesture-handler'
import {
  useNavigation,
  useRoute,
  useIsFocused,
  useFocusEffect,
  RouteProp,
} from '@react-navigation/native'
import type { StackNavigationProp } from '@react-navigation/stack'
import { triggerCapture } from '../services/cameraStore'
import type { RootStackParamList } from '../../App'

type CameraRouteProp = RouteProp<RootStackParamList, 'Camera'>
type CameraNavProp   = StackNavigationProp<RootStackParamList, 'Camera'>
type FlashMode  = 'off' | 'on' | 'auto'
type Facing     = 'back' | 'front'
type FocusMode  = 'auto' | 'locked'

// Controls-strip width in landscape mode (px)
const CONTROLS_STRIP_W = 110

export default function CameraScreen() {
  const navigation = useNavigation<CameraNavProp>()
  const route      = useRoute<CameraRouteProp>()
  const { inspectionId } = route.params

  // ── Orientation tracking ───────────────────────────────────────────────────
  // Listen for Dimensions changes so the layout adapts when the device rotates.
  const [windowDims, setWindowDims] = useState(Dimensions.get('window'))
  useEffect(() => {
    const sub = Dimensions.addEventListener('change', ({ window }) => setWindowDims(window))
    return () => sub.remove()
  }, [])

  const W = windowDims.width
  const H = windowDims.height
  const isLandscape = W > H

  // Portrait: viewfinder = full screen width, 4:3 height
  // Landscape: viewfinder fills the screen vertically; controls are a side strip
  const VFINDER_W = isLandscape ? W - CONTROLS_STRIP_W : W
  const VFINDER_H = isLandscape ? H : Math.round(W * 4 / 3)

  // ── Hardware back button ───────────────────────────────────────────────────
  useFocusEffect(useCallback(() => {
    const onBack = () => { navigation.goBack(); return true }
    BackHandler.addEventListener('hardwareBackPress', onBack)
    return () => BackHandler.removeEventListener('hardwareBackPress', onBack)
  }, [navigation]))

  // ── VisionCamera permission ────────────────────────────────────────────────
  const { hasPermission, requestPermission } = useCameraPermission()

  // ── Device selection ───────────────────────────────────────────────────────
  const [facing, setFacing]     = useState<Facing>('back')
  const [lensMode, setLensMode] = useState<'main' | 'ultraWide'>('main')

  // Camera.getAvailableCameraDevices() is a synchronous static call in VisionCamera v4
  // that returns ALL physical camera devices — unlike useCameraDevice('back') which
  // only returns one "best" fused camera and may omit the ultra-wide entirely.
  const [allDevices, setAllDevices] = useState<CameraDevice[]>(() => {
    try { return Camera.getAvailableCameraDevices() } catch { return [] }
  })
  const frontDevice = useCameraDevice('front')

  // Re-fetch device list when camera permission is granted
  useEffect(() => {
    try { setAllDevices(Camera.getAvailableCameraDevices()) } catch {}
  }, [hasPermission])

  // From all devices, find back-facing cameras and pick best main + ultra-wide.
  const backDevices: CameraDevice[] = allDevices.filter((d: CameraDevice) => d.position === 'back')

  // Main back camera: prefer the device whose physicalDevices includes
  // 'wide-angle-camera' (but NOT ultra-wide-angle-camera alone).
  const backDevice: CameraDevice | undefined =
    backDevices.find((d: CameraDevice) =>
      d.physicalDevices?.includes('wide-angle-camera') &&
      !(d.physicalDevices ?? []).every((p: string) => p === 'ultra-wide-angle-camera')
    ) ?? backDevices[0]

  // Ultra-wide device: find a back-facing device that explicitly includes
  // 'ultra-wide-angle-camera'. Do NOT match 'wide' alone — it falsely matches
  // 'wide-angle-camera' (the main lens).
  const ultraWideDevice: CameraDevice | undefined = backDevices.find((d: CameraDevice) =>
    (d.physicalDevices ?? []).some(
      (p: string) => p === 'ultra-wide-angle-camera' || p.toLowerCase().includes('ultra')
    )
  )

  const hasSeparateUltraWide =
    !!ultraWideDevice && !!backDevice && ultraWideDevice.id !== backDevice.id
  const hasZoomBasedUltraWide =
    !!backDevice && backDevice.minZoom < backDevice.neutralZoom
  const hasUltraWide = hasSeparateUltraWide || hasZoomBasedUltraWide

  const device: CameraDevice | undefined = facing === 'front'
    ? frontDevice
    : lensMode === 'ultraWide' && hasSeparateUltraWide
      ? ultraWideDevice
      : backDevice

  // Camera pauses automatically when screen is not focused
  const isFocused = useIsFocused()

  // ── State ──────────────────────────────────────────────────────────────────
  const cameraRef = useRef<Camera>(null)
  const [flash, setFlash]                     = useState<FlashMode>('off')
  const [zoom, setZoom]                       = useState(1)
  const [activeZoomLabel, setActiveZoomLabel] = useState('1×')
  const [isCapturing, setIsCapturing]         = useState(false)
  // Last captured photo — shown as thumbnail next to shutter button
  const [lastPhotoUri, setLastPhotoUri]       = useState<string | null>(null)

  // ── Focus state ────────────────────────────────────────────────────────────
  const [focusMode, setFocusMode]   = useState<FocusMode>('auto')
  const [focusPoint, setFocusPoint] = useState<{ x: number; y: number } | null>(null)
  const focusAnim    = useRef(new Animated.Value(0)).current
  const focusTimer   = useRef<Animated.CompositeAnimation | null>(null)

  // Pre-request MediaLibrary permission once at mount (not on every shot)
  const mlPermGranted = useRef(false)
  useEffect(() => {
    MediaLibrary.requestPermissionsAsync().then(p => {
      mlPermGranted.current = p.status === 'granted'
    })
  }, [])

  // Pre-create the photo directory at mount so we never pay that I/O cost
  // during capture. Stored in a ref so handleCapture can read it synchronously.
  const photoDirRef = useRef<string>('')
  useEffect(() => {
    const dir = `${FileSystem.documentDirectory}photos/${inspectionId}/`
    photoDirRef.current = dir
    FileSystem.makeDirectoryAsync(dir, { intermediates: true }).catch(() => {})
  }, [inspectionId])

  // Ref-based capture guard — avoids a state re-render between shots which
  // was adding visible latency. isCapturing state is kept only for the UI.
  const capturingRef = useRef(false)

  // Subtle flash blink on capture
  const captureFlash = useRef(new Animated.Value(0)).current
  function triggerFlash() {
    Animated.sequence([
      Animated.timing(captureFlash, { toValue: 0.35, duration: 20,  useNativeDriver: true }),
      Animated.timing(captureFlash, { toValue: 0,    duration: 80,  useNativeDriver: true }),
    ]).start()
  }

  // Update zoom to device neutral when active device changes
  const lastDeviceId = useRef<string | undefined>(undefined)
  if (device && device.id !== lastDeviceId.current) {
    lastDeviceId.current = device.id
    setZoom(device.neutralZoom)
    setActiveZoomLabel(lensMode === 'ultraWide' ? '0.6×' : '1×')
  }

  // ── Focus ──────────────────────────────────────────────────────────────────
  function handleFocus(x: number, y: number, persistent: boolean) {
    cameraRef.current?.focus({ x, y }).catch(() => {})
    focusTimer.current?.stop()
    setFocusPoint({ x, y })
    focusAnim.setValue(1)

    if (!persistent) {
      focusTimer.current = Animated.sequence([
        Animated.delay(1200),
        Animated.timing(focusAnim, { toValue: 0, duration: 400, useNativeDriver: true }),
      ])
      focusTimer.current.start(({ finished }) => {
        if (finished) setFocusPoint(null)
      })
    }
  }

  const cycleFocusMode = useCallback(() => {
    if (focusMode === 'auto') {
      setFocusMode('locked')
      handleFocus(VFINDER_W / 2, VFINDER_H / 2, true)
    } else {
      setFocusMode('auto')
      focusTimer.current?.stop()
      focusAnim.setValue(0)
      setFocusPoint(null)
    }
  }, [focusMode, VFINDER_W, VFINDER_H])

  // ── Lens / zoom buttons ────────────────────────────────────────────────────
  interface LensButton { label: string; zoom: number; lens: 'main' | 'ultraWide' }

  function buildZoomButtons(): LensButton[] {
    if (!backDevice) return [{ label: '1×', zoom: 1, lens: 'main' }]
    const neutral = backDevice.neutralZoom
    const max     = backDevice.maxZoom
    const buttons: LensButton[] = []

    if (hasUltraWide) {
      buttons.push({
        label: '0.6×',
        zoom: hasSeparateUltraWide
          ? (ultraWideDevice?.neutralZoom ?? backDevice.minZoom)
          : backDevice.minZoom,
        lens: hasSeparateUltraWide ? 'ultraWide' : 'main',
      })
    }
    buttons.push({ label: '1×', zoom: neutral, lens: 'main' })
    if (neutral * 2 <= max) buttons.push({ label: '2×', zoom: neutral * 2, lens: 'main' })
    if (neutral * 5 <= max) buttons.push({ label: '5×', zoom: neutral * 5, lens: 'main' })
    return buttons
  }
  const zoomButtons = buildZoomButtons()

  // ── Pinch gesture ─────────────────────────────────────────────────────────
  const baseZoom = useRef(1)
  const pinchGesture = Gesture.Pinch()
    .onStart(() => { baseZoom.current = zoom })
    .onUpdate((e) => {
      if (!device) return
      const next = Math.min(
        device.maxZoom,
        Math.max(device.minZoom, baseZoom.current * e.scale)
      )
      setZoom(next)
      setActiveZoomLabel('')
    })
    .runOnJS(true)

  // ── Tap-to-focus gesture ───────────────────────────────────────────────────
  const tapGesture = Gesture.Tap()
    .runOnJS(true)
    .onEnd((e) => {
      handleFocus(e.x, e.y, focusMode === 'locked')
    })

  // ── Capture ────────────────────────────────────────────────────────────────
  // Speed optimisation: the capture gate (capturingRef) is released immediately
  // after takePhoto() resolves — before the file copy finishes — so the user
  // can trigger the next shot right away. copyAsync + triggerCapture run as an
  // independent async chain and never block the shutter button.
  const handleCapture = useCallback(async () => {
    if (!cameraRef.current || capturingRef.current || !device || !photoDirRef.current) return
    capturingRef.current = true
    setIsCapturing(true)
    try {
      const photo = await cameraRef.current.takePhoto({
        flash,
        enableShutterSound: false,
        // skipMetadata skips EXIF processing on Android — measurably faster
        // on lower-end devices. Disable if GPS-tagged photos are ever needed.
        skipMetadata: true,
      })

      const srcUri = photo.path.startsWith('file://')
        ? photo.path
        : `file://${photo.path}`

      // Release gate BEFORE file I/O — next shot can start immediately
      capturingRef.current = false
      setIsCapturing(false)
      triggerFlash()

      // File copy + handoff + gallery save run asynchronously
      const dest = `${photoDirRef.current}${Date.now()}.jpg`
      FileSystem.copyAsync({ from: srcUri, to: dest })
        .then(() => {
          triggerCapture(dest)
          setLastPhotoUri(dest)
          if (mlPermGranted.current) {
            MediaLibrary.saveToLibraryAsync(srcUri).catch(e =>
              console.warn('[CameraScreen] gallery save failed:', e)
            )
          }
        })
        .catch(e => console.warn('[CameraScreen] copy failed:', e))

    } catch (err: any) {
      console.error('[CameraScreen] capture error', err)
      Alert.alert(
        'Photo failed',
        err?.message ?? 'Could not save the photo. Please try again.'
      )
      capturingRef.current = false
      setIsCapturing(false)
    }
  }, [device, flash])

  // ── Controls ───────────────────────────────────────────────────────────────
  const toggleFacing = useCallback(() => {
    setFacing(f => f === 'back' ? 'front' : 'back')
    setLensMode('main')
    setFocusMode('auto')
    focusAnim.setValue(0)
    setFocusPoint(null)
  }, [])

  const cycleFlash = useCallback(() => {
    setFlash(f => f === 'off' ? 'on' : f === 'on' ? 'auto' : 'off')
  }, [])

  const flashLabel  = flash === 'off' ? '⚡✕' : flash === 'on' ? '⚡' : '⚡A'
  const focusLocked = focusMode === 'locked'

  // In landscape, rotate button labels 90° CCW so they face the user
  const btnRotate: { rotate: string }[] = isLandscape ? [{ rotate: '-90deg' }] : []

  // ── Permission gate ────────────────────────────────────────────────────────
  if (!hasPermission) {
    return (
      <View style={[styles.root, styles.centreBox]}>
        <Text style={styles.centreTitle}>Camera access needed</Text>
        <Text style={styles.centreSub}>
          InspectPro needs camera access to photograph inspection items.
        </Text>
        <TouchableOpacity style={styles.permBtn} onPress={requestPermission}>
          <Text style={styles.permBtnText}>Grant Permission</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.cancelBtn} onPress={() => navigation.goBack()}>
          <Text style={styles.cancelBtnText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    )
  }

  if (!device) {
    return (
      <View style={[styles.root, styles.centreBox]}>
        <Text style={styles.centreTitle}>Camera unavailable</Text>
        <Text style={styles.centreSub}>
          Could not initialise the camera on this device.
        </Text>
        <TouchableOpacity style={styles.cancelBtn} onPress={() => navigation.goBack()}>
          <Text style={styles.cancelBtnText}>Go back</Text>
        </TouchableOpacity>
      </View>
    )
  }

  // ── Camera UI ──────────────────────────────────────────────────────────────
  return (
    <GestureHandlerRootView style={styles.root}>
      {/* Outer gesture detector: pinch-to-zoom across the whole screen */}
      <GestureDetector gesture={pinchGesture}>
        <View style={[styles.root, isLandscape && styles.rootLandscape]}>

          {/* ── Viewfinder (tap anywhere to focus) ── */}
          <GestureDetector gesture={tapGesture}>
            <View style={[styles.viewfinder, { width: VFINDER_W, height: VFINDER_H }]}>
              <Camera
                ref={cameraRef}
                style={StyleSheet.absoluteFill}
                device={device}
                isActive={isFocused}
                photo={true}
                zoom={zoom}
                photoQualityBalance="speed"
                // Bakes device rotation into pixel data so thumbnails always
                // appear upright, regardless of EXIF support on the device.
                outputOrientation="device"
              />

              {/* White flash overlay — briefly visible after each capture */}
              <Animated.View
                pointerEvents="none"
                style={[StyleSheet.absoluteFill, { backgroundColor: '#fff', opacity: captureFlash }]}
              />

              {/* Focus reticule — appears at tap point */}
              {focusPoint && (
                <Animated.View
                  pointerEvents="none"
                  style={[
                    styles.focusReticule,
                    focusLocked && styles.focusReticuleLocked,
                    {
                      left: focusPoint.x - 30,
                      top:  focusPoint.y - 30,
                      opacity: focusLocked ? 0.9 : focusAnim,
                    },
                  ]}
                />
              )}

              {/* Top bar overlaid on the viewfinder */}
              <View style={styles.topBar}>
                <TouchableOpacity style={styles.iconBtn} onPress={() => navigation.goBack()}>
                  <Text style={styles.iconText}>✕</Text>
                </TouchableOpacity>
                {/* Focus mode toggle: AF (auto) ↔ 🔒 (locked) */}
                <TouchableOpacity
                  style={[styles.iconBtn, focusLocked && styles.iconBtnActive]}
                  onPress={cycleFocusMode}
                >
                  <Text style={[styles.iconText, focusLocked && styles.iconTextActive]}>
                    {focusLocked ? '🔒' : 'AF'}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.iconBtn} onPress={cycleFlash}>
                  <Text style={styles.iconText}>{flashLabel}</Text>
                </TouchableOpacity>
              </View>
            </View>
          </GestureDetector>

          {/* ── Controls (below viewfinder in portrait · right strip in landscape) ── */}
          <View style={[
            styles.controlsArea,
            isLandscape && { width: CONTROLS_STRIP_W, height: H },
          ]}>
            {/* Zoom / lens buttons */}
            <View style={[styles.zoomBar, isLandscape && styles.zoomBarLandscape]}>
              {zoomButtons.map(({ label, zoom: z, lens }) => (
                <TouchableOpacity
                  key={label}
                  style={[styles.zoomBtn, activeZoomLabel === label && styles.zoomBtnActive]}
                  onPress={() => {
                    setLensMode(lens)
                    setZoom(z)
                    setActiveZoomLabel(label)
                  }}
                >
                  <Text style={[
                    styles.zoomText,
                    activeZoomLabel === label && styles.zoomTextActive,
                    btnRotate.length > 0 && { transform: btnRotate },
                  ]}>
                    {label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Shutter row: flip · shutter · last-photo thumbnail */}
            <View style={[styles.shutterRow, isLandscape && styles.shutterRowLandscape]}>
              <TouchableOpacity style={styles.iconBtn} onPress={toggleFacing}>
                <Text style={[styles.iconText, btnRotate.length > 0 && { transform: btnRotate }]}>🔄</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.shutter, isCapturing && styles.shutterDisabled]}
                onPress={handleCapture}
                disabled={isCapturing}
              >
                {isCapturing
                  ? <ActivityIndicator color="#1e3a8a" />
                  : <View style={styles.shutterInner} />
                }
              </TouchableOpacity>

              {/* Last-photo thumbnail — tap to open ItemGallery */}
              <TouchableOpacity
                style={styles.thumbBtn}
                onPress={() => {
                  if (!lastPhotoUri || !route.params.sectionKey) return
                  navigation.navigate('ItemGallery', {
                    inspectionId,
                    sectionKey:  route.params.sectionKey,
                    sectionName: route.params.sectionName ?? '',
                    itemKey:     route.params.itemKey    ?? '',
                    itemName:    route.params.itemName   ?? '',
                  })
                }}
                activeOpacity={lastPhotoUri && route.params.sectionKey ? 0.75 : 1}
              >
                {lastPhotoUri ? (
                  <Image source={{ uri: lastPhotoUri }} style={styles.thumbImg} />
                ) : (
                  <View style={styles.thumbEmpty} />
                )}
              </TouchableOpacity>
            </View>
          </View>

        </View>
      </GestureDetector>
    </GestureHandlerRootView>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#000',
  },
  // In landscape the viewfinder and controls sit side-by-side
  rootLandscape: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },

  // Centred info screens (permission / no device)
  centreBox: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  centreTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 12,
    textAlign: 'center',
  },
  centreSub: {
    color: '#aaa',
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 32,
  },
  permBtn: {
    backgroundColor: '#1e3a8a',
    paddingHorizontal: 28,
    paddingVertical: 14,
    borderRadius: 12,
    marginBottom: 16,
  },
  permBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  cancelBtn: {
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  cancelBtnText: {
    color: '#888',
    fontSize: 15,
  },

  // Viewfinder — dimensions set dynamically from VFINDER_W / VFINDER_H
  viewfinder: {
    backgroundColor: '#000',
    overflow: 'hidden',
  },

  // Controls area — portrait: flex below viewfinder · landscape: fixed-width strip
  controlsArea: {
    flex: 1,
    backgroundColor: '#111',
    justifyContent: 'center',
    paddingBottom: 16,
  },

  // Top bar overlaid on the viewfinder
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 52,
    paddingBottom: 12,
  },

  // Zoom buttons — portrait: horizontal row · landscape: vertical column
  zoomBar: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 12,
    marginBottom: 20,
  },
  zoomBarLandscape: {
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    marginBottom: 0,
  },
  zoomBtn: {
    paddingHorizontal: 16,
    paddingVertical: 7,
    borderRadius: 20,
    backgroundColor: 'rgba(0,0,0,0.5)',
    borderWidth: 1,
    borderColor: 'transparent',
  },
  zoomBtnActive: {
    backgroundColor: 'rgba(255,220,0,0.9)',
    borderColor: '#fff',
  },
  zoomText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  zoomTextActive: {
    color: '#000',
  },

  // Shutter row — portrait: horizontal · landscape: vertical column
  shutterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-around',
    paddingHorizontal: 32,
  },
  shutterRowLandscape: {
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'space-around',
    paddingHorizontal: 0,
    paddingVertical: 16,
    gap: 16,
  },

  iconBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: 'rgba(0,0,0,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconBtnActive: {
    backgroundColor: 'rgba(255,220,0,0.9)',
  },
  iconText: {
    color: '#fff',
    fontSize: 18,
  },
  iconTextActive: {
    color: '#000',
  },

  shutter: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 4,
    borderColor: 'rgba(255,255,255,0.6)',
  },
  shutterDisabled: {
    opacity: 0.5,
  },
  shutterInner: {
    width: 58,
    height: 58,
    borderRadius: 29,
    backgroundColor: '#fff',
    borderWidth: 2,
    borderColor: '#ddd',
  },

  // Last-photo thumbnail
  thumbBtn: {
    width: 52,
    height: 52,
    borderRadius: 8,
    overflow: 'hidden',
    borderWidth: 2,
    borderColor: 'rgba(255,255,255,0.4)',
    backgroundColor: 'rgba(255,255,255,0.1)',
  },
  thumbImg: {
    width: '100%',
    height: '100%',
  },
  thumbEmpty: {
    width: '100%',
    height: '100%',
    backgroundColor: 'rgba(255,255,255,0.07)',
  },

  // Focus reticule — yellow square that appears at tap point
  focusReticule: {
    position: 'absolute',
    width: 60,
    height: 60,
    borderWidth: 1.5,
    borderColor: '#ffdc00',
    borderRadius: 3,
  },
  focusReticuleLocked: {
    borderWidth: 2.5,
    borderColor: '#ffdc00',
  },
})
