import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import DashboardView from '../views/DashboardView.vue'
import ClientsView from '../views/ClientsView.vue'
import PropertiesView from '../views/PropertiesView.vue'
import InspectionsView from '../views/InspectionsView.vue'
import InspectionDetailView from '../views/InspectionDetailView.vue'
import InspectionReportView from '../views/InspectionReportView.vue'
import UsersView from '../views/UsersView.vue'
import SettingsView from '../views/SettingsView.vue'
import TemplateEditorView from '../views/TemplateEditorView.vue'
import MobileHome         from '../views-mobile/MobileHome.vue'
import MobileLogin        from '../views-mobile/MobileLogin.vue'
import MobilePropertyView from '../views-mobile/MobilePropertyView.vue'
import MobileReportEditor from '../views-mobile/MobileReportEditor.vue'

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
      component: LoginView
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: DashboardView,
      meta: { requiresAuth: true }
    },
    {
      path: '/clients',
      name: 'Clients',
      component: ClientsView,
      meta: { requiresAuth: true }
    },
    {
      path: '/properties',
      name: 'Properties',
      component: PropertiesView,
      meta: { requiresAuth: true }
    },
    {
      path: '/inspections',
      name: 'Inspections',
      component: InspectionsView,
      meta: { requiresAuth: true }
    },
    {
      path: '/inspections/:id',
      name: 'InspectionDetail',
      component: InspectionDetailView,
      meta: { requiresAuth: true }
    },
    {
      path: '/inspections/:id/report',
      name: 'InspectionReport',
      component: InspectionReportView,
      meta: { requiresAuth: true }
    },
    {
      path: '/users',
      name: 'Users',
      component: UsersView,
      meta: { requiresAuth: true }
    },
    {
      path: '/settings',
      name: 'Settings',
      component: SettingsView,
      meta: { requiresAuth: true }
    },
    {
      path: '/settings/templates/new',
      name: 'TemplateNew',
      component: TemplateEditorView,
      meta: { requiresAuth: true }
    },
    {
      path: '/settings/templates/:id',
      name: 'TemplateEdit',
      component: TemplateEditorView,
      meta: { requiresAuth: true }
    },
    {
      path: '/mobile/login',
      name: 'MobileLogin',
      component: MobileLogin,
    },
    {
      path: '/mobile',
      name: 'MobileHome',
      component: MobileHome,
      meta: { requiresMobileAuth: true },
    },
    {
      path: '/mobile/inspection/:id',
      name: 'MobilePropertyView',
      component: MobilePropertyView,
      meta: { requiresMobileAuth: true },
    },
    {
      path: '/mobile/inspection/:id/report',
      name: 'MobileReportEditor',
      component: MobileReportEditor,
      meta: { requiresMobileAuth: true },
    },
  ]
})

// Navigation guard
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')

  // Mobile auth guard — redirect to mobile login if not logged in
  if (to.meta.requiresMobileAuth && !token) {
    next('/mobile/login')
    return
  }

  // Desktop auth guard
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
