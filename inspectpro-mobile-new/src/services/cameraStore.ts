/**
 * cameraStore — module-level singleton for camera → screen photo handoff.
 *
 * Pattern:
 *  1. Before navigating to CameraScreen, call setCameraTarget(handler).
 *  2. CameraScreen calls triggerCapture(fileUri) after saving the photo.
 *  3. When the originating screen regains focus it checks processPendingPhotos()
 *     as a fallback (in case the handler was cleared due to JS GC / re-mount).
 */

type CameraHandler = (fileUri: string) => void

let _handler: CameraHandler | null = null
let _pendingUri: string | null = null

/**
 * Register the callback that should receive the captured photo URI.
 * Call this immediately before navigating to CameraScreen.
 */
export function setCameraTarget(handler: CameraHandler): void {
  _handler = handler
  _pendingUri = null
}

/**
 * Called by CameraScreen once the photo file has been saved to documentDirectory.
 * Invokes the registered handler immediately if present, otherwise parks the URI
 * so the originating screen can collect it via processPendingPhotos().
 */
export function triggerCapture(fileUri: string): void {
  if (_handler) {
    _handler(fileUri)
    _handler = null
    _pendingUri = null
  } else {
    // Handler was cleared (e.g. component unmounted) — park for later collection
    _pendingUri = fileUri
  }
}

/**
 * Call this in a useFocusEffect on the originating screen as a safety net.
 * Returns the pending URI and clears it, or returns null if nothing is waiting.
 */
export function processPendingPhotos(): string | null {
  const uri = _pendingUri
  _pendingUri = null
  _handler = null
  return uri
}

/**
 * Clear all state — call when navigating away without taking a photo,
 * or on screen unmount.
 */
export function clearCameraTarget(): void {
  _handler = null
  _pendingUri = null
}
