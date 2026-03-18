import React from 'react'
import { View, Text, StyleSheet } from 'react-native'
import { colors, font, radius, spacing } from '../utils/theme'

interface Props { status: string }

const MAP: Record<string, { bg: string; text: string; label: string }> = {
  downloaded: { bg: colors.primaryLight, text: colors.primary,  label: '↓ Downloaded' },
  active:     { bg: colors.warningLight, text: colors.warning,  label: '● Active' },
  ready:      { bg: colors.successLight, text: colors.success,  label: '✓ Ready to Sync' },
}

export default function LocalBadge({ status }: Props) {
  const s = MAP[status] ?? MAP.downloaded
  return (
    <View style={[styles.badge, { backgroundColor: s.bg }]}>
      <Text style={[styles.text, { color: s.text }]}>{s.label}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.sm,
    alignSelf: 'flex-start',
  },
  text: { fontSize: font.xs, fontWeight: '700', letterSpacing: 0.3 },
})
