import React, { useState } from 'react'
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator, Image,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useAuthStore } from '../stores/authStore'
import { api } from '../services/api'
import { colors, font, radius, spacing } from '../utils/theme'

export default function LoginScreen() {
  const insets = useSafeAreaInsets()
  const { login } = useAuthStore()

  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  // Forgot password
  const [showForgot, setShowForgot]         = useState(false)
  const [forgotEmail, setForgotEmail]       = useState('')
  const [forgotLoading, setForgotLoading]   = useState(false)
  const [forgotMessage, setForgotMessage]   = useState('')
  const [forgotError, setForgotError]       = useState('')

  async function handleLogin() {
    setError('')
    if (!email.trim() || !password) { setError('Please enter your email and password.'); return }
    setLoading(true)
    try {
      await login(email.trim().toLowerCase(), password)
    } catch (err: any) {
      setError(err.response?.data?.error || 'Login failed. Please check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  async function handleForgot() {
    setForgotError('')
    if (!forgotEmail.trim()) { setForgotError('Please enter your email address.'); return }
    setForgotLoading(true)
    try {
      await api.forgotPassword(forgotEmail.trim().toLowerCase())
      setForgotMessage('Check your inbox — if that email is registered, a reset link is on its way.')
    } catch {
      setForgotError('Something went wrong. Please try again.')
    } finally {
      setForgotLoading(false)
    }
  }

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.primary }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={[styles.scroll, { paddingTop: insets.top + spacing.xl, paddingBottom: insets.bottom + spacing.xl }]}
        keyboardShouldPersistTaps="handled"
      >
        {/* Logo */}
        <View style={styles.logoWrap}>
          <View style={styles.logoBox}>
            <Text style={styles.logoText}>InspectPro</Text>
          </View>
        </View>

        <View style={styles.card}>
          {!showForgot ? (
            <>
              <Text style={styles.heading}>Welcome Back</Text>
              <Text style={styles.sub}>Sign in to your InspectPro account</Text>

              <View style={styles.field}>
                <Text style={styles.label}>Email</Text>
                <TextInput
                  style={styles.input}
                  value={email}
                  onChangeText={setEmail}
                  placeholder="your@email.com"
                  placeholderTextColor={colors.textLight}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                  returnKeyType="next"
                />
              </View>

              <View style={styles.field}>
                <Text style={styles.label}>Password</Text>
                <TextInput
                  style={styles.input}
                  value={password}
                  onChangeText={setPassword}
                  placeholder="••••••••"
                  placeholderTextColor={colors.textLight}
                  secureTextEntry
                  returnKeyType="done"
                  onSubmitEditing={handleLogin}
                />
              </View>

              {error ? <Text style={styles.errorText}>{error}</Text> : null}

              <TouchableOpacity style={styles.btnPrimary} onPress={handleLogin} disabled={loading}>
                {loading
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={styles.btnPrimaryText}>Sign In</Text>
                }
              </TouchableOpacity>

              <TouchableOpacity style={styles.btnGhost} onPress={() => { setShowForgot(true); setForgotEmail(email); }}>
                <Text style={styles.btnGhostText}>Forgot your password?</Text>
              </TouchableOpacity>
            </>
          ) : (
            <>
              <Text style={styles.heading}>Reset Password</Text>
              <Text style={styles.sub}>Enter your email and we'll send a reset link.</Text>

              {!forgotMessage ? (
                <>
                  <View style={styles.field}>
                    <Text style={styles.label}>Email</Text>
                    <TextInput
                      style={styles.input}
                      value={forgotEmail}
                      onChangeText={setForgotEmail}
                      placeholder="your@email.com"
                      placeholderTextColor={colors.textLight}
                      keyboardType="email-address"
                      autoCapitalize="none"
                      autoCorrect={false}
                    />
                  </View>

                  {forgotError ? <Text style={styles.errorText}>{forgotError}</Text> : null}

                  <TouchableOpacity style={styles.btnPrimary} onPress={handleForgot} disabled={forgotLoading}>
                    {forgotLoading
                      ? <ActivityIndicator color="#fff" />
                      : <Text style={styles.btnPrimaryText}>Send Reset Link</Text>
                    }
                  </TouchableOpacity>
                </>
              ) : (
                <View style={styles.successBox}>
                  <Text style={styles.successText}>{forgotMessage}</Text>
                </View>
              )}

              <TouchableOpacity style={styles.btnGhost} onPress={() => { setShowForgot(false); setForgotMessage(''); setForgotError('') }}>
                <Text style={styles.btnGhostText}>← Back to Login</Text>
              </TouchableOpacity>
            </>
          )}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  scroll: {
    flexGrow: 1,
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
  },
  logoWrap: { marginBottom: spacing.xl, alignItems: 'center' },
  logoBox: {
    backgroundColor: 'rgba(255,255,255,0.15)',
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
  },
  logoText: {
    fontSize: font.xxl,
    fontWeight: '800',
    color: '#ffffff',
    letterSpacing: 1,
  },
  card: {
    width: '100%',
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    padding: spacing.lg,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.15,
    shadowRadius: 20,
    elevation: 10,
  },
  heading: { fontSize: font.xl, fontWeight: '700', color: colors.text, marginBottom: 4 },
  sub: { fontSize: font.sm, color: colors.textMid, marginBottom: spacing.lg },
  field: { marginBottom: spacing.md },
  label: { fontSize: font.sm, fontWeight: '600', color: colors.textMid, marginBottom: 6 },
  input: {
    borderWidth: 2,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontSize: font.md,
    color: colors.text,
    backgroundColor: colors.surface,
  },
  errorText: {
    color: colors.danger,
    fontSize: font.sm,
    marginBottom: spacing.sm,
    backgroundColor: colors.dangerLight,
    padding: spacing.sm,
    borderRadius: radius.sm,
  },
  successBox: {
    backgroundColor: colors.successLight,
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  successText: { color: colors.success, fontSize: font.sm, lineHeight: 20 },
  btnPrimary: {
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    padding: 14,
    alignItems: 'center',
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  btnPrimaryText: { color: '#fff', fontSize: font.md, fontWeight: '700' },
  btnGhost: { alignItems: 'center', padding: spacing.sm },
  btnGhostText: { color: colors.accent, fontSize: font.sm },
})
