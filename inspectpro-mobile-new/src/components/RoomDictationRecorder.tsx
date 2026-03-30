/**
 * RoomDictationRecorder
 *
 * Bottom overlay for AI-by-Room mode.
 *
 * Layout:
 *   [ 🎵 N clips ]  [  ●  Record / ❚❚ Pause  ]  [ ✨ AI ]
 *
 * Clips badge (left) — taps to open a playback modal showing all recorded
 * clips with individual play buttons and swipe-to-delete.
 *
 * Record/Pause (centre) — starts a clip on press; press again to pause and
 * save the clip to the list. Resume adds another clip.
 *
 * AI Transcribe (right) — sends all saved clips to the backend in one go.
 * The button pulses (indigo) while transcribing.
 *
 * Props:
 *   inspectionId  – for persisting clips to SQLite
 *   sectionKey    – room section key
 *   sectionName   – room display name
 *   items         – template items (AI uses names as chapters)
 *   onTranscribed – called with { itemId: { description?, condition? } } on success
 *   showAiButton  – set false for human-typist mode (clips saved, no AI fill)
 */
import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  View, Text, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, Animated,
  Modal, ScrollView, Pressable,
} from 'react-native'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import {
  useAudioRecorder as useExpoAudioRecorder,
  AudioModule,
  RecordingPresets,
  createAudioPlayer,
} from 'expo-audio'
import * as FileSystem from 'expo-file-system'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import SwipeableRow from './SwipeableRow'
import { saveAudioRecording } from '../services/database'
import { api } from '../services/api'
import { colors, font, radius, spacing } from '../utils/theme'

export interface RoomDictationItem {
  id: string
  name: string
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
  showAiButton?: boolean
}

type Mode = 'idle' | 'recording' | 'paused' | 'transcribing'

const BG  = '#1a1a2e'
const FG  = '#ffffff'
const RED = '#e63946'

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

  const [mode, setMode]       = useState<Mode>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [totalMs, setTotalMs] = useState(0)
  const [clips, setClips]     = useState<SavedClip[]>([])

  // Playback modal
  const [modalVisible, setModalVisible] = useState(false)
  const [playingUri, setPlayingUri]     = useState<string | null>(null)
  const playerRef = useRef<ReturnType<typeof createAudioPlayer> | null>(null)

  const timerRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number>(0)

  // Pulse animation — runs while transcribing
  const pulseAnim = useRef(new Animated.Value(1)).current
  const pulseLoop = useRef<Animated.CompositeAnimation | null>(null)

  useEffect(() => {
    if (mode === 'transcribing') {
      pulseLoop.current = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 1.15, duration: 650, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1.00, duration: 650, useNativeDriver: true }),
        ])
      )
      pulseLoop.current.start()
    } else {
      pulseLoop.current?.stop()
      pulseAnim.setValue(1)
    }
    return () => { pulseLoop.current?.stop() }
  }, [mode])

  useEffect(() => () => {
    timerRef.current && clearInterval(timerRef.current)
    playerRef.current?.remove()
  }, [])

  // ── Timer ─────────────────────────────────────────────────────────────────
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

  // ── Record ────────────────────────────────────────────────────────────────
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

  // ── Pause — saves clip ────────────────────────────────────────────────────
  async function handlePause() {
    if (mode !== 'recording') return
    stopTimer()
    try {
      const durationMs = Date.now() - startTimeRef.current
      await recorder.stop()

      let uri: string | null = null
      for (let i = 0; i < 15; i++) {
        uri = recorder.uri ?? null
        if (uri) break
        await new Promise(r => setTimeout(r, 20))
      }

      await AudioModule.setAudioModeAsync({ allowsRecording: false })
      await new Promise(r => setTimeout(r, 300))

      if (!uri) {
        Alert.alert('Error', 'Could not save clip. Please try again.')
        setMode('paused')
        return
      }

      const filename = `room_${inspectionId}_${sectionKey}_${Date.now()}.m4a`
      const destUri  = `${FileSystem.documentDirectory}${filename}`
      try { await FileSystem.copyAsync({ from: uri, to: destUri }) } catch {}
      const finalUri = destUri

      try {
        saveAudioRecording(
          inspectionId, sectionKey, sectionName,
          undefined, undefined, sectionName, finalUri, durationMs,
        )
      } catch {}

      setClips(prev => [...prev, { uri: finalUri, durationMs }])
      setTotalMs(prev => prev + durationMs)
      setElapsed(0)
      setMode('paused')
    } catch (err) {
      console.error('[RoomDictation] pause error:', err)
      setMode('paused')
    }
  }

  // ── Delete clip ───────────────────────────────────────────────────────────
  function handleDeleteClip(uri: string) {
    if (playingUri === uri) {
      playerRef.current?.remove()
      playerRef.current = null
      setPlayingUri(null)
    }
    setClips(prev => {
      const removed = prev.find(c => c.uri === uri)
      if (removed) setTotalMs(t => t - removed.durationMs)
      return prev.filter(c => c.uri !== uri)
    })
  }

  // ── Clear all ─────────────────────────────────────────────────────────────
  function handleClear() {
    Alert.alert(
      'Clear all clips?',
      'All clips for this room will be discarded.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Clear', style: 'destructive', onPress: () => {
          playerRef.current?.remove()
          playerRef.current = null
          setPlayingUri(null)
          setClips([])
          setTotalMs(0)
          setElapsed(0)
          setMode('idle')
        }},
      ]
    )
  }

  // ── Playback (modal) ──────────────────────────────────────────────────────
  async function handlePlayClip(uri: string) {
    // Tap again → stop
    if (playingUri === uri) {
      await playerRef.current?.pause()
      playerRef.current?.remove()
      playerRef.current = null
      setPlayingUri(null)
      return
    }
    // Stop previous
    if (playerRef.current) {
      playerRef.current.remove()
      playerRef.current = null
    }
    try {
      await AudioModule.setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true })
      const player = createAudioPlayer({ uri })
      playerRef.current = player
      setPlayingUri(uri)
      player.addListener('playbackStatusUpdate', (status: any) => {
        if (status.didJustFinish) {
          player.remove()
          playerRef.current = null
          setPlayingUri(null)
        }
      })
      await player.play()
    } catch (err) {
      console.error('[RoomDictation] playback error:', err)
      setPlayingUri(null)
    }
  }

  // ── AI Transcribe ─────────────────────────────────────────────────────────
  const handleTranscribe = useCallback(async () => {
    if (clips.length === 0) return
    setMode('transcribing')
    try {
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
        items: items.map(it => ({
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
        Alert.alert('Nothing filled', 'AI could not match dictation to room items. Please try again.')
        setMode('paused')
        return
      }

      onTranscribed(filled)
      setClips([])
      setTotalMs(0)
      setElapsed(0)
      setMode('idle')
    } catch (err: any) {
      console.error('[RoomDictation] transcribe error:', err)
      Alert.alert('AI Error', err.response?.data?.error || err.message || 'Transcription failed')
      setMode('paused')
    }
  }, [clips, sectionName, sectionKey, items, onTranscribed])

  // ── Derived state ─────────────────────────────────────────────────────────
  const isRecording    = mode === 'recording'
  const isPaused       = mode === 'paused'
  const isTranscribing = mode === 'transcribing'
  const hasClips       = clips.length > 0

  // ── Status line below the row ─────────────────────────────────────────────
  function statusText() {
    if (isTranscribing) return `AI filling ${sectionName}…`
    if (isRecording)    return `Recording ${sectionName} — pause to save clip`
    if (isPaused && hasClips) {
      const tip = showAiButton ? 'tap ✨ to transcribe' : 'clips saved'
      return `${clips.length} clip${clips.length !== 1 ? 's' : ''} saved · ${fmt(totalMs)} total · ${tip}`
    }
    if (mode === 'idle') {
      return showAiButton
        ? 'Say each item name then describe it · pause to save a clip'
        : 'Record your dictation · pause to save clips'
    }
    return ''
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <View style={[bar.wrap, { paddingBottom: Math.max(insets.bottom, 12) }]}>

      {/* ── Three-column row ─────────────────────────────────────────── */}
      <View style={bar.row}>

        {/* LEFT: Clip count badge */}
        <TouchableOpacity
          style={[bar.clipsBtn, !hasClips && bar.clipsBtnEmpty]}
          onPress={() => hasClips && setModalVisible(true)}
          disabled={!hasClips || isTranscribing}
          activeOpacity={0.7}
        >
          <Text style={bar.clipsIcon}>🎵</Text>
          <Text style={[bar.clipsCount, !hasClips && bar.clipsDimmed]}>
            {clips.length}
          </Text>
          <Text style={[bar.clipsLabel, !hasClips && bar.clipsDimmed]}>
            {clips.length === 1 ? 'clip' : 'clips'}
          </Text>
        </TouchableOpacity>

        {/* CENTRE: Record / Pause / Transcribing button */}
        <View style={bar.centreSection}>
          <Animated.View style={{ transform: [{ scale: isTranscribing ? pulseAnim : 1 }] }}>
            {isTranscribing ? (
              <View style={[bar.recBtn, bar.recBtnTranscribing]}>
                <ActivityIndicator color={FG} size="large" />
              </View>
            ) : isRecording ? (
              <TouchableOpacity style={[bar.recBtn, bar.recBtnLive]} onPress={handlePause}>
                <View style={bar.pauseIcon}>
                  <View style={bar.pauseBar} />
                  <View style={bar.pauseBar} />
                </View>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={bar.recBtn}
                onPress={handleRecord}
                disabled={isTranscribing}
              >
                <View style={bar.recDot} />
              </TouchableOpacity>
            )}
          </Animated.View>
          <Text style={bar.recLabel}>
            {isTranscribing ? 'Transcribing…'
              : isRecording  ? fmt(elapsed * 1000)
              : isPaused     ? 'Resume'
              : 'Record'}
          </Text>
        </View>

        {/* RIGHT: AI Transcribe button (or spacer if human mode) */}
        {showAiButton ? (
          <TouchableOpacity
            style={[bar.aiBtn, (!hasClips || isRecording || isTranscribing) && bar.disabled]}
            onPress={handleTranscribe}
            disabled={!hasClips || isRecording || isTranscribing}
            activeOpacity={0.7}
          >
            <Text style={bar.aiBtnIcon}>✨</Text>
            <Text style={bar.aiBtnLabel}>Transcribe</Text>
          </TouchableOpacity>
        ) : (
          // Spacer to keep layout balanced in human mode
          <View style={bar.aiBtn} />
        )}

      </View>

      {/* Status / hint */}
      <Text style={bar.status} numberOfLines={2}>{statusText()}</Text>

      {/* Clear button — only shown when paused with clips */}
      {isPaused && hasClips && !isTranscribing && (
        <TouchableOpacity style={bar.clearBtn} onPress={handleClear}>
          <Text style={bar.clearBtnText}>Clear all clips</Text>
        </TouchableOpacity>
      )}

      {/* ── Recordings playback modal ─────────────────────────────── */}
      <Modal
        visible={modalVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setModalVisible(false)}
      >
        <GestureHandlerRootView style={{ flex: 1 }}>
          <Pressable style={modal.overlay} onPress={() => setModalVisible(false)}>
            <Pressable style={modal.sheet} onPress={e => e.stopPropagation()}>

              {/* Header */}
              <View style={modal.header}>
                <Text style={modal.title}>
                  {sectionName} — {clips.length} clip{clips.length !== 1 ? 's' : ''} · {fmt(totalMs)}
                </Text>
                <TouchableOpacity onPress={() => setModalVisible(false)} style={modal.closeBtn}>
                  <Text style={modal.closeBtnText}>✕</Text>
                </TouchableOpacity>
              </View>

              <Text style={modal.hint}>Swipe a clip to delete it</Text>

              <ScrollView style={modal.list} showsVerticalScrollIndicator={false}>
                {clips.map((clip, i) => (
                  <SwipeableRow
                    key={clip.uri}
                    actions={[{
                      icon: '🗑',
                      label: 'Delete',
                      bg: colors.dangerLight,
                      onPress: () => handleDeleteClip(clip.uri),
                    }]}
                  >
                    <View style={modal.clipRow}>
                      <TouchableOpacity
                        style={[modal.playBtn, playingUri === clip.uri && modal.playBtnActive]}
                        onPress={() => handlePlayClip(clip.uri)}
                      >
                        <Text style={modal.playBtnText}>
                          {playingUri === clip.uri ? '⏸' : '▶'}
                        </Text>
                      </TouchableOpacity>

                      <View style={modal.clipInfo}>
                        <Text style={modal.clipName}>Clip {i + 1}</Text>
                        <Text style={modal.clipDuration}>{fmt(clip.durationMs)}</Text>
                      </View>

                      {playingUri === clip.uri && (
                        <ActivityIndicator size="small" color={colors.accent} />
                      )}
                    </View>
                  </SwipeableRow>
                ))}
              </ScrollView>

            </Pressable>
          </Pressable>
        </GestureHandlerRootView>
      </Modal>

    </View>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────────
const bar = StyleSheet.create({
  wrap: {
    backgroundColor: BG,
    paddingTop: 12,
    paddingHorizontal: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.08)',
  },

  // Three-column row
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    paddingBottom: 8,
  },

  // LEFT: clip count badge
  clipsBtn: {
    width: 68,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    paddingVertical: 8,
    paddingHorizontal: 6,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: 'rgba(99,102,241,0.5)',
    backgroundColor: 'rgba(99,102,241,0.15)',
  },
  clipsBtnEmpty: {
    borderColor: 'rgba(255,255,255,0.1)',
    backgroundColor: 'transparent',
  },
  clipsIcon:  { fontSize: 18 },
  clipsCount: { fontSize: font.lg, fontWeight: '800', color: FG, lineHeight: 22 },
  clipsLabel: { fontSize: 9, color: 'rgba(255,255,255,0.6)', fontWeight: '600', textTransform: 'uppercase' },
  clipsDimmed:{ color: 'rgba(255,255,255,0.25)' },

  // CENTRE: record button
  centreSection: {
    flex: 1,
    alignItems: 'center',
    gap: 6,
  },
  recBtn: {
    width: 62, height: 62, borderRadius: 31,
    backgroundColor: RED,
    alignItems: 'center', justifyContent: 'center',
    shadowColor: RED,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 8,
    elevation: 6,
  },
  recBtnLive:         { backgroundColor: '#f87171' },
  recBtnTranscribing: { backgroundColor: '#6366f1' },
  recDot:    { width: 22, height: 22, borderRadius: 11, backgroundColor: FG },
  pauseIcon: { flexDirection: 'row', gap: 5 },
  pauseBar:  { width: 5, height: 20, borderRadius: 2, backgroundColor: FG },
  recLabel:  {
    fontSize: 9, color: 'rgba(255,255,255,0.6)', fontWeight: '700',
    letterSpacing: 0.5, textTransform: 'uppercase',
  },

  // RIGHT: AI button
  aiBtn: {
    width: 68,
    alignItems: 'center',
    gap: 4,
    paddingVertical: 8,
    paddingHorizontal: 6,
    borderRadius: radius.md,
    backgroundColor: 'rgba(99,102,241,0.25)',
    borderWidth: 1,
    borderColor: 'rgba(99,102,241,0.5)',
  },
  aiBtnIcon:  { fontSize: 20 },
  aiBtnLabel: { fontSize: 9, color: 'rgba(255,255,255,0.7)', fontWeight: '700', textTransform: 'uppercase' },
  disabled:   { opacity: 0.3 },

  // Status + clear
  status: {
    fontSize: font.xs,
    color: 'rgba(255,255,255,0.4)',
    textAlign: 'center',
    paddingBottom: 4,
    fontStyle: 'italic',
    lineHeight: 16,
  },
  clearBtn: {
    alignSelf: 'center',
    paddingHorizontal: 14,
    paddingVertical: 5,
    borderRadius: 8,
    backgroundColor: 'rgba(239,68,68,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(239,68,68,0.3)',
    marginBottom: 4,
  },
  clearBtnText: { fontSize: font.xs, color: '#f87171', fontWeight: '600' },
})

const modal = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  sheet: {
    backgroundColor: '#1e1e2e',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingTop: 16,
    paddingBottom: 32,
    maxHeight: '70%',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    marginBottom: 4,
  },
  title: {
    flex: 1,
    fontSize: font.md,
    fontWeight: '700',
    color: '#fff',
  },
  closeBtn: {
    width: 30, height: 30, borderRadius: 15,
    backgroundColor: 'rgba(255,255,255,0.1)',
    alignItems: 'center', justifyContent: 'center',
  },
  closeBtnText: { fontSize: 14, color: '#fff', fontWeight: '700' },
  hint: {
    fontSize: font.xs,
    color: 'rgba(255,255,255,0.3)',
    paddingHorizontal: spacing.lg,
    marginBottom: 10,
    fontStyle: 'italic',
  },
  list: {
    paddingHorizontal: spacing.md,
  },
  clipRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: radius.md,
    padding: spacing.sm,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
  },
  playBtn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: 'rgba(99,102,241,0.3)',
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'rgba(99,102,241,0.5)',
  },
  playBtnActive: {
    backgroundColor: 'rgba(99,102,241,0.6)',
  },
  playBtnText: { fontSize: 16, color: '#fff' },
  clipInfo: { flex: 1 },
  clipName: { fontSize: font.sm, fontWeight: '600', color: '#fff' },
  clipDuration: { fontSize: font.xs, color: 'rgba(255,255,255,0.45)', marginTop: 2 },
})
