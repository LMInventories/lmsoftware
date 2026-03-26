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
  // useCameraDevice returns the BEST device for that position —
  // on multi-lens phones this is the triple/dual camera, giving access to
  // ultra-wide, main, and telephoto via the zoom range.
  const [facing, setFacing] = useState<Facing>('back')
  const backDevice  = useCameraDevice('back')
  const frontDevice = useCameraDevice('front')
  const device = facing === 'back' ? backDevice : frontDevice

  // Camera pauses automatically when screen is not focused
  const isFocused = useIsFocused()

  // ── State ──────────────────────────────────────────────────────────────────
  const cameraRef        = useRef<Camera>(null)
  const [flash, setFlash]               = useState<FlashMode>('off')
  const [zoom, setZoom]                 = useState(1)           // overridden once device loads
  const [activeZoomLabel, setActiveZoomLabel] = useState('1×')
  const [isCapturing, setIsCapturing]   = useState(false)

  // Update zoom to device neutral when device changes (back ↔ front flip,
  // or first device load). Use a ref to avoid re-running on every render.
  const lastDeviceId = useRef<string | undefined>()
  if (device && device.id !== lastDeviceId.current) {
    lastDeviceId.current = device.id
    // setState during render is valid in React when guarded like this
    setZoom(device.neutralZoom)
    setActiveZoomLabel('1×')
  }

  // Debug: log actual device lens info so we can verify physicalDevices strings
  useEffect(() => {
    if (!device) return
    console.log('[Camera] device.id:', device.id)
    console.log('[Camera] device.physicalDevices:', JSON.stringify(device.physicalDevices))
    console.log('[Camera] minZoom:', device.minZoom, '| neutralZoom:', device.neutralZoom, '| maxZoom:', device.maxZoom)
    console.log('[Camera] hasUltraWide check → physicalDevices includes ultra-wide-angle-camera:', device.physicalDevices.includes('ultra-wide-angle-camera'))
    console.log('[Camera] minZoom < neutralZoom * 0.9:', device.minZoom < device.neutralZoom * 0.9)
  }, [device?.id])

  // ── Derived ────────────────────────────────────────────────────────────────
  // An ultra-wide lens is available when the device's minimum zoom is
  // meaningfully less than its neutral (1×) zoom.
  const hasUltraWide =
    !!device &&
    device.physicalDevices.includes('ultra-wide-angle-camera') &&
    device.minZoom < device.neutralZoom * 0.9

  // Build zoom button list from the device's actual capabilities.
  function buildZoomButtons(): { label: string; zoom: number }[] {
    if (!device) return [{ label: '1×', zoom: 1 }]
    const neutral = device.neutralZoom
    const max     = device.maxZoom
    const buttons: { label: string; zoom: number }[] = []
    if (hasUltraWide) {
      buttons.push({ label: '0.6×', zoom: device.minZoom })
    }
    buttons.push({ label: '1×', zoom: neutral })
    const z2 = neutral * 2
    if (z2 <= max) buttons.push({ label: '2×', zoom: z2 })
    const z5 = neutral * 5
    if (z5 <= max) buttons.push({ label: '5×', zoom: z5 })
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
        enableShutterSound: false, // silences system shutter (where OS allows it)
      })

      // VisionCamera returns an absolute file path without file:// on Android.
      const srcUri = photo.path.startsWith('file://')
        ? photo.path
        : `file://${photo.path}`

      // 1. Save to device gallery so the inspector can find photos easily.
      //    Request permission inline; if denied we still save to app storage.
      const mlPerm = await MediaLibrary.requestPermissionsAsync()
      if (mlPerm.status === 'granted') {
        await MediaLibrary.saveToLibraryAsync(srcUri)
      }

      // 2. Copy to app-private storage — this path is what report_data references.
      //    documentDirectory persists through app updates (not uninstalls).
      const dir  = `${FileSystem.documentDirectory}photos/${inspectionId}/`
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true })
      const dest = `${dir}${Date.now()}.jpg`
      await FileSystem.copyAsync({ from: srcUri, to: dest })

      // 3. Hand off the final path to whichever screen opened the camera.
      triggerCapture(dest)
      navigation.goBack()
    } catch (err: any) {
      console.error('[CameraScreen] capture error', err)
      Alert.alert(
        'Photo failed',
        err?.message ?? 'Could not save the photo. Please try again.'
      )
      setIsCapturing(false)
    }
  }, [isCapturing, device, flash, inspectionId, navigation])

  // ── Controls ───────────────────────────────────────────────────────────────
  const toggleFacing = useCallback(() => {
    setFacing(f => f === 'back' ? 'front' : 'back')
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
            {/* Zoom buttons — built from real device capabilities */}
            <View style={styles.zoomBar}>
              {zoomButtons.map(({ label, zoom: z }) => (
                <TouchableOpacity
                  key={label}
                  style={[
                    styles.zoomBtn,
                    activeZoomLabel === label && styles.zoomBtnActive,
                  ]}
                  onPress={() => {
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
