import { useState, useRef, useCallback } from 'react'
import { Audio } from 'expo-av'
import * as FileSystem from 'expo-file-system'
import { Alert } from 'react-native'

export interface Recording {
  uri: string
  durationMs: number
  transcription?: string
}

export function useAudioRecorder() {
  const recordingRef = useRef<Audio.Recording | null>(null)
  const [isRecording, setIsRecording]   = useState(false)
  const [isPlaying, setIsPlaying]       = useState(false)
  const soundRef = useRef<Audio.Sound | null>(null)

  const startRecording = useCallback(async (): Promise<boolean> => {
    try {
      const { status } = await Audio.requestPermissionsAsync()
      if (status !== 'granted') {
        Alert.alert('Permission required', 'Microphone access is needed for audio dictation.')
        return false
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      })

      const rec = new Audio.Recording()
      await rec.prepareToRecordAsync(Audio.RecordingOptionsPresets.HIGH_QUALITY)
      await rec.startAsync()
      recordingRef.current = rec
      setIsRecording(true)
      return true
    } catch (err) {
      console.error('startRecording error', err)
      Alert.alert('Recording error', 'Could not start recording. Please try again.')
      return false
    }
  }, [])

  const stopRecording = useCallback(async (): Promise<Recording | null> => {
    if (!recordingRef.current) return null
    try {
      await recordingRef.current.stopAndUnloadAsync()
      const status = await recordingRef.current.getStatusAsync()
      const uri    = recordingRef.current.getURI()
      recordingRef.current = null
      setIsRecording(false)

      await Audio.setAudioModeAsync({ allowsRecordingIOS: false })

      if (!uri) return null
      return { uri, durationMs: status.durationMillis ?? 0 }
    } catch (err) {
      console.error('stopRecording error', err)
      setIsRecording(false)
      return null
    }
  }, [])

  const playRecording = useCallback(async (uri: string) => {
    try {
      if (soundRef.current) {
        await soundRef.current.unloadAsync()
        soundRef.current = null
      }
      const { sound } = await Audio.Sound.createAsync({ uri })
      soundRef.current = sound
      setIsPlaying(true)
      sound.setOnPlaybackStatusUpdate((s) => {
        if (s.isLoaded && s.didJustFinish) setIsPlaying(false)
      })
      await sound.playAsync()
    } catch (err) {
      console.error('playRecording error', err)
      setIsPlaying(false)
    }
  }, [])

  const stopPlayback = useCallback(async () => {
    if (soundRef.current) {
      await soundRef.current.stopAsync()
      await soundRef.current.unloadAsync()
      soundRef.current = null
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
