import axios from 'axios'

// ── API BASE URL ─────────────────────────────────────────────────────────────
//
// Priority order:
//  1. VITE_API_URL env var — set this in Vercel dashboard to your Render URL
//     e.g. https://your-app.onrender.com
//  2. Android LAN detection — Capacitor native platform
//  3. Relative URL — works when frontend and backend are on same origin
//
// For LOCAL DEV: create frontend/.env.local with:
//   VITE_API_URL=http://localhost:5000
//
// For VERCEL PRODUCTION: add in Vercel dashboard → Settings → Environment Variables:
//   VITE_API_URL = https://your-backend-name.onrender.com
//
const BACKEND_LAN_IP = '192.168.50.2'  // ← your local PC IP for Android dev

function getBaseURL() {
  // 1. Explicit env var (Vercel or local .env.local)
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL
  }
  // 2. Android native
  try {
    if (window.Capacitor?.isNativePlatform?.()) {
      return `http://${BACKEND_LAN_IP}:5000`
    }
  } catch (_) {}
  // 3. Relative (same origin)
  return ''
}

const API_URL = getBaseURL()

const axiosInstance = axios.create({
  baseURL: API_URL,
  timeout: 30000,  // 30s — accounts for Render free-tier cold start (~15-20s)
})

axiosInstance.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  },
  (error) => Promise.reject(error)
)

axiosInstance.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (window.location.pathname !== '/login') window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

const api = {
  getToken() { return localStorage.getItem('token') },
  setToken(token) { localStorage.setItem('token', token) },
  removeToken() { localStorage.removeItem('token'); localStorage.removeItem('user') },

  login(credentials) { return axiosInstance.post('/api/auth/login', credentials) },
  register(userData) { return axiosInstance.post('/api/auth/register', userData) },
  getCurrentUser() { return axiosInstance.get('/api/auth/me') },

  getDashboardStats() { return axiosInstance.get('/api/dashboard/stats') },

  getUsers() { return axiosInstance.get('/api/users') },
  getUser(id) { return axiosInstance.get(`/api/users/${id}`) },
  createUser(data) { return axiosInstance.post('/api/users', data) },
  updateUser(id, data) { return axiosInstance.put(`/api/users/${id}`, data) },
  deleteUser(id) { return axiosInstance.delete(`/api/users/${id}`) },

  getClients() { return axiosInstance.get('/api/clients') },
  getClient(id) { return axiosInstance.get(`/api/clients/${id}`) },
  createClient(data) { return axiosInstance.post('/api/clients', data) },
  updateClient(id, data) { return axiosInstance.put(`/api/clients/${id}`, data) },
  deleteClient(id) { return axiosInstance.delete(`/api/clients/${id}`) },

  getProperties() { return axiosInstance.get('/api/properties') },
  getProperty(id) { return axiosInstance.get(`/api/properties/${id}`) },
  createProperty(data) { return axiosInstance.post('/api/properties', data) },
  updateProperty(id, data) { return axiosInstance.put(`/api/properties/${id}`, data) },
  deleteProperty(id) { return axiosInstance.delete(`/api/properties/${id}`) },

  getInspections(params) { return axiosInstance.get('/api/inspections', { params }) },
  getInspection(id) { return axiosInstance.get(`/api/inspections/${id}`) },
  createInspection(data) { return axiosInstance.post('/api/inspections', data) },
  updateInspection(id, data) { return axiosInstance.put(`/api/inspections/${id}`, data) },
  deleteInspection(id) { return axiosInstance.delete(`/api/inspections/${id}`) },
  updateInspectionStatus(id, status) { return axiosInstance.patch(`/api/inspections/${id}/status`, { status }) },
  getInspectionReport(id) { return axiosInstance.get(`/api/inspections/${id}/report`) },
  saveInspectionReport(id, data) { return axiosInstance.put(`/api/inspections/${id}/report`, data) },
  getLinkedCheckIn(id) { return axiosInstance.get(`/api/inspections/${id}/linked-checkin`) },

  getTemplates() { return axiosInstance.get('/api/templates') },
  getTemplate(id) { return axiosInstance.get(`/api/templates/${id}`) },
  createTemplate(data) { return axiosInstance.post('/api/templates', data) },
  updateTemplate(id, data) { return axiosInstance.put(`/api/templates/${id}`, data) },
  deleteTemplate(id) { return axiosInstance.delete(`/api/templates/${id}`) },
  reorderSection(id, direction) { return axiosInstance.post(`/api/templates/sections/${id}/reorder`, { direction }) },
  reorderItem(id, direction) { return axiosInstance.post(`/api/templates/items/${id}/reorder`, { direction }) },
}

export default api
