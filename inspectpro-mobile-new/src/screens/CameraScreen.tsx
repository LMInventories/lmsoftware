import React, { useRef, useState, useCallback } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
} from 'react-native'
import { CameraView, useCameraPermissions } from 'expo-camera'
import type { CameraType, FlashMode } from 'expo-camera'
import * as FileSystem from 'expo-file-system'
import { GestureDetector, Gesture, GestureHandlerRootView } from 'react-native-gesture-handler'
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native'
import { triggerCapture } from '../services/cameraStore'
import type { RootStackParamList } from '../../App'

type CameraRouteProp = RouteProp<RootStackParamList, 'Camera'>

// Zoom levels as fractions of expo-camera's 0–1 range.
// 0.6× ultrawide removed: Android lens names don't match 'ultra-wide' reliably.
const ZOOM_BUTTONS = [
  { label: '1×', zoom: 0    },
  { label: '2×', zoom: 0.15 }, // approx 2× on most sensors
  { label: '5×', zoom: 0.45 }, // approx 5× on most sensors
] as const

export default function CameraScreen() {
  const navigation = useNavigation()
  const route = useRoute<CameraRouteProp>()
  const { inspectionId } = route.params

  const [permission, requestPermission] = useCameraPermissions()

  const cameraRef = useRef<React.ComponentRef<typeof CameraView>>(null)

  const [facing, setFacing] = useState<CameraType>('back')
  const [flash, setFlash]   = useState<FlashMode>('off')
  const [zoom, setZoom]     = useState(0)
  const [activeZoomLabel, setActiveZoomLabel] = useState<string>('1×')
  const [isCapturing, setIsCapturing]         = useState(false)
  const [cameraReady, setCameraReady]         = useState(false)

  // Pinch-to-zoom tracking
  const baseZoom = useRef(0)

  const onCameraReady = useCallback(() => {
    setCameraReady(true)
  }, [])

  const handleZoomButton = useCallback((label: string, zoomVal: number) => {
    setZoom(zoomVal)
    setActiveZoomLabel(label)
  }, [])

  // Pinch gesture
  const pinchGesture = Gesture.Pinch()
    .onStart(() => { baseZoom.current = zoom })
    .onUpdate((e) => {
      const next = Math.min(1, Math.max(0, baseZoom.current + (e.scale - 1) * 0.3))
      setZoom(next)
      setActiveZoomLabel('')  // deselect preset during manual pinch
    })
    .runOnJS(true)

  const handleCapture = useCallback(async () => {
    if (!cameraRef.current || isCapturing || !cameraReady) return
    setIsCapturing(true)
    try {
      // skipProcessing is intentionally omitted.
      // On Android with New Architecture, skipProcessing:true returns a temp
      // content:// URI that expo-file-system cannot copy — photos silently vanish.
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.85 })

      if (!photo?.uri) throw new Error('Camera returned no file URI.')

      const dir = `${FileSystem.documentDirectory}photos/${inspectionId}/`
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true })
      const dest = `${dir}${Date.now()}.jpg`
      await FileSystem.copyAsync({ from: photo.uri, to: dest })

      triggerCapture(dest)
      navigation.goBack()
    } catch (err: any) {
      console.error('[CameraScreen] capture error', err)
      Alert.alert('Photo failed', err?.message ?? 'Could not save the photo. Please try again.')
      setIsCapturing(false)
    }
  }, [isCapturing, cameraReady, inspectionId, navigation])

  const toggleFacing = useCallback(() => {
    setFacing(f => f === 'back' ? 'front' : 'back')
  }, [])

  const toggleFlash = useCallback(() => {
    setFlash(f => {
      if (f === 'off') return 'on'
      if (f === 'on')  return 'auto'
      return 'off'
    })
  }, [])

  const flashLabel = flash === 'off' ? '⚡✕' : flash === 'on' ? '⚡' : '⚡A'

  // ── Permission gate ────────────────────────────────────────────────────────
  if (!permission) return <View style={styles.root} />

  if (!permission.granted) {
    return (
      <View style={[styles.root, styles.permBox]}>
        <Text style={styles.permTitle}>Camera access needed</Text>
        <Text style={styles.permSub}>
          InspectPro needs camera access to photograph inspection items.
        </Text>
        <TouchableOpacity style={styles.permBtn} onPress={requestPermission}>
          <Text style={styles.permBtnText}>Grant Permission</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.permCancel} onPress={() => navigation.goBack()}>
          <Text style={styles.permCancelText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    )
  }

  // ── Camera UI ──────────────────────────────────────────────────────────────
  return (
    <GestureHandlerRootView style={styles.root}>
      <GestureDetector gesture={pinchGesture}>
        <CameraView
          ref={cameraRef}
          style={styles.camera}
          facing={facing}
          flash={flash}
          zoom={zoom}
          onCameraReady={onCameraReady}
        >
          {/* ── Top bar: close + flash ── */}
          <View style={styles.topBar}>
            <TouchableOpacity style={styles.iconBtn} onPress={() => navigation.goBack()}>
              <Text style={styles.iconText}>✕</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.iconBtn} onPress={toggleFlash}>
              <Text style={styles.iconText}>{flashLabel}</Text>
            </TouchableOpacity>
          </View>

          {/* ── Spacer pushes controls to the bottom ── */}
          <View style={{ flex: 1 }} />

          {/* ── Bottom group: zoom row + shutter row ── */}
          <View style={styles.bottomGroup}>
            {/* Zoom buttons */}
            <View style={styles.zoomBar}>
              {ZOOM_BUTTONS.map(({ label, zoom: z }) => (
                <TouchableOpacity
                  key={label}
                  style={[styles.zoomBtn, activeZoomLabel === label && styles.zoomBtnActive]}
                  onPress={() => handleZoomButton(label, z)}
                >
                  <Text style={[styles.zoomText, activeZoomLabel === label && styles.zoomTextActive]}>
                    {label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Shutter row */}
            <View style={styles.shutterRow}>
              {/* Flip camera */}
              <TouchableOpacity style={styles.iconBtn} onPress={toggleFacing}>
                <Text style={styles.iconText}>🔄</Text>
              </TouchableOpacity>

              {/* Shutter */}
              <TouchableOpacity
                style={[styles.shutter, isCapturing && styles.shutterDisabled]}
                onPress={handleCapture}
                disabled={isCapturing || !cameraReady}
              >
                {isCapturing
                  ? <ActivityIndicator color="#1e3a8a" />
                  : <View style={styles.shutterInner} />
                }
              </TouchableOpacity>

              {/* Spacer balances layout */}
              <View style={styles.iconBtn} />
            </View>
          </View>
        </CameraView>
      </GestureDetector>
    </GestureHandlerRootView>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#000',
  },

  // Permission screen
  permBox: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  permTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 12,
    textAlign: 'center',
  },
  permSub: {
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
  permCancel: {
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  permCancelText: {
    color: '#888',
    fontSize: 15,
  },

  // Camera layout
  camera: {
    flex: 1,
    // Do NOT use justifyContent:'space-between' with 3+ children —
    // it puts the middle child in screen centre. Use flex:1 spacer instead.
    flexDirection: 'column',
  },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 52,
    paddingBottom: 12,
  },

  // Bottom group keeps zoom + shutter together at the bottom
  bottomGroup: {
    paddingBottom: 48,
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
