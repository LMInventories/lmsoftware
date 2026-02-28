<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'

const router = useRouter()

const current   = ref('')
const newPass   = ref('')
const confirm   = ref('')
const saving    = ref(false)
const error     = ref('')
const success   = ref(false)

function validate() {
  if (!current.value)  return 'Please enter your current password'
  if (!newPass.value)  return 'Please enter a new password'
  if (newPass.value.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Z]/.test(newPass.value)) return 'Password must contain at least one uppercase letter'
  if (!/[a-z]/.test(newPass.value)) return 'Password must contain at least one lowercase letter'
  if (!/[0-9]/.test(newPass.value)) return 'Password must contain at least one number'
  if (newPass.value !== confirm.value) return 'Passwords do not match'
  return null
}

async function submit() {
  error.value   = ''
  success.value = false
  const msg = validate()
  if (msg) { error.value = msg; return }

  saving.value = true
  try {
    await api.changePassword({ current_password: current.value, new_password: newPass.value })
    success.value = true
    current.value = ''
    newPass.value = ''
    confirm.value = ''
    setTimeout(() => router.push('/dashboard'), 1800)
  } catch (e) {
    error.value = e.response?.data?.error || 'Failed to change password'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="cp-wrap">
    <div class="cp-card">
      <div class="cp-header">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        <h1>Change Password</h1>
        <p>Your new password must contain uppercase, lowercase and a number</p>
      </div>

      <div class="cp-body">
        <div v-if="success" class="cp-success">
          ✅ Password changed successfully — redirecting…
        </div>

        <div v-else>
          <div class="field">
            <label>Current Password</label>
            <input v-model="current" type="password" placeholder="Enter current password" class="input" @keyup.enter="submit" />
          </div>

          <div class="field">
            <label>New Password</label>
            <input v-model="newPass" type="password" placeholder="Min 8 chars, upper, lower, number" class="input" @keyup.enter="submit" />
            <!-- Strength indicators -->
            <div class="strength-row">
              <span :class="['req', newPass.length >= 8 ? 'met' : '']">8+ chars</span>
              <span :class="['req', /[A-Z]/.test(newPass) ? 'met' : '']">Uppercase</span>
              <span :class="['req', /[a-z]/.test(newPass) ? 'met' : '']">Lowercase</span>
              <span :class="['req', /[0-9]/.test(newPass) ? 'met' : '']">Number</span>
            </div>
          </div>

          <div class="field">
            <label>Confirm New Password</label>
            <input v-model="confirm" type="password" placeholder="Repeat new password" class="input" @keyup.enter="submit" />
          </div>

          <div v-if="error" class="cp-error">{{ error }}</div>

          <div class="cp-actions">
            <button class="btn-cancel" @click="router.back()">Cancel</button>
            <button class="btn-save" :disabled="saving" @click="submit">
              {{ saving ? 'Saving…' : 'Change Password' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cp-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f1f5f9; padding: 24px; }
.cp-card { background: white; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); width: 100%; max-width: 420px; overflow: hidden; }
.cp-header { padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid #f1f5f9; }
.cp-header h1 { font-size: 22px; font-weight: 700; color: #1e293b; margin: 12px 0 6px; }
.cp-header p { font-size: 13px; color: #64748b; }
.cp-body { padding: 28px 32px 32px; }

.field { margin-bottom: 20px; }
.field label { display: block; font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 6px; }
.input { width: 100%; padding: 10px 14px; border: 1px solid #cbd5e1; border-radius: 7px; font-size: 14px; font-family: inherit; transition: border-color 0.15s; box-sizing: border-box; }
.input:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }

.strength-row { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.req { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 10px; background: #f1f5f9; color: #94a3b8; transition: all 0.2s; }
.req.met { background: #dcfce7; color: #16a34a; }

.cp-error { background: #fef2f2; border: 1px solid #fca5a5; color: #dc2626; padding: 10px 14px; border-radius: 7px; font-size: 13px; margin-bottom: 16px; }
.cp-success { background: #f0fdf4; border: 1px solid #bbf7d0; color: #16a34a; padding: 16px; border-radius: 7px; font-size: 14px; font-weight: 600; text-align: center; }

.cp-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px; }
.btn-cancel { padding: 10px 20px; background: white; border: 1px solid #e2e8f0; color: #64748b; border-radius: 7px; font-size: 14px; font-weight: 600; cursor: pointer; }
.btn-cancel:hover { background: #f8fafc; }
.btn-save { padding: 10px 24px; background: #6366f1; color: white; border: none; border-radius: 7px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.btn-save:hover:not(:disabled) { background: #4f46e5; }
.btn-save:disabled { background: #94a3b8; cursor: not-allowed; }
</style>
