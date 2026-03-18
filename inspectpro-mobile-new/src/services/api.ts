import axios from 'axios'
import * as SecureStore from 'expo-secure-store'

const BASE_URL = 'https://lmsoftware.onrender.com'

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
})

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

  // AI transcription
  transcribeItem: (data: any) =>
    http.post('/api/transcribe/item', data),

  checkAiStatus: () =>
    http.get('/api/ai/status'),
}

export default api
