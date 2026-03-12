<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../services/api'

const router    = useRouter()
const authStore = useAuthStore()

// ── Sidebar collapse ──────────────────────────────────────────────────────
const sidebarCollapsed = ref(false)

// ── Mobile drawer ─────────────────────────────────────────────────────────
const drawerOpen = ref(false)

// ── User popup ────────────────────────────────────────────────────────────
const userPopupOpen = ref(false)

// ── Change password (inline in popup) ─────────────────────────────────────
const showChangePassword = ref(false)
const cpCurrent  = ref('')
const cpNew      = ref('')
const cpConfirm  = ref('')
const cpSaving   = ref(false)
const cpError    = ref('')
const cpSuccess  = ref(false)

function openUserPopup() {
  userPopupOpen.value = true
  showChangePassword.value = false
  cpCurrent.value = ''
  cpNew.value = ''
  cpConfirm.value = ''
  cpError.value = ''
  cpSuccess.value = false
}

function closeUserPopup() {
  userPopupOpen.value = false
  showChangePassword.value = false
}

function cpValidate() {
  if (!cpCurrent.value)  return 'Please enter your current password'
  if (!cpNew.value)      return 'Please enter a new password'
  if (cpNew.value.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Z]/.test(cpNew.value)) return 'Must contain an uppercase letter'
  if (!/[a-z]/.test(cpNew.value)) return 'Must contain a lowercase letter'
  if (!/[0-9]/.test(cpNew.value)) return 'Must contain a number'
  if (cpNew.value !== cpConfirm.value) return 'Passwords do not match'
  return null
}

async function cpSubmit() {
  cpError.value = ''
  const msg = cpValidate()
  if (msg) { cpError.value = msg; return }
  cpSaving.value = true
  try {
    await api.changePassword({ current_password: cpCurrent.value, new_password: cpNew.value })
    cpSuccess.value = true
    cpCurrent.value = ''
    cpNew.value = ''
    cpConfirm.value = ''
    setTimeout(() => { closeUserPopup() }, 2000)
  } catch (e) {
    cpError.value = e.response?.data?.error || 'Failed to change password'
  } finally {
    cpSaving.value = false
  }
}

function logout() {
  authStore.logout()
  router.push('/login')
  drawerOpen.value = false
  closeUserPopup()
}

function navigate(path) {
  router.push(path)
  drawerOpen.value = false
}
</script>

<template>
  <div class="layout" :class="{ 'sidebar-is-collapsed': sidebarCollapsed }">

    <!-- ══ DESKTOP SIDEBAR ══════════════════════════════════════════ -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">

      <div class="sidebar-header">
        <img v-if="!sidebarCollapsed" src="/ip-logo.png" alt="InspectPro" class="sidebar-logo" />
        <img v-else src="/ip-logo.png" alt="InspectPro" class="sidebar-logo-icon" />
      </div>

      <nav class="sidebar-nav">
        <router-link to="/dashboard" class="nav-item" :title="sidebarCollapsed ? 'Dashboard' : undefined">
          <span class="icon">📊</span><span class="nav-label">Dashboard</span>
        </router-link>
        <router-link to="/inspections" class="nav-item" :title="sidebarCollapsed ? 'Inspections' : undefined">
          <span class="icon">📋</span><span class="nav-label">Inspections</span>
        </router-link>
        <router-link to="/properties" class="nav-item" :title="sidebarCollapsed ? 'Properties' : undefined">
          <span class="icon">🏢</span><span class="nav-label">Properties</span>
        </router-link>
        <router-link to="/clients" class="nav-item" v-if="authStore.isAdmin || authStore.isManager" :title="sidebarCollapsed ? 'Clients' : undefined">
          <span class="icon">👥</span><span class="nav-label">Clients</span>
        </router-link>
        <router-link to="/users" class="nav-item" v-if="authStore.isAdmin || authStore.isManager" :title="sidebarCollapsed ? 'Users' : undefined">
          <span class="icon">👤</span><span class="nav-label">Users</span>
        </router-link>
        <div class="nav-divider"></div>
        <router-link to="/settings" class="nav-item" v-if="authStore.isAdmin || authStore.isManager" :title="sidebarCollapsed ? 'Settings' : undefined">
          <span class="icon">⚙️</span><span class="nav-label">Settings</span>
        </router-link>
      </nav>

      <!-- User button -->
      <div class="sidebar-footer">
        <button class="user-btn" @click="openUserPopup" :title="sidebarCollapsed ? (authStore.user?.name || 'Account') : undefined">
          <div class="user-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
          <div v-if="!sidebarCollapsed" class="user-details">
            <div class="user-name">{{ authStore.user?.name }}</div>
            <div class="user-role">{{ authStore.user?.role }}</div>
          </div>
          <svg v-if="!sidebarCollapsed" class="user-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="18 15 12 9 6 15"/></svg>
        </button>
      </div>

      <!-- Collapse toggle — centred on sidebar edge -->
      <button class="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed" :title="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <polyline v-if="!sidebarCollapsed" points="15 18 9 12 15 6"/>
          <polyline v-else points="9 18 15 12 9 6"/>
        </svg>
      </button>
    </aside>

    <!-- ══ MOBILE TOPBAR ════════════════════════════════════════════ -->
    <header class="mobile-topbar">
      <div class="mobile-topbar-brand">
        <img src="/ip-logo.png" alt="InspectPro" class="mobile-brand-logo" />
      </div>
      <div class="mobile-topbar-right">
        <div class="mobile-user-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
        <button class="mobile-menu-btn" @click="drawerOpen = true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
      </div>
    </header>

    <!-- ══ MAIN CONTENT ══════════════════════════════════════════════ -->
    <main class="main-content">
      <router-view />
    </main>

    <!-- ══ MOBILE BOTTOM NAV ════════════════════════════════════════ -->
    <nav class="mobile-bottom-nav">
      <router-link to="/dashboard" class="bnav-item">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
        <span>Dashboard</span>
      </router-link>
      <router-link to="/inspections" class="bnav-item">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="13" y2="16"/></svg>
        <span>Inspections</span>
      </router-link>
      <router-link to="/properties" class="bnav-item">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        <span>Properties</span>
      </router-link>
      <button class="bnav-item bnav-more" @click="drawerOpen = true">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="19" r="1" fill="currentColor"/></svg>
        <span>More</span>
      </button>
    </nav>

    <!-- ══ MOBILE DRAWER ════════════════════════════════════════════ -->
    <Transition name="drawer-fade">
      <div v-if="drawerOpen" class="drawer-backdrop" @click="drawerOpen = false"></div>
    </Transition>
    <Transition name="drawer-slide">
      <div v-if="drawerOpen" class="mobile-drawer">
        <div class="drawer-header">
          <div class="drawer-user">
            <div class="drawer-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
            <div>
              <div class="drawer-name">{{ authStore.user?.name }}</div>
              <div class="drawer-role">{{ authStore.user?.role }}</div>
            </div>
          </div>
          <button class="drawer-close" @click="drawerOpen = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="drawer-nav">
          <button class="drawer-item" @click="navigate('/dashboard')"><span class="drawer-icon">📊</span><span>Dashboard</span></button>
          <button class="drawer-item" @click="navigate('/inspections')"><span class="drawer-icon">📋</span><span>Inspections</span></button>
          <button class="drawer-item" @click="navigate('/properties')"><span class="drawer-icon">🏢</span><span>Properties</span></button>
          <button class="drawer-item" v-if="authStore.isAdmin || authStore.isManager" @click="navigate('/clients')"><span class="drawer-icon">👥</span><span>Clients</span></button>
          <button class="drawer-item" v-if="authStore.isAdmin || authStore.isManager" @click="navigate('/users')"><span class="drawer-icon">👤</span><span>Users</span></button>
          <div class="drawer-divider"></div>
          <button class="drawer-item" v-if="authStore.isAdmin || authStore.isManager" @click="navigate('/settings')"><span class="drawer-icon">⚙️</span><span>Settings</span></button>
          <button class="drawer-item" @click="navigate('/change-password')"><span class="drawer-icon">🔑</span><span>Change Password</span></button>
          <div class="drawer-divider"></div>
          <button class="drawer-item drawer-logout" @click="logout"><span class="drawer-icon">🚪</span><span>Logout</span></button>
        </div>
      </div>
    </Transition>

    <!-- ══ USER POPUP (desktop) ══════════════════════════════════════ -->
    <Transition name="popup-fade">
      <div v-if="userPopupOpen" class="user-popup-backdrop" @click.self="closeUserPopup">
        <div class="user-popup" :class="{ collapsed: sidebarCollapsed }">

          <div class="popup-header">
            <div class="popup-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
            <div class="popup-user-info">
              <div class="popup-name">{{ authStore.user?.name }}</div>
              <div class="popup-role">{{ authStore.user?.role }}</div>
            </div>
            <button class="popup-close" @click="closeUserPopup">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <Transition name="cp-slide">
            <div v-if="showChangePassword" class="cp-form">
              <div v-if="cpSuccess" class="cp-success">✅ Password changed successfully</div>
              <div v-else>
                <div class="cp-field">
                  <label>Current Password</label>
                  <input v-model="cpCurrent" type="password" placeholder="Current password" class="cp-input" @keyup.enter="cpSubmit" />
                </div>
                <div class="cp-field">
                  <label>New Password</label>
                  <input v-model="cpNew" type="password" placeholder="Min 8 chars, upper, lower, number" class="cp-input" @keyup.enter="cpSubmit" />
                  <div class="strength-row">
                    <span :class="['req', cpNew.length >= 8 ? 'met' : '']">8+</span>
                    <span :class="['req', /[A-Z]/.test(cpNew) ? 'met' : '']">A–Z</span>
                    <span :class="['req', /[a-z]/.test(cpNew) ? 'met' : '']">a–z</span>
                    <span :class="['req', /[0-9]/.test(cpNew) ? 'met' : '']">0–9</span>
                  </div>
                </div>
                <div class="cp-field">
                  <label>Confirm New Password</label>
                  <input v-model="cpConfirm" type="password" placeholder="Repeat new password" class="cp-input" @keyup.enter="cpSubmit" />
                </div>
                <div v-if="cpError" class="cp-error">{{ cpError }}</div>
                <div class="cp-actions">
                  <button class="btn-cp-cancel" @click="showChangePassword = false">Cancel</button>
                  <button class="btn-cp-save" :disabled="cpSaving" @click="cpSubmit">
                    {{ cpSaving ? 'Saving…' : 'Change Password' }}
                  </button>
                </div>
              </div>
            </div>
          </Transition>

          <div v-if="!showChangePassword" class="popup-actions">
            <button class="popup-action" @click="showChangePassword = true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              Change Password
            </button>
            <button class="popup-action popup-logout" @click="logout">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
              Logout
            </button>
          </div>

        </div>
      </div>
    </Transition>

  </div>
</template>

<style scoped>
/* ── Base layout ───────────────────────────────────────────────────── */
.layout {
  display: flex;
  min-height: 100vh;
  background: #f1f5f9;
}

/* ── Desktop sidebar ───────────────────────────────────────────────── */
.sidebar {
  width: 260px;
  background: #1e293b;
  color: white;
  display: flex;
  flex-direction: column;
  position: fixed;
  left: 0; top: 0; bottom: 0;
  z-index: 100;
  transition: width 0.25s ease;
  overflow: visible;
}
.sidebar.collapsed { width: 64px; }

/* ── Sidebar header ── */
.sidebar-header {
  padding: 20px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 72px;
  overflow: hidden;
}
.sidebar-logo {
  width: 140px; height: auto; display: block;
  filter: brightness(0) invert(1);
}
.sidebar-logo-icon {
  width: 36px; height: 36px; object-fit: contain;
  filter: brightness(0) invert(1);
}

/* ── Nav items ── */
.sidebar-nav {
  flex: 1;
  padding: 16px 8px;
  overflow-y: auto;
  overflow-x: hidden;
}
.nav-item {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 12px; border-radius: 8px;
  color: #cbd5e1; text-decoration: none;
  transition: all 0.2s; margin-bottom: 2px;
  font-weight: 500; font-size: 14px;
  white-space: nowrap; overflow: hidden;
}
.nav-item:hover { background: rgba(255,255,255,0.1); color: white; }
.nav-item.router-link-active { background: #6366f1; color: white; }
.nav-item .icon { font-size: 18px; width: 22px; text-align: center; flex-shrink: 0; }
.nav-label { transition: opacity 0.15s; }

.collapsed .nav-item { justify-content: center; padding: 11px 0; }
.collapsed .nav-label { opacity: 0; width: 0; overflow: hidden; }

.nav-divider { height: 1px; background: rgba(255,255,255,0.1); margin: 10px 8px; }
.collapsed .nav-divider { margin: 10px 4px; }

/* ── Sidebar footer / user button ── */
.sidebar-footer {
  padding: 12px 8px;
  border-top: 1px solid rgba(255,255,255,0.1);
}
.user-btn {
  width: 100%; display: flex; align-items: center; gap: 10px;
  padding: 10px; background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;
  color: white; cursor: pointer; transition: background 0.2s;
  text-align: left; overflow: hidden;
}
.user-btn:hover { background: rgba(255,255,255,0.12); }
.collapsed .user-btn { justify-content: center; padding: 10px 0; }

.user-avatar {
  width: 34px; height: 34px; background: #6366f1; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 14px; flex-shrink: 0;
}
.user-details { flex: 1; min-width: 0; }
.user-name { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 11px; color: #94a3b8; text-transform: capitalize; }
.user-chevron { color: #64748b; flex-shrink: 0; }

/* ── Collapse toggle — vertically centred on sidebar edge ── */
.sidebar-toggle {
  position: absolute;
  top: 50%;
  right: -14px;
  transform: translateY(-50%);
  width: 28px; height: 28px;
  background: #1e293b;
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 50%;
  color: #94a3b8;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.2s, color 0.2s, box-shadow 0.2s;
  z-index: 101;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}
.sidebar-toggle:hover { background: #334155; color: white; box-shadow: 0 2px 12px rgba(0,0,0,0.4); }

/* ── Main content ── */
.main-content {
  flex: 1;
  margin-left: 260px;
  padding: 32px;
  overflow-y: auto;
  min-height: 100vh;
  transition: margin-left 0.25s ease;
}
.sidebar-is-collapsed .main-content { margin-left: 64px; }

/* ── Mobile elements — hidden on desktop ── */
.mobile-topbar,
.mobile-bottom-nav,
.mobile-drawer,
.drawer-backdrop { display: none; }

/* ══════════════════════════════════════════════════════════════════════
   USER POPUP
   z-index: 500+ ensures it stays above sidebar (100) and everything else
══════════════════════════════════════════════════════════════════════ */
.user-popup-backdrop {
  position: fixed;
  inset: 0;
  z-index: 500;
}
.user-popup {
  position: fixed;
  bottom: 80px;
  left: 272px;
  width: 280px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.08);
  z-index: 501;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  transition: left 0.25s ease;
}
.user-popup.collapsed { left: 76px; }

.popup-header {
  display: flex; align-items: center; gap: 10px;
  padding: 16px; background: #f8fafc;
  border-bottom: 1px solid #f1f5f9;
}
.popup-avatar {
  width: 38px; height: 38px; background: #6366f1; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 15px; color: white; flex-shrink: 0;
}
.popup-user-info { flex: 1; min-width: 0; }
.popup-name { font-weight: 700; font-size: 14px; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.popup-role { font-size: 11px; color: #64748b; text-transform: capitalize; margin-top: 1px; }
.popup-close {
  width: 28px; height: 28px; background: #f1f5f9; border: none; border-radius: 50%;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: #64748b; flex-shrink: 0; transition: background 0.15s;
}
.popup-close:hover { background: #e2e8f0; }

.popup-actions { padding: 8px; }
.popup-action {
  width: 100%; display: flex; align-items: center; gap: 10px;
  padding: 11px 12px; background: none; border: none; border-radius: 8px;
  font-size: 14px; font-weight: 500; color: #374151;
  cursor: pointer; text-align: left; transition: background 0.15s;
}
.popup-action:hover { background: #f8fafc; }
.popup-action svg { flex-shrink: 0; color: #64748b; }
.popup-logout { color: #dc2626; }
.popup-logout:hover { background: #fef2f2; }
.popup-logout svg { color: #dc2626; }

/* ── Change password form inside popup ── */
.cp-form { padding: 16px; border-top: 1px solid #f1f5f9; }
.cp-field { margin-bottom: 14px; }
.cp-field label { display: block; font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 5px; }
.cp-input {
  width: 100%; padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 6px;
  font-size: 13px; font-family: inherit; box-sizing: border-box; transition: border-color 0.15s;
}
.cp-input:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }

.strength-row { display: flex; gap: 5px; margin-top: 6px; }
.req { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 10px; background: #f1f5f9; color: #94a3b8; transition: all 0.2s; }
.req.met { background: #dcfce7; color: #16a34a; }

.cp-error { background: #fef2f2; border: 1px solid #fca5a5; color: #dc2626; padding: 8px 12px; border-radius: 6px; font-size: 12px; margin-bottom: 12px; }
.cp-success { background: #f0fdf4; border: 1px solid #bbf7d0; color: #16a34a; padding: 12px; border-radius: 6px; font-size: 13px; font-weight: 600; text-align: center; }

.cp-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
.btn-cp-cancel { padding: 7px 14px; background: white; border: 1px solid #e2e8f0; color: #64748b; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn-cp-cancel:hover { background: #f8fafc; }
.btn-cp-save { padding: 7px 16px; background: #6366f1; color: white; border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.btn-cp-save:hover:not(:disabled) { background: #4f46e5; }
.btn-cp-save:disabled { background: #94a3b8; cursor: not-allowed; }

/* ══════════════════════════════════════════════════════════════════════
   MOBILE STYLES  ≤ 768px
══════════════════════════════════════════════════════════════════════ */
@media (max-width: 768px) {
  .sidebar { display: none; }
  .sidebar-toggle { display: none; }
  .user-popup { display: none; }
  .layout { flex-direction: column; }

  .main-content {
    margin-left: 0;
    padding: 14px 14px 80px;
    padding-top: calc(52px + 14px);
    min-height: 100vh;
  }

  .mobile-topbar {
    display: flex; align-items: center; justify-content: space-between;
    position: fixed; top: 0; left: 0; right: 0; height: 52px;
    background: #1e293b; padding: 0 16px;
    z-index: 200; border-bottom: 1px solid rgba(255,255,255,0.07);
  }
  .mobile-topbar-brand { display: flex; align-items: center; }
  .mobile-brand-logo { height: 32px; width: auto; filter: brightness(0) invert(1); }
  .mobile-topbar-right { display: flex; align-items: center; gap: 10px; }
  .mobile-user-avatar {
    width: 30px; height: 30px; background: #6366f1; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; color: white;
  }
  .mobile-menu-btn {
    background: none; border: none; color: #94a3b8; cursor: pointer;
    padding: 4px; display: flex; align-items: center; justify-content: center; border-radius: 6px;
  }
  .mobile-menu-btn:hover { background: rgba(255,255,255,0.1); color: white; }

  .mobile-bottom-nav {
    display: flex; position: fixed; bottom: 0; left: 0; right: 0; height: 60px;
    background: white; border-top: 1px solid #e2e8f0;
    z-index: 200; box-shadow: 0 -2px 12px rgba(0,0,0,0.06);
  }
  .bnav-item {
    flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 3px; text-decoration: none; color: #94a3b8; font-size: 10px; font-weight: 600;
    background: none; border: none; cursor: pointer; transition: color 0.15s; padding: 8px 4px;
  }
  .bnav-item.router-link-active { color: #6366f1; }
  .bnav-item:hover { color: #475569; }

  .drawer-backdrop {
    display: block; position: fixed; inset: 0;
    background: rgba(0,0,0,0.45); z-index: 300;
  }
  .mobile-drawer {
    display: flex; flex-direction: column;
    position: fixed; bottom: 0; left: 0; right: 0;
    max-height: 85vh; background: white;
    border-radius: 20px 20px 0 0; z-index: 301;
    overflow-y: auto;
    padding-bottom: env(safe-area-inset-bottom, 16px);
  }
  .drawer-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 20px 20px 14px; border-bottom: 1px solid #f1f5f9;
  }
  .drawer-user { display: flex; align-items: center; gap: 12px; }
  .drawer-avatar {
    width: 40px; height: 40px; background: #6366f1; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 700; color: white;
  }
  .drawer-name { font-size: 14px; font-weight: 700; color: #0f172a; }
  .drawer-role { font-size: 11px; color: #94a3b8; text-transform: capitalize; margin-top: 1px; }
  .drawer-close {
    width: 32px; height: 32px; background: #f1f5f9; border: none; border-radius: 50%;
    cursor: pointer; display: flex; align-items: center; justify-content: center; color: #64748b;
  }
  .drawer-nav { padding: 8px 12px 20px; }
  .drawer-item {
    display: flex; align-items: center; gap: 14px;
    width: 100%; padding: 13px 12px; border: none; background: none;
    font-size: 15px; font-weight: 500; color: #1e293b;
    text-align: left; cursor: pointer; border-radius: 10px; transition: background 0.1s;
  }
  .drawer-item:hover { background: #f8fafc; }
  .drawer-icon { font-size: 18px; width: 26px; text-align: center; }
  .drawer-divider { height: 1px; background: #f1f5f9; margin: 6px 0; }
  .drawer-logout { color: #dc2626; }
  .drawer-logout:hover { background: #fef2f2; }
}

/* ── Transitions ───────────────────────────────────────────────────── */
.drawer-fade-enter-active, .drawer-fade-leave-active { transition: opacity 0.2s; }
.drawer-fade-enter-from, .drawer-fade-leave-to { opacity: 0; }

.drawer-slide-enter-active, .drawer-slide-leave-active { transition: transform 0.25s ease; }
.drawer-slide-enter-from, .drawer-slide-leave-to { transform: translateY(100%); }

.popup-fade-enter-active, .popup-fade-leave-active { transition: opacity 0.15s; }
.popup-fade-enter-from, .popup-fade-leave-to { opacity: 0; }

.cp-slide-enter-active, .cp-slide-leave-active { transition: all 0.2s ease; overflow: hidden; }
.cp-slide-enter-from, .cp-slide-leave-to { opacity: 0; max-height: 0; }
.cp-slide-enter-to, .cp-slide-leave-from { opacity: 1; max-height: 400px; }
</style>
