<script setup>
import { useToast } from '../composables/useToast'
const { toasts, dismiss } = useToast()
</script>

<template>
  <Teleport to="body">
    <div class="toast-container" aria-live="polite">
      <TransitionGroup name="toast" tag="div" class="toast-list">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="toast"
          :class="`toast--${toast.type}`"
          role="alert"
        >
          <!-- Icon -->
          <div class="toast-icon">
            <!-- Success -->
            <svg v-if="toast.type === 'success'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <!-- Error -->
            <svg v-else-if="toast.type === 'error'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            <!-- Warning -->
            <svg v-else-if="toast.type === 'warning'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <!-- Info -->
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </div>

          <span class="toast-message">{{ toast.message }}</span>

          <button class="toast-close" @click="dismiss(toast.id)" aria-label="Dismiss">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>

          <!-- Progress bar -->
          <div class="toast-progress" :class="`toast-progress--${toast.type}`"></div>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 99999;
  pointer-events: none;
  width: 380px;
  max-width: calc(100vw - 40px);
}

.toast-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px 18px;
  border-radius: 10px;
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.1),
    0 2px 4px -2px rgba(0, 0, 0, 0.1),
    0 0 0 1px rgba(0, 0, 0, 0.05);
  pointer-events: all;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
  overflow: hidden;
}

.toast--success { background: #f0fdf4; color: #166534; }
.toast--error   { background: #fef2f2; color: #991b1b; }
.toast--warning { background: #fffbeb; color: #92400e; }
.toast--info    { background: #eff6ff; color: #1e40af; }

.toast-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.toast-message { flex: 1; }

.toast-close {
  flex-shrink: 0;
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  opacity: 0.45;
  display: flex;
  align-items: center;
  padding: 3px;
  border-radius: 4px;
  transition: opacity 0.15s;
}
.toast-close:hover { opacity: 0.9; }

/* Shrinking progress bar at bottom */
.toast-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 3px;
  width: 100%;
  border-radius: 0 0 10px 10px;
  animation: shrink 3.5s linear forwards;
}

.toast-progress--success { background: #16a34a; }
.toast-progress--error   { background: #dc2626; animation-duration: 5s; }
.toast-progress--warning { background: #d97706; animation-duration: 4s; }
.toast-progress--info    { background: #2563eb; }

@keyframes shrink {
  from { width: 100%; }
  to   { width: 0%; }
}

/* Vue TransitionGroup */
.toast-enter-active {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.toast-leave-active {
  transition: all 0.25s ease-in;
  position: absolute;
  width: 100%;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(110%) scale(0.9);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(110%);
}
.toast-move {
  transition: transform 0.3s ease;
}
</style>
