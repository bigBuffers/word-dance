// listen/screenAwake (docs/LISTEN_MODE_DESIGN.md §3.5): a no-op without the Wake Lock API (jsdom, plain-http origins), a lock
// while wanted, asked for again when the page returns to the foreground, released on demand, silent when the browser refuses.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { keepScreenAwake } from './screenAwake';

interface FakeLock {
  released: boolean;
  release: () => Promise<void>;
}

function installWakeLock(refuse = false) {
  const locks: FakeLock[] = [];
  const request = vi.fn((_type: string) => {
    if (refuse) return Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' }));
    const lock: FakeLock = {
      released: false,
      release: vi.fn(async () => {
        lock.released = true;
      }),
    };
    locks.push(lock);
    return Promise.resolve(lock);
  });
  Object.defineProperty(navigator, 'wakeLock', { value: { request }, configurable: true });
  return { request, locks };
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
}

const settle = async () => {
  for (let i = 0; i < 4; i += 1) await Promise.resolve();
};

afterEach(() => {
  delete (navigator as unknown as Record<string, unknown>)['wakeLock'];
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
});

describe('keepScreenAwake', () => {
  it('does nothing where the browser has no Wake Lock API', () => {
    expect('wakeLock' in navigator).toBe(false); // jsdom — and every plain-http origin
    const release = keepScreenAwake();
    expect(() => release()).not.toThrow();
  });

  it('holds a screen lock until released', async () => {
    const { request, locks } = installWakeLock();
    const release = keepScreenAwake();
    expect(request).toHaveBeenCalledWith('screen');
    await settle();
    expect(locks).toHaveLength(1);
    release();
    expect(locks[0]!.release).toHaveBeenCalledTimes(1);
    setVisibility('visible'); // the listener is gone: no new request
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('asks again when the page comes back to the foreground (the browser drops the lock while hidden)', async () => {
    const { request, locks } = installWakeLock();
    const release = keepScreenAwake();
    await settle();
    setVisibility('visible'); // still held: nothing to do
    expect(request).toHaveBeenCalledTimes(1);
    locks[0]!.released = true; // what the browser does when the tab is hidden
    setVisibility('hidden');
    expect(request).toHaveBeenCalledTimes(1);
    setVisibility('visible');
    expect(request).toHaveBeenCalledTimes(2);
    await settle();
    release();
    expect(locks[1]!.release).toHaveBeenCalledTimes(1);
    expect(locks[0]!.release).not.toHaveBeenCalled(); // already released by the browser
  });

  it('releases a lock that arrives after the caller stopped wanting it', async () => {
    const { locks } = installWakeLock();
    const release = keepScreenAwake();
    release(); // paused before the request settled
    await settle();
    expect(locks[0]!.release).toHaveBeenCalledTimes(1);
  });

  it('stays silent when the browser refuses the lock', async () => {
    const { request } = installWakeLock(true);
    const release = keepScreenAwake();
    await settle();
    expect(request).toHaveBeenCalledTimes(1);
    expect(() => release()).not.toThrow();
  });
});
