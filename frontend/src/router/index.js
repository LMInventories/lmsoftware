import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/dashboard'
    },
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/LoginView.vue')
    },
    {
      path: '/reset-password',
      name: 'ResetPassword',
      component: () => import('../views/ResetPasswordView.vue')
    },

    // All desktop routes wrapped in MainLayout sidebar
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('../views/DashboardView.vue')
        },
        {
          path: 'clients',
          name: 'Clients',
          component: () => import('../views/ClientsView.vue')
        },
        {
          path: 'properties',
          name: 'Properties',
          component: () => import('../views/PropertiesView.vue')
        },
        {
          path: 'properties/:id',
          name: 'PropertyDetail',
          component: () => import('../views/PropertyDetailView.vue')
        },
        {
          path: 'inspections',
          name: 'Inspections',
          component: () => import('../views/InspectionsView.vue')
        },
        {
          path: 'inspections/:id',
          name: 'InspectionDetail',
          component: () => import('../views/InspectionDetailView.vue')
        },
        {
          path: 'inspections/:id/report',
          name: 'InspectionReport',
          component: () => import('../views/InspectionReportView.vue')
        },
        {
          path: 'users',
          name: 'Users',
          component: () => import('../views/UsersView.vue')
        },
        {
          path: 'settings',
          name: 'Settings',
          component: () => import('../views/SettingsView.vue')
        },
        {
          path: 'settings/templates/new',
          name: 'TemplateNew',
          component: () => import('../views/settings/TemplateEditorView.vue')
        },
        {
          path: 'settings/templates/:id',
          name: 'TemplateEdit',
          component: () => import('../views/settings/TemplateEditorView.vue')
        },
        {
          path: 'settings/fixed-sections',
          name: 'FixedSections',
          component: () => import('../views/settings/FixedSectionsSettings.vue')
        },
        {
          path: 'change-password',
          name: 'ChangePassword',
          component: () => import('../views/ChangePasswordView.vue')
        },
      ]
    },

    // Mobile routes — no layout wrapper. Lazy-loaded like everything else so the
    // desktop clerk's initial bundle never ships mobile-only code it never touches.
    {
      path: '/mobile/login',
      name: 'MobileLogin',
      component: () => import('../views-mobile/MobileLogin.vue'),
    },
    {
      path: '/mobile',
      name: 'MobileHome',
      component: () => import('../views-mobile/MobileHome.vue'),
      meta: { requiresMobileAuth: true },
    },
    {
      path: '/mobile/inspection/:id',
      name: 'MobilePropertyView',
      component: () => import('../views-mobile/MobilePropertyView.vue'),
      meta: { requiresMobileAuth: true },
    },
    {
      path: '/mobile/inspection/:id/report',
      name: 'MobileReportEditor',
      component: () => import('../views-mobile/MobileReportEditor.vue'),
      meta: { requiresMobileAuth: true },
    },
  ]
})

// Navigation guard
function _tokenIsValid(token) {
  if (!token) return false
  try {
    // Decode the JWT payload (second segment) without any external library.
    // atob() requires standard base64; JWT uses base64url, so swap the chars first.
    const base64Url = token.split('.')[1]
    if (!base64Url) return false
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(atob(base64))
    // exp is in seconds; Date.now() is in milliseconds
    return typeof payload.exp === 'number' && payload.exp * 1000 > Date.now()
  } catch {
    // Malformed token — treat as invalid so the user gets redirected to login
    return false
  }
}

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  const valid  = _tokenIsValid(token)

  // Clear an expired token so old stale JWTs don't persist in localStorage
  if (token && !valid) {
    localStorage.removeItem('token')
  }

  if (to.meta.requiresMobileAuth && !valid) {
    next('/mobile/login')
    return
  }
  if (to.meta.requiresAuth && !valid) {
    next('/login')
  } else if (to.path === '/login' && valid) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
