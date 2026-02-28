<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router    = useRouter()
const route     = useRoute()
const authStore = useAuthStore()

const showSettingsDropdown = ref(false)
const menuOpen             = ref(false)

function isActive(path)     { return route.path === path }
function isSettingsActive() { return route.path.startsWith('/settings') }
function navigate(path)     { router.push(path); showSettingsDropdown.value = false }
function toggleSettings()   { showSettingsDropdown.value = !showSettingsDropdown.value }
function toggleMenu()       { menuOpen.value = !menuOpen.value }
function closeMenu()        { menuOpen.value = false }

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

function goChangePassword() {
  closeMenu()
  router.push('/change-password')
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
      <!-- All roles -->
      <button @click="navigate('/dashboard')" class="nav-item" :class="{ active: isActive('/dashboard') }">
        <span class="nav-icon">📊</span>
        <span class="nav-text">Dashboard</span>
      </button>

      <button @click="navigate('/inspections')" class="nav-item" :class="{ active: isActive('/inspections') }">
        <span class="nav-icon">📋</span>
        <span class="nav-text">Inspections</span>
      </button>

      <!-- Admin, Manager, Clerk only — hidden from typist -->
      <button
        v-if="authStore.isAdmin || authStore.isManager || authStore.isClerk"
        @click="navigate('/properties')"
        class="nav-item"
        :class="{ active: isActive('/properties') }"
      >
        <span class="nav-icon">🏢</span>
        <span class="nav-text">Properties</span>
      </button>

      <!-- Admin / Manager only -->
      <button
        v-if="authStore.isAdmin || authStore.isManager"
        @click="navigate('/clients')"
        class="nav-item"
        :class="{ active: isActive('/clients') }"
      >
        <span class="nav-icon">👥</span>
        <span class="nav-text">Portfolio</span>
      </button>

      <button
        v-if="authStore.isAdmin || authStore.isManager"
        @click="navigate('/users')"
        class="nav-item"
        :class="{ active: isActive('/users') }"
      >
        <span class="nav-icon">👤</span>
        <span class="nav-text">Users</span>
      </button>

      <div class="nav-dropdown" v-if="authStore.isAdmin || authStore.isManager">
        <button @click="toggleSettings" class="nav-item" :class="{ active: isSettingsActive() }">
          <span class="nav-icon">⚙️</span>
          <span class="nav-text">Settings</span>
          <span class="dropdown-arrow" :class="{ open: showSettingsDropdown }">▼</span>
        </button>
        <div class="dropdown-menu" v-show="showSettingsDropdown">
          <button @click="navigate('/settings/templates')" class="dropdown-item" :class="{ active: isActive('/settings/templates') }">
            <span class="dropdown-icon">📄</span>
            <span>Templates</span>
          </button>
        </div>
      </div>
    </nav>

    <!-- Footer with person icon dropdown -->
    <div class="sidebar-footer">
      <div class="user-info">
        <div class="user-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
        <div class="user-details">
          <div class="user-name">{{ authStore.user?.name }}</div>
          <div class="user-role">{{ authStore.user?.role }}</div>
        </div>

        <div class="user-menu-wrap">
          <button class="user-menu-btn" @click="toggleMenu" :class="{ open: menuOpen }" title="Account">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
          </button>

          <div v-if="menuOpen" class="user-dropdown">
            <button class="drop-item" @click="goChangePassword">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              Change Password
            </button>
            <div class="drop-divider"></div>
            <button class="drop-item danger" @click="handleLogout">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
              Logout
            </button>
          </div>
        </div>
      </div>
    </div>
  </aside>

  <!-- Click-outside backdrop -->
  <div v-if="menuOpen" class="menu-backdrop" @click="closeMenu"></div>
</template>

<style scoped>
.sidebar { width: 260px; height: 100vh; background: white; border-right: 1px solid #e5e7eb; display: flex; flex-direction: column; position: fixed; left: 0; top: 0; }
.sidebar-header { padding: 24px 20px; border-bottom: 1px solid #e5e7eb; }
.logo { display: flex; align-items: center; gap: 12px; }
.logo-icon { font-size: 28px; }
.logo-text { font-size: 18px; font-weight: 700; color: #1e293b; }

.sidebar-nav { flex: 1; padding: 20px 12px; overflow-y: auto; }
.nav-item { display: flex; align-items: center; gap: 12px; padding: 12px 16px; width: 100%; background: none; border: none; border-radius: 8px; cursor: pointer; transition: all 0.2s; margin-bottom: 4px; text-align: left; position: relative; }
.nav-item:hover { background: #f1f5f9; }
.nav-item.active { background: #e0e7ff; color: #4f46e5; font-weight: 600; }
.nav-icon { font-size: 20px; width: 24px; text-align: center; }
.nav-text { font-size: 15px; flex: 1; }
.dropdown-arrow { font-size: 10px; transition: transform 0.2s; margin-left: auto; }
.dropdown-arrow.open { transform: rotate(180deg); }
.nav-dropdown { position: relative; }
.dropdown-menu { padding-left: 12px; margin-top: 4px; margin-bottom: 8px; }
.dropdown-item { display: flex; align-items: center; gap: 12px; padding: 10px 16px 10px 44px; width: 100%; background: none; border: none; border-radius: 8px; cursor: pointer; transition: all 0.2s; margin-bottom: 2px; text-align: left; font-size: 14px; color: #64748b; }
.dropdown-item:hover { background: #f1f5f9; }
.dropdown-item.active { background: #e0e7ff; color: #4f46e5; font-weight: 600; }
.dropdown-icon { font-size: 16px; }

.sidebar-footer { padding: 16px; border-top: 1px solid #e5e7eb; }
.user-info { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 8px; background: #f8fafc; }
.user-avatar { width: 38px; height: 38px; border-radius: 50%; background: #6366f1; color: white; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 15px; flex-shrink: 0; }
.user-details { flex: 1; min-width: 0; }
.user-name { font-size: 13px; font-weight: 600; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 11px; color: #64748b; text-transform: capitalize; }

.user-menu-wrap { position: relative; flex-shrink: 0; }
.user-menu-btn { width: 30px; height: 30px; border-radius: 6px; border: 1px solid #e2e8f0; background: white; color: #64748b; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.15s; }
.user-menu-btn:hover, .user-menu-btn.open { background: #e0e7ff; border-color: #6366f1; color: #4f46e5; }

.user-dropdown { position: absolute; bottom: 38px; right: 0; background: white; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); min-width: 175px; overflow: hidden; z-index: 200; }
.drop-item { width: 100%; padding: 10px 14px; background: none; border: none; text-align: left; font-size: 13px; font-weight: 500; color: #374151; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.12s; }
.drop-item:hover { background: #f8fafc; }
.drop-item.danger { color: #ef4444; }
.drop-item.danger:hover { background: #fef2f2; }
.drop-divider { height: 1px; background: #e2e8f0; }

.menu-backdrop { position: fixed; inset: 0; z-index: 99; }
</style>
