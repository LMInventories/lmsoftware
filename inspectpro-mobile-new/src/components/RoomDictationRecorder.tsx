/**
 * RoomDictationRecorder
 *
 * The clerk records the entire room in one continuous dictation session,
 * using pause/resume to take breaks. Each pause saves a clip immediately.
 * When finished, pressing "AI Transcribe" sends all clips to the backend,
 * which transcribes (Whisper) + fills fields (Claude) using item names as chapters.
 *
 * Flow:
 *   Idle → Record → (recording) → Pause → (paused, clip saved)
 *                              ↗ Resume ↗    ↓ AI Transcribe
 *                                          Fields filled in report_data
 *
 * Props:
 *   inspectionId    – for persisting clips to SQLite
 *   sectionKey      – room section key
 *   sectionName     – room display name
 *   items           – template items for this room (AI uses these as chapters)
 *   onTranscribed   – called with filled fields when AI transcription completes
 */
import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  View, Text, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert,
} from 'react-native'
import {
  useAudioRecorder as useExpoAudioRecorder,
  AudioModule,
  RecordingPresets,
} from 'expo-audio'
import * as FileSystem from 'expo-file-system'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { saveAudioRecording } from '../services/database'
import { api } from '../services/api'
import { colors, font, radius, spacing } from '../utils/theme'

export interface RoomDictationItem {
  id: string
  name: string       // display label (used by AI as chapter heading)
  hasCondition?: boolean
  hasDescription?: boolean
}

interface SavedClip {
  uri: string
  durationMs: number
}

interface Props {
  inspectionId: number
  sectionKey: string
  sectionName: string
  items: RoomDictationItem[]
  onTranscribed: (filled: Record<string, { description?: string; condition?: string }>) => void
  /** Show the AI Transcribe button (default true). Set false for human-typist mode
   *  where clips are just saved and synced — no on-device AI fill is performed. */
  showAiButton?: boolean
}

type Mode = 'idle' | 'recording' | 'paused' | 'transcribing'

const BG  = '#1a1a2e'
const FG  = '#ffffff'
const RED = '#e63946'
const GRN = '#22c55e'

export default function RoomDictationRecorder({
  inspectionId,
  sectionKey,
  sectionName,
  items,
  onTranscribed,
  showAiButton = true,
}: Props) {
  const insets   = useSafeAreaInsets()
  const recorder = useExpoAudioRecorder(RecordingPresets.HIGH_QUALITY)

  const [mode, setMode]         = useState<Mode>('idle')
  const [elapsed, setElapsed]   = useState(0)   // current clip seconds
  const [totalMs, setTotalMs]   = useState(0)   // total saved clip duration
  const [clips, setClips]       = useState<SavedClip[]>([])

  const timerRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number>(0)

  useEffect(() => () => { timerRef.current && clearInterval(timerRef.current) }, [])

  // ── Timer helpers ────────────────────────────────────────────────────────
  function startTimer() {
    setElapsed(0)
    startTimeRef.current = Date.now()
    timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)
  }
  function stopTimer() {
    timerRef.current && clearInterval(timerRef.current)
    timerRef.current = null
  }
  function fmt(ms: number) {
    const s = Math.round(ms / 1000)
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  }

  // ── Start/resume recording ────────────────────────────────────────────────
  async function handleRecord() {
    try {
      const { granted } = await AudioModule.requestRecordingPermissionsAsync()
      if (!granted) {
        Alert.alert('Permission required', 'Microphone access is needed.')
        return
      }
      await AudioModule.setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true })
      recorder.record()
      setMode('recording')
      startTimer()
    } catch (err) {
      console.error('[RoomDictation] start error:', err)
      Alert.alert('Recording error', 'Could not start recording. Please try again.')
    }
  }

  // ── Pause — saves clip immediately ───────────────────────────────────────
  async function handlePause() {
    if (mode !== 'recording') return
    stopTimer()

    try {
      const durationMs = Date.now() - startTimeRef.current
      await recorder.stop()

      // Poll for URI
      let uri: string | null = null
      for (let i = 0; i < 15; i++) {
        uri = recorder.uri ?? null
        if (uri) break
        await new Promise(r => setTimeout(r, 20))
      }

      await AudioModule.setAudioModeAsync({ allowsRecording: false })
      await new Promise(r => setTimeout(r, 300))  // let Android flush to disk

      if (!uri) {
        Alert.alert('Error', 'Could not save clip. Please try again.')
        setMode('paused')
        return
      }

      // Copy to documentDirectory for persistence
      const filename = `room_${inspectionId}_${sectionKey}_${Date.now()}.m4a`
      const destUri  = `${FileSystem.documentDirectory}${filename}`
      try {
        await FileSystem.copyAsync({ from: uri, to: destUri })
      } catch (e) {
        console.warn('[RoomDictation] copy failed, using cache uri:', e)
      }
      const finalUri = destUri

      // Persist to SQLite (item_key=undefined → room-level recording)
      try {
        saveAudioRecording(
          inspectionId,
          sectionKey,
          sectionName,
          undefined,   // item_key
          undefined,   // item_name
          sectionName, // label = room name
          finalUri,
          durationMs,
        )
      } catch (e) {
        console.warn('[RoomDictation] SQLite save failed:', e)
      }

      const newClip: SavedClip = { uri: finalUri, durationMs }
      setClips(prev => [...prev, newClip])
      setTotalMs(prev => prev + durationMs)
      setElapsed(0)
      setMode('paused')
    } catch (err) {
      console.error('[RoomDictation] pause error:', err)
      setMode('paused')
    }
  }

  // ── Clear all clips ───────────────────────────────────────────────────────
  function handleClear() {
    Alert.alert(
      'Clear recording?',
      'All clips for this room will be discarded.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear', style: 'destructive',
          onPress: () => {
            setClips([])
            setTotalMs(0)
            setElapsed(0)
            setMode('idle')
          },
        },
      ]
    )
  }

  // ── AI transcribe all clips ───────────────────────────────────────────────
  const handleTranscribe = useCallback(async () => {
    if (clips.length === 0) return
    setMode('transcribing')

    try {
      // Read each clip as base64
      const clipPayloads = await Promise.all(
        clips.map(async (clip) => {
          const b64 = await FileSystem.readAsStringAsync(clip.uri, {
            encoding: FileSystem.EncodingType.Base64,
          })
          return { audio: b64, mimeType: 'audio/m4a' }
        })
      )

      const response = await api.transcribeRoom({
        clips:       clipPayloads,
        sectionName,
        sectionKey,
        items:       items.map(it => ({
          id:             it.id,
          name:           it.name,
          hasCondition:   it.hasCondition !== false,
          hasDescription: it.hasDescription !== false,
        })),
      })

      const { filled } = response.data as {
        transcript: string
        filled: Record<string, { description?: string; condition?: string }>
      }

      const count = Object.keys(filled).length
      if (count === 0) {
        Alert.alert('Nothing filled', 'AI could not match any dictation to room items. Please check the transcript.')
        setMode('paused')
        return
      }

      onTranscribed(filled)
      // Reset recorder after successful transcription
      setClips([])
      setTotalMs(0)
      setElapsed(0)
      setMode('idle')
    } catch (err: any) {
      console.error('[RoomDictation] transcribe error:', err)
      const msg = err.response?.data?.error || err.message || 'Transcription failed'
      Alert.alert('AI Error', msg)
      setMode('paused')
    }
  }, [clips, sectionName, sectionKey, items, onTranscribed])

  // ── Render ────────────────────────────────────────────────────────────────
  const isRecording     = mode === 'recording'
  const isPaused        = mode === 'paused'
  const isTranscribing  = mode === 'transcribing'
  const hasClips        = clips.length > 0
  const clipCountLabel  = hasClips
    ? `${clips.length} clip${clips.length !== 1 ? 's' : ''} · ${fmt(totalMs)}`
    : 'No clips yet'

  return (
    <View style={[bar.wrap, { paddingBottom: Math.max(insets.bottom, 10) }]}>
      {/* Title row */}
      <View style={bar.titleRow}>
        <Text style={bar.title}>🎙 Room Dictation</Text>
        <Text style={bar.clipCount}>{clipCountLabel}</Text>
        {(isPaused || isRecording) && hasClips && (
          <TouchableOpacity style={bar.clearBtn} onPress={handleClear}>
            <Text style={bar.clearBtnText}>Clear</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Main controls row */}
      <View style={bar.row}>
        {/* Left: Record / Pause button */}
        <View style={bar.leftSection}>
          {isTranscribing ? (
            <View style={[bar.recBtn, bar.recBtnSaving]}>
              <ActivityIndicator color={FG} />
            </View>
          ) : isRecording ? (
            <TouchableOpacity style={[bar.recBtn, bar.recBtnLive]} onPress={handlePause}>
              {/* Pause icon: two bars */}
              <View style={bar.pauseIcon}>
                <View style={bar.pauseBar} />
                <View style={bar.pauseBar} />
              </View>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              style={[bar.recBtn, isTranscribing && bar.disabled]}
              onPress={handleRecord}
              disabled={isTranscribing}
            >
              <View style={bar.recDot} />
            </TouchableOpacity>
          )}
          <Text style={bar.recLabel}>
            {isTranscribing
              ? 'Processing…'
              : isRecording
              ? fmt(elapsed * 1000)
              : isPaused
              ? 'Resume'
              : 'Record'}
          </Text>
        </View>

        {/* Centre: status text */}
        <View style={bar.centreSection}>
          {isTranscribing ? (
            <>
              <Text style={bar.statusTitle}>AI filling room fields…</Text>
              <Text style={bar.statusSub}>{sectionName}</Text>
            </>
          ) : isRecording ? (
            <>
              <Text style={bar.statusTitle}>Recording {sectionName}</Text>
              <Text style={bar.statusSub}>Press pause to save clip</Text>
            </>
          ) : isPaused ? (
            <>
              <Text style={bar.statusTitle}>{sectionName}</Text>
              <Text style={bar.statusSub}>
                {showAiButton ? 'Press resume or transcribe when ready' : 'Press resume or sync when finished'}
              </Text>
            </>
          ) : (
            <>
              <Text style={bar.statusTitle}>{sectionName}</Text>
              <Text style={bar.statusSub}>Press record to start dictation</Text>
            </>
          )}
        </View>

        {/* Right: AI Transcribe button — hidden for human typist mode */}
        {showAiButton && (
          <View style={bar.rightSection}>
            <TouchableOpacity
              style={[bar.aiBtn, (!hasClips || isRecording || isTranscribing) && bar.disabled]}
              onPress={handleTranscribe}
              disabled={!hasClips || isRecording || isTranscribing}
            >
              <Text style={bar.aiBtnIcon}>✨</Text>
              <Text style={bar.aiBtnLabel}>Transcribe</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* Hint line */}
      {mode === 'idle' && (
        <Text style={bar.hint}>
          {showAiButton
            ? 'Say each item name then describe it: "Door and Frame… white painted door… good condition… Ceiling…"'
            : 'Record your dictation for the typist. Pause between clips if needed — clips sync automatically.'}
        </Text>
      )}
    </View>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────
const bar = StyleSheet.create({
  wrap: {
    backgroundColor: BG,
    paddingTop: 10,
    paddingHorizontal: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.08)',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: 10,
  },
  title: {
    fontSize: font.sm,
    fontWeight: '700',
    color: FG,
    flex: 1,
  },
  clipCount: {
    fontSize: font.xs,
    color: 'rgba(255,255,255,0.5)',
  },
  clearBtn: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    backgroundColor: 'rgba(239,68,68,0.2)',
    borderWidth: 1,
    borderColor: 'rgba(239,68,68,0.4)',
  },
  clearBtnText: {
    fontSize: font.xs,
    color: '#f87171',
    fontWeight: '600',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingBottom: 6,
  },
  leftSection: {
    alignItems: 'center',
    gap: 4,
    width: 64,
  },
  centreSection: {
    flex: 1,
    alignItems: 'center',
  },
  rightSection: {
    alignItems: 'center',
    width: 64,
  },
  // Record button
  recBtn: {
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: RED,
    alignItems: 'center', justifyContent: 'center',
    shadowColor: RED,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 8,
    elevation: 6,
  },
  recBtnLive:   { backgroundColor: '#f87171' },
  recBtnSaving: { backgroundColor: '#6b7280' },
  recDot:  { width: 20, height: 20, borderRadius: 10, backgroundColor: FG },
  pauseIcon: { flexDirection: 'row', gap: 4 },
  pauseBar:  { width: 4, height: 18, borderRadius: 2, backgroundColor: FG },
  recLabel: {
    fontSize: 9, color: 'rgba(255,255,255,0.6)', fontWeight: '700',
    letterSpacing: 0.3, textTransform: 'uppercase',
  },
  // Status text
  statusTitle: { fontSize: font.sm, fontWeight: '700', color: FG, textAlign: 'center' },
  statusSub:   { fontSize: font.xs, color: 'rgba(255,255,255,0.45)', textAlign: 'center', marginTop: 2 },
  // AI transcribe button
  aiBtn: {
    alignItems: 'center', gap: 2,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: radius.md,
    backgroundColor: 'rgba(99,102,241,0.3)',
    borderWidth: 1,
    borderColor: 'rgba(99,102,241,0.6)',
  },
  aiBtnIcon:  { fontSize: 18 },
  aiBtnLabel: { fontSize: 9, color: 'rgba(255,255,255,0.7)', fontWeight: '700', textTransform: 'uppercase' },
  disabled:   { opacity: 0.3 },
  // Hint
  hint: {
    fontSize: font.xs,
    color: 'rgba(255,255,255,0.3)',
    textAlign: 'center',
    paddingBottom: 6,
    fontStyle: 'italic',
    lineHeight: 16,
  },
})
