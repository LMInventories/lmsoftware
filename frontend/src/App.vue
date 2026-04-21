<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from './stores/auth'
import ToastContainer from './components/ToastContainer.vue'

const authStore = useAuthStore()

onMounted(() => {
  authStore.initAuth()
})
</script>

<template>
  <router-view />
  <ToastContainer />
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  color: #1e293b;
  min-height: 100vh;
  background: #f8fafc;
}

.page { max-width: 1400px; margin: 0 auto; }
.page-header { display: none !important; }
.page-description { color: #64748b; font-size: 16px; }

.form-group { margin-bottom: 20px; }
.form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #475569; font-size: 14px; }
.input-field, .select-field, .textarea-field { width: 100%; padding: 10px 14px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; font-family: inherit; transition: all 0.2s; }
.input-field:focus, .select-field:focus, .textarea-field:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
.textarea-field { resize: vertical; min-height: 100px; }

.btn-primary { padding: 12px 24px; background: #6366f1; color: white; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.btn-primary:hover { background: #4f46e5; }
.btn-primary:disabled { background: #94a3b8; cursor: not-allowed; }
.btn-secondary { padding: 12px 24px; background: #f1f5f9; color: #475569; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.btn-secondary:hover { background: #e2e8f0; }
.btn-danger { padding: 12px 24px; background: #fee2e2; color: #991b1b; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.btn-danger:hover { background: #fecaca; }

.card { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 24px; }
.loading { text-align: center; padding: 60px; color: #64748b; font-size: 16px; }
.empty-state { text-align: center; padding: 80px 20px; }
.empty-state .empty-icon { font-size: 64px; display: block; margin-bottom: 16px; }
.empty-state h3 { font-size: 20px; font-weight: 600; color: #1e293b; margin-bottom: 8px; }
.empty-state p { color: #64748b; margin-bottom: 24px; }

.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: white; border-radius: 12px; max-width: 600px; width: 100%; max-height: 90vh; overflow-y: auto; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); }
.modal-header { padding: 24px; border-bottom: 1px solid #e5e7eb; }
.modal-header h2 { font-size: 24px; font-weight: 600; color: #1e293b; }
.modal-body { padding: 24px; }
.modal-footer { padding: 24px; border-top: 1px solid #e5e7eb; display: flex; justify-content: flex-end; gap: 12px; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: #f1f5f9; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 5px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
</style>
