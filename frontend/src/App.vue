<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from './services/api'
import ToastContainer from './components/ToastContainer.vue'

const router = useRouter()
const route = useRoute()

const isAuthenticated = ref(false)
const currentUser = ref(null)

const isLoginPage = computed(() => route.path === '/login')

function checkAuth() {
  const token = api.getToken()
  isAuthenticated.value = !!token
  
  if (token && !currentUser.value) {
    loadCurrentUser()
  }
}

async function loadCurrentUser() {
  try {
    // You might want to add a /api/auth/me endpoint to get current user info
    // For now, we'll just check if token exists
    const token = api.getToken()
    if (token) {
      isAuthenticated.value = true
    }
  } catch (error) {
    console.error('Failed to load user:', error)
    logout()
  }
}

function logout() {
  api.removeToken()
  currentUser.value = null
  isAuthenticated.value = false
  router.push('/login')
}

onMounted(() => {
  checkAuth()
})

// Watch route changes to update auth status
router.afterEach(() => {
  checkAuth()
})
</script>

<template>
  <div id="app">
    <!-- Navigation -->
    <nav v-if="isAuthenticated && !isLoginPage" class="main-nav">
      <div class="nav-container">
        <div class="nav-brand">
          <span class="brand-icon">📋</span>
          <span class="brand-name">InspectPro</span>
        </div>
        
        <div class="nav-links">
          <router-link to="/dashboard" class="nav-link">
            <span class="nav-icon">📊</span>
            <span class="nav-text">Dashboard</span>
          </router-link>
          
          <router-link to="/inspections" class="nav-link">
            <span class="nav-icon">🔍</span>
            <span class="nav-text">Inspections</span>
          </router-link>
          
          <router-link to="/properties" class="nav-link">
            <span class="nav-icon">🏠</span>
            <span class="nav-text">Properties</span>
          </router-link>
          
          <router-link to="/clients" class="nav-link">
            <span class="nav-icon">👥</span>
            <span class="nav-text">Clients</span>
          </router-link>
          
          <router-link to="/users" class="nav-link">
            <span class="nav-icon">👤</span>
            <span class="nav-text">Users</span>
          </router-link>
          
          <router-link to="/settings" class="nav-link">
            <span class="nav-icon">⚙️</span>
            <span class="nav-text">Settings</span>
          </router-link>
        </div>
        
        <button @click="logout" class="btn-logout">
          <span class="logout-icon">🚪</span>
          <span class="logout-text">Logout</span>
        </button>
      </div>
    </nav>

    <!-- Main Content -->
    <main :class="{ 'with-nav': isAuthenticated && !isLoginPage }">
      <router-view />
    </main>
  </div>
  <ToastContainer />
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #1e293b;
  min-height: 100vh;
  background: #f8fafc;
}

/* Navigation Styles */
.main-nav {
  background: white;
  border-bottom: 1px solid #e5e7eb;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  position: sticky;
  top: 0;
  z-index: 100;
}

.nav-container {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  gap: 32px;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  font-size: 20px;
  color: #6366f1;
  flex-shrink: 0;
}

.brand-icon {
  font-size: 24px;
}

.brand-name {
  font-weight: 700;
  letter-spacing: -0.5px;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 8px;
  text-decoration: none;
  color: #64748b;
  font-weight: 600;
  font-size: 15px;
  transition: all 0.2s;
  white-space: nowrap;
}

.nav-link:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.nav-link.router-link-active {
  background: #eef2ff;
  color: #6366f1;
}

.nav-icon {
  font-size: 18px;
}

.btn-logout {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: #fee2e2;
  color: #991b1b;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.btn-logout:hover {
  background: #fecaca;
}

.logout-icon {
  font-size: 16px;
}

/* Main Content */
main {
  padding: 32px 24px;
  max-width: 1600px;
  margin: 0 auto;
}

main.with-nav {
  min-height: calc(100vh - 64px);
}

/* Common Page Styles */
.page {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 32px;
}

.page-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 8px;
}

.page-description {
  color: #64748b;
  font-size: 16px;
}

/* Common Form Styles */
.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #475569;
  font-size: 14px;
}

.input-field,
.select-field,
.textarea-field {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
  transition: all 0.2s;
}

.input-field:focus,
.select-field:focus,
.textarea-field:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.textarea-field {
  resize: vertical;
  min-height: 100px;
}

/* Common Button Styles */
.btn-primary {
  padding: 12px 24px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover {
  background: #4f46e5;
}

.btn-primary:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 12px 24px;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-danger {
  padding: 12px 24px;
  background: #fee2e2;
  color: #991b1b;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-danger:hover {
  background: #fecaca;
}

/* Common Card Styles */
.card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  padding: 24px;
}

/* Loading State */
.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
  font-size: 16px;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 80px 20px;
}

.empty-state .empty-icon {
  font-size: 64px;
  display: block;
  margin-bottom: 16px;
}

.empty-state h3 {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.empty-state p {
  color: #64748b;
  margin-bottom: 24px;
}

/* Modal Overlay */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal {
  background: white;
  border-radius: 12px;
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
}

.modal-header {
  padding: 24px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  font-size: 24px;
  font-weight: 600;
  color: #1e293b;
}

.modal-body {
  padding: 24px;
}

.modal-footer {
  padding: 24px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* Responsive Design */
@media (max-width: 1024px) {
  .nav-text {
    display: none;
  }
  
  .nav-link {
    padding: 10px 12px;
  }
  
  .logout-text {
    display: none;
  }
  
  .btn-logout {
    padding: 10px 14px;
  }
  
  .brand-name {
    display: none;
  }
}

@media (max-width: 768px) {
  .nav-container {
    padding: 0 16px;
    gap: 16px;
  }
  
  .nav-links {
    gap: 2px;
  }
  
  main {
    padding: 20px 16px;
  }
  
  .page-header h1 {
    font-size: 24px;
  }
  
  .modal {
    margin: 20px;
  }
}

@media (max-width: 480px) {
  .nav-container {
    height: 56px;
    padding: 0 12px;
    gap: 8px;
  }
  
  .nav-links {
    gap: 0;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  
  .nav-links::-webkit-scrollbar {
    display: none;
  }
  
  .nav-icon {
    font-size: 20px;
  }
  
  .logout-icon {
    font-size: 18px;
  }
}

/* Scrollbar Styles */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-track {
  background: #f1f5f9;
}

::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 5px;
}

::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>
