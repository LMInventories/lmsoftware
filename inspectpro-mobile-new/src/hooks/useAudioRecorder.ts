import { useState, useRef, useCallback } from 'react'
import {
  useAudioRecorder as useExpoAudioRecorder,
  AudioModule,
  RecordingPresets,
  createAudioPlayer,
} from 'expo-audio'
import * as FileSystem from 'expo-file-system'
import { Alert } from 'react-native'

export interface Recording {
  uri: string
  durationMs: number
  transcription?: string
}

export function useAudioRecorder() {
  const recorder = useExpoAudioRecorder(RecordingPresets.HIGH_QUALITY)

  const [isRecording, setIsRecording] = useState(false)
  const [isPlaying, setIsPlaying]     = useState(false)

  // Track elapsed time for duration since recorder.currentTime may not be
  // available post-stop on all platforms
  const startTimeRef = useRef<number>(0)
  const playerRef    = useRef<ReturnType<typeof createAudioPlayer> | null>(null)

  const startRecording = useCallback(async (): Promise<boolean> => {
    try {
      const { granted } = await AudioModule.requestRecordingPermissionsAsync()
      if (!granted) {
        Alert.alert('Permission required', 'Microphone access is needed for audio dictation.')
        return false
      }

      await AudioModule.setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
      })

      recorder.record()
      startTimeRef.current = Date.now()
      setIsRecording(true)
      return true
    } catch (err) {
      console.error('startRecording error', err)
      Alert.alert('Recording error', 'Could not start recording. Please try again.')
      return false
    }
  }, [recorder])

  const stopRecording = useCallback(async (): Promise<Recording | null> => {
    if (!isRecording) return null
    try {
      const durationMs = Date.now() - startTimeRef.current
      await recorder.stop()

      // Poll for URI — may take a brief moment to flush on Android
      let uri: string | null = null
      for (let i = 0; i < 10; i++) {
        uri = recorder.uri ?? null
        if (uri) break
        await new Promise(r => setTimeout(r, 20))
      }

      setIsRecording(false)
      await AudioModule.setAudioModeAsync({ allowsRecording: false })

      if (!uri) return null
      return { uri, durationMs }
    } catch (err) {
      console.error('stopRecording error', err)
      setIsRecording(false)
      return null
    }
  }, [isRecording, recorder])

  const playRecording = useCallback(async (uri: string) => {
    try {
      if (playerRef.current) {
        playerRef.current.remove()
        playerRef.current = null
      }

      const player = createAudioPlayer({ uri })
      playerRef.current = player
      setIsPlaying(true)

      player.addListener('playbackStatusUpdate', (status: any) => {
        if (status.didJustFinish) {
          setIsPlaying(false)
          player.remove()
          playerRef.current = null
        }
      })

      await player.play()
    } catch (err) {
      console.error('playRecording error', err)
      setIsPlaying(false)
    }
  }, [])

  const stopPlayback = useCallback(async () => {
    if (playerRef.current) {
      await playerRef.current.pause()
      playerRef.current.remove()
      playerRef.current = null
    }
    setIsPlaying(false)
  }, [])

  const deleteRecording = useCallback(async (uri: string) => {
    try {
      await FileSystem.deleteAsync(uri, { idempotent: true })
    } catch {}
  }, [])

  function formatDuration(ms: number) {
    const s = Math.round(ms / 1000)
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  return {
    isRecording,
    isPlaying,
    startRecording,
    stopRecording,
    playRecording,
    stopPlayback,
    deleteRecording,
    formatDuration,
  }
}
