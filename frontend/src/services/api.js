import axios from 'axios'

// ── BASE URL RESOLUTION ───────────────────────────────────────────────────────
// Set VITE_API_URL in Railway frontend service env vars to point at the backend.
// e.g. VITE_API_URL=https://inspectpro-backend.up.railway.app
const BACKEND_LAN_IP = '192.168.50.2'

function getBaseURL() {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL
  try {
    if (window.Capacitor?.isNativePlatform?.()) return `http://${BACKEND_LAN_IP}:5000`
  } catch (_) {}
  return ''
}

// ── AXIOS INSTANCE ────────────────────────────────────────────────────────────
const http = axios.create({
  baseURL: getBaseURL(),
  timeout: 30000,
})

http.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  },
  (error) => Promise.reject(error)
)

http.interceptors.response.use(
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

// ── API ───────────────────────────────────────────────────────────────────────
const api = {
  // Token management
  getToken()    { return localStorage.getItem('token') },
  setToken(t)   { localStorage.setItem('token', t) },
  removeToken() { localStorage.removeItem('token'); localStorage.removeItem('user') },

  // ── Auth ──────────────────────────────────────────────────────────────────
  login(data)          { return http.post('/api/auth/login', data) },
  register(data)       { return http.post('/api/auth/register', data) },
  getCurrentUser()     { return http.get('/api/auth/me') },
  changePassword(data) { return http.post('/api/users/me/change-password', data) },

  // ── Dashboard ─────────────────────────────────────────────────────────────
  getDashboardStats() { return http.get('/api/dashboard/stats') },

  // ── Users ─────────────────────────────────────────────────────────────────
  getUsers()            { return http.get('/api/users') },
  getUser(id)           { return http.get(`/api/users/${id}`) },
  createUser(data)      { return http.post('/api/users', data) },
  updateUser(id, data)  { return http.put(`/api/users/${id}`, data) },
  deleteUser(id)        { return http.delete(`/api/users/${id}`) },

  // ── Clients ───────────────────────────────────────────────────────────────
  getClients()            { return http.get('/api/clients') },
  getClient(id)           { return http.get(`/api/clients/${id}`) },
  createClient(data)      { return http.post('/api/clients', data) },
  updateClient(id, data)  { return http.put(`/api/clients/${id}`, data) },
  deleteClient(id)        { return http.delete(`/api/clients/${id}`) },

  // ── Properties ────────────────────────────────────────────────────────────
  getProperties()                { return http.get('/api/properties') },
  getProperty(id)                { return http.get(`/api/properties/${id}`) },
  createProperty(data)           { return http.post('/api/properties', data) },
  updateProperty(id, data)       { return http.put(`/api/properties/${id}`, data) },
  deleteProperty(id)             { return http.delete(`/api/properties/${id}`) },
  uploadPropertyPhoto(id, photo) { return http.post(`/api/properties/${id}/photo`, { photo }) },

  // ── Address Lookup ────────────────────────────────────────────────────────
  addressFindByPostcode(postcode) { return http.get(`/api/address/find/${encodeURIComponent(postcode)}`) },
  addressAutocomplete(q)          { return http.get('/api/address/autocomplete', { params: { q } }) },
  addressGet(url)                 { return http.get('/api/address/get', { params: { url } }) },

  // ── Inspections ───────────────────────────────────────────────────────────
  getInspections(params)             { return http.get('/api/inspections', { params }) },
  getInspection(id)                  { return http.get(`/api/inspections/${id}`) },
  createInspection(data)             { return http.post('/api/inspections', data) },
  updateInspection(id, data)         { return http.put(`/api/inspections/${id}`, data) },
  deleteInspection(id)               { return http.delete(`/api/inspections/${id}`) },
  updateInspectionStatus(id, status) { return http.patch(`/api/inspections/${id}/status`, { status }) },
  getInspectionReport(id)            { return http.get(`/api/inspections/${id}/report`) },
  saveInspectionReport(id, data)     { return http.put(`/api/inspections/${id}/report`, data) },
  getLinkedCheckIn(id)               { return http.get(`/api/inspections/${id}/linked-checkin`) },
  getPropertyHistory(propertyId)     { return http.get(`/api/inspections/property/${propertyId}/history`) },
  applyPdfImport(id, data)           { return http.post(`/api/inspections/${id}/apply-pdf-import`, data) },

  // ── Templates ─────────────────────────────────────────────────────────────
  getTemplates()            { return http.get('/api/templates') },
  getTemplate(id)           { return http.get(`/api/templates/${id}`) },
  createTemplate(data)      { return http.post('/api/templates', data) },
  updateTemplate(id, data)  { return http.put(`/api/templates/${id}`, data) },
  deleteTemplate(id)        { return http.delete(`/api/templates/${id}`) },
  reorderSection(id, dir)   { return http.post(`/api/templates/sections/${id}/reorder`, { direction: dir }) },
  reorderItem(id, dir)      { return http.post(`/api/templates/items/${id}/reorder`, { direction: dir }) },
  addSection(templateId, data)   { return http.post(`/api/templates/${templateId}/sections`, data) },
  duplicateSection(sectionId)    { return http.post(`/api/templates/sections/${sectionId}/duplicate`) },
  updateSection(sectionId, data) { return http.put(`/api/templates/sections/${sectionId}`, data) },
  deleteSection(sectionId)       { return http.delete(`/api/templates/sections/${sectionId}`) },
  addItem(sectionId, data)       { return http.post(`/api/templates/sections/${sectionId}/items`, data) },
  updateItem(itemId, data)       { return http.put(`/api/templates/items/${itemId}`, data) },
  duplicateItem(itemId)          { return http.post(`/api/templates/items/${itemId}/duplicate`) },
  deleteItem(itemId)             { return http.delete(`/api/templates/items/${itemId}`) },

  // ── Section Library (presets) ─────────────────────────────────────────────
  getSectionPresets()                    { return http.get('/api/section-presets') },
  createSectionPreset(data)              { return http.post('/api/section-presets', data) },
  saveSectionAsPreset(sectionId, data)   { return http.post(`/api/section-presets/from-section/${sectionId}`, data) },
  addPresetToTemplate(presetId, templateId, data = {}) {
    return http.post(`/api/section-presets/${presetId}/add-to-template/${templateId}`, data)
  },
  updateSectionPreset(presetId, data)    { return http.put(`/api/section-presets/${presetId}`, data) },
  deleteSectionPreset(presetId)          { return http.delete(`/api/section-presets/${presetId}`) },

  // ── Transcription ─────────────────────────────────────────────────────────
  getTranscribeStatus()           { return http.get('/api/transcribe/status') },
  getTranscribeUsage(period = 30) { return http.get(`/api/transcribe/usage?period=${period}`) },
  transcribeItem(data)            { return http.post('/api/transcribe/item', data) },
  transcribeFull(data)            { return http.post('/api/transcribe/full', data) },

  // ── Actions ───────────────────────────────────────────────────────────────
  getActions()       { return http.get('/api/actions') },
  saveActions(data)  { return http.put('/api/actions', data) },

  // ── System settings ───────────────────────────────────────────────────────
  getSystemSettings()        { return http.get('/api/system-settings') },
  updateSystemSettings(data) { return http.put('/api/system-settings', data) },

  // ── Fixed sections ────────────────────────────────────────────────────────
  getFixedSections()         { return http.get('/api/fixed-sections') },
  updateFixedSections(data)  { return http.put('/api/fixed-sections', data) },

  // ── AI proxy ──────────────────────────────────────────────────────────────
  claudeProxy(payload) {
    return http.post('/api/ai/claude', payload, { timeout: 120000 })
  },
  transcribeAudio(audioBlob, prompt = '') {
    const form = new FormData()
    form.append('file', audioBlob, audioBlob.name || 'audio.webm')
    if (prompt) form.append('prompt', prompt)
    return http.post('/api/ai/transcribe', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 90000,
    })
  },
  checkAiStatus() { return http.get('/api/ai/status') },
  pdfImport(data) {
    return http.post('/api/ai/pdf-import', data, { timeout: 120000 })
  },

  // ── Email notifications ───────────────────────────────────────────────────
  getEmailGlobalSettings()             { return http.get('/api/email/settings') },
  saveEmailGlobalSettings(data)        { return http.put('/api/email/settings', data) },
  getClientEmailSettings(clientId)     { return http.get(`/api/email/client/${clientId}/settings`) },
  saveClientEmailSettings(clientId, prefs) { return http.put(`/api/email/client/${clientId}/settings`, prefs) },
  sendTestEmail(to)                    { return http.post('/api/email/test', { to }) },
  triggerClerkSummaries()              { return http.post('/api/email/clerk-summary/run') },
}

export default api
