// audio/serverAudio (FRONTEND §6.4): the clip URL played straight from one element (synchronously, inside the gesture), the enabled
// flag, the diagnosis of a clip the element could not play (the API error → a reason the hook maps to copy), interruption by a
// later play / stop, a clip the browser pauses by itself or never starts, and Chinese: `serverAudioSpeaks` per language and the
// session-level switch-off after a refused Chinese clip.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_EXPIRED_EVENT } from '@/api/client';
import { STALL_MS, ServerAudioError, clipUrl, diagnose, playServerAudio, resetServerAudio, serverAudioEnabled, serverAudioSpeaks, setServerAudio, stopServerAudio } from './serverAudio';

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
  vi.useRealTimers();
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
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'missing' }));
    expect(await reason(playServerAudio('b2', 'en-US'))).toBe('missing'); // the read-only cache lacks this clip: the route stays on
    expect(serverAudioEnabled()).toBe(true);
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
    expect(fetchMock).toHaveBeenCalledTimes(8); // one diagnosis per failure, nothing on success
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

describe('a clip the browser pauses by itself, or never starts', () => {
  /** jsdom's element is for ever `paused` and never `ended`: the test plays the browser. */
  function drive(el: HTMLAudioElement) {
    const flags = { paused: false, ended: false };
    Object.defineProperty(el, 'paused', { get: () => flags.paused, configurable: true });
    Object.defineProperty(el, 'ended', { get: () => flags.ended, configurable: true });
    return flags;
  }

  it('rejects `paused` when the user agent pauses the element mid-clip (audio focus lost, a call, the headset unplugged)', async () => {
    const p = playServerAudio('farmer', 'en-US');
    const el = played[0]!;
    const flags = drive(el);
    flags.paused = true;
    el.dispatchEvent(new Event('pause'));
    expect(await reason(p)).toBe('paused');
    expect(fetchMock).not.toHaveBeenCalled(); // the server did nothing wrong: no diagnosis
  });

  it('is not fooled by the pause event of a natural end, nor by the stale one of its own pause() landing on the next clip', async () => {
    const first = playServerAudio('first', 'en-US');
    const el = played[0]!;
    const flags = drive(el);
    flags.paused = true;
    flags.ended = true;
    el.dispatchEvent(new Event('pause')); // the end of playback: `pause` (ended = true), then `ended`
    el.dispatchEvent(new Event('ended'));
    await expect(first).resolves.toBeUndefined();

    flags.ended = false;
    const second = playServerAudio('second', 'en-US'); // stopServerAudio() paused the element; its event is still queued…
    flags.paused = false; // …and lands when play() has already started the next clip
    el.dispatchEvent(new Event('pause'));
    el.dispatchEvent(new Event('ended'));
    await expect(second).resolves.toBeUndefined();

    const cut = playServerAudio('third', 'en-US');
    stopServerAudio();
    flags.paused = true;
    el.dispatchEvent(new Event('pause')); // the learner's own stop: settled already, and nobody listens any more
    await expect(cut).resolves.toBeUndefined();
  });

  it('gives a clip that has not started playing within the stall time up as network; one that plays is never cut', async () => {
    vi.useFakeTimers();
    expect(STALL_MS).toBe(20_000); // the server may hold a request 8 s for a slot, plus the synthesis
    const hung = reason(playServerAudio('farmer', 'en-US'));
    let answer: string | null = null;
    void hung.then((r) => (answer = r));
    await vi.advanceTimersByTimeAsync(STALL_MS - 1);
    expect(answer).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    expect(await hung).toBe('network');
    expect(fetchMock).not.toHaveBeenCalled(); // a diagnosis would hang on the same network

    const long = playServerAudio('The farmer grows rice.', 'en-US');
    played[1]!.dispatchEvent(new Event('playing'));
    await vi.advanceTimersByTimeAsync(10 * STALL_MS);
    played[1]!.dispatchEvent(new Event('ended'));
    await expect(long).resolves.toBeUndefined();

    void playServerAudio('rice', 'en-US');
    stopServerAudio();
    expect(vi.getTimerCount()).toBe(0); // a settled clip leaves no watchdog behind
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

describe('Chinese clips (ServerFlags.audio_zh; docs/LISTEN_MODE_DESIGN.md §6.1)', () => {
  it('serverAudioSpeaks: English follows the provider flag, Chinese also needs the provider to have a Chinese voice', () => {
    expect(serverAudioSpeaks('en-US')).toBe(true); // beforeEach: a provider, nothing said about Chinese
    expect(serverAudioSpeaks('en-GB')).toBe(true);
    expect(serverAudioSpeaks('zh-CN')).toBe(false);
    setServerAudio(true, 'k1', true);
    expect(serverAudioSpeaks('zh-CN')).toBe(true);
    setServerAudio(true, 'k1', null); // an older server without the field
    expect(serverAudioSpeaks('zh-CN')).toBe(false);
    setServerAudio(false, '', true); // no provider at all: the flag alone speaks nothing
    expect(serverAudioSpeaks('zh-CN')).toBe(false);
    expect(serverAudioSpeaks('en-US')).toBe(false);
  });

  it('asks for a Chinese clip with accent=zh-CN, on the same shared element', async () => {
    setServerAudio(true, 'k1', true);
    const en = playServerAudio('share', 'en-US', 0.92);
    const el = played[0]!;
    el.dispatchEvent(new Event('ended'));
    await en;
    const zh = playServerAudio('分享，共用', 'zh-CN', 1);
    expect(played[1]).toBe(el);
    expect(el.getAttribute('src')).toBe(`/media/audio?text=${encodeURIComponent('分享，共用')}&accent=zh-CN&v=k1`);
    expect(clipUrl('你好', 'zh-CN')).toBe(`/media/audio?text=${encodeURIComponent('你好')}&accent=zh-CN&v=k1`);
    el.dispatchEvent(new Event('ended'));
    await expect(zh).resolves.toBeUndefined();
    expect(serverAudioSpeaks('zh-CN')).toBe(true);
  });

  it('a Chinese clip the server could not make (failed) or would not take (invalid) switches Chinese off for the session — English stays on', async () => {
    setServerAudio(true, '', true);
    playImpl = notSupported;
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'failed' })); // no Chinese voice after all
    expect(await reason(playServerAudio('你好', 'zh-CN'))).toBe('failed');
    expect(serverAudioSpeaks('zh-CN')).toBe(false);
    expect(serverAudioSpeaks('en-US')).toBe(true);
    setServerAudio(true, '', true); // the next /api/auth/me repeats the flag: the session's verdict stands
    expect(serverAudioSpeaks('zh-CN')).toBe(false);

    resetServerAudio();
    setServerAudio(true, '', true);
    fetchMock.mockResolvedValueOnce(errorResponse(400, 'validation_error', { fields: { accent: 'x' } })); // an older server knows no zh-CN
    expect(await diagnose('你好', 'zh-CN')).toBe('invalid');
    expect(serverAudioSpeaks('zh-CN')).toBe(false);
    expect(serverAudioEnabled()).toBe(true);
  });

  it('busy, missing, network and decode leave Chinese on, and an English failure never touches it', async () => {
    setServerAudio(true, '', true);
    playImpl = notSupported;
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'busy' }));
    expect(await reason(playServerAudio('你好', 'zh-CN'))).toBe('busy');
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'missing' }));
    expect(await reason(playServerAudio('你好', 'zh-CN'))).toBe('missing');
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    expect(await reason(playServerAudio('你好', 'zh-CN'))).toBe('network');
    fetchMock.mockResolvedValueOnce(audioResponse());
    expect(await reason(playServerAudio('你好', 'zh-CN'))).toBe('decode');
    fetchMock.mockResolvedValueOnce(errorResponse(503, 'audio_unavailable', { reason: 'failed' }));
    expect(await reason(playServerAudio('share', 'en-US'))).toBe('failed');
    fetchMock.mockResolvedValueOnce(errorResponse(400, 'validation_error', { fields: { text: 'x' } }));
    expect(await reason(playServerAudio('@@', 'en-GB'))).toBe('invalid');
    expect(serverAudioSpeaks('zh-CN')).toBe(true);
  });
});

describe('a diagnosis a newer call overtook', () => {
  it('reports the older call as interrupted, never with its reason (the hook must not speak the older text)', async () => {
    playImpl = notSupported;
    let answer!: (r: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { answer = resolve; }));
    const older = playServerAudio('older', 'en-US');
    await new Promise((r) => setTimeout(r, 0)); // the element's rejection reached explain(): the diagnosis is in flight
    playImpl = () => Promise.resolve();
    const newer = playServerAudio('newer', 'en-US');
    answer(errorResponse(503, 'audio_unavailable', { reason: 'missing' }));
    expect(await reason(older)).toBe('interrupted');
    stopServerAudio();
    await newer;
  });
});
