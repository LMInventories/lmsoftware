<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const router = useRouter()
const authStore = useAuthStore()

// ── Login ──────────────────────────────────────────────────────────────────
const form = ref({ email: '', password: '' })
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  if (!form.value.email || !form.value.password) {
    error.value = 'Please enter email and password'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await authStore.login(form.value)
    router.push('/dashboard')
  } catch (err) {
    error.value = err.response?.data?.error || 'Login failed. Please check your credentials.'
  } finally {
    loading.value = false
  }
}

// ── Forgot password ────────────────────────────────────────────────────────
const showForgot = ref(false)
const forgotEmail = ref('')
const forgotLoading = ref(false)
const forgotMessage = ref('')
const forgotError = ref('')

function openForgot() {
  forgotEmail.value = form.value.email   // pre-fill if they already typed it
  forgotMessage.value = ''
  forgotError.value = ''
  showForgot.value = true
}

function closeForgot() {
  showForgot.value = false
}

async function handleForgot() {
  if (!forgotEmail.value) {
    forgotError.value = 'Please enter your email address.'
    return
  }
  forgotLoading.value = true
  forgotError.value = ''
  try {
    await api.post('/api/auth/forgot-password', { email: forgotEmail.value })
    forgotMessage.value = 'Check your inbox — if that email is registered, a reset link is on its way.'
  } catch {
    forgotError.value = 'Something went wrong. Please try again.'
  } finally {
    forgotLoading.value = false
  }
}
</script>

<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <img src="/ip-logo.png" alt="InspectPro" class="login-logo" />
      </div>

      <!-- ── Login form ── -->
      <form v-if="!showForgot" @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label for="email">Email</label>
          <input
            id="email"
            v-model="form.email"
            type="email"
            placeholder="your@email.com"
            required
            autocomplete="email"
          />
        </div>

        <div class="form-group">
          <label for="password">Password</label>
          <input
            id="password"
            v-model="form.password"
            type="password"
            placeholder="••••••••"
            required
            autocomplete="current-password"
          />
        </div>

        <div v-if="error" class="error-message">{{ error }}</div>

        <button type="submit" class="btn-login" :disabled="loading">
          {{ loading ? 'Logging in...' : 'Login' }}
        </button>

        <button type="button" class="btn-forgot" @click="openForgot">
          Forgot your password?
        </button>
      </form>

      <!-- ── Forgot password panel ── -->
      <div v-else class="forgot-panel">
        <h2 class="forgot-title">Reset password</h2>
        <p class="forgot-sub">Enter your email and we'll send you a reset link.</p>

        <div v-if="!forgotMessage" class="login-form">
          <div class="form-group">
            <label for="forgot-email">Email</label>
            <input
              id="forgot-email"
              v-model="forgotEmail"
              type="email"
              placeholder="your@email.com"
              autocomplete="email"
            />
          </div>

          <div v-if="forgotError" class="error-message">{{ forgotError }}</div>

          <button class="btn-login" :disabled="forgotLoading" @click="handleForgot">
            {{ forgotLoading ? 'Sending...' : 'Send reset link' }}
          </button>
        </div>

        <div v-else class="success-message">
          {{ forgotMessage }}
        </div>

        <button type="button" class="btn-forgot" @click="closeForgot">
          ← Back to login
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}

.login-card {
  background: white;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 100%;
  max-width: 420px;
  padding: 40px;
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-logo {
  width: 220px;
  height: auto;
  display: block;
  margin: 0 auto;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-weight: 600;
  color: #475569;
  font-size: 14px;
}

.form-group input {
  padding: 12px 16px;
  border: 2px solid #e2e8f0;
  border-radius: 8px;
  font-size: 15px;
  transition: all 0.2s;
}

.form-group input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.error-message {
  padding: 12px;
  background: #fee2e2;
  color: #991b1b;
  border-radius: 8px;
  font-size: 14px;
  text-align: center;
}

.success-message {
  padding: 14px;
  background: #dcfce7;
  color: #166534;
  border-radius: 8px;
  font-size: 14px;
  text-align: center;
  line-height: 1.5;
  margin-bottom: 4px;
}

.btn-login {
  padding: 14px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  margin-top: 8px;
}

.btn-login:hover:not(:disabled) {
  background: #4f46e5;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.btn-login:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-forgot {
  background: none;
  border: none;
  color: #6366f1;
  font-size: 14px;
  cursor: pointer;
  text-align: center;
  padding: 4px;
  transition: color 0.2s;
}

.btn-forgot:hover { color: #4f46e5; text-decoration: underline; }

/* Forgot panel */
.forgot-panel { display: flex; flex-direction: column; gap: 20px; }
.forgot-title { font-size: 20px; font-weight: 700; color: #1e293b; margin: 0; }
.forgot-sub { font-size: 14px; color: #64748b; margin: -12px 0 0; }
</style>
