import React from 'react'
import { View, Text, StyleSheet } from 'react-native'
import { STATUS_COLORS, font, radius, spacing } from '../utils/theme'

interface Props {
  status: string
  small?: boolean
}

export default function StatusBadge({ status, small }: Props) {
  const s = STATUS_COLORS[status] ?? { bg: '#f1f5f9', text: '#475569', label: status }
  return (
    <View style={[styles.badge, { backgroundColor: s.bg }]}>
      <Text style={[styles.label, { color: s.text }, small && styles.smallText]} numberOfLines={1}>
        {s.label.toUpperCase()}
      </Text>
    </View>
  )
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.sm,
    alignSelf: 'flex-start',
    flexShrink: 0,           // never compress — always fit full text
  },
  label: {
    fontSize: font.xs,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  smallText: { fontSize: 10 },
})
