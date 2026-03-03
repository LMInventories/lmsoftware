import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import MainLayout from '../layouts/MainLayout.vue'
import MobileHome from '../views-mobile/MobileHome.vue'
import MobileLogin from '../views-mobile/MobileLogin.vue'
import MobilePropertyView from '../views-mobile/MobilePropertyView.vue'
import MobileReportEditor from '../views-mobile/MobileReportEditor.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/login', name: 'Login', component: LoginView },

    // ── Desktop routes — wrapped in MainLayout sidebar ──────────────────
    {
      path: '/',
      component: MainLayout,
      meta: { requiresAuth: true },
      children: [
        { path: 'dashboard',  name: 'Dashboard',  component: () => import('../views/DashboardView.vue') },
        { path: 'clients',    name: 'Clients',    component: () => import('../views/ClientsView.vue') },
        { path: 'properties', name: 'Properties', component: () => import('../views/PropertiesView.vue') },
        { path: 'inspections',         name: 'Inspections',      component: () => import('../views/InspectionsView.vue') },
        { path: 'inspections/:id',     name: 'InspectionDetail', component: () => import('../views/InspectionDetailView.vue') },
        { path: 'inspections/:id/report', name: 'InspectionReport', component: () => import('../views/InspectionReportView.vue') },
        { path: 'users',      name: 'Users',      component: () => import('../views/UsersView.vue') },

        // Settings — Admin + Manager only (guard applied in MainLayout nav; route itself just requires auth)
        { path: 'settings',                   name: 'Settings',     component: () => import('../views/SettingsView.vue') },
        { path: 'settings/templates/new',     name: 'TemplateNew',  component: () => import('../views/TemplateEditorView.vue') },
        { path: 'settings/templates/:id',     name: 'TemplateEdit', component: () => import('../views/TemplateEditorView.vue') },

        { path: 'change-password', name: 'ChangePassword', component: () => import('../views/ChangePasswordView.vue') },
      ]
    },

    // ── Mobile routes — no layout wrapper ──────────────────────────────
    { path: '/mobile/login',                 name: 'MobileLogin',       component: MobileLogin },
    { path: '/mobile',                       name: 'MobileHome',        component: MobileHome,        meta: { requiresMobileAuth: true } },
    { path: '/mobile/inspection/:id',        name: 'MobilePropertyView', component: MobilePropertyView, meta: { requiresMobileAuth: true } },
    { path: '/mobile/inspection/:id/report', name: 'MobileReportEditor', component: MobileReportEditor, meta: { requiresMobileAuth: true } },
  ]
})

// ── Navigation guard ────────────────────────────────────────────────────────
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')

  if (to.meta.requiresMobileAuth && !token) {
    next('/mobile/login')
    return
  }
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
