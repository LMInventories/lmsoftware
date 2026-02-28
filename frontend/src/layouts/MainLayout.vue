<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router    = useRouter()
const authStore = useAuthStore()

// ── User menu dropdown ─────────────────────────────────────────────────────
const menuOpen = ref(false)

function toggleMenu() { menuOpen.value = !menuOpen.value }
function closeMenu()  { menuOpen.value = false }

function logout() {
  authStore.logout()
  router.push('/login')
}

function goChangePassword() {
  closeMenu()
  router.push('/change-password')
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1>🏠 L&M</h1>
        <p>Inventories</p>
      </div>

      <nav class="sidebar-nav">
        <router-link to="/dashboard" class="nav-item">
          <span class="icon">📊</span>
          <span>Dashboard</span>
        </router-link>

        <router-link to="/inspections" class="nav-item">
          <span class="icon">📋</span>
          <span>Inspections</span>
        </router-link>

        <!-- Hidden from typist -->
        <template v-if="!authStore.isTypist">
          <router-link to="/properties" class="nav-item">
            <span class="icon">🏢</span>
            <span>Properties</span>
          </router-link>
        </template>

        <!-- Admin / Manager only -->
        <template v-if="authStore.isAdmin || authStore.isManager">
          <router-link to="/clients" class="nav-item">
            <span class="icon">👥</span>
            <span>Portfolio</span>
          </router-link>

          <router-link to="/users" class="nav-item">
            <span class="icon">👤</span>
            <span>Users</span>
          </router-link>

          <div class="nav-divider"></div>

          <router-link to="/settings/templates" class="nav-item">
            <span class="icon">⚙️</span>
            <span>Settings</span>
          </router-link>
        </template>
      </nav>

      <!-- User menu -->
      <div class="sidebar-footer">
        <div class="user-info">
          <div class="user-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
          <div class="user-details">
            <div class="user-name">{{ authStore.user?.name }}</div>
            <div class="user-role">{{ authStore.user?.role }}</div>
          </div>

          <!-- Person icon button -->
          <div class="user-menu-wrap">
            <button class="user-menu-btn" @click="toggleMenu" :class="{ open: menuOpen }" title="Account">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
            </button>

            <!-- Dropdown -->
            <div v-if="menuOpen" class="user-dropdown">
              <button class="dropdown-item" @click="goChangePassword">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                Change Password
              </button>
              <div class="dropdown-divider"></div>
              <button class="dropdown-item danger" @click="logout">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                Logout
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>

    <!-- Click outside to close menu -->
    <div v-if="menuOpen" class="menu-backdrop" @click="closeMenu"></div>

    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.layout { display: flex; min-height: 100vh; background: #f1f5f9; }

.sidebar { width: 260px; background: #1e293b; color: white; display: flex; flex-direction: column; position: fixed; left: 0; top: 0; bottom: 0; z-index: 100; }

.sidebar-header { padding: 24px 20px; border-bottom: 1px solid rgba(255,255,255,0.1); }
.sidebar-header h1 { font-size: 24px; font-weight: 700; margin-bottom: 2px; }
.sidebar-header p { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }

.sidebar-nav { flex: 1; padding: 16px 12px; overflow-y: auto; }

.nav-item { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 8px; color: #cbd5e1; text-decoration: none; transition: all 0.2s; margin-bottom: 4px; font-weight: 500; }
.nav-item:hover { background: rgba(255,255,255,0.1); color: white; }
.nav-item.router-link-active { background: #6366f1; color: white; }
.nav-item .icon { font-size: 20px; width: 24px; text-align: center; }

.nav-divider { height: 1px; background: rgba(255,255,255,0.1); margin: 12px 8px; }

/* Footer / user area */
.sidebar-footer { padding: 16px; border-top: 1px solid rgba(255,255,255,0.1); }
.user-info { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: rgba(255,255,255,0.05); border-radius: 8px; }
.user-avatar { width: 36px; height: 36px; background: #6366f1; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; flex-shrink: 0; }
.user-details { flex: 1; min-width: 0; }
.user-name { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 11px; color: #94a3b8; text-transform: capitalize; }

/* Person icon button */
.user-menu-wrap { position: relative; flex-shrink: 0; }
.user-menu-btn { width: 32px; height: 32px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15); background: rgba(255,255,255,0.05); color: #cbd5e1; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.15s; }
.user-menu-btn:hover, .user-menu-btn.open { background: rgba(99,102,241,0.3); border-color: #6366f1; color: white; }

/* Dropdown */
.user-dropdown { position: absolute; bottom: 42px; right: 0; background: white; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.15); min-width: 180px; overflow: hidden; z-index: 200; }
.dropdown-item { width: 100%; padding: 10px 14px; background: none; border: none; text-align: left; font-size: 13px; font-weight: 500; color: #374151; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.12s; }
.dropdown-item:hover { background: #f8fafc; }
.dropdown-item.danger { color: #ef4444; }
.dropdown-item.danger:hover { background: #fef2f2; }
.dropdown-divider { height: 1px; background: #e2e8f0; margin: 2px 0; }

.menu-backdrop { position: fixed; inset: 0; z-index: 99; }

.main-content { flex: 1; margin-left: 260px; padding: 32px; overflow-y: auto; }
</style>
