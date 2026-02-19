import axios from 'axios'

const API_URL = 'http://localhost:5000'

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
      // Token is expired or invalid — clear everything and redirect to login
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      // Avoid redirect loop if already on login page
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

const api = {
  // Token management
  getToken() {
    return localStorage.getItem('token')
  },

  setToken(token) {
    localStorage.setItem('token', token)
  },

  removeToken() {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  },

  // Auth endpoints (no token needed)
  login(credentials) {
    return axiosInstance.post('/api/auth/login', credentials)
  },

  register(userData) {
    return axiosInstance.post('/api/auth/register', userData)
  },

  getCurrentUser() {
    return axiosInstance.get('/api/auth/me')
  },

  // Dashboard
  getDashboardStats() {
    return axiosInstance.get('/api/dashboard/stats')
  },

  // Users
  getUsers() {
    return axiosInstance.get('/api/users')
  },

  getUser(id) {
    return axiosInstance.get(`/api/users/${id}`)
  },

  createUser(data) {
    return axiosInstance.post('/api/users', data)
  },

  updateUser(id, data) {
    return axiosInstance.put(`/api/users/${id}`, data)
  },

  deleteUser(id) {
    return axiosInstance.delete(`/api/users/${id}`)
  },

  // Clients
  getClients() {
    return axiosInstance.get('/api/clients')
  },

  getClient(id) {
    return axiosInstance.get(`/api/clients/${id}`)
  },

  createClient(data) {
    return axiosInstance.post('/api/clients', data)
  },

  updateClient(id, data) {
    return axiosInstance.put(`/api/clients/${id}`, data)
  },

  deleteClient(id) {
    return axiosInstance.delete(`/api/clients/${id}`)
  },

  // Properties
  getProperties() {
    return axiosInstance.get('/api/properties')
  },

  getProperty(id) {
    return axiosInstance.get(`/api/properties/${id}`)
  },

  createProperty(data) {
    return axiosInstance.post('/api/properties', data)
  },

  updateProperty(id, data) {
    return axiosInstance.put(`/api/properties/${id}`, data)
  },

  deleteProperty(id) {
    return axiosInstance.delete(`/api/properties/${id}`)
  },

  // Inspections
  getInspections() {
    return axiosInstance.get('/api/inspections')
  },

  getInspection(id) {
    return axiosInstance.get(`/api/inspections/${id}`)
  },

  createInspection(data) {
    return axiosInstance.post('/api/inspections', data)
  },

  updateInspection(id, data) {
    return axiosInstance.put(`/api/inspections/${id}`, data)
  },

  deleteInspection(id) {
    return axiosInstance.delete(`/api/inspections/${id}`)
  },

  // Templates
  getTemplates() {
    return axiosInstance.get('/api/templates')
  },

  getTemplate(id) {
    return axiosInstance.get(`/api/templates/${id}`)
  },

  createTemplate(data) {
    return axiosInstance.post('/api/templates', data)
  },

  updateTemplate(id, data) {
    return axiosInstance.put(`/api/templates/${id}`, data)
  },

  deleteTemplate(id) {
    return axiosInstance.delete(`/api/templates/${id}`)
  }
}

export default api