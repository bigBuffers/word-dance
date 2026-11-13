// listen/mediaSession (docs/LISTEN_MODE_DESIGN.md §3.5): the four transport actions reach the handlers, the lock screen gets a
// title and a playback state, unbinding clears both — and nothing throws where the browser has no Media Session or refuses an action.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { bindMediaSession, describeMediaSession } from './mediaSession';

class FakeMetadata {
  title: string;
  album: string;
  constructor(init: { title: string; album: string }) {
    this.title = init.title;
    this.album = init.album;
  }
}

function installMediaSession(unknownAction?: string) {
  const handlers = new Map<string, (() => void) | null>();
  const media = {
    metadata: null as FakeMetadata | null,
    playbackState: 'none',
    setActionHandler: vi.fn((action: string, handler: (() => void) | null) => {
      if (action === unknownAction) throw new TypeError(`unknown action ${action}`);
      handlers.set(action, handler);
    }),
  };
  Object.defineProperty(navigator, 'mediaSession', { value: media, configurable: true });
  vi.stubGlobal('MediaMetadata', FakeMetadata);
  return { media, handlers };
}

const transport = () => ({ play: vi.fn(), pause: vi.fn(), prev: vi.fn(), next: vi.fn() });

afterEach(() => {
  delete (navigator as unknown as Record<string, unknown>)['mediaSession'];
  vi.unstubAllGlobals();
});

describe('mediaSession helpers', () => {
  it('are no-ops where the browser has no Media Session', () => {
    expect('mediaSession' in navigator).toBe(false); // jsdom
    const unbind = bindMediaSession(transport());
    expect(() => describeMediaSession({ title: 'share', album: 'x', playing: true })).not.toThrow();
    expect(() => unbind()).not.toThrow();
  });

  it('bind play / pause / previoustrack / nexttrack to the transport and unbind them again', () => {
    const { handlers } = installMediaSession();
    const t = transport();
    const unbind = bindMediaSession(t);
    expect([...handlers.keys()]).toEqual(['play', 'pause', 'previoustrack', 'nexttrack']);
    handlers.get('play')?.();
    handlers.get('pause')?.();
    handlers.get('previoustrack')?.();
    handlers.get('nexttrack')?.();
    expect([t.play, t.pause, t.prev, t.next].map((fn) => fn.mock.calls.length)).toEqual([1, 1, 1, 1]);
    unbind();
    expect([...handlers.values()]).toEqual([null, null, null, null]);
  });

  it('name what is playing on the lock screen and clear it on unbind', () => {
    const { media } = installMediaSession();
    const unbind = bindMediaSession(transport());
    describeMediaSession({ title: 'share', album: 'album', playing: true });
    expect(media.metadata).toMatchObject({ title: 'share', album: 'album' });
    expect(media.playbackState).toBe('playing');
    describeMediaSession({ title: 'share', album: 'album', playing: false });
    expect(media.playbackState).toBe('paused');
    unbind();
    expect(media.metadata).toBeNull();
    expect(media.playbackState).toBe('none');
  });

  it('skip an action this browser does not know and keep the others', () => {
    const { handlers } = installMediaSession('previoustrack');
    const t = transport();
    const unbind = bindMediaSession(t);
    expect([...handlers.keys()]).toEqual(['play', 'pause', 'nexttrack']);
    expect(() => unbind()).not.toThrow();
  });
});
