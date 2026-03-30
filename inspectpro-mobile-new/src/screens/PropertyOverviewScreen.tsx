import React, { useEffect, useState } from 'react'
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  Image, Alert, ActivityIndicator,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Linking } from 'react-native'
import { useNavigation, useRoute } from '@react-navigation/native'
import type { StackNavigationProp, RouteProp } from '@react-navigation/stack'
import * as ImagePicker from 'expo-image-picker'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import { updateLocalStatus, updateInspectionServerStatus, markFinalised, unmarkFinalised } from '../services/database'
import { api } from '../services/api'
import Header from '../components/Header'
import { colors, font, radius, spacing, TYPE_LABELS } from '../utils/theme'

type Nav = StackNavigationProp<RootStackParamList, 'PropertyOverview'>
type Route = RouteProp<RootStackParamList, 'PropertyOverview'>

export default function PropertyOverviewScreen() {
  const navigation = useNavigation<Nav>()
  const route = useRoute<Route>()
  const insets = useSafeAreaInsets()
  const { inspectionId } = route.params
  const { activeInspection, loadInspection, updateItemInReport } = useInspectionStore()
  const [starting, setStarting] = useState(false)
  const [finalising, setFinalising] = useState(false)

  useEffect(() => { loadInspection(inspectionId) }, [inspectionId])

  const inspection = activeInspection?.id === inspectionId ? activeInspection : null
  if (!inspection) {
    return (
      <View style={[styles.screen, { paddingTop: insets.top }]}>
        <Header title="Property Overview" onBack={() => navigation.goBack()} />
        <View style={styles.loading}><ActivityIndicator color={colors.primary} size="large" /></View>
      </View>
    )
  }

  async function handleTakeOverviewPhoto() {
    const { status } = await ImagePicker.requestCameraPermissionsAsync()
    if (status !== 'granted') { Alert.alert('Permission required', 'Camera permission is needed to take photos.'); return }

    const result = await ImagePicker.launchCameraAsync({
      quality: 0.85,
      base64: false,
      allowsEditing: false,
    })
    if (result.canceled) return

    const uri = result.assets[0].uri
    const reportData = inspection.report_data ? JSON.parse(inspection.report_data) : {}
    reportData._overview_photo = uri
    await updateItemInReport(inspectionId, '_overview', 'photo', { uri })
    Alert.alert('Photo saved', 'Overview photo has been saved locally.')
  }

  async function handleStartInspection() {
    Alert.alert(
      'Start Inspection',
      'This will mark the inspection as Active on the server. Are you ready to begin?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Start Inspection',
          onPress: async () => {
            setStarting(true)
            try {
              await api.updateInspection(inspectionId, { status: 'active' })
              // Patch the data blob so inspection.status reads correctly everywhere
              // (blob is otherwise frozen at the value from download time)
              updateInspectionServerStatus(inspectionId, 'active')
              updateLocalStatus(inspectionId, 'active')
              await loadInspection(inspectionId)
              navigation.replace('RoomSelection', { inspectionId })
            } catch {
              // Offline — allow starting locally; server will be updated on next sync
              updateLocalStatus(inspectionId, 'active')
              await loadInspection(inspectionId)
              navigation.replace('RoomSelection', { inspectionId })
            } finally {
              setStarting(false)
            }
          },
        },
      ]
    )
  }

  function formatDate(str: string | null) {
    if (!str) return '—'
    return new Date(str).toLocaleDateString('en-GB', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    })
  }

  function formatTime(pref: string | null) {
    if (!pref) return '—'
    if (pref === 'anytime') return 'Anytime'
    if (pref.startsWith('specific:')) {
      const [h, m] = pref.replace('specific:', '').split('_')
      return `${h}:${m ?? '00'}`
    }
    return pref
  }

  const reportData = inspection.report_data ? JSON.parse(inspection.report_data) : {}
  // overview_photo comes from property data downloaded at fetch time
  const overviewPhoto = inspection.property?.overview_photo || reportData._overview?.items?.photo?.uri || null
  const isActive = inspection.local_status === 'active' || inspection.status === 'active'
  const isFinalised: boolean = !!(inspection as any).is_finalised

  async function handleFinalise() {
    if (isFinalised) {
      Alert.alert(
        'Undo Finalise',
        'This inspection is marked as finalised. Do you want to undo this so it syncs back to Active?',
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Undo Finalise',
            style: 'destructive',
            onPress: async () => {
              setFinalising(true)
              try {
                unmarkFinalised(inspectionId)
                await loadInspection(inspectionId)
              } finally {
                setFinalising(false)
              }
            },
          },
        ]
      )
    } else {
      Alert.alert(
        'Finalise Inspection',
        'Mark this inspection as complete on device. When synced, it will be sent for typist/review processing instead of staying Active.',
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Finalise',
            onPress: async () => {
              setFinalising(true)
              try {
                markFinalised(inspectionId)
                await loadInspection(inspectionId)
                Alert.alert('Finalised ✓', 'Inspection marked as finalised. It will be sent for processing on your next sync.')
              } finally {
                setFinalising(false)
              }
            },
          },
        ]
      )
    }
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <Header
        title="Property Overview"
        onBack={() => navigation.goBack()}

      />

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Overview photo */}
        <TouchableOpacity style={styles.photoArea} onPress={handleTakeOverviewPhoto} activeOpacity={0.85}>
          {overviewPhoto ? (
            <Image source={{ uri: overviewPhoto }} style={styles.overviewImage} />
          ) : (
            <View style={styles.photoPlaceholder}>
              <Text style={styles.photoPlaceholderIcon}>📷</Text>
              <Text style={styles.photoPlaceholderText}>Tap to take overview photo</Text>
            </View>
          )}
          <View style={styles.photoOverlay}>
            <Text style={styles.photoOverlayText}>📷 Overview Photo</Text>
          </View>
        </TouchableOpacity>

        {/* Address + Maps button */}
        <View style={styles.addressBlock}>
          <View style={styles.addressRow}>
            <View style={styles.addressText}>
              <Text style={styles.address}>{inspection.property_address || 'Unknown address'}</Text>
              <Text style={styles.clientName}>{inspection.client_name || '—'}</Text>
            </View>
            <TouchableOpacity
              style={styles.mapsBtn}
              onPress={() => {
                const addr = encodeURIComponent(inspection.property_address || '')
                Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${addr}`)
              }}
            >
              <Text style={styles.mapsBtnIcon}>📍</Text>
              <Text style={styles.mapsBtnText}>Map</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* CTA — immediately below address */}
        <View style={styles.ctaWrap}>
          {isActive ? (
            <>
              <TouchableOpacity
                style={styles.btnPrimary}
                onPress={() => navigation.navigate('RoomSelection', { inspectionId })}
              >
                <Text style={styles.btnPrimaryText}>Continue Inspection →</Text>
              </TouchableOpacity>

              {isFinalised ? (
                <TouchableOpacity
                  style={[styles.btnSecondary, styles.btnFinalised]}
                  onPress={handleFinalise}
                  disabled={finalising}
                >
                  {finalising
                    ? <ActivityIndicator color={colors.success} size="small" />
                    : <Text style={styles.btnFinalisedText}>✓ Finalised — tap to undo</Text>
                  }
                </TouchableOpacity>
              ) : (
                <TouchableOpacity
                  style={styles.btnSecondary}
                  onPress={handleFinalise}
                  disabled={finalising}
                >
                  {finalising
                    ? <ActivityIndicator color={colors.primary} size="small" />
                    : <Text style={styles.btnSecondaryText}>Finalise Inspection</Text>
                  }
                </TouchableOpacity>
              )}
            </>
          ) : (
            <TouchableOpacity style={styles.btnPrimary} onPress={handleStartInspection} disabled={starting}>
              {starting
                ? <ActivityIndicator color="#fff" />
                : <Text style={styles.btnPrimaryText}>Start Inspection</Text>
              }
            </TouchableOpacity>
          )}
        </View>

        {/* Detail rows */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Inspection Details</Text>
          <DetailRow label="Type"       value={TYPE_LABELS[inspection.inspection_type] ?? inspection.inspection_type} />
          <DetailRow label="Date"       value={formatDate(inspection.conduct_date)} />
          <DetailRow label="Time"       value={formatTime(inspection.conduct_time_preference)} />
          <DetailRow label="Inspector"  value={inspection.inspector_name || '—'} />
          <DetailRow label="Typist"     value={inspection.typist_name || '—'} />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Property Details</Text>
          <DetailRow label="Address"   value={inspection.property_address || '—'} />
          <DetailRow label="Client"    value={inspection.client_name || '—'} />
          <DetailRow label="Tenant"    value={inspection.tenant_email || '—'} />
        </View>

        {(inspection.key_location || inspection.key_return) && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Keys</Text>
            {inspection.key_location && <DetailRow label="Key Location" value={inspection.key_location} />}
            {inspection.key_return   && <DetailRow label="Key Return"   value={inspection.key_return} />}
          </View>
        )}

        {inspection.internal_notes ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Internal Notes</Text>
            <Text style={styles.notesText}>{inspection.internal_notes}</Text>
          </View>
        ) : null}


      </ScrollView>
    </View>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={drStyles.row}>
      <Text style={drStyles.label}>{label}</Text>
      <Text style={drStyles.value}>{value}</Text>
    </View>
  )
}

const drStyles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  label: { fontSize: font.sm, color: colors.textMid, fontWeight: '600' },
  value: { fontSize: font.sm, color: colors.text, flex: 1, textAlign: 'right', marginLeft: spacing.sm },
})

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { paddingBottom: 40 },
  photoArea: { position: 'relative', height: 220, backgroundColor: colors.muted },
  overviewImage: { width: '100%', height: '100%', resizeMode: 'cover' },
  photoPlaceholder: {
    flex: 1, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.muted,
  },
  photoPlaceholderIcon: { fontSize: 40, marginBottom: spacing.sm },
  photoPlaceholderText: { fontSize: font.sm, color: colors.textLight },
  photoOverlay: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    backgroundColor: 'rgba(0,0,0,0.45)',
    paddingVertical: 6, paddingHorizontal: spacing.md,
  },
  photoOverlayText: { color: '#fff', fontSize: font.sm, fontWeight: '600' },
  addressBlock: { padding: spacing.md, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  addressRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  addressText: { flex: 1 },
  mapsBtn: { alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primaryLight, borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: spacing.sm, minWidth: 56 },
  mapsBtnIcon: { fontSize: 20 },
  mapsBtnText: { fontSize: 10, color: colors.primary, fontWeight: '700', marginTop: 2 },
  address: { fontSize: font.xl, fontWeight: '700', color: colors.text },
  clientName: { fontSize: font.sm, color: colors.textMid, marginTop: 2 },
  section: {
    margin: spacing.md,
    marginBottom: 0,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sectionTitle: {
    fontSize: font.xs,
    fontWeight: '700',
    color: colors.textLight,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: spacing.xs,
  },
  notesText: { fontSize: font.sm, color: colors.text, lineHeight: 20 },
  ctaWrap: { marginHorizontal: spacing.md, marginTop: spacing.sm, marginBottom: spacing.xs },
  btnPrimary: {
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    padding: 16,
    alignItems: 'center',
  },
  btnPrimaryText: { color: '#fff', fontSize: font.lg, fontWeight: '700' },
  btnSecondary: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: 13,
    alignItems: 'center',
    marginTop: spacing.xs,
    borderWidth: 1.5,
    borderColor: colors.primary,
  },
  btnSecondaryText: { color: colors.primary, fontSize: font.md, fontWeight: '600' },
  btnFinalised: {
    borderColor: colors.success,
    backgroundColor: colors.successLight,
  },
  btnFinalisedText: { color: colors.success, fontSize: font.md, fontWeight: '600' },
})
