// audio/utter over the real audio/serverAudio module (FRONTEND §6.4; utter.test.ts fakes it): the chain 磨耳朵 depends on —
// clip after clip on the one shared <audio> element, `play()` called synchronously, an autoplay refusal reported as blocked and
// playable from the tap, a stop that settles the clip, a refused Chinese clip that switches Chinese off for the session, a clip
// the browser paused by itself (blocked: a tap resumes), and a server that cannot be reached (asked again, then offline).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { STALL_MS, resetServerAudio, serverAudioSpeaks, setServerAudio } from './serverAudio';
import { BUSY_RETRY_MS, resetUtter, stopUtter, utter, utterAvailable } from './utter';

const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>();
const played: HTMLAudioElement[] = [];
let playImpl: (el: HTMLAudioElement) => Promise<void> | undefined;

const unavailable = (reason: string) =>
  new Response(JSON.stringify({ error: { code: 'audio_unavailable', message: 'x', details: { reason } } }), { status: 503, headers: { 'Content-Type': 'application/json' } });
const refuse = (name: string) => () => Promise.reject(Object.assign(new Error(name), { name }));
const ended = () => played[played.length - 1]!.dispatchEvent(new Event('ended'));

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLAudioElement) {
    played.push(this);
    return playImpl(this) as Promise<void>;
  });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
  resetServerAudio();
  resetUtter();
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

describe('utter over the server clips', () => {
  it('chains English and Chinese clips on the one shared element, each resolving when its clip ends', async () => {
    setServerAudio(true, 'k1', true);
    const word = utter('share', 'en-GB', 0.92);
    expect(played).toHaveLength(1); // play() ran inside the call
    const el = played[0]!;
    expect(el.getAttribute('src')).toBe('/media/audio?text=share&accent=en-GB&v=k1');
    expect(el.playbackRate).toBe(0.92);
    ended();
    expect(await word).toBe('ended');
    const gloss = utter('分享，共用', 'zh-CN', 1);
    expect(played[1]).toBe(el); // the element a tap once unlocked keeps playing without further taps
    expect(el.getAttribute('src')).toContain('accent=zh-CN');
    expect(el.playbackRate).toBe(1);
    ended();
    expect(await gloss).toBe('ended');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('reports an autoplay refusal as blocked and plays the same clip from the tap that follows', async () => {
    setServerAudio(true);
    playImpl = refuse('NotAllowedError');
    expect(await utter('share', 'en-US', 0.92)).toBe('blocked');
    expect(fetchMock).not.toHaveBeenCalled(); // nothing to diagnose
    playImpl = () => Promise.resolve();
    const tapped = utter('share', 'en-US', 0.92);
    expect(played).toHaveLength(2);
    ended();
    expect(await tapped).toBe('ended');
  });

  it('stopUtter() pauses the element and settles the clip as ended', async () => {
    setServerAudio(true);
    const pending = utter('share', 'en-US', 0.92);
    stopUtter();
    expect(await pending).toBe('ended');
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it('a Chinese clip the server cannot make switches Chinese off: asked once, then left to the device — English goes on', async () => {
    setServerAudio(true, '', true);
    expect(utterAvailable('zh-CN')).toBe(true);
    playImpl = refuse('NotSupportedError');
    fetchMock.mockResolvedValueOnce(unavailable('failed'));
    expect(await utter('你好', 'zh-CN', 1)).toBe('unspoken'); // jsdom has no voice to fall back to
    expect(serverAudioSpeaks('zh-CN')).toBe(false);
    expect(utterAvailable('zh-CN')).toBe(false); // the listen page now leaves Chinese out and says so
    expect(await utter('你好', 'zh-CN', 1)).toBe('unspoken');
    expect(played).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1); // the server is not asked for Chinese again
    playImpl = () => Promise.resolve();
    const english = utter('share', 'en-US', 0.92);
    ended();
    expect(await english).toBe('ended');
  });

  it('a clip the browser paused by itself is blocked — the caller offers the tap — and the tap plays it again', async () => {
    setServerAudio(true);
    const pending = utter('share', 'en-US', 0.92);
    played[0]!.dispatchEvent(new Event('pause')); // jsdom's element: paused, not ended — a pause in the middle of the clip
    expect(await pending).toBe('blocked');
    expect(fetchMock).not.toHaveBeenCalled();
    const tapped = utter('share', 'en-US', 0.92);
    expect(played).toHaveLength(2);
    ended();
    expect(await tapped).toBe('ended');
  });

  it('a server that cannot be reached is asked again and heard once it is back; one that stays away is offline, not unspoken', async () => {
    vi.useFakeTimers();
    setServerAudio(true);
    playImpl = refuse('NotSupportedError');
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch')); // the diagnosis cannot reach it either
    const restarted = utter('share', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS);
    expect(played).toHaveLength(2);
    playImpl = () => Promise.resolve(); // an ordinary restart: back within 3 s
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS);
    expect(played).toHaveLength(3);
    ended();
    expect(await restarted).toBe('ended');

    playImpl = refuse('NotSupportedError');
    const gone = utter('share', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(2 * BUSY_RETRY_MS);
    expect(await gone).toBe('offline'); // jsdom has no voice to fall back to: the playlist parks instead of running out
    expect(played).toHaveLength(6);
    expect(utterAvailable('en-US')).toBe(true); // the route stays on: the next tap asks again
  });

  it('a clip that never starts playing is given up after the stall time and not asked again', async () => {
    vi.useFakeTimers();
    setServerAudio(true);
    const pending = utter('share', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(STALL_MS);
    expect(await pending).toBe('offline');
    expect(played).toHaveLength(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('a clip the read-only cache lacks is unspoken here, and the route stays on for the next one', async () => {
    setServerAudio(true);
    playImpl = refuse('NotSupportedError');
    fetchMock.mockResolvedValueOnce(unavailable('missing'));
    expect(await utter('zebra', 'en-US', 0.92)).toBe('unspoken');
    expect(utterAvailable('en-US')).toBe(true);
    playImpl = () => Promise.resolve();
    const next = utter('apple', 'en-US', 0.92);
    ended();
    expect(await next).toBe('ended');
  });
});
