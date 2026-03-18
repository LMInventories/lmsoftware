/**
 * HumanTypistRecorder
 *
 * Recording flow:
 *   Record → (recording) → Pause → clip saved immediately → idle
 *   Record → (recording) → Stop  → clip saved immediately → idle
 *
 * Each pause/stop creates one clip, stored immediately in the parent store.
 * Clips are grouped by section in the drawer and can be played individually.
 * Full sequential playback plays all clips in order.
 */
import React, { useState, useRef, useEffect } from 'react'
import {
  View, Text, TouchableOpacity, StyleSheet, Modal,
  ScrollView, Alert, ActivityIndicator,
} from 'react-native'
import { Audio } from 'expo-av'
import * as FileSystem from 'expo-file-system'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { saveAudioRecording, deleteAudioRecording } from '../services/database'
import { colors, font, radius, spacing } from '../utils/theme'

export interface HumanRecording {
  id: string
  sqliteId?: number      // row id in audio_recordings table
  uri: string
  durationMs: number
  sectionKey: string
  sectionName: string
  itemKey?: string
  itemName?: string
  label: string
  createdAt: string
}

interface Props {
  inspectionId: number
  currentSectionKey: string
  currentSectionName: string
  currentItemKey?: string
  currentItemName?: string
  recordings: HumanRecording[]
  onRecordingAdded: (rec: HumanRecording) => void
  onRecordingDeleted: (id: string) => void
}

type Mode = 'idle' | 'recording' | 'playing'

// Android-compatible recording options
const REC_OPTIONS = {
  android: {
    extension: '.m4a',
    outputFormat: Audio.AndroidOutputFormat.MPEG_4,
    audioEncoder: Audio.AndroidAudioEncoder.AAC,
    sampleRate: 44100,
    numberOfChannels: 1,
    bitRate: 128000,
  },
  ios: {
    extension: '.m4a',
    outputFormat: Audio.IOSOutputFormat.MPEG4AAC,
    audioQuality: Audio.IOSAudioQuality.MEDIUM,
    sampleRate: 44100,
    numberOfChannels: 1,
    bitRate: 128000,
    linearPCMBitDepth: 16 as const,
    linearPCMIsBigEndian: false,
    linearPCMIsFloat: false,
  },
  web: {},
}

export default function HumanTypistRecorder({
  inspectionId,
  currentSectionKey,
  currentSectionName,
  currentItemKey,
  currentItemName,
  recordings,
  onRecordingAdded,
  onRecordingDeleted,
}: Props) {
  const insets = useSafeAreaInsets()

  const [mode, setMode]           = useState<Mode>('idle')
  const [elapsed, setElapsed]     = useState(0)
  const [playPos, setPlayPos]     = useState(0)
  const [playDur, setPlayDur]     = useState(0)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [saving, setSaving]       = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const recRef   = useRef<Audio.Recording | null>(null)
  const soundRef = useRef<Audio.Sound | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // Queue for sequential playback
  const playQueueRef = useRef<HumanRecording[]>([])
  const playQueueIdx = useRef(0)

  useEffect(() => () => {
    timerRef.current && clearInterval(timerRef.current)
    soundRef.current?.unloadAsync()
  }, [])

  // ── Helpers ──────────────────────────────────────────────────────────────
  function fmt(ms: number) {
    const s = Math.round(ms / 1000)
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  }
  function currentLabel() {
    return currentItemName
      ? `${currentSectionName} — ${currentItemName}`
      : currentSectionName
  }
  function startTimer() {
    setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)
  }
  function stopTimer() {
    timerRef.current && clearInterval(timerRef.current)
    timerRef.current = null
  }

  // ── Save a clip immediately ───────────────────────────────────────────────
  async function finaliseClip(uri: string, durationMs: number) {
    if (!uri) {
      console.warn('[HumanRecorder] finaliseClip: uri is empty')
      return
    }

    // Verify file exists
    try {
      const info = await FileSystem.getInfoAsync(uri)
      if (!info.exists || (info as any).size === 0) {
        console.warn('[HumanRecorder] file missing or empty:', uri)
        return
      }
    } catch (e) {
      console.warn('[HumanRecorder] could not stat file:', e)
      return
    }

    // Copy to documentDirectory — persists across app restarts and cache clears
    const filename = `rec_${inspectionId}_${Date.now()}.m4a`
    const destUri  = `${FileSystem.documentDirectory}${filename}`
    try {
      await FileSystem.copyAsync({ from: uri, to: destUri })
    } catch (e) {
      console.warn('[HumanRecorder] copy failed, using cache uri:', e)
    }

    const finalUri   = destUri
    const now        = new Date().toISOString()
    const dur        = durationMs > 0 ? durationMs : elapsed * 1000
    const label      = currentLabel()

    // Persist to SQLite so recordings survive app restarts
    let sqliteId: number | undefined
    try {
      await saveAudioRecording(
        inspectionId,
        currentSectionKey,
        currentSectionName,
        currentItemKey,
        currentItemName,
        label,
        finalUri,
        dur,
      )
      // Get the inserted id
      const { getAudioRecordings } = await import('../services/database') as any
      const all = await getAudioRecordings(inspectionId)
      sqliteId = all[0]?.id  // most recent first
    } catch (e) {
      console.warn('[HumanRecorder] SQLite save failed:', e)
    }

    const rec: HumanRecording = {
      id:          `rec_${Date.now()}`,
      sqliteId,
      uri:         finalUri,
      durationMs:  dur,
      sectionKey:  currentSectionKey,
      sectionName: currentSectionName,
      itemKey:     currentItemKey,
      itemName:    currentItemName,
      label,
      createdAt:   now,
    }
    console.log('[HumanRecorder] clip saved:', rec.label, rec.durationMs, 'ms', finalUri)
    onRecordingAdded(rec)
  }

  // ── Record ────────────────────────────────────────────────────────────────
  async function handleRecord() {
    if (mode === 'playing') await stopPlayback()

    try {
      const { status } = await Audio.requestPermissionsAsync()
      if (status !== 'granted') {
        Alert.alert('Permission required', 'Microphone access is needed.')
        return
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true })

      const rec = new Audio.Recording()
      await rec.prepareToRecordAsync(REC_OPTIONS)
      await rec.startAsync()
      recRef.current = rec
      setMode('recording')
      startTimer()
    } catch (err) {
      console.error('[HumanRecorder] start error:', err)
      Alert.alert('Recording error', 'Could not start recording. Please try again.')
    }
  }

  // ── Pause — saves clip immediately ───────────────────────────────────────
  async function handlePause() {
    if (!recRef.current) return
    setSaving(true)
    stopTimer()

    try {
      // Read URI and status BEFORE unloading
      const uri    = recRef.current.getURI() ?? ''
      const status = await recRef.current.getStatusAsync()
      const dur    = status.isLoaded ? (status.durationMillis ?? 0) : 0

      await recRef.current.stopAndUnloadAsync()
      recRef.current = null
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false })

      // Small delay to let Android flush the file to disk
      await new Promise(r => setTimeout(r, 300))

      await finaliseClip(uri, dur)
    } catch (err) {
      console.error('[HumanRecorder] pause error:', err)
    } finally {
      setElapsed(0)
      setMode('idle')
      setSaving(false)
    }
  }

  // ── Stop — alias for pause (same outcome: clip saved, back to idle) ───────
  const handleStop = handlePause

  // ── Play single clip ──────────────────────────────────────────────────────
  async function playClip(rec: HumanRecording) {
    if (soundRef.current) {
      await soundRef.current.unloadAsync()
      soundRef.current = null
    }
    if (playingId === rec.id) {
      setPlayingId(null)
      setPlayPos(0)
      setMode('idle')
      return
    }

    try {
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true })
      const { sound } = await Audio.Sound.createAsync(
        { uri: rec.uri },
        { shouldPlay: true },
        (s) => {
          if (s.isLoaded) {
            setPlayPos(s.positionMillis ?? 0)
            setPlayDur(s.durationMillis ?? rec.durationMs)
            if (s.didJustFinish) {
              // Advance queue if playing all
              if (playQueueRef.current.length > 0) {
                playQueueIdx.current += 1
                if (playQueueIdx.current < playQueueRef.current.length) {
                  playClip(playQueueRef.current[playQueueIdx.current])
                  return
                } else {
                  playQueueRef.current = []
                  playQueueIdx.current = 0
                }
              }
              setPlayingId(null)
              setPlayPos(0)
              setMode('idle')
            }
          }
        }
      )
      soundRef.current = sound
      setPlayingId(rec.id)
      setPlayDur(rec.durationMs)
      setMode('playing')
    } catch (err) {
      console.error('[HumanRecorder] playClip error:', err)
    }
  }

  // ── Play all clips in sequence ────────────────────────────────────────────
  async function playAll() {
    if (recordings.length === 0) return
    if (mode === 'playing') { await stopPlayback(); return }
    playQueueRef.current = [...recordings]
    playQueueIdx.current = 0
    await playClip(recordings[0])
  }

  async function stopPlayback() {
    playQueueRef.current = []
    playQueueIdx.current = 0
    if (soundRef.current) {
      await soundRef.current.stopAsync()
      await soundRef.current.unloadAsync()
      soundRef.current = null
    }
    setPlayingId(null)
    setPlayPos(0)
    setMode('idle')
  }

  function confirmDelete(rec: HumanRecording) {
    Alert.alert('Delete clip?', `"${rec.label}"`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete', style: 'destructive',
        onPress: async () => {
          if (playingId === rec.id) await stopPlayback()
          // Remove from SQLite and disk
          if (rec.sqliteId) {
            try { await deleteAudioRecording(rec.sqliteId, rec.uri) } catch {}
          } else {
            try { await FileSystem.deleteAsync(rec.uri, { idempotent: true }) } catch {}
          }
          onRecordingDeleted(rec.id)
        },
      },
    ])
  }

  // Group clips by section name
  const grouped = recordings.reduce((acc: Record<string, HumanRecording[]>, r) => {
    if (!acc[r.sectionName]) acc[r.sectionName] = []
    acc[r.sectionName].push(r)
    return acc
  }, {})

  const recCount = recordings.length
  const progress = playDur > 0 ? playPos / playDur : 0
  const isRecording = mode === 'recording'
  const isPlaying   = mode === 'playing'

  return (
    <>
      {/* ── Recorder bar ────────────────────────────────────────────────── */}
      <View style={[bar.wrap, { paddingBottom: Math.max(insets.bottom, 10) }]}>

        {/* Progress bar — animates during playback */}
        <View style={bar.progressTrack}>
          <View style={[bar.progressFill, { width: `${progress * 100}%` as any }]} />
        </View>

        <View style={bar.row}>
          {/* ▶ Play all / stop */}
          <TouchableOpacity
            style={[bar.sideBtn, (recCount === 0 || isRecording) && bar.disabled]}
            onPress={playAll}
            disabled={recCount === 0 || isRecording || saving}
          >
            <Text style={bar.sideBtnIcon}>{isPlaying ? '⏹' : '▶'}</Text>
            <Text style={bar.sideBtnLabel}>{isPlaying ? 'Stop' : 'Play all'}</Text>
          </TouchableOpacity>

          {/* Centre record / pause button */}
          <View style={bar.centreWrap}>
            {saving ? (
              <View style={[bar.recBtn, bar.recBtnSaving]}>
                <ActivityIndicator color="#fff" />
              </View>
            ) : isRecording ? (
              <TouchableOpacity style={[bar.recBtn, bar.recBtnLive]} onPress={handlePause}>
                {/* Two pause bars */}
                <View style={bar.pauseIcon}>
                  <View style={bar.pauseBar} />
                  <View style={bar.pauseBar} />
                </View>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={[bar.recBtn, isPlaying && bar.disabled]}
                onPress={handleRecord}
                disabled={isPlaying || saving}
              >
                <View style={bar.recDot} />
              </TouchableOpacity>
            )}
            <Text style={bar.recLabel}>
              {saving ? 'Saving…' : isRecording ? fmt(elapsed * 1000) : 'Record'}
            </Text>
          </View>

          {/* Files drawer */}
          <TouchableOpacity style={bar.sideBtn} onPress={() => setDrawerOpen(true)}>
            <View style={bar.filesIcon}>
              <View style={bar.filesLine} />
              <View style={bar.filesLine} />
              <View style={[bar.filesLine, bar.filesLineShort]} />
            </View>
            {recCount > 0 && (
              <View style={bar.badge}>
                <Text style={bar.badgeText}>{recCount}</Text>
              </View>
            )}
            <Text style={bar.sideBtnLabel}>Clips</Text>
          </TouchableOpacity>
        </View>

        {/* Context label */}
        <Text style={bar.context} numberOfLines={1}>
          {isRecording
            ? `● ${currentLabel()}`
            : isPlaying && playingId
            ? `▶ ${recordings.find(r => r.id === playingId)?.label ?? ''}`
            : recCount > 0
            ? `${recCount} clip${recCount !== 1 ? 's' : ''} recorded`
            : 'Press record to start'}
        </Text>
      </View>

      {/* ── Clips drawer ────────────────────────────────────────────────── */}
      <Modal visible={drawerOpen} animationType="slide" presentationStyle="pageSheet">
        <View style={dr.screen}>
          <View style={dr.header}>
            <Text style={dr.title}>Recorded Clips</Text>
            <TouchableOpacity style={dr.doneBtn} onPress={() => setDrawerOpen(false)}>
              <Text style={dr.doneBtnText}>Done</Text>
            </TouchableOpacity>
          </View>

          {recCount === 0 ? (
            <View style={dr.empty}>
              <Text style={dr.emptyIcon}>🎙</Text>
              <Text style={dr.emptyTitle}>No clips yet</Text>
              <Text style={dr.emptySub}>
                Press Record on the bar below, then Pause to save each clip.
              </Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={dr.scroll}>
              {/* Play all button */}
              <TouchableOpacity style={dr.playAllBtn} onPress={() => { setDrawerOpen(false); setTimeout(playAll, 300) }}>
                <Text style={dr.playAllText}>▶  Play All Clips in Order</Text>
              </TouchableOpacity>

              {Object.entries(grouped).map(([section, recs]) => (
                <View key={section}>
                  <Text style={dr.groupLabel}>{section}</Text>
                  {recs.map((rec, idx) => (
                    <View key={rec.id} style={dr.row}>
                      <TouchableOpacity
                        style={[dr.playBtn, playingId === rec.id && dr.playBtnActive]}
                        onPress={() => { setDrawerOpen(false); setTimeout(() => playingId === rec.id ? stopPlayback() : playClip(rec), 300) }}
                      >
                        <Text style={dr.playBtnIcon}>{playingId === rec.id ? '⏸' : '▶'}</Text>
                      </TouchableOpacity>

                      <View style={dr.info}>
                        <Text style={dr.infoLabel} numberOfLines={1}>
                          Clip {idx + 1}{rec.itemName ? ` — ${rec.itemName}` : ''}
                        </Text>
                        <Text style={dr.infoMeta}>
                          {fmt(rec.durationMs)} · {new Date(rec.createdAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                        </Text>
                        {playingId === rec.id && playDur > 0 && (
                          <View style={dr.mini}>
                            <View style={[dr.miniFill, { width: `${(playPos / playDur) * 100}%` as any }]} />
                          </View>
                        )}
                      </View>

                      <TouchableOpacity style={dr.delBtn} onPress={() => confirmDelete(rec)}>
                        <Text style={dr.delBtnText}>🗑</Text>
                      </TouchableOpacity>
                    </View>
                  ))}
                </View>
              ))}
            </ScrollView>
          )}
        </View>
      </Modal>
    </>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────
const BG = '#1a1a2e'
const FG = '#ffffff'
const RED = '#e63946'

const bar = StyleSheet.create({
  wrap: {
    backgroundColor: BG,
    paddingTop: 10,
    paddingHorizontal: spacing.lg,
  },
  progressTrack: {
    height: 3,
    backgroundColor: 'rgba(255,255,255,0.12)',
    borderRadius: 2,
    marginBottom: 12,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: RED,
    borderRadius: 2,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: 6,
  },

  // Side buttons
  sideBtn: {
    width: 60,
    alignItems: 'center',
    gap: 4,
  },
  disabled: { opacity: 0.3 },
  sideBtnIcon:  { fontSize: 22, color: FG },
  sideBtnLabel: { fontSize: 9, color: 'rgba(255,255,255,0.6)', fontWeight: '600' },

  // Centre record button
  centreWrap: { alignItems: 'center', gap: 5 },
  recBtn: {
    width: 64, height: 64, borderRadius: 32,
    backgroundColor: RED,
    alignItems: 'center', justifyContent: 'center',
    shadowColor: RED,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.6,
    shadowRadius: 10,
    elevation: 8,
  },
  recBtnLive: { backgroundColor: '#f87171' },
  recBtnSaving: { backgroundColor: '#6b7280' },
  recDot: {
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: FG,
  },
  pauseIcon: { flexDirection: 'row', gap: 5 },
  pauseBar: { width: 5, height: 20, borderRadius: 3, backgroundColor: FG },
  recLabel: {
    fontSize: 10,
    color: 'rgba(255,255,255,0.65)',
    fontWeight: '700',
    letterSpacing: 0.3,
  },

  // Files button
  filesIcon: { gap: 3.5, alignItems: 'flex-end' },
  filesLine: { width: 20, height: 2.5, backgroundColor: FG, borderRadius: 2 },
  filesLineShort: { width: 13 },
  badge: {
    position: 'absolute', top: -4, right: -4,
    backgroundColor: RED,
    width: 18, height: 18, borderRadius: 9,
    alignItems: 'center', justifyContent: 'center',
  },
  badgeText: { fontSize: 10, color: FG, fontWeight: '800' },

  // Context label
  context: {
    fontSize: 10,
    color: 'rgba(255,255,255,0.45)',
    textAlign: 'center',
    paddingBottom: 6,
    fontStyle: 'italic',
  },
})

const dr = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    padding: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  title:       { fontSize: font.lg, fontWeight: '700', color: colors.text },
  doneBtn:     { backgroundColor: colors.primary, paddingHorizontal: spacing.md, paddingVertical: 7, borderRadius: radius.md },
  doneBtnText: { color: '#fff', fontWeight: '700', fontSize: font.sm },
  scroll:      { padding: spacing.md, paddingBottom: 40 },

  playAllBtn: {
    backgroundColor: colors.primary, borderRadius: radius.md,
    padding: spacing.md, alignItems: 'center', marginBottom: spacing.md,
  },
  playAllText: { color: '#fff', fontWeight: '700', fontSize: font.md },

  groupLabel: {
    fontSize: font.xs, fontWeight: '700', color: colors.textLight,
    textTransform: 'uppercase', letterSpacing: 0.6,
    marginTop: spacing.md, marginBottom: spacing.xs,
  },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: 4,
    borderWidth: 1, borderColor: colors.border,
  },
  playBtn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  playBtnActive: { backgroundColor: colors.warningLight },
  playBtnIcon:   { fontSize: 13, color: colors.primary },
  info:          { flex: 1 },
  infoLabel:     { fontSize: font.sm, fontWeight: '600', color: colors.text },
  infoMeta:      { fontSize: font.xs, color: colors.textLight, marginTop: 2 },
  mini:          { height: 3, backgroundColor: colors.border, borderRadius: 2, marginTop: 4, overflow: 'hidden' },
  miniFill:      { height: '100%', backgroundColor: colors.primary, borderRadius: 2 },
  delBtn:        { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.dangerLight, alignItems: 'center', justifyContent: 'center' },
  delBtnText:    { fontSize: 16 },

  empty:      { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.md, paddingTop: 80 },
  emptyIcon:  { fontSize: 48 },
  emptyTitle: { fontSize: font.lg, fontWeight: '700', color: colors.textMid },
  emptySub:   { fontSize: font.sm, color: colors.textLight, textAlign: 'center', lineHeight: 20, paddingHorizontal: spacing.lg },
})
