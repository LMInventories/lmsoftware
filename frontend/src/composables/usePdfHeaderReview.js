/**
 * usePdfHeaderReview — lets the user confirm which PDF-extracted "rooms" are
 * real room headers vs. continuation pages (e.g. "Bedroom 1" / "Bedroom 1 (cont)")
 * before a Keep-Layout import is saved. Un-confirmed rows fold their items into
 * the nearest preceding confirmed header, in document order.
 */
import { ref, computed, watch } from 'vue'

/** Strip continuation markers so 'Bedroom 1 (cont.)' normalises to 'bedroom 1'. */
function _normRoomName(name) {
  let n = (name || '').toLowerCase().trim()
  n = n.replace(/\s*\(?\s*cont(?:inued|'?d)?\.?\s*\)?\s*$/i, '')
  n = n.replace(/\s*[-–—]\s*cont(?:inued|'?d)?\.?\s*$/i, '')
  return n.trim()
}

export function usePdfHeaderReview(parsed) {
  const isHeader          = ref({})   // roomIndex → boolean
  const continuationHint  = ref({})   // roomIndex → name it looks like a continuation of (pre-toggle guess, static)

  function _rebuild() {
    const rooms      = parsed.value?.rooms || []
    const nextHeader = {}
    const nextHint   = {}
    let lastHeaderIdx = null

    rooms.forEach((room, i) => {
      const norm = _normRoomName(room.name)
      const looksLikeContinuation =
        i > 0 && lastHeaderIdx !== null && norm && norm === _normRoomName(rooms[lastHeaderIdx].name)

      if (i === 0 || !looksLikeContinuation) {
        nextHeader[i] = true
        lastHeaderIdx = i
      } else {
        nextHeader[i] = false
        nextHint[i]   = rooms[lastHeaderIdx].name
      }
    })

    isHeader.value         = nextHeader
    continuationHint.value = nextHint
  }

  watch(() => parsed.value?.rooms, _rebuild, { immediate: true })

  /** Index 0 must stay a header — nothing precedes it to merge into. */
  function toggleHeader(index) {
    if (index === 0) return
    isHeader.value = { ...isHeader.value, [index]: !isHeader.value[index] }
  }

  /** Rooms grouped by confirmed header, keeping member provenance for the review UI. */
  const groups = computed(() => {
    const rooms = parsed.value?.rooms || []
    const out   = []
    rooms.forEach((room, i) => {
      if (isHeader.value[i] || out.length === 0) {
        out.push({ name: room.name, headerIndex: i, members: [{ room, index: i }] })
      } else {
        out[out.length - 1].members.push({ room, index: i })
      }
    })
    return out
  })

  /** Final { name, items, _photos?, _photoRefs? }[] ready to send as `parsed.rooms`. */
  const mergedRooms = computed(() => groups.value.map(g => {
    const items      = []
    const photos     = []
    const photoRefs  = []
    let hasPhotos    = false
    let hasPhotoRefs = false

    for (const { room } of g.members) {
      items.push(...(room.items || []))
      if (room._photos)    { hasPhotos = true; photos.push(...room._photos) }
      if (room._photoRefs) { hasPhotoRefs = true; photoRefs.push(...room._photoRefs) }
    }

    const out = { name: g.name, items }
    if (hasPhotos)    out._photos    = photos
    if (hasPhotoRefs) out._photoRefs = photoRefs
    return out
  }))

  return { isHeader, continuationHint, toggleHeader, groups, mergedRooms }
}
