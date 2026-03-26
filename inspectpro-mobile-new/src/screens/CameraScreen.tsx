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
} from 'react-native'
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera'
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
import { triggerCapture } from '../services/cameraStore'
import type { RootStackParamList } from '../../App'

type CameraRouteProp = RouteProp<RootStackParamList, 'Camera'>
type FlashMode = 'off' | 'on' | 'auto'
type Facing    = 'back' | 'front'

// 4:3 viewfinder dimensions — width is full screen, height is 4/3 of that
const SCREEN_W      = Dimensions.get('window').width
const PREVIEW_H     = Math.round(SCREEN_W * 4 / 3)

export default function CameraScreen() {
  const navigation = useNavigation()
  const route      = useRoute<CameraRouteProp>()
  const { inspectionId } = route.params

  // ── VisionCamera permission ────────────────────────────────────────────────
  const { hasPermission, requestPermission } = useCameraPermission()

  // ── Device selection ───────────────────────────────────────────────────────
  const [facing, setFacing]     = useState<Facing>('back')
  const [lensMode, setLensMode] = useState<'main' | 'ultraWide'>('main')

  const backDevice  = useCameraDevice('back')
  const frontDevice = useCameraDevice('front')

  // Fuzzy-match the ultra-wide physical device string — different OEMs use
  // different names ('ultra-wide-angle-camera', 'ultrawide', 'wide', etc.).
  // We scan physicalDevices for any string containing 'ultra' or 'wide' and
  // pass that exact ID back to useCameraDevice. If no match, passes undefined
  // (hook still called — React rules are satisfied; just gets null back).
  const ultraWidePhysicalId = backDevice?.physicalDevices?.find(
    (p: string) => p.toLowerCase().includes('ultra') || p.toLowerCase().includes('wide')
  )
  const ultraWideDevice = useCameraDevice(
    'back',
    ultraWidePhysicalId ? { physicalDevices: [ultraWidePhysicalId] } : undefined
  )

  // Dual detection strategy — covers two different OEM architectures:
  //   hasSeparateUltraWide: the OS exposes the wide lens as its own camera ID.
  //     Fix: physically swap to that device when 0.6× is pressed.
  //   hasZoomBasedUltraWide: fused multi-lens camera where wide is reachable
  //     by setting zoom below neutralZoom on the same device.
  //     Fix: stay on backDevice and set zoom = minZoom.
  const hasSeparateUltraWide =
    !!ultraWideDevice && !!backDevice && ultraWideDevice.id !== backDevice.id
  const hasZoomBasedUltraWide =
    !!backDevice && backDevice.minZoom < backDevice.neutralZoom
  const hasUltraWide = hasSeparateUltraWide || hasZoomBasedUltraWide

  const device = facing === 'front'
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

  // Pre-request MediaLibrary permission once at mount (not on every shot)
  const mlPermGranted = useRef(false)
  useEffect(() => {
    MediaLibrary.requestPermissionsAsync().then(p => {
      mlPermGranted.current = p.status === 'granted'
    })
  }, [])

  // Flash-white overlay shown briefly after each shot as capture feedback
  const captureFlash = useRef(new Animated.Value(0)).current
  function triggerFlash() {
    Animated.sequence([
      Animated.timing(captureFlash, { toValue: 1, duration: 60,  useNativeDriver: true }),
      Animated.timing(captureFlash, { toValue: 0, duration: 200, useNativeDriver: true }),
    ]).start()
  }

  // Update zoom to device neutral when active device changes (lens switch / flip).
  const lastDeviceId = useRef<string | undefined>()
  if (device && device.id !== lastDeviceId.current) {
    lastDeviceId.current = device.id
    setZoom(device.neutralZoom)
    setActiveZoomLabel(lensMode === 'ultraWide' ? '0.6×' : '1×')
  }

  // Debug: comprehensive log of both detection paths
  useEffect(() => {
    console.log('--- CAMERA DEBUG ---')
    console.log('[Camera] backDevice.id:', backDevice?.id)
    console.log('[Camera] physicalDevices:', JSON.stringify(backDevice?.physicalDevices))
    console.log('[Camera] ultraWidePhysicalId (fuzzy match):', ultraWidePhysicalId)
    console.log('[Camera] ultraWideDevice.id:', ultraWideDevice?.id)
    console.log('[Camera] hasSeparateUltraWide:', hasSeparateUltraWide)
    console.log('[Camera] hasZoomBasedUltraWide:', hasZoomBasedUltraWide)
    console.log('[Camera] minZoom:', backDevice?.minZoom, '| neutralZoom:', backDevice?.neutralZoom, '| maxZoom:', backDevice?.maxZoom)
  }, [backDevice?.id, ultraWideDevice?.id])

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
    if (!cameraRef.current || isCapturing || !device) return
    setIsCapturing(true)
    try {
      const photo = await cameraRef.current.takePhoto({
        flash,
        enableShutterSound: false,
      })

      // VisionCamera returns an absolute path without file:// on Android.
      const srcUri = photo.path.startsWith('file://')
        ? photo.path
        : `file://${photo.path}`

      // 1. Copy to app-private storage FIRST (fast, same-filesystem copy).
      //    This path is what report_data stores and galleries read from.
      const dir  = `${FileSystem.documentDirectory}photos/${inspectionId}/`
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true })
      const dest = `${dir}${Date.now()}.jpg`
      await FileSystem.copyAsync({ from: srcUri, to: dest })

      // 2. Hand off path to the calling screen immediately.
      triggerCapture(dest)

      // 3. Show capture feedback and re-arm (camera stays open).
      triggerFlash()
      setIsCapturing(false)

      // 4. Save to device gallery in the background — don't block the next shot.
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
      setIsCapturing(false)
    }
  }, [isCapturing, device, flash, inspectionId])

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
                physDev: {JSON.stringify(backDevice?.physicalDevices ?? [])}
              </Text>
              <Text style={styles.debugText}>
                fuzzyId: {ultraWidePhysicalId ?? 'none'}
              </Text>
              <Text style={styles.debugText}>
                sepUW: {String(hasSeparateUltraWide)}  zoomUW: {String(hasZoomBasedUltraWide)}
              </Text>
              <Text style={styles.debugText}>
                min:{backDevice?.minZoom?.toFixed(2) ?? '?'}  neu:{backDevice?.neutralZoom?.toFixed(2) ?? '?'}  max:{backDevice?.maxZoom?.toFixed(2) ?? '?'}
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

            {/* Shutter row: flip · shutter · spacer */}
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

              {/* Spacer keeps shutter centred */}
              <View style={styles.iconBtn} />
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
})
