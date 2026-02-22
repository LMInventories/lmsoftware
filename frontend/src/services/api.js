import axios from 'axios'

// ── API URL ─────────────────────────────────────────────────────────────────
// Android WebViews always report window.location.hostname as 'localhost'.
// We detect this and point straight at the real server IP instead.
// No Capacitor import needed — avoids any plugin-load timing issues.
//
// ⚠️  Set BACKEND_LAN_IP to your PC's Wi-Fi IPv4 address (run: ipconfig)
//
const BACKEND_LAN_IP = '192.168.50.2'

const API_URL = (() => {
  try {
    const hostname = window.location.hostname
    const protocol = window.location.protocol
    // Capacitor/Ionic WebView always has hostname 'localhost' on device
    if (hostname === 'localhost' || protocol === 'capacitor:' || protocol === 'ionic:') {
      return `http://${BACKEND_LAN_IP}:5000`
    }
    return `${protocol}//${hostname}:5000`
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
  register(userData)  { return axiosInstance.post('/api/auth/register', userData) },
  getCurrentUser()    { return axiosInstance.get('/api/auth/me') },

  // Dashboard
  getDashboardStats() { return axiosInstance.get('/api/dashboard/stats') },

  // Users
  getUsers()        { return axiosInstance.get('/api/users') },
  getUser(id)       { return axiosInstance.get(`/api/users/${id}`) },
  createUser(data)  { return axiosInstance.post('/api/users', data) },
  updateUser(id, data) { return axiosInstance.put(`/api/users/${id}`, data) },
  deleteUser(id)    { return axiosInstance.delete(`/api/users/${id}`) },

  // Clients
  getClients()       { return axiosInstance.get('/api/clients') },
  getClient(id)      { return axiosInstance.get(`/api/clients/${id}`) },
  createClient(data) { return axiosInstance.post('/api/clients', data) },
  updateClient(id, data) { return axiosInstance.put(`/api/clients/${id}`, data) },
  deleteClient(id)   { return axiosInstance.delete(`/api/clients/${id}`) },

  // Properties
  getProperties()       { return axiosInstance.get('/api/properties') },
  getProperty(id)       { return axiosInstance.get(`/api/properties/${id}`) },
  createProperty(data)  { return axiosInstance.post('/api/properties', data) },
  updateProperty(id, data) { return axiosInstance.put(`/api/properties/${id}`, data) },
  deleteProperty(id)    { return axiosInstance.delete(`/api/properties/${id}`) },

  // Inspections
  getInspections()       { return axiosInstance.get('/api/inspections') },
  getInspection(id)      { return axiosInstance.get(`/api/inspections/${id}`) },
  createInspection(data) { return axiosInstance.post('/api/inspections', data) },
  updateInspection(id, data) { return axiosInstance.put(`/api/inspections/${id}`, data) },
  deleteInspection(id)   { return axiosInstance.delete(`/api/inspections/${id}`) },

  // ── Property lifecycle ────────────────────────────────────────────────
  // Returns all inspections for a property ordered newest-first.
  // Used to find previous Check In / Check Out when creating a new inspection.
  getPropertyHistory(propertyId) {
    return axiosInstance.get(`/api/inspections/property/${propertyId}/history`)
  },

  // Returns a preview of the report_data that would be seeded into a new
  // inspection of target_type if the given inspection is used as the source.
  getSeedPreview(inspectionId, targetType) {
    return axiosInstance.get(`/api/inspections/${inspectionId}/seed-preview`, {
      params: { target_type: targetType }
    })
  },

  // Templates
  getTemplates()        { return axiosInstance.get('/api/templates') },
  getTemplate(id)       { return axiosInstance.get(`/api/templates/${id}`) },
  createTemplate(data)  { return axiosInstance.post('/api/templates', data) },
  updateTemplate(id, data) { return axiosInstance.put(`/api/templates/${id}`, data) },
  deleteTemplate(id)    { return axiosInstance.delete(`/api/templates/${id}`) },
}

export default api
