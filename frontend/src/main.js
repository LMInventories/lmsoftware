import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// Initialize auth from localStorage before mounting
const authStore = useAuthStore()
authStore.initAuth()

app.mount('#app')

import { Capacitor } from '@capacitor/core'
if (Capacitor.isNativePlatform() && router.currentRoute.value.path === '/') {
  router.replace('/mobile')
}