<script setup>
import { useConfirm } from '../composables/useConfirm'
const { visible, title, message, confirmText, cancelText, danger, confirm, cancel } = useConfirm()
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay confirm-overlay" @click.self="cancel">
      <div class="confirm-modal" role="alertdialog" aria-modal="true">
        <h3 v-if="title" class="confirm-title">{{ title }}</h3>
        <p class="confirm-message">{{ message }}</p>
        <div class="confirm-actions">
          <button class="confirm-btn confirm-btn-cancel" @click="cancel">{{ cancelText }}</button>
          <button
            class="confirm-btn"
            :class="danger ? 'confirm-btn-danger' : 'confirm-btn-primary'"
            @click="confirm"
          >{{ confirmText }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.confirm-overlay { z-index: 100000; }

.confirm-modal {
  background: #fff;
  border-radius: 12px;
  max-width: 420px;
  width: 100%;
  padding: 24px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.confirm-title {
  font-size: 17px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.confirm-message {
  font-size: 14px;
  color: #475569;
  line-height: 1.5;
  white-space: pre-line;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 22px;
}

.confirm-btn {
  padding: 9px 18px;
  border-radius: 7px;
  border: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.confirm-btn-cancel { background: #f1f5f9; color: #334155; }
.confirm-btn-cancel:hover { background: #e2e8f0; }

.confirm-btn-primary { background: #4f46e5; color: #fff; }
.confirm-btn-primary:hover { background: #4338ca; }

.confirm-btn-danger { background: #dc2626; color: #fff; }
.confirm-btn-danger:hover { background: #b91c1c; }
</style>
