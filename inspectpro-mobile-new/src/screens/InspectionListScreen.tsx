import React, { useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  RefreshControl, Alert, Image,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useFocusEffect, useNavigation } from '@react-navigation/native'
import type { StackNavigationProp } from '@react-navigation/stack'

import type { RootStackParamList } from '../../App'
import { useInspectionStore } from '../stores/inspectionStore'
import { useAuthStore } from '../stores/authStore'
import StatusBadge from '../components/StatusBadge'
import LocalBadge from '../components/LocalBadge'
import { colors, font, radius, spacing, TYPE_LABELS } from '../utils/theme'

type Nav = StackNavigationProp<RootStackParamList, 'InspectionList'>

export default function InspectionListScreen() {
  const navigation = useNavigation<Nav>()
  const insets = useSafeAreaInsets()
  const { user, logout } = useAuthStore()
  const { inspections, loadInspections } = useInspectionStore()
  const [refreshing, setRefreshing] = React.useState(false)

  useFocusEffect(useCallback(() => { loadInspections() }, []))

  async function onRefresh() {
    setRefreshing(true)
    await loadInspections()
    setRefreshing(false)
  }

  function handleLogout() {
    Alert.alert('Log Out', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Log Out', style: 'destructive', onPress: () => logout() },
    ])
  }

  function formatDate(dateStr: string | null) {
    if (!dateStr) return 'No date set'
    return new Date(dateStr).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  }

  function renderItem({ item }: { item: any }) {
    const isSynced = item.synced
    // overview_photo is stored in the full inspection data under property.overview_photo
    const overviewPhoto = (() => {
      try {
        const data = typeof item.data === 'string' ? JSON.parse(item.data) : item
        return data?.property?.overview_photo || null
      } catch { return null }
    })()

    return (
      <TouchableOpacity
        style={[styles.card, isSynced && styles.cardSynced]}
        onPress={() => !isSynced && navigation.navigate('PropertyOverview', { inspectionId: item.id })}
        activeOpacity={isSynced ? 1 : 0.75}
      >
        {/* Property photo strip */}
        {overviewPhoto ? (
          <Image source={{ uri: overviewPhoto }} style={styles.cardPhoto} />
        ) : null}

        <View style={styles.cardBody}>
          <View style={styles.cardTop}>
            <View style={styles.cardTopLeft}>
              <Text style={styles.address} numberOfLines={2}>{item.property_address || 'Unknown address'}</Text>
              <Text style={styles.client}>{item.client_name || '—'}</Text>
            </View>
            <View style={styles.cardTopRight}>
              <StatusBadge status={item.status} small />
              <View style={{ marginTop: 4 }}>
                <LocalBadge status={isSynced ? 'ready' : item.local_status} />
              </View>
            </View>
          </View>

          <View style={styles.cardMeta}>
            <View style={styles.metaItem}>
              <Text style={styles.metaLabel}>Type</Text>
              <Text style={styles.metaValue}>{TYPE_LABELS[item.inspection_type] ?? item.inspection_type}</Text>
            </View>
            <View style={styles.metaItem}>
              <Text style={styles.metaLabel}>Date</Text>
              <Text style={styles.metaValue}>{formatDate(item.conduct_date)}</Text>
            </View>
          </View>

          {isSynced ? (
            <View style={styles.syncedBanner}>
              <Text style={styles.syncedBannerText}>✓ Synced — tap Sync to remove</Text>
            </View>
          ) : (
            <Text style={styles.tapHint}>Tap to open →</Text>
          )}
        </View>
      </TouchableOpacity>
    )
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>My Inspections</Text>
          <Text style={styles.headerSub}>{user?.name}</Text>
        </View>
        <View style={styles.headerActions}>
          <TouchableOpacity style={styles.fetchBtn} onPress={() => navigation.navigate('FetchInspections')}>
            <Text style={styles.fetchBtnText}>↓ Fetch</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.syncBtn} onPress={() => navigation.navigate('Sync')}>
            <Text style={styles.syncBtnText}>⇅ Sync</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
            <Text style={styles.logoutText}>⏻</Text>
          </TouchableOpacity>
        </View>
      </View>

      {inspections.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyIcon}>📋</Text>
          <Text style={styles.emptyTitle}>No inspections downloaded</Text>
          <Text style={styles.emptySub}>Tap Fetch to download your assigned inspections.</Text>
          <TouchableOpacity style={styles.btnPrimary} onPress={() => navigation.navigate('FetchInspections')}>
            <Text style={styles.btnPrimaryText}>↓ Fetch Inspections</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={inspections}
          keyExtractor={i => String(i.id)}
          renderItem={renderItem}
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
        />
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: colors.surface, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerTitle: { fontSize: font.xl, fontWeight: '700', color: colors.text },
  headerSub: { fontSize: font.xs, color: colors.textLight, marginTop: 1 },
  headerActions: { flexDirection: 'row', gap: spacing.xs, alignItems: 'center' },
  fetchBtn: { backgroundColor: colors.primary, paddingHorizontal: spacing.sm, paddingVertical: 7, borderRadius: radius.sm, minWidth: 64, alignItems: 'center' },
  fetchBtnText: { color: '#fff', fontSize: font.sm, fontWeight: '600' },
  syncBtn: { backgroundColor: colors.accent, paddingHorizontal: spacing.sm, paddingVertical: 7, borderRadius: radius.sm },
  syncBtnText: { color: '#fff', fontSize: font.sm, fontWeight: '600' },
  logoutBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.muted, alignItems: 'center', justifyContent: 'center' },
  logoutText: { fontSize: font.md, color: colors.textMid },
  list: { padding: spacing.md, gap: spacing.md },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, overflow: 'hidden', borderWidth: 1, borderColor: colors.border, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 },
  cardSynced: { opacity: 0.6 },
  cardPhoto: { width: '100%', height: 120, resizeMode: 'cover' },
  cardBody: { padding: spacing.md },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.sm },
  cardTopLeft: { flex: 1, marginRight: spacing.sm },
  cardTopRight: { alignItems: 'flex-end' },
  address: { fontSize: font.md, fontWeight: '700', color: colors.text, marginBottom: 2 },
  client: { fontSize: font.sm, color: colors.textMid },
  cardMeta: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  metaItem: {},
  metaLabel: { fontSize: 10, color: colors.textLight, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.4 },
  metaValue: { fontSize: font.sm, color: colors.text, fontWeight: '500', marginTop: 1 },
  syncedBanner: { marginTop: spacing.sm, backgroundColor: colors.successLight, borderRadius: radius.sm, padding: spacing.xs, alignItems: 'center' },
  syncedBannerText: { fontSize: font.xs, color: colors.success, fontWeight: '600' },
  tapHint: { marginTop: spacing.sm, fontSize: font.xs, color: colors.textLight, textAlign: 'right' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  emptyIcon: { fontSize: 48, marginBottom: spacing.md },
  emptyTitle: { fontSize: font.lg, fontWeight: '700', color: colors.text, marginBottom: spacing.xs },
  emptySub: { fontSize: font.sm, color: colors.textMid, textAlign: 'center', marginBottom: spacing.lg },
  btnPrimary: { backgroundColor: colors.primary, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: 12, alignItems: 'center', minWidth: 180 },
  btnPrimaryText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
})
