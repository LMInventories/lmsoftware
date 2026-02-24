import axios from 'axios'

// ── API URL ─────────────────────────────────────────────────────────────────
// Supports three environments:
// 1. Production: Vercel frontend → Render backend (uses VITE_API_URL env var)
// 2. Local dev:  localhost:5173 → localhost:5000
// 3. Mobile dev: Capacitor app → LAN IP backend
//
// ⚠️  For mobile dev, set BACKEND_LAN_IP to your PC's Wi-Fi IPv4 (run: ipconfig)
//
const BACKEND_LAN_IP = '192.168.50.2'

const API_URL = (() => {
  // 1. Production: Use environment variable if set (Vercel will inject this)
  if (import.meta.env.VITE_API_URL) {
    console.log('[api] Using VITE_API_URL:', import.meta.env.VITE_API_URL)
    return import.meta.env.VITE_API_URL
  }

  try {
    const hostname = window.location.hostname
    const protocol = window.location.protocol

    // 2. Mobile/Capacitor: WebView reports 'localhost' — use LAN IP
    if (protocol === 'capacitor:' || protocol === 'ionic:') {
      return `http://${BACKEND_LAN_IP}:5000`
    }

    // 3. Local development: localhost → localhost:5000
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return 'http://localhost:5000'
    }

    // 4. LAN development (accessing from another device on same network)
    if (/^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(hostname)) {
      return `http://${hostname}:5000`
    }

    // 5. Production fallback: Same origin without port (shouldn't normally hit this)
    // This assumes API is on same domain or VITE_API_URL should have been set
    return `${protocol}//${hostname}`
  } catch {
    return `http://${BACKEND_LAN_IP}:5000`
  }
})()

console.log('[api] API_URL resolved to:', API_URL)

// Create a single axios instance — all requests go through this
const axiosInstance = axios.create({
  baseURL: API_URL
})

// REQUEST interceptor — automatically attach token to every request
axiosInstance.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// RESPONSE interceptor — catch 401s anywhere in the app and force re-login
axiosInstance.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      const isMobile = window.location.pathname.startsWith('/mobile')
      const loginPath = isMobile ? '/mobile/login' : '/login'
      if (window.location.pathname !== loginPath) {
        window.location.href = loginPath
      }
    }
    return Promise.reject(error)
  }
)

const api = {
  // Token management
  getToken() { return localStorage.getItem('token') },
  setToken(token) { localStorage.setItem('token', token) },
  removeToken() { localStorage.removeItem('token'); localStorage.removeItem('user') },

  // Auth
  login(credentials) { return axiosInstance.post('/api/auth/login', credentials) },
  register(userData) { return axiosInstance.post('/api/auth/register', userData) },
  getCurrentUser() { return axiosInstance.get('/api/auth/me') },

  // Dashboard
  getDashboardStats() { return axiosInstance.get('/api/dashboard/stats') },

  // Users
  getUsers() { return axiosInstance.get('/api/users') },
  getUser(id) { return axiosInstance.get(`/api/users/${id}`) },
  createUser(data) { return axiosInstance.post('/api/users', data) },
  updateUser(id, data) { return axiosInstance.put(`/api/users/${id}`, data) },
  deleteUser(id) { return axiosInstance.delete(`/api/users/${id}`) },

  // Clients
  getClients() { return axiosInstance.get('/api/clients') },
  getClient(id) { return axiosInstance.get(`/api/clients/${id}`) },
  createClient(data) { return axiosInstance.post('/api/clients', data) },
  updateClient(id, data) { return axiosInstance.put(`/api/clients/${id}`, data) },
  deleteClient(id) { return axiosInstance.delete(`/api/clients/${id}`) },

  // Properties
  getProperties() { return axiosInstance.get('/api/properties') },
  getProperty(id) { return axiosInstance.get(`/api/properties/${id}`) },
  createProperty(data) { return axiosInstance.post('/api/properties', data) },
  updateProperty(id, data) { return axiosInstance.put(`/api/properties/${id}`, data) },
  deleteProperty(id) { return axiosInstance.delete(`/api/properties/${id}`) },

  // Inspections
  getInspections() { return axiosInstance.get('/api/inspections') },
  getInspection(id) { return axiosInstance.get(`/api/inspections/${id}`) },
  createInspection(data) { return axiosInstance.post('/api/inspections', data) },
  updateInspection(id, data) { return axiosInstance.put(`/api/inspections/${id}`, data) },
  deleteInspection(id) { return axiosInstance.delete(`/api/inspections/${id}`) },

  // ── Property lifecycle ────────────────────────────────────────────────
  getPropertyHistory(propertyId) {
    return axiosInstance.get(`/api/inspections/property/${propertyId}/history`)
  },

  getSeedPreview(inspectionId, targetType) {
    return axiosInstance.get(`/api/inspections/${inspectionId}/seed-preview`, {
      params: { target_type: targetType }
    })
  },

  // Templates
  getTemplates() { return axiosInstance.get('/api/templates') },
  getTemplate(id) { return axiosInstance.get(`/api/templates/${id}`) },
  createTemplate(data) { return axiosInstance.post('/api/templates', data) },
  updateTemplate(id, data) { return axiosInstance.put(`/api/templates/${id}`, data) },
  deleteTemplate(id) { return axiosInstance.delete(`/api/templates/${id}`) },
}

export default api
