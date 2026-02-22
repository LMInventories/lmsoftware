<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'

const router = useRouter()

const email    = ref('')
const password = ref('')
const loading  = ref(false)
const error    = ref('')

async function login() {
  if (!email.value || !password.value) {
    error.value = 'Please enter your email and password'
    return
  }
  loading.value = true
  error.value   = ''
  try {
    const res = await api.login({ email: email.value, password: password.value })
    const token = res.data.access_token || res.data.token
    if (!token) throw new Error('No token in response')
    localStorage.setItem('token', token)
    // Store user info if returned
    if (res.data.user) {
      localStorage.setItem('user', JSON.stringify(res.data.user))
    }
    router.replace('/mobile')
  } catch (err) {
    const msg = err.response?.data?.msg || err.response?.data?.message || err.message
    if (err.response?.status === 401) {
      error.value = 'Incorrect email or password'
    } else if (!err.response) {
      error.value = 'Cannot reach server — check you are on the same Wi-Fi'
    } else {
      error.value = msg || 'Login failed — please try again'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="ml-shell">

    <div class="ml-card">

      <!-- Logo / branding -->
      <div class="ml-logo">
        <div class="ml-logo-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
            <path d="M9 11l3 3L22 4"/>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
          </svg>
        </div>
        <h1 class="ml-title">InspectPro</h1>
        <p class="ml-subtitle">Sign in to view your inspections</p>
      </div>

      <!-- Error -->
      <div v-if="error" class="ml-error">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        {{ error }}
      </div>

      <!-- Form -->
      <div class="ml-form">
        <div class="ml-field">
          <label class="ml-label">Email</label>
          <input
            v-model="email"
            class="ml-input"
            type="email"
            placeholder="you@example.com"
            autocomplete="email"
            autocapitalize="none"
            @keyup.enter="login"
          />
        </div>

        <div class="ml-field">
          <label class="ml-label">Password</label>
          <input
            v-model="password"
            class="ml-input"
            type="password"
            placeholder="••••••••"
            autocomplete="current-password"
            @keyup.enter="login"
          />
        </div>

        <button
          class="ml-btn"
          :disabled="loading"
          @click="login"
        >
          <svg v-if="loading" class="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M21 12a9 9 0 1 1-6.2-8.6"/>
          </svg>
          {{ loading ? 'Signing in…' : 'Sign In' }}
        </button>
      </div>

    </div>

  </div>
</template>

<style scoped>
.ml-shell {
  min-height: 100vh;
  background: #0f172a;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.ml-card {
  width: 100%;
  max-width: 380px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* Logo */
.ml-logo {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  text-align: center;
}
.ml-logo-icon {
  width: 64px;
  height: 64px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 32px rgba(99, 102, 241, 0.4);
}
.ml-title {
  font-size: 26px;
  font-weight: 800;
  color: #f8fafc;
  margin: 0;
  letter-spacing: -0.5px;
}
.ml-subtitle {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}

/* Error */
.ml-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #1c0a0a;
  border: 1px solid #7f1d1d;
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 13px;
  color: #f87171;
  line-height: 1.4;
}

/* Form */
.ml-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ml-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ml-label {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
}
.ml-input {
  width: 100%;
  padding: 14px 16px;
  background: #1e293b;
  border: 1.5px solid #334155;
  border-radius: 12px;
  font-size: 16px; /* 16px prevents iOS/Android zoom on focus */
  color: #f1f5f9;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s;
  -webkit-appearance: none;
}
.ml-input:focus {
  border-color: #6366f1;
}
.ml-input::placeholder {
  color: #475569;
}

.ml-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 16px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
  margin-top: 4px;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.35);
  transition: opacity 0.15s;
}
.ml-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.ml-btn:active:not(:disabled) {
  opacity: 0.85;
}

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }
</style>
