// listen/mediaSession — headset buttons and lock-screen controls for 磨耳朵 (docs/LISTEN_MODE_DESIGN.md §3.5). Where the browser
// has a Media Session, play / pause / previoustrack / nexttrack reach the player and the lock screen names what is playing; where
// it has none (jsdom, older WebViews) or refuses an action, nothing happens — every call is feature-detected and fails silently.
// The controls only show while the shared <audio> element of audio/serverAudio.ts plays; device voices have no media session.

export interface TransportHandlers {
  play(): void;
  pause(): void;
  prev(): void;
  next(): void;
}

export interface NowPlaying {
  /** The headword in 跟着听; in 听写 the caller passes the position instead — the lock screen must not give the word away. */
  title: string;
  album: string;
  playing: boolean;
}

function session(): MediaSession | null {
  return typeof navigator !== 'undefined' && 'mediaSession' in navigator && navigator.mediaSession ? navigator.mediaSession : null;
}

/** Registers the four transport actions; the returned function removes them and clears the lock-screen entry. */
export function bindMediaSession(handlers: TransportHandlers): () => void {
  const media = session();
  if (!media) return () => undefined;
  const actions: [MediaSessionAction, () => void][] = [
    ['play', handlers.play],
    ['pause', handlers.pause],
    ['previoustrack', handlers.prev],
    ['nexttrack', handlers.next],
  ];
  const set = (action: MediaSessionAction, handler: (() => void) | null) => {
    try {
      media.setActionHandler(action, handler);
    } catch {
      /* this browser does not know the action */
    }
  };
  for (const [action, handler] of actions) set(action, handler);
  return () => {
    for (const [action] of actions) set(action, null);
    describeMediaSession(null);
  };
}

/** What the lock screen shows (null clears it). */
export function describeMediaSession(now: NowPlaying | null): void {
  const media = session();
  if (!media) return;
  try {
    media.metadata = now && typeof MediaMetadata === 'function' ? new MediaMetadata({ title: now.title, album: now.album }) : null;
    media.playbackState = now ? (now.playing ? 'playing' : 'paused') : 'none';
  } catch {
    /* a partial implementation: the controls simply stay generic */
  }
}
