import { ref } from 'vue'

// Module-level state — single instance shared across all components, same
// pattern as useToast.js. Replaces native window.confirm() with a styled
// modal that returns a Promise<boolean>, so call sites just add `await`.
const visible     = ref(false)
const title       = ref('')
const message     = ref('')
const confirmText = ref('Confirm')
const cancelText  = ref('Cancel')
const danger      = ref(false)
let resolvePromise = null

function ask(msg, { title: t = '', confirmText: ct = 'Confirm', cancelText: cxt = 'Cancel', danger: d = false } = {}) {
  message.value = msg
  title.value = t
  confirmText.value = ct
  cancelText.value = cxt
  danger.value = d
  visible.value = true
  return new Promise(resolve => { resolvePromise = resolve })
}

function _settle(result) {
  visible.value = false
  if (resolvePromise) {
    resolvePromise(result)
    resolvePromise = null
  }
}

export function useConfirm() {
  return {
    visible, title, message, confirmText, cancelText, danger,
    ask,
    confirm: () => _settle(true),
    cancel:  () => _settle(false),
  }
}
