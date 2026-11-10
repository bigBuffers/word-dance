// audio/serverAudio (FRONTEND §6.4): the clip URL played straight from one element (synchronously, inside the gesture), the enabled
// flag, the diagnosis of a clip the element could not play (the API error → a reason the hook maps to copy), and interruption by a
// later play / stop.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_EXPIRED_EVENT } from '@/api/client';
import { ServerAudioError, clipUrl, diagnose, playServerAudio, resetServerAudio, serverAudioEnabled, setServerAudio, stopServerAudio } from './serverAudio';

const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>();
const played: HTMLAudioElement[] = [];
let playImpl: (el: HTMLAudioElement) => Promise<void> | undefined;

function audioResponse(bytes = 600): Response {
  return new Response(new Uint8Array(bytes), { status: 200, headers: { 'Content-Type': 'audio/mp4' } });
}

function errorResponse(status: number, code: string, details?: Record<string, unknown>): Response {
  return new Response(JSON.stringify({ error: { code, message: 'x', ...(details ? { details } : {}) } }), { status, headers: { 'Content-Type': 'application/json' } });
}

const notSupported = () => Promise.reject(Object.assign(new Error('The element has no supported sources.'), { name: 'NotSupportedError' }));

async function reason(p: Promise<unknown>): Promise<string> {
  try {
    await p;
    return 'resolved';
  } catch (e) {
    return e instanceof ServerAudioError ? e.reason : `other:${String(e)}`;
  }
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLAudioElement) {
    played.push(this);
    return playImpl(this) as Promise<void>;
  });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined); // jsdom's pause() only logs "not implemented"
  resetServerAudio();
  setServerAudio(true);
  fetchMock.mockReset();
  played.length = 0;
  playImpl = () => Promise.resolve();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('clipUrl', () => {
  it('asks /media/audio with the text and accent URL-encoded', () => {
    expect(clipUrl("rock 'n' roll", 'en-GB')).toBe('/media/audio?text=rock+%27n%27+roll&accent=en-GB');
  });
});

describe('the enabled flag', () => {
  it('mirrors ServerFlags.audio and treats null / undefined as off', () => {
    setServerAudio(null);
    expect(serverAudioEnabled()).toBe(false);
    setServerAudio(true);
    expect(serverAudioEnabled()).toBe(true);
    setServerAudio(undefined);
    expect(serverAudioEnabled()).toBe(false);
  });
});

describe('playServerAudio', () => {
  it('plays the clip URL from one element at the rate, synchronously, without a fetch, and resolves when it ends', async () => {
    const promise = playServerAudio('farmer', 'en-US', 0.92);
    expect(played).toHaveLength(1); // play() ran inside the call: the tap's gesture covers it
    const el = played[0]!;
    expect(el.getAttribute('src')).toBe('/media/audio?text=farmer&accent=en-US');
    expect(el.playbackRate).toBe(0.92);
    expect(el.preload).toBe('auto');
    expect(fetchMock).not.toHaveBeenCalled(); // the browser loads (and caches) the clip itself
    el.dispatchEvent(new Event('ended'));
    await expect(promise).resolves.toBeUndefined();
    const again = playServerAudio('farmer', 'en-GB');
    expect(played).toHaveLength(2);
    expect(played[1]).toBe(el); // one shared element
    expect(el.getAttribute('src')).toBe('/media/audio?text=farmer&accent=en-GB');
    el.dispatchEvent(new Event('ended'));
    await again;
  });

  it('asks the server why when the element cannot play the source, and turns itself off on 503 {reason: off}', async () => {
    playImpl = notSupported;
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'off' }));
    expect(await reason(playServerAudio('farmer', 'en-US'))).toBe('off');
    expect(fetchMock).toHaveBeenCalledWith('/media/audio?text=farmer&accent=en-US', { credentials: 'same-origin', headers: { Accept: 'audio/*' } });
    expect(serverAudioEnabled()).toBe(false);
  });

  it('maps the other failures to reasons the hook can phrase', async () => {
    playImpl = notSupported;
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'busy' }));
    expect(await reason(playServerAudio('a', 'en-US'))).toBe('busy');
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'failed' }));
    expect(await reason(playServerAudio('b', 'en-US'))).toBe('failed');
    fetchMock.mockResolvedValueOnce(errorResponse(429, 'rate_limited', { retry_after_s: 30 }));
    expect(await reason(playServerAudio('c', 'en-US'))).toBe('busy');
    fetchMock.mockResolvedValueOnce(errorResponse(400, 'validation_error', { fields: { text: 'x' } }));
    expect(await reason(playServerAudio('d', 'en-US'))).toBe('invalid');
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    expect(await reason(playServerAudio('e', 'en-US'))).toBe('network');
    fetchMock.mockResolvedValueOnce(new Response('oops', { status: 500 }));
    expect(await reason(playServerAudio('f', 'en-US'))).toBe('failed');
    fetchMock.mockResolvedValueOnce(audioResponse());
    expect(await reason(playServerAudio('g', 'en-US'))).toBe('decode'); // the server serves it: the element is the problem
    expect(serverAudioEnabled()).toBe(true); // none of these switches the server off
    expect(fetchMock).toHaveBeenCalledTimes(7); // one diagnosis per failure, nothing on success
  });

  it('the error event of the element leads to the same diagnosis, once', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(errorResponse(503, 'audio_unavailable', { reason: 'busy' })));
    const p = playServerAudio('farmer', 'en-US');
    const el = played[0]!;
    el.dispatchEvent(new Event('error'));
    el.dispatchEvent(new Event('error'));
    expect(await reason(p)).toBe('busy');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reports a lost session as auth and lets client.ts announce it', async () => {
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    playImpl = notSupported;
    fetchMock.mockResolvedValueOnce(errorResponse(401, 'unauthorized'));
    expect(await reason(playServerAudio('farmer', 'en-US'))).toBe('auth');
    expect(expired).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
  });

  it('distinguishes an autoplay refusal from a broken clip', async () => {
    playImpl = () => Promise.reject(Object.assign(new Error('gesture'), { name: 'NotAllowedError' }));
    expect(await reason(playServerAudio('a', 'en-US'))).toBe('blocked');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('a later play settles the clip playing (resolved, not rejected) and a stop pauses the element', async () => {
    const first = playServerAudio('first', 'en-US');
    const second = playServerAudio('second', 'en-US');
    await expect(first).resolves.toBeUndefined(); // cut short by the next play
    expect(played).toHaveLength(2);
    expect(played[1]!.getAttribute('src')).toBe('/media/audio?text=second&accent=en-US');
    stopServerAudio();
    await expect(second).resolves.toBeUndefined();
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('a superseded call never diagnoses or toasts: its pending play() rejection is swallowed', async () => {
    let rejectPlay!: (e: unknown) => void;
    playImpl = () => new Promise<void>((_resolve, reject) => (rejectPlay = reject));
    const slow = playServerAudio('slow', 'en-US');
    playImpl = () => Promise.resolve();
    const fast = playServerAudio('fast', 'en-US');
    rejectPlay(Object.assign(new Error('aborted'), { name: 'AbortError' })); // the source changed under the pending play()
    expect(await reason(slow)).toBe('resolved');
    expect(fetchMock).not.toHaveBeenCalled();
    played[1]!.dispatchEvent(new Event('ended'));
    await expect(fast).resolves.toBeUndefined();
  });
});

describe('diagnose', () => {
  it('reads the API error behind the URL', async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'failed' }));
    expect(await diagnose('x', 'en-GB')).toBe('failed');
    expect(fetchMock).toHaveBeenCalledWith('/media/audio?text=x&accent=en-GB', { credentials: 'same-origin', headers: { Accept: 'audio/*' } });
  });
});

describe('clipUrl (FRONTEND §6.4)', () => {
  it("carries the server's voice fingerprint as `v` when one is known, so a switched voice is a new URL for the browser cache", () => {
    setServerAudio(true);
    expect(clipUrl('farmer', 'en-US')).toBe('/media/audio?text=farmer&accent=en-US');
    setServerAudio(true, 'k1a2b3c4');
    expect(clipUrl('The farmer grows rice.', 'en-GB')).toBe('/media/audio?text=The+farmer+grows+rice.&accent=en-GB&v=k1a2b3c4');
    setServerAudio(true, null); // an older server without the field
    expect(clipUrl('farmer', 'en-US')).not.toContain('v=');
    setServerAudio(true, 'k1a2b3c4');
    resetServerAudio();
    expect(clipUrl('farmer', 'en-US')).not.toContain('v=');
  });
});
