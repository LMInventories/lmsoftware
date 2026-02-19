import { ref } from 'vue'

// Module-level state — single instance shared across all components
const toasts = ref([])
let nextId = 0

function addToast(message, type = 'info', duration = 3500) {
  const id = ++nextId
  toasts.value.push({ id, message, type, leaving: false })
  setTimeout(() => dismiss(id), duration)
}

function dismiss(id) {
  const toast = toasts.value.find(t => t.id === id)
  if (!toast) return
  toast.leaving = true
  setTimeout(() => {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }, 350)
}

export function useToast() {
  return {
    toasts,
    dismiss,
    success: (msg, duration)  => addToast(msg, 'success', duration ?? 3500),
    error:   (msg, duration)  => addToast(msg, 'error',   duration ?? 5000),
    info:    (msg, duration)  => addToast(msg, 'info',    duration ?? 3500),
    warning: (msg, duration)  => addToast(msg, 'warning', duration ?? 4000),
  }
}
