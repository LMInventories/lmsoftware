import { ref, watch } from 'vue'
import api from '../services/api'

/**
 * Tracks which users have marked themselves unavailable for a given date + time slot.
 *
 * @param {() => string} getDate  YYYY-MM-DD (or ISO datetime) — empty means "no date chosen"
 * @param {() => string} getTime  'am' | 'pm' | 'anytime' | 'specific:HH_MM'
 * @returns {{ unavailableIds: import('vue').Ref<number[]> }}
 */
export function useUnavailableUsers(getDate, getTime) {
  const unavailableIds = ref([])
  let seq = 0

  watch(
    () => [getDate(), getTime()],
    async ([date, time]) => {
      const mine = ++seq
      if (!date) { unavailableIds.value = []; return }
      try {
        const res = await api.http.get('/api/availability/unavailable', {
          params: { date: String(date).slice(0, 10), time: time || 'anytime' },
        })
        if (mine === seq) unavailableIds.value = res.data.user_ids || []
      } catch {
        if (mine === seq) unavailableIds.value = []
      }
    },
    { immediate: true },
  )

  return { unavailableIds }
}

/** Build a conduct_time_preference value from a form's time fields. */
export function timePrefFromForm(pref, hour, minute) {
  return pref === 'specific' ? `specific:${hour}_${minute}` : (pref || 'anytime')
}
