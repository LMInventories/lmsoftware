import axios from 'axios'
import * as SecureStore from 'expo-secure-store'

// Set EXPO_PUBLIC_API_URL in your .env or EAS secrets to override.
// e.g. EXPO_PUBLIC_API_URL=https://inspectpro-backend.up.railway.app
const BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'https://lmsoftware.onrender.com'

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
})

// Separate instance with a longer timeout for AI audio endpoints
const httpAi = axios.create({
  baseURL: BASE_URL,
  timeout: 120000,   // 2 min — Whisper + Claude can take a while for multi-clip rooms
})

httpAi.interceptors.request.use(async (config) => {
  const token = await SecureStore.getItemAsync('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

httpAi.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
)

http.interceptors.request.use(async (config) => {
  const token = await SecureStore.getItemAsync('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    return Promise.reject(error)
  }
)

export const api = {
  // Auth
  login: (data: { email: string; password: string }) =>
    http.post('/api/auth/login', data),

  forgotPassword: (email: string) =>
    http.post('/api/auth/forgot-password', { email }),

  getCurrentUser: () =>
    http.get('/api/auth/me'),

  // Inspections
  getInspections: () =>
    http.get('/api/inspections'),

  getInspection: (id: number) =>
    http.get(`/api/inspections/${id}`),

  updateInspection: (id: number, data: any) =>
    http.put(`/api/inspections/${id}`, data),

  // Templates
  getTemplate: (id: number) =>
    http.get(`/api/templates/${id}`),

  // Fixed sections
  getFixedSections: () =>
    http.get('/api/fixed-sections'),

  // Section presets
  getSectionPresets: () =>
    http.get('/api/section-presets'),

  // AI transcription — per-item (AI instant mode)
  transcribeItem: (data: any) =>
    httpAi.post('/api/transcribe/item', data),

  // AI transcription — per-room or per-fixed-section dictation
  transcribeRoom: (data: {
    clips: Array<{ audio: string; mimeType: string }>
    sectionName: string
    sectionKey: string
    sectionType?: string   // 'room' (default) or fixed section type
    items: Array<{ id: string; name: string; hasCondition?: boolean; hasDescription?: boolean }>
  }) =>
    httpAi.post('/api/transcribe/room', data),

  // AI photo classification (for reassign)
  classifyPhoto: (data: { imageBase64: string; mimeType: string; roomContext: string; inspectionId?: string | number }) =>
    httpAi.post('/api/transcribe/classify-photo', data),

  checkAiStatus: () =>
    http.get('/api/ai/status'),
}

export default api
