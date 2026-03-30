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

      // prepareToRecordAsync must be called before every record() call —
      // the hook creates the recorder but does not auto-prepare it.
      await recorder.prepareToRecordAsync()
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

      // stop() is async — awaiting it ensures the native layer has finished
      // writing the file before we read recorder.uri.
      await recorder.stop()

      // URI should be available immediately after stop() resolves.
      // Short safety poll (10 × 50 ms = 500 ms) covers any edge-case native lag.
      let uri: string | null = recorder.uri ?? null
      for (let i = 0; i < 10 && !uri; i++) {
        await new Promise(r => setTimeout(r, 50))
        uri = recorder.uri ?? null
      }

      setIsRecording(false)
      await AudioModule.setAudioModeAsync({ allowsRecording: false })

      if (!uri) {
        console.warn('[useAudioRecorder] URI not available after stop — recording lost')
        return null
      }
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
