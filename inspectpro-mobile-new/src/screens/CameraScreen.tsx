import React, { useRef, useState, useCallback } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
} from 'react-native'
import { CameraView, useCameraPermissions } from 'expo-camera'
import type { CameraType, FlashMode } from 'expo-camera'
import * as FileSystem from 'expo-file-system'
import { GestureDetector, Gesture, GestureHandlerRootView } from 'react-native-gesture-handler'
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native'
import { triggerCapture } from '../services/cameraStore'
import type { RootStackParamList } from '../../App'

type CameraRouteProp = RouteProp<RootStackParamList, 'Camera'>

// Zoom levels as fractions of the camera's zoom range (0–1)
// 0.6× is achieved via ultrawide lens (selectedLens='ultra-wide') if available,
// otherwise falls back to main lens at minimum zoom.
const ZOOM_BUTTONS = [
  { label: '0.6×', zoom: 0, ultrawide: true },
  { label: '1×',   zoom: 0,    ultrawide: false },
  { label: '2×',   zoom: 0.15, ultrawide: false },  // approx 2× on most sensors
  { label: '5×',   zoom: 0.45, ultrawide: false },  // approx 5× on most sensors
] as const

export default function CameraScreen() {
  const navigation = useNavigation()
  const route = useRoute<CameraRouteProp>()
  const { inspectionId } = route.params

  const [permission, requestPermission] = useCameraPermissions()

  const cameraRef = useRef<React.ComponentRef<typeof CameraView>>(null)

  const [facing, setFacing] = useState<CameraType>('back')
  const [flash, setFlash] = useState<FlashMode>('off')
  const [zoom, setZoom] = useState(0)
  const [selectedLens, setSelectedLens] = useState<string | undefined>(undefined)
  const [availableLenses, setAvailableLenses] = useState<string[]>([])
  const [activeZoomButton, setActiveZoomButton] = useState<string>('1×')
  const [isCapturing, setIsCapturing] = useState(false)
  const [cameraReady, setCameraReady] = useState(false)

  // Pinch-to-zoom tracking
  const baseZoom = useRef(0)

  // Fetch available lenses once camera is ready
  const onCameraReady = useCallback(async () => {
    setCameraReady(true)
    try {
      const lenses = await cameraRef.current?.getAvailableLensesAsync?.() ?? []
      setAvailableLenses(lenses)
    } catch {
      setAvailableLenses([])
    }
  }, [])

  const hasUltrawide = availableLenses.includes('ultra-wide')

  // Activate a zoom button
  const handleZoomButton = useCallback((label: string, zoomVal: number, isUltrawide: boolean) => {
    if (isUltrawide) {
      if (hasUltrawide) {
        setSelectedLens('ultra-wide')
        setZoom(0)
      } else {
        // Fallback: main lens at minimum zoom
        setSelectedLens(undefined)
        setZoom(0)
      }
    } else {
      setSelectedLens(undefined)
      setZoom(zoomVal)
    }
    setActiveZoomButton(label)
  }, [hasUltrawide])

  // Pinch gesture for zoom
  const pinchGesture = Gesture.Pinch()
    .onStart(() => {
      baseZoom.current = zoom
    })
    .onUpdate((e) => {
      // Scale the zoom: pinch scale > 1 = zooming in
      // Clamp between 0 and 1 (expo-camera zoom range)
      const newZoom = Math.min(1, Math.max(0, baseZoom.current + (e.scale - 1) * 0.3))
      setZoom(newZoom)
      // Pinch always uses main lens
      setSelectedLens(undefined)
      setActiveZoomButton('')  // deselect preset buttons during manual pinch
    })
    .runOnJS(true)

  const handleCapture = useCallback(async () => {
    if (!cameraRef.current || isCapturing || !cameraReady) return
    setIsCapturing(true)
    try {
      const photo = await cameraRef.current.takePictureAsync({
        quality: 0.85,
        skipProcessing: Platform.OS === 'android',
      })

      if (!photo?.uri) throw new Error('No URI returned from camera')

      // Save to app-specific folder immediately
      const dir = `${FileSystem.documentDirectory}photos/${inspectionId}/`
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true })
      const timestamp = Date.now()
      const dest = `${dir}${timestamp}.jpg`
      await FileSystem.copyAsync({ from: photo.uri, to: dest })

      // Hand off to originating screen
      triggerCapture(dest)

      navigation.goBack()
    } catch (err) {
      console.error('[CameraScreen] capture error', err)
      setIsCapturing(false)
    }
  }, [isCapturing, cameraReady, inspectionId, navigation])

  const toggleFacing = useCallback(() => {
    setFacing(f => f === 'back' ? 'front' : 'back')
  }, [])

  const toggleFlash = useCallback(() => {
    setFlash(f => {
      if (f === 'off') return 'on'
      if (f === 'on') return 'auto'
      return 'off'
    })
  }, [])

  const flashIcon = flash === 'off' ? '⚡️✕' : flash === 'on' ? '⚡️' : '⚡️A'

  // ── Permission gate ───────────────────────────────────────────────────────
  // permission is null while the module loads; show nothing (avoid flash)
  if (!permission) {
    return <View style={styles.root} />
  }

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

  return (
    <GestureHandlerRootView style={styles.root}>
      <GestureDetector gesture={pinchGesture}>
        <CameraView
          ref={cameraRef}
          style={styles.camera}
          facing={facing}
          flash={flash}
          zoom={zoom}
          selectedLens={selectedLens}
          onCameraReady={onCameraReady}
        >
          {/* Top controls */}
          <View style={styles.topBar}>
            <TouchableOpacity style={styles.iconBtn} onPress={() => navigation.goBack()}>
              <Text style={styles.iconText}>✕</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.iconBtn} onPress={toggleFlash}>
              <Text style={styles.iconText}>{flashIcon}</Text>
            </TouchableOpacity>
          </View>

          {/* Zoom buttons */}
          <View style={styles.zoomBar}>
            {ZOOM_BUTTONS.map(({ label, zoom: z, ultrawide }) => (
              <TouchableOpacity
                key={label}
                style={[styles.zoomBtn, activeZoomButton === label && styles.zoomBtnActive]}
                onPress={() => handleZoomButton(label, z, ultrawide)}
              >
                <Text style={[styles.zoomText, activeZoomButton === label && styles.zoomTextActive]}>
                  {label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Bottom controls */}
          <View style={styles.bottomBar}>
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

            {/* Spacer to balance layout */}
            <View style={styles.iconBtn} />
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
  camera: {
    flex: 1,
    justifyContent: 'space-between',
  },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 52,
    paddingBottom: 12,
  },
  bottomBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-around',
    paddingBottom: 48,
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
  zoomBar: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 10,
    marginBottom: 24,
  },
  zoomBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: 'rgba(0,0,0,0.45)',
    borderWidth: 1,
    borderColor: 'transparent',
  },
  zoomBtnActive: {
    backgroundColor: 'rgba(255,220,0,0.85)',
    borderColor: '#fff',
  },
  zoomText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
  },
  zoomTextActive: {
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
})
