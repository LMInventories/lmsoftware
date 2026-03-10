<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router    = useRouter()
const authStore = useAuthStore()

const drawerOpen = ref(false)

function logout() {
  authStore.logout()
  router.push('/login')
  drawerOpen.value = false
}

function navigate(path) {
  router.push(path)
  drawerOpen.value = false
}
</script>

<template>
  <div class="layout">

    <!-- ══ DESKTOP SIDEBAR ══════════════════════════════════════════ -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <img src="/ip-logo.png" alt="InspectPro" class="sidebar-logo" />
      </div>

      <nav class="sidebar-nav">
        <router-link to="/dashboard" class="nav-item">
          <span class="icon">📊</span><span>Dashboard</span>
        </router-link>
        <router-link to="/inspections" class="nav-item">
          <span class="icon">📋</span><span>Inspections</span>
        </router-link>
        <router-link to="/properties" class="nav-item">
          <span class="icon">🏢</span><span>Properties</span>
        </router-link>
        <router-link to="/clients" class="nav-item" v-if="authStore.isAdmin || authStore.isManager">
          <span class="icon">👥</span><span>Clients</span>
        </router-link>
        <router-link to="/users" class="nav-item" v-if="authStore.isAdmin || authStore.isManager">
          <span class="icon">👤</span><span>Users</span>
        </router-link>
        <div class="nav-divider"></div>
        <router-link to="/settings" class="nav-item" v-if="authStore.isAdmin || authStore.isManager">
          <span class="icon">⚙️</span><span>Settings</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="user-info">
          <div class="user-avatar">{{ authStore.user?.name?.charAt(0) || 'U' }}</div>
          <div class="user-details">
            <div class="user-name">{{ authStore.user?.name }}</div>
            <div class="user-role">{{ authStore.user?.role }}</div>
          </div>
        </div>
        <button @click="logout" class="btn-logout">🚪 Logout</button>
      </div>
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
          <button class="drawer-item" @click="navigate('/dashboard')">
            <span class="drawer-icon">📊</span><span>Dashboard</span>
          </button>
          <button class="drawer-item" @click="navigate('/inspections')">
            <span class="drawer-icon">📋</span><span>Inspections</span>
          </button>
          <button class="drawer-item" @click="navigate('/properties')">
            <span class="drawer-icon">🏢</span><span>Properties</span>
          </button>
          <button class="drawer-item" v-if="authStore.isAdmin || authStore.isManager" @click="navigate('/clients')">
            <span class="drawer-icon">👥</span><span>Clients</span>
          </button>
          <button class="drawer-item" v-if="authStore.isAdmin || authStore.isManager" @click="navigate('/users')">
            <span class="drawer-icon">👤</span><span>Users</span>
          </button>

          <div class="drawer-divider"></div>

          <button class="drawer-item" v-if="authStore.isAdmin || authStore.isManager" @click="navigate('/settings')">
            <span class="drawer-icon">⚙️</span><span>Settings</span>
          </button>
          <button class="drawer-item" @click="navigate('/change-password')">
            <span class="drawer-icon">🔑</span><span>Change Password</span>
          </button>

          <div class="drawer-divider"></div>

          <button class="drawer-item drawer-logout" @click="logout">
            <span class="drawer-icon">🚪</span><span>Logout</span>
          </button>
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
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  background: white;
}
.sidebar-logo {
  width: 160px;
  height: auto;
  display: block;
  margin: 0 auto;
}

.sidebar-nav { flex: 1; padding: 16px 12px; overflow-y: auto; }

.nav-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; border-radius: 8px;
  color: #cbd5e1; text-decoration: none;
  transition: all 0.2s; margin-bottom: 4px; font-weight: 500;
}
.nav-item:hover { background: rgba(255,255,255,0.1); color: white; }
.nav-item.router-link-active { background: #6366f1; color: white; }
.nav-item .icon { font-size: 20px; width: 24px; text-align: center; }

.nav-divider { height: 1px; background: rgba(255,255,255,0.1); margin: 12px 8px; }

.sidebar-footer { padding: 16px; border-top: 1px solid rgba(255,255,255,0.1); }
.user-info { display: flex; align-items: center; gap: 12px; padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px; margin-bottom: 12px; }
.user-avatar { width: 40px; height: 40px; background: #6366f1; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 16px; flex-shrink: 0; }
.user-details { flex: 1; min-width: 0; }
.user-name { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 12px; color: #94a3b8; text-transform: capitalize; }

.btn-logout { width: 100%; padding: 10px; background: rgba(239,68,68,0.1); color: #fca5a5; border: 1px solid rgba(239,68,68,0.2); border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.btn-logout:hover { background: rgba(239,68,68,0.2); color: #fef2f2; }

/* ── Main content ──────────────────────────────────────────────────── */
.main-content {
  flex: 1;
  margin-left: 260px;
  padding: 32px;
  overflow-y: auto;
  min-height: 100vh;
}

/* ── Mobile elements — hidden on desktop ───────────────────────────── */
.mobile-topbar,
.mobile-bottom-nav,
.mobile-drawer,
.drawer-backdrop { display: none; }

/* ══════════════════════════════════════════════════════════════════════
   MOBILE STYLES  ≤ 768px
══════════════════════════════════════════════════════════════════════ */
@media (max-width: 768px) {

  /* Hide desktop sidebar */
  .sidebar { display: none; }

  /* Layout becomes full-width column */
  .layout { flex-direction: column; }

  .main-content {
    margin-left: 0;
    padding: 14px 14px 80px;   /* bottom pad clears the nav bar */
    padding-top: calc(52px + 14px); /* clears the topbar */
    min-height: 100vh;
  }

  /* ── Topbar ── */
  .mobile-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: fixed;
    top: 0; left: 0; right: 0;
    height: 52px;
    background: #1e293b;
    padding: 0 16px;
    z-index: 200;
    border-bottom: 1px solid rgba(255,255,255,0.07);
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
    padding: 4px; display: flex; align-items: center; justify-content: center;
    border-radius: 6px;
  }
  .mobile-menu-btn:hover { background: rgba(255,255,255,0.1); color: white; }

  /* ── Bottom nav ── */
  .mobile-bottom-nav {
    display: flex;
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 60px;
    background: white;
    border-top: 1px solid #e2e8f0;
    z-index: 200;
    box-shadow: 0 -2px 12px rgba(0,0,0,0.06);
  }

  .bnav-item {
    flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 3px; text-decoration: none; color: #94a3b8; font-size: 10px; font-weight: 600;
    background: none; border: none; cursor: pointer;
    transition: color 0.15s;
    padding: 8px 4px;
  }
  .bnav-item.router-link-active { color: #6366f1; }
  .bnav-item:hover { color: #475569; }
  .bnav-more { color: #94a3b8; }

  /* ── Drawer backdrop ── */
  .drawer-backdrop {
    display: block;
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.45);
    z-index: 300;
  }

  /* ── Drawer ── */
  .mobile-drawer {
    display: flex;
    flex-direction: column;
    position: fixed;
    bottom: 0; left: 0; right: 0;
    max-height: 85vh;
    background: white;
    border-radius: 20px 20px 0 0;
    z-index: 301;
    overflow-y: auto;
    padding-bottom: env(safe-area-inset-bottom, 16px);
  }

  .drawer-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 20px 20px 14px;
    border-bottom: 1px solid #f1f5f9;
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
    width: 32px; height: 32px; background: #f1f5f9; border: none;
    border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center;
    color: #64748b;
  }

  .drawer-nav { padding: 8px 12px 20px; }

  .drawer-item {
    display: flex; align-items: center; gap: 14px;
    width: 100%; padding: 13px 12px; border: none; background: none;
    font-size: 15px; font-weight: 500; color: #1e293b;
    text-align: left; cursor: pointer; border-radius: 10px;
    transition: background 0.1s;
  }
  .drawer-item:hover { background: #f8fafc; }
  .drawer-icon { font-size: 18px; width: 26px; text-align: center; }

  .drawer-divider { height: 1px; background: #f1f5f9; margin: 6px 0; }

  .drawer-logout { color: #dc2626; }
  .drawer-logout:hover { background: #fef2f2; }
}

/* ── Drawer transitions ────────────────────────────────────────────── */
.drawer-fade-enter-active, .drawer-fade-leave-active { transition: opacity 0.2s; }
.drawer-fade-enter-from, .drawer-fade-leave-to { opacity: 0; }

.drawer-slide-enter-active, .drawer-slide-leave-active { transition: transform 0.25s ease; }
.drawer-slide-enter-from, .drawer-slide-leave-to { transform: translateY(100%); }
</style>
