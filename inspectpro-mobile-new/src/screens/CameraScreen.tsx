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
 * • Front/back flip supported with separate device lookup.
 * • Camera paused when screen loses focus (navigation push/pop).
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
} from 'react-native'
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera'
import type { CameraDevice } from 'react-native-vision-camera'
import * as MediaLibrary from 'expo-media-library'
// expo-file-system/legacy preserves the makeDirectoryAsync / copyAsync API
// (the top-level export deprecated them in favour of the new File/Directory classes)
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
  RouteProp,
} from '@react-navigation/native'
import type { StackNavigationProp } from '@react-navigation/stack'
import { triggerCapture } from '../services/cameraStore'
import type { RootStackParamList } from '../../App'

type CameraRouteProp = RouteProp<RootStackParamList, 'Camera'>
type CameraNavProp   = StackNavigationProp<RootStackParamList, 'Camera'>
type FlashMode = 'off' | 'on' | 'auto'
type Facing    = 'back' | 'front'

// 4:3 viewfinder dimensions — width is full screen, height is 4/3 of that
const SCREEN_W      = Dimensions.get('window').width
const PREVIEW_H     = Math.round(SCREEN_W * 4 / 3)

export default function CameraScreen() {
  const navigation = useNavigation<CameraNavProp>()
  const route      = useRoute<CameraRouteProp>()
  const { inspectionId } = route.params

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

  // Re-fetch device list when camera permission is granted (devices may change)
  useEffect(() => {
    try { setAllDevices(Camera.getAvailableCameraDevices()) } catch {}
  }, [hasPermission])

  // From all devices, find back-facing cameras and pick best main + ultra-wide.
  const backDevices: CameraDevice[] = allDevices.filter((d: CameraDevice) => d.position === 'back')

  // Main back camera: prefer the device whose physicalDevices includes
  // 'wide-angle-camera' (but NOT ultra-wide-angle-camera alone), or fall back
  // to the first back-facing device.
  const backDevice: CameraDevice | undefined =
    backDevices.find((d: CameraDevice) =>
      d.physicalDevices?.includes('wide-angle-camera') &&
      !(d.physicalDevices ?? []).every((p: string) => p === 'ultra-wide-angle-camera')
    ) ?? backDevices[0]

  // Ultra-wide device: find a back-facing device that explicitly includes
  // 'ultra-wide-angle-camera' in its physical devices, OR find one where
  // physicalDevices contains only ultra-wide (some OEMs expose it standalone).
  // Also check for OEM variants ('ultrawide', 'ultra_wide', etc.) via fuzzy match.
  const ultraWideDevice: CameraDevice | undefined = backDevices.find((d: CameraDevice) =>
    (d.physicalDevices ?? []).some(
      (p: string) => p === 'ultra-wide-angle-camera' || p.toLowerCase().includes('ultra')
    )
  )

  // Dual detection strategy:
  //   hasSeparateUltraWide: a distinct camera device for the ultra-wide lens.
  //   hasZoomBasedUltraWide: fused camera where minZoom < neutralZoom allows
  //     reaching the wide angle by zooming out below 1×.
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
  const cameraRef        = useRef<Camera>(null)
  const [flash, setFlash]               = useState<FlashMode>('off')
  const [zoom, setZoom]                 = useState(1)           // overridden once device loads
  const [activeZoomLabel, setActiveZoomLabel] = useState('1×')
  const [isCapturing, setIsCapturing]   = useState(false)
  // Last captured photo — shown as thumbnail next to shutter button
  const [lastPhotoUri, setLastPhotoUri]   = useState<string | null>(null)

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

  // Subtle flash blink on capture — quick enough to not slow down rapid shooting
  const captureFlash = useRef(new Animated.Value(0)).current
  function triggerFlash() {
    Animated.sequence([
      Animated.timing(captureFlash, { toValue: 0.35, duration: 20,  useNativeDriver: true }),
      Animated.timing(captureFlash, { toValue: 0,    duration: 80,  useNativeDriver: true }),
    ]).start()
  }

  // Update zoom to device neutral when active device changes (lens switch / flip).
  const lastDeviceId = useRef<string | undefined>(undefined)
  if (device && device.id !== lastDeviceId.current) {
    lastDeviceId.current = device.id
    setZoom(device.neutralZoom)
    setActiveZoomLabel(lensMode === 'ultraWide' ? '0.6×' : '1×')
  }

  // Debug: log ALL back cameras so we can see what the device exposes
  useEffect(() => {
    console.log('--- CAMERA DEBUG ---')
    console.log('[Camera] total devices:', allDevices.length)
    backDevices.forEach((d, i) => {
      console.log(`[Camera] back[${i}] id=${d.id} physDev=${JSON.stringify(d.physicalDevices)} min=${d.minZoom} neu=${d.neutralZoom} max=${d.maxZoom}`)
    })
    console.log('[Camera] selected backDevice.id:', backDevice?.id)
    console.log('[Camera] ultraWideDevice.id:', ultraWideDevice?.id)
    console.log('[Camera] hasSeparateUltraWide:', hasSeparateUltraWide)
    console.log('[Camera] hasZoomBasedUltraWide:', hasZoomBasedUltraWide)
  }, [allDevices.length, backDevice?.id, ultraWideDevice?.id])

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
        // Separate device: use its own neutral zoom (1× for that sensor)
        // Zoom-based: use the fused camera's minZoom
        zoom: hasSeparateUltraWide
          ? (ultraWideDevice?.neutralZoom ?? backDevice.minZoom)
          : backDevice.minZoom,
        // Only physically switch device if it's separate; otherwise stay on
        // backDevice and just adjust the zoom value
        lens: hasSeparateUltraWide ? 'ultraWide' : 'main',
      })
    }
    buttons.push({ label: '1×', zoom: neutral, lens: 'main' })
    if (neutral * 2 <= max) buttons.push({ label: '2×', zoom: neutral * 2, lens: 'main' })
    if (neutral * 5 <= max) buttons.push({ label: '5×', zoom: neutral * 5, lens: 'main' })
    return buttons
  }
  const zoomButtons = buildZoomButtons()

  // ── Pinch gesture (JS thread, no Reanimated needed) ───────────────────────
  const baseZoom = useRef(1)
  const pinchGesture = Gesture.Pinch()
    .onStart(() => {
      baseZoom.current = zoom
    })
    .onUpdate((e) => {
      if (!device) return
      const next = Math.min(
        device.maxZoom,
        Math.max(device.minZoom, baseZoom.current * e.scale)
      )
      setZoom(next)
      setActiveZoomLabel('') // deselect preset button during manual pinch
    })
    .runOnJS(true)

  // ── Capture ────────────────────────────────────────────────────────────────
  const handleCapture = useCallback(async () => {
    // Use capturingRef as the hard gate — no state update, no re-render stall.
    if (!cameraRef.current || capturingRef.current || !device || !photoDirRef.current) return
    capturingRef.current = true
    setIsCapturing(true)   // UI only: dims shutter button
    try {
      const photo = await cameraRef.current.takePhoto({
        flash,
        enableShutterSound: false,
        // skipMetadata skips EXIF processing on Android — measurably faster
        // on lower-end devices. Disable if GPS-tagged photos are ever needed.
        skipMetadata: true,
      })

      // VisionCamera returns an absolute path without file:// on Android.
      const srcUri = photo.path.startsWith('file://')
        ? photo.path
        : `file://${photo.path}`

      // 1. Copy to app-private storage (directory was pre-created at mount).
      const dest = `${photoDirRef.current}${Date.now()}.jpg`
      await FileSystem.copyAsync({ from: srcUri, to: dest })

      // 2. Hand off to calling screen. Release gate BEFORE gallery save so the
      //    next shot can be triggered immediately without waiting for MediaLibrary.
      triggerCapture(dest)
      triggerFlash()
      setLastPhotoUri(dest)
      capturingRef.current = false
      setIsCapturing(false)

      // 3. Save to device gallery async — never blocks the capture pipeline.
      if (mlPermGranted.current) {
        MediaLibrary.saveToLibraryAsync(srcUri).catch(e =>
          console.warn('[CameraScreen] gallery save failed:', e)
        )
      }
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
    setLensMode('main')  // always start on main lens when flipping
  }, [])

  const cycleFlash = useCallback(() => {
    setFlash(f => f === 'off' ? 'on' : f === 'on' ? 'auto' : 'off')
  }, [])

  const flashLabel = flash === 'off' ? '⚡✕' : flash === 'on' ? '⚡' : '⚡A'

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

  // ── No device available ────────────────────────────────────────────────────
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
      <GestureDetector gesture={pinchGesture}>
        <View style={styles.root}>

          {/* ── 4:3 viewfinder ── */}
          <View style={styles.viewfinder}>
            <Camera
              ref={cameraRef}
              style={StyleSheet.absoluteFill}
              device={device}
              isActive={isFocused}
              photo={true}
              zoom={zoom}
              photoQualityBalance="speed"
            />

            {/* White flash overlay — briefly visible after each capture */}
            <Animated.View
              pointerEvents="none"
              style={[StyleSheet.absoluteFill, { backgroundColor: '#fff', opacity: captureFlash }]}
            />

            {/* Top bar overlaid on the viewfinder */}
            <View style={styles.topBar}>
              <TouchableOpacity style={styles.iconBtn} onPress={() => navigation.goBack()}>
                <Text style={styles.iconText}>✕</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.iconBtn} onPress={cycleFlash}>
                <Text style={styles.iconText}>{flashLabel}</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* ── Controls below the viewfinder ── */}
          <View style={styles.controlsArea}>
            {/* ── TEMP DEBUG OVERLAY — remove once ultra-wide is confirmed working ── */}
            <View style={styles.debugBox}>
              <Text style={styles.debugText}>
                allDev:{allDevices.length}  back:{backDevices.length}  UW:{ultraWideDevice?.id?.slice(-4) ?? 'none'}
              </Text>
              {backDevices.map((d, i) => (
                <Text key={d.id} style={styles.debugText}>
                  [{i}] {JSON.stringify(d.physicalDevices)} {d.minZoom.toFixed(1)}-{d.maxZoom.toFixed(0)}x
                </Text>
              ))}
              <Text style={styles.debugText}>
                sepUW:{String(hasSeparateUltraWide)} zoomUW:{String(hasZoomBasedUltraWide)}
              </Text>
            </View>

            {/* Zoom / lens buttons — switching to 0.6× physically swaps to ultra-wide device */}
            <View style={styles.zoomBar}>
              {zoomButtons.map(({ label, zoom: z, lens }) => (
                <TouchableOpacity
                  key={label}
                  style={[
                    styles.zoomBtn,
                    activeZoomLabel === label && styles.zoomBtnActive,
                  ]}
                  onPress={() => {
                    setLensMode(lens)
                    setZoom(z)
                    setActiveZoomLabel(label)
                  }}
                >
                  <Text
                    style={[
                      styles.zoomText,
                      activeZoomLabel === label && styles.zoomTextActive,
                    ]}
                  >
                    {label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Shutter row: flip · shutter · last-photo thumbnail */}
            <View style={styles.shutterRow}>
              <TouchableOpacity style={styles.iconBtn} onPress={toggleFacing}>
                <Text style={styles.iconText}>🔄</Text>
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

              {/* Last-photo thumbnail — tap to open ItemGallery for rotate/delete */}
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

  // 4:3 viewfinder box
  viewfinder: {
    width: SCREEN_W,
    height: PREVIEW_H,
    backgroundColor: '#000',
    overflow: 'hidden',
  },

  // Controls area below the viewfinder
  controlsArea: {
    flex: 1,
    backgroundColor: '#111',
    justifyContent: 'center',
    paddingBottom: 16,
  },

  // Temporary debug overlay
  debugBox: {
    backgroundColor: 'rgba(0,0,0,0.75)',
    padding: 6,
    marginHorizontal: 8,
    marginBottom: 6,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '#ff0',
  },
  debugText: {
    color: '#ff0',
    fontSize: 10,
    fontFamily: 'monospace',
    lineHeight: 15,
  },

  // Camera layout
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 52,
    paddingBottom: 12,
  },
  zoomBar: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 12,
    marginBottom: 20,
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
  shutterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-around',
    paddingHorizontal: 32,
  },
  iconBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: 'rgba(0,0,0,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconText: {
    color: '#fff',
    fontSize: 18,
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

  // Last-photo thumbnail (replaces blank spacer to the right of shutter)
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

})
