import { defineStore } from 'pinia'
import api from '../services/api'
export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: null,
    isAuthenticated: false
  }),
  getters: {
    isAdmin:   (state) => state.user?.role === 'admin',
    isManager: (state) => state.user?.role === 'manager',
    isClerk:   (state) => state.user?.role === 'clerk',
    isTypist:  (state) => state.user?.role === 'typist' && !state.user?.is_ai,
    isClient:       (state) => state.user?.role === 'client',
    typistMode:     (state) => state.user?.typist_mode ?? null,
    isAiInstant:    (state) => state.user?.typist_mode === 'ai_instant',
    isAiRoom:       (state) => state.user?.typist_mode === 'ai_room',
    isHumanTypist:  (state) => state.user?.typist_mode === 'human',
  },
  actions: {
    async login(credentials) {
      try {
        const response = await api.login(credentials)
        this.token = response.data.token
        this.user = response.data.user
        this.isAuthenticated = true
        localStorage.setItem('token', this.token)
        localStorage.setItem('user', JSON.stringify(this.user))
        return response.data
      } catch (error) {
        console.error('Login failed:', error)
        throw error
      }
    },
    async fetchCurrentUser() {
      try {
        const response = await api.getCurrentUser()
        this.user = response.data
        this.isAuthenticated = true
        localStorage.setItem('user', JSON.stringify(this.user))
        return response.data
      } catch (error) {
        console.error('Failed to fetch user:', error)
        this.logout()
        throw error
      }
    },
    logout() {
      this.user = null
      this.token = null
      this.isAuthenticated = false
      localStorage.removeItem('token')
      localStorage.removeItem('user')
    },
    initAuth() {
      const token = localStorage.getItem('token')
      const user = localStorage.getItem('user')
      if (token && user) {
        this.token = token
        this.user = JSON.parse(user)
        this.isAuthenticated = true
      }
    }
  }
})
