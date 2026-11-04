import { ref, watch } from 'vue'

// Filter state that survives page reloads. Stored in localStorage under a key
// scoped to the logged-in user, so different logins on one browser don't share
// filter settings. Only keys present in `defaults` are restored, so adding or
// removing a filter field later never breaks old saved values. Keys listed in
// `exclude` are never saved (e.g. a month picker that would make the list look
// empty on the next visit).
export function usePersistedFilters(name, defaults, { exclude = [] } = {}) {
  let userId = 'anon'
  try { userId = JSON.parse(localStorage.getItem('user') || 'null')?.id ?? 'anon' } catch { /* ignore */ }
  const storageKey = `filters:${name}:${userId}`

  const state = ref({ ...defaults })
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
    if (saved && typeof saved === 'object') {
      for (const k of Object.keys(defaults)) {
        if (exclude.includes(k) || !(k in saved)) continue
        // Only accept values of the same shape (array vs scalar) as the default
        if (Array.isArray(defaults[k]) !== Array.isArray(saved[k])) continue
        state.value[k] = saved[k]
      }
    }
  } catch { /* corrupt or unavailable storage — fall back to defaults */ }

  watch(state, val => {
    try {
      const out = {}
      for (const k of Object.keys(defaults)) if (!exclude.includes(k)) out[k] = val[k]
      localStorage.setItem(storageKey, JSON.stringify(out))
    } catch { /* storage full or blocked — ignore */ }
  }, { deep: true })

  return state
}
