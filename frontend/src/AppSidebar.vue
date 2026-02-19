<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const showSettingsDropdown = ref(false)

function isActive(path) {
  return route.path === path
}

function isSettingsActive() {
  return route.path.startsWith('/settings')
}

function navigate(path) {
  router.push(path)
  showSettingsDropdown.value = false
}

function toggleSettings() {
  showSettingsDropdown.value = !showSettingsDropdown.value
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="logo">
        <span class="logo-icon">🏠</span>
        <span class="logo-text">L&M Inventories</span>
      </div>
    </div>

    <nav class="sidebar-nav">
      <button 
        @click="navigate('/dashboard')" 
        class="nav-item"
        :class="{ active: isActive('/dashboard') }"
      >
        <span class="nav-icon">📊</span>
        <span class="nav-text">Dashboard</span>
      </button>

      <button 
        @click="navigate('/inspections')" 
        class="nav-item"
        :class="{ active: isActive('/inspections') }"
      >
        <span class="nav-icon">📋</span>
        <span class="nav-text">Inspections</span>
      </button>

      <button 
        @click="navigate('/properties')" 
        class="nav-item"
        :class="{ active: isActive('/properties') }"
      >
        <span class="nav-icon">🏢</span>
        <span class="nav-text">Properties</span>
      </button>

      <button 
        @click="navigate('/clients')" 
        class="nav-item"
        :class="{ active: isActive('/clients') }"
        v-if="authStore.isAdmin || authStore.isManager"
      >
        <span class="nav-icon">👥</span>
        <span class="nav-text">Clients</span>
      </button>

      <button 
        @click="navigate('/users')" 
        class="nav-item"
        :class="{ active: isActive('/users') }"
        v-if="authStore.isAdmin || authStore.isManager"
      >
        <span class="nav-icon">👤</span>
        <span class="nav-text">Users</span>
      </button>

      <!-- Settings Dropdown -->
      <div class="nav-dropdown" v-if="authStore.isAdmin || authStore.isManager">
        <button 
          @click="toggleSettings" 
          class="nav-item"
          :class="{ active: isSettingsActive() }"
        >
          <span class="nav-icon">⚙️</span>
          <span class="nav-text">Settings</span>
          <span class="dropdown-arrow" :class="{ open: showSettingsDropdown }">▼</span>
        </button>

        <div class="dropdown-menu" v-show="showSettingsDropdown">
          <button 
            @click="navigate('/settings/templates')" 
            class="dropdown-item"
            :class="{ active: isActive('/settings/templates') }"
          >
            <span class="dropdown-icon">📄</span>
            <span>Templates</span>
          </button>
          <!-- Future settings items -->
          <!-- <button @click="navigate('/settings/email')" class="dropdown-item">
            <span class="dropdown-icon">📧</span>
            <span>Email</span>
          </button> -->
        </div>
      </div>
    </nav>

    <div class="sidebar-footer">
      <div class="user-info">
        <div class="user-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
        <div class="user-details">
          <div class="user-name">{{ authStore.user?.name }}</div>
          <div class="user-role">{{ authStore.user?.role }}</div>
        </div>
      </div>
      <button @click="handleLogout" class="logout-btn">
        <span>🚪</span>
        <span>Logout</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 260px;
  height: 100vh;
  background: white;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  position: fixed;
  left: 0;
  top: 0;
}

.sidebar-header {
  padding: 24px 20px;
  border-bottom: 1px solid #e5e7eb;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  font-size: 28px;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
}

.sidebar-nav {
  flex: 1;
  padding: 20px 12px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  width: 100%;
  background: none;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 4px;
  text-align: left;
  position: relative;
}

.nav-item:hover {
  background: #f1f5f9;
}

.nav-item.active {
  background: #e0e7ff;
  color: #4f46e5;
  font-weight: 600;
}

.nav-icon {
  font-size: 20px;
  width: 24px;
  text-align: center;
}

.nav-text {
  font-size: 15px;
  flex: 1;
}

.dropdown-arrow {
  font-size: 10px;
  transition: transform 0.2s;
  margin-left: auto;
}

.dropdown-arrow.open {
  transform: rotate(180deg);
}

.nav-dropdown {
  position: relative;
}

.dropdown-menu {
  padding-left: 12px;
  margin-top: 4px;
  margin-bottom: 8px;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  padding-left: 44px;
  width: 100%;
  background: none;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 2px;
  text-align: left;
  font-size: 14px;
  color: #64748b;
}

.dropdown-item:hover {
  background: #f1f5f9;
}

.dropdown-item.active {
  background: #e0e7ff;
  color: #4f46e5;
  font-weight: 600;
}

.dropdown-icon {
  font-size: 16px;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid #e5e7eb;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 8px;
  background: #f8fafc;
}

.user-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #6366f1;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
}

.user-details {
  flex: 1;
  min-width: 0;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 12px;
  color: #64748b;
  text-transform: capitalize;
}

.logout-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  width: 100%;
  background: none;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
}

.logout-btn:hover {
  background: #fee2e2;
  border-color: #ef4444;
  color: #ef4444;
}
</style>
