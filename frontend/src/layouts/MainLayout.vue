<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router    = useRouter()
const authStore = useAuthStore()

const collapsed    = ref(false)
const accountOpen  = ref(false)
const accountRef   = ref(null)

function toggleSidebar() {
  collapsed.value = !collapsed.value
}

function toggleAccount() {
  accountOpen.value = !accountOpen.value
}

function logout() {
  accountOpen.value = false
  authStore.logout()
  router.push('/login')
}

function goChangePassword() {
  accountOpen.value = false
  router.push('/change-password')
}

function handleOutsideClick(e) {
  if (accountRef.value && !accountRef.value.contains(e.target)) {
    accountOpen.value = false
  }
}

onMounted(() => document.addEventListener('mousedown', handleOutsideClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', handleOutsideClick))
</script>

<template>
  <div class="layout" :class="{ 'sidebar-collapsed': collapsed }">

    <!-- Sidebar -->
    <aside class="sidebar">

      <!-- Header -->
      <div class="sidebar-header">
        <div class="brand">
          <span class="brand-icon">🏠</span>
          <transition name="fade-text">
            <div v-if="!collapsed" class="brand-text">
              <span class="brand-name">L&amp;M</span>
              <span class="brand-sub">Inventories</span>
            </div>
          </transition>
        </div>
        <button class="collapse-btn" @click="toggleSidebar" :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <polyline v-if="!collapsed" points="15 18 9 12 15 6"/>
            <polyline v-else points="9 18 15 12 9 6"/>
          </svg>
        </button>
      </div>

      <!-- Nav -->
      <nav class="sidebar-nav">
        <router-link to="/dashboard" class="nav-item" :title="collapsed ? 'Dashboard' : ''">
          <span class="nav-icon">📊</span>
          <span v-if="!collapsed" class="nav-label">Dashboard</span>
        </router-link>

        <router-link to="/inspections" class="nav-item" :title="collapsed ? 'Inspections' : ''">
          <span class="nav-icon">📋</span>
          <span v-if="!collapsed" class="nav-label">Inspections</span>
        </router-link>

        <router-link to="/properties" class="nav-item" :title="collapsed ? 'Properties' : ''">
          <span class="nav-icon">🏢</span>
          <span v-if="!collapsed" class="nav-label">Properties</span>
        </router-link>

        <router-link to="/clients" class="nav-item" v-if="authStore.isAdmin || authStore.isManager" :title="collapsed ? 'Clients' : ''">
          <span class="nav-icon">👥</span>
          <span v-if="!collapsed" class="nav-label">Clients</span>
        </router-link>

        <router-link to="/users" class="nav-item" v-if="authStore.isAdmin || authStore.isManager" :title="collapsed ? 'Users' : ''">
          <span class="nav-icon">👤</span>
          <span v-if="!collapsed" class="nav-label">Users</span>
        </router-link>

        <div class="nav-divider"></div>

        <router-link to="/settings" class="nav-item" v-if="authStore.isAdmin || authStore.isManager" :title="collapsed ? 'Settings' : ''">
          <span class="nav-icon">⚙️</span>
          <span v-if="!collapsed" class="nav-label">Settings</span>
        </router-link>
      </nav>

      <!-- Footer: account menu -->
      <div class="sidebar-footer" ref="accountRef">
        <button class="account-btn" @click="toggleAccount" :class="{ open: accountOpen }">
          <div class="user-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
          <transition name="fade-text">
            <div v-if="!collapsed" class="user-details">
              <div class="user-name">{{ authStore.user?.name }}</div>
              <div class="user-role">{{ authStore.user?.role }}</div>
            </div>
          </transition>
          <transition name="fade-text">
            <svg v-if="!collapsed" class="chevron" :class="{ rotated: accountOpen }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="18 15 12 9 6 15"/>
            </svg>
          </transition>
        </button>

        <!-- Dropdown -->
        <transition name="dropdown">
          <div v-if="accountOpen" class="account-dropdown">
            <button class="dropdown-item" @click="goChangePassword">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              Change Password
            </button>
            <div class="dropdown-divider"></div>
            <button class="dropdown-item dropdown-item--danger" @click="logout">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
              Logout
            </button>
          </div>
        </transition>
      </div>

    </aside>

    <!-- Main Content -->
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
/* ── Layout shell ─────────────────────────────────────────── */
.layout {
  display: flex;
  min-height: 100vh;
  background: #f1f5f9;
  transition: none;
}

/* ── Sidebar ──────────────────────────────────────────────── */
.sidebar {
  width: 240px;
  background: #1e293b;
  color: white;
  display: flex;
  flex-direction: column;
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  z-index: 100;
  transition: width 0.22s ease;
  overflow: hidden;
}

.sidebar-collapsed .sidebar {
  width: 60px;
}

/* ── Header ───────────────────────────────────────────────── */
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px 0 16px;
  height: 60px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  overflow: hidden;
  flex: 1;
  min-width: 0;
}

.brand-icon { font-size: 20px; flex-shrink: 0; }

.brand-text {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  white-space: nowrap;
}

.brand-name {
  font-size: 16px;
  font-weight: 800;
  color: white;
  line-height: 1;
}

.brand-sub {
  font-size: 10px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 600;
  margin-top: 2px;
}

.collapse-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
}

.collapse-btn:hover {
  background: rgba(255,255,255,0.12);
  color: white;
}

/* ── Nav ──────────────────────────────────────────────────── */
.sidebar-nav {
  flex: 1;
  padding: 12px 8px;
  overflow-y: auto;
  overflow-x: hidden;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 7px;
  color: #94a3b8;
  text-decoration: none;
  transition: all 0.15s;
  margin-bottom: 2px;
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
}

.nav-item:hover {
  background: rgba(255,255,255,0.08);
  color: white;
}

.nav-item.router-link-active {
  background: #6366f1;
  color: white;
}

.nav-icon {
  font-size: 17px;
  width: 22px;
  text-align: center;
  flex-shrink: 0;
}

.nav-label { overflow: hidden; }

.nav-divider {
  height: 1px;
  background: rgba(255,255,255,0.08);
  margin: 8px 6px;
}

/* ── Footer / account ─────────────────────────────────────── */
.sidebar-footer {
  padding: 10px 8px;
  border-top: 1px solid rgba(255,255,255,0.08);
  position: relative;
  flex-shrink: 0;
}

.account-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: rgba(255,255,255,0.05);
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  overflow: hidden;
  text-align: left;
}

.account-btn:hover,
.account-btn.open {
  background: rgba(255,255,255,0.1);
  border-color: rgba(255,255,255,0.1);
}

.user-avatar {
  width: 32px;
  height: 32px;
  background: #6366f1;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  color: white;
  flex-shrink: 0;
}

.user-details {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: white;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 11px;
  color: #64748b;
  text-transform: capitalize;
}

.chevron {
  flex-shrink: 0;
  color: #64748b;
  transition: transform 0.2s;
}

.chevron.rotated { transform: rotate(180deg); }

/* ── Account dropdown ─────────────────────────────────────── */
.account-dropdown {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 8px;
  right: 8px;
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 9px;
  padding: 5px;
  box-shadow: 0 -8px 24px rgba(0,0,0,0.4);
  z-index: 200;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 11px;
  background: none;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  color: #cbd5e1;
  cursor: pointer;
  transition: all 0.12s;
  text-align: left;
}

.dropdown-item:hover {
  background: rgba(255,255,255,0.08);
  color: white;
}

.dropdown-item--danger { color: #fca5a5; }
.dropdown-item--danger:hover {
  background: rgba(239,68,68,0.15);
  color: #fecaca;
}

.dropdown-divider {
  height: 1px;
  background: rgba(255,255,255,0.08);
  margin: 4px 0;
}

/* ── Main content ─────────────────────────────────────────── */
.main-content {
  flex: 1;
  margin-left: 240px;
  padding: 28px 32px;
  overflow-y: auto;
  transition: margin-left 0.22s ease;
}

.sidebar-collapsed .main-content {
  margin-left: 60px;
}

/* ── Transitions ──────────────────────────────────────────── */
.fade-text-enter-active { transition: opacity 0.15s ease 0.05s; }
.fade-text-leave-active { transition: opacity 0.1s ease; }
.fade-text-enter-from,
.fade-text-leave-to { opacity: 0; }

.dropdown-enter-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.dropdown-leave-active { transition: opacity 0.1s ease, transform 0.1s ease; }
.dropdown-enter-from { opacity: 0; transform: translateY(4px); }
.dropdown-leave-to   { opacity: 0; transform: translateY(4px); }
</style>
