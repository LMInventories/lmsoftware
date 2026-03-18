import React from 'react'
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { colors, font, spacing } from '../utils/theme'

interface HeaderProps {
  title: string
  subtitle?: string
  onBack?: () => void
  right?: React.ReactNode
}

export default function Header({ title, subtitle, onBack, right }: HeaderProps) {
  const insets = useSafeAreaInsets()

  return (
    <View style={[styles.container, { paddingTop: insets.top + spacing.sm }]}>
      <View style={styles.row}>
        {onBack ? (
          <TouchableOpacity style={styles.backBtn} onPress={onBack} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
            <Text style={styles.backArrow}>←</Text>
          </TouchableOpacity>
        ) : (
          <View style={styles.backPlaceholder} />
        )}

        <View style={styles.titleWrap}>
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
          {subtitle ? <Text style={styles.subtitle} numberOfLines={1}>{subtitle}</Text> : null}
        </View>

        <View style={styles.rightWrap}>
          {right || <View style={styles.backPlaceholder} />}
        </View>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  backBtn: {
    width: 36,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 18,
    backgroundColor: colors.muted,
  },
  backArrow: {
    fontSize: font.lg,
    color: colors.primary,
    fontWeight: '600',
  },
  backPlaceholder: { width: 36 },
  titleWrap: {
    flex: 1,
    alignItems: 'center',
  },
  title: {
    fontSize: font.lg,
    fontWeight: '700',
    color: colors.text,
  },
  subtitle: {
    fontSize: font.xs,
    color: colors.textLight,
    marginTop: 1,
  },
  rightWrap: {
    width: 36,
    alignItems: 'flex-end',
  },
})
