<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../services/api'

const route  = useRoute()
const router = useRouter()

const token    = ref('')
const password = ref('')
const confirm  = ref('')
const loading  = ref(false)
const message  = ref('')
const error    = ref('')
const done     = ref(false)

onMounted(() => {
  token.value = route.query.token || ''
  if (!token.value) {
    error.value = 'Invalid reset link. Please request a new one.'
  }
})

async function handleReset() {
  error.value = ''
  if (!password.value || password.value.length < 8) {
    error.value = 'Password must be at least 8 characters.'
    return
  }
  if (password.value !== confirm.value) {
    error.value = 'Passwords do not match.'
    return
  }
  loading.value = true
  try {
    await api.post('/api/auth/reset-password', {
      token: token.value,
      password: password.value,
    })
    done.value = true
    message.value = 'Password updated! Redirecting to login…'
    setTimeout(() => router.push('/login'), 2500)
  } catch (err) {
    error.value = err.response?.data?.error || 'Something went wrong. Please try again.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="reset-container">
    <div class="reset-card">
      <div class="reset-header">
        <img src="/ip-logo.png" alt="InspectPro" class="reset-logo" />
      </div>

      <h2 class="reset-title">Choose a new password</h2>

      <div v-if="done" class="success-message">{{ message }}</div>

      <form v-else-if="token" @submit.prevent="handleReset" class="reset-form">
        <div class="form-group">
          <label>New password</label>
          <input
            v-model="password"
            type="password"
            placeholder="At least 8 characters"
            autocomplete="new-password"
            required
          />
        </div>

        <div class="form-group">
          <label>Confirm password</label>
          <input
            v-model="confirm"
            type="password"
            placeholder="Repeat your new password"
            autocomplete="new-password"
            required
          />
        </div>

        <div v-if="error" class="error-message">{{ error }}</div>

        <button type="submit" class="btn-reset" :disabled="loading">
          {{ loading ? 'Saving...' : 'Set new password' }}
        </button>
      </form>

      <div v-else class="error-message">{{ error }}</div>

      <a href="/login" class="btn-back">← Back to login</a>
    </div>
  </div>
</template>

<style scoped>
.reset-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}

.reset-card {
  background: white;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 100%;
  max-width: 420px;
  padding: 40px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.reset-header { text-align: center; }

.reset-logo {
  width: 220px;
  height: auto;
  display: block;
  margin: 0 auto;
}

.reset-title {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
  text-align: center;
}

.reset-form { display: flex; flex-direction: column; gap: 20px; }

.form-group { display: flex; flex-direction: column; gap: 8px; }

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
}

.btn-reset {
  padding: 14px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-reset:hover:not(:disabled) {
  background: #4f46e5;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.btn-reset:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-back {
  text-align: center;
  color: #6366f1;
  font-size: 14px;
  text-decoration: none;
}

.btn-back:hover { text-decoration: underline; }
</style>
