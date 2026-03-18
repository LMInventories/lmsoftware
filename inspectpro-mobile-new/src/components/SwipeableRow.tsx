import React, { useRef } from 'react'
import { View, Text, TouchableOpacity, StyleSheet, Animated } from 'react-native'
import Swipeable from 'react-native-gesture-handler/Swipeable'
import { colors, font, radius, spacing } from '../utils/theme'

interface Action {
  icon: string
  label: string
  bg: string
  onPress: () => void
}

interface Props {
  children: React.ReactNode
  actions: Action[]
  disabled?: boolean
}

export default function SwipeableRow({ children, actions, disabled }: Props) {
  const swipeRef = useRef<Swipeable>(null)

  function close() {
    swipeRef.current?.close()
  }

  // Same actions shown on both left and right swipe
  function renderActions(
    _progress: Animated.AnimatedInterpolation<number>,
    side: 'left' | 'right'
  ) {
    if (!actions.length) return null
    return (
      <View style={[styles.actionsRow, side === 'left' ? styles.actionsLeft : styles.actionsRight]}>
        {actions.map((action, i) => (
          <TouchableOpacity
            key={i}
            style={[styles.actionBtn, { backgroundColor: action.bg }]}
            onPress={() => {
              close()
              action.onPress()
            }}
          >
            <Text style={styles.actionIcon}>{action.icon}</Text>
            <Text style={styles.actionLabel}>{action.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    )
  }

  if (disabled) return <>{children}</>

  return (
    <Swipeable
      ref={swipeRef}
      friction={2}
      leftThreshold={40}
      rightThreshold={40}
      renderLeftActions={(p) => renderActions(p, 'left')}
      renderRightActions={(p) => renderActions(p, 'right')}
    >
      {children}
    </Swipeable>
  )
}

const styles = StyleSheet.create({
  actionsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.xs,
    gap: 2,
  },
  actionsLeft:  { paddingRight: 4 },
  actionsRight: { paddingLeft: 4 },
  actionBtn: {
    width: 64,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    gap: 3,
  },
  actionIcon:  { fontSize: 18 },
  actionLabel: { fontSize: 9, fontWeight: '700', color: colors.text, letterSpacing: 0.2 },
})
