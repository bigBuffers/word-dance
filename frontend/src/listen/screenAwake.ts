// listen/screenAwake — keeps the display on while 磨耳朵 plays (docs/LISTEN_MODE_DESIGN.md §3.5, §7.1). The Screen Wake Lock API
// exists only in secure contexts (https, localhost) and not in every WebView: on a plain-http LAN origin there is no
// `navigator.wakeLock` and the device dims on its own schedule — so everything here is feature-detected and fails silently.
// The browser drops the lock whenever the page is hidden; it is asked for again when the page comes back to the foreground.

/** Asks for a screen wake lock until the returned function is called; a no-op where the API is missing or refuses. */
export function keepScreenAwake(): () => void {
  const wakeLock = typeof navigator !== 'undefined' && 'wakeLock' in navigator ? navigator.wakeLock : undefined;
  if (!wakeLock || typeof wakeLock.request !== 'function') return () => undefined;
  let wanted = true;
  let asking = false;
  let sentinel: WakeLockSentinel | null = null;
  const acquire = () => {
    if (!wanted || asking || document.visibilityState !== 'visible') return;
    if (sentinel && !sentinel.released) return;
    asking = true;
    let request: Promise<WakeLockSentinel>;
    try {
      request = wakeLock.request('screen');
    } catch {
      asking = false;
      return;
    }
    request.then(
      (lock) => {
        asking = false;
        if (wanted) sentinel = lock;
        else void lock.release().catch(() => undefined); // released while the request was in flight
      },
      () => {
        asking = false; // refused (battery saver, permissions policy): the screen follows the system setting
      },
    );
  };
  document.addEventListener('visibilitychange', acquire);
  acquire();
  return () => {
    wanted = false;
    document.removeEventListener('visibilitychange', acquire);
    const lock = sentinel;
    sentinel = null;
    if (lock && !lock.released) void lock.release().catch(() => undefined);
  };
}
