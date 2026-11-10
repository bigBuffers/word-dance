// useSpeech inside the native shell (FRONTEND §6.4 / §6.6): the TTS plugin speaks, the hook reports supported + voicesReady without
// speechSynthesis (Android's WebView has none), `speaking` follows the plugin promise, and a rejected plugin falls back to the
// server's clip when the server has one — the toast speaks only when nothing could.
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const native = vi.hoisted(() => ({ speakNative: vi.fn(async (_text: string, _lang: string, _rate: number) => undefined), stopNativeSpeech: vi.fn(async () => undefined) }));
const server = vi.hoisted(() => ({ enabled: false, play: vi.fn<(text: string, accent: string, rate: number) => Promise<void>>(async () => undefined), stop: vi.fn() }));
const toastApi = vi.hoisted(() => ({ toast: vi.fn(), success: vi.fn(), error: vi.fn(), dismiss: vi.fn(), dismissAll: vi.fn() }));
vi.mock('@/hooks/useToast', () => ({ useToast: () => toastApi }));
vi.mock('@/native/capacitor', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/native/capacitor')>()), isNative: () => true, ...native }));
vi.mock('@/audio/serverAudio', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/audio/serverAudio')>()),
  serverAudioEnabled: () => server.enabled,
  playServerAudio: server.play,
  stopServerAudio: server.stop,
}));

import { ServerAudioError } from '@/audio/serverAudio';
import { zh } from '@/i18n/zh';
import { speak, speechAvailable, speechRoute, speechSupported, useSpeech } from './useSpeech';

const unavailable = () => Object.assign(new Error('Not yet initialized or not available on this device.'), { code: 'UNAVAILABLE' });

async function settle() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

afterEach(() => {
  vi.clearAllMocks();
  server.enabled = false;
});

describe('useSpeech in the native shell', () => {
  it('speak() goes to the plugin and reports success although the WebView has no speechSynthesis', () => {
    expect(speechSupported()).toBe(false);
    expect(speechAvailable()).toBe(true);
    expect(speechRoute('en-US')).toBe('native');
    expect(speak('abandon', 'en-GB')).toBe(true);
    expect(native.speakNative).toHaveBeenCalledWith('abandon', 'en-GB', 0.92);
  });

  it('the hook is supported, has voices and tracks speaking across the plugin promise', async () => {
    let finish!: () => void;
    native.speakNative.mockImplementationOnce(() => new Promise<undefined>((resolve) => (finish = () => resolve(undefined))));
    const { result } = renderHook(() => useSpeech('en-US'));
    expect(result.current.supported).toBe(true);
    expect(result.current.voicesReady).toBe(true);
    let ok = false;
    act(() => {
      ok = result.current.speak('apple');
    });
    expect(ok).toBe(true);
    expect(result.current.speaking).toBe(true);
    await act(async () => {
      finish();
      await Promise.resolve();
    });
    expect(result.current.speaking).toBe(false);
    act(() => result.current.cancel());
    expect(native.stopNativeSpeech).toHaveBeenCalledTimes(1);
    expect(server.stop).toHaveBeenCalled(); // a server clip still playing is silenced before the plugin speaks and on cancel
  });

  it('without a server provider a rejected plugin means a missing voice (no second chance exists)', async () => {
    native.speakNative.mockImplementationOnce(() => Promise.reject(new Error('This language is not supported.')));
    const { result } = renderHook(() => useSpeech('en-US'));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenCalledWith(zh.word.voiceMissing);
    expect(server.play).not.toHaveBeenCalled();
    expect(result.current.speaking).toBe(false);
  });

  it('an engine that never initialised (code UNAVAILABLE — no TTS engine in the container) is served by the server clip, silently', async () => {
    server.enabled = true;
    native.speakNative.mockImplementationOnce(() => Promise.reject(unavailable()));
    const { result } = renderHook(() => useSpeech('en-GB'));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(server.play).toHaveBeenCalledWith('apple', 'en-GB', 0.92);
    expect(toastApi.error).not.toHaveBeenCalled();
    expect(result.current.speaking).toBe(false);
    // the module-level speak() (auto-pronounce) takes the same road
    native.speakNative.mockImplementationOnce(() => Promise.reject(unavailable()));
    expect(speak('pear', 'en-US')).toBe(true);
    await settle();
    expect(server.play).toHaveBeenLastCalledWith('pear', 'en-US', 0.92);
  });

  it('phrases what went wrong when the server could not help either', async () => {
    server.enabled = true;
    native.speakNative.mockImplementation(() => Promise.reject(unavailable()));
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('network')));
    const { result } = renderHook(() => useSpeech('en-US'));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceFetchFailed);
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('failed')));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceServerFailed);
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('invalid')));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceTextUnsupported);
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('off')));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceMissing);
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('missing'))); // the tablet's path: no plugin voice, the server's read-only cache lacks this clip
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceClipMissing);
    expect(result.current.speaking).toBe(false);
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('blocked')));
    toastApi.error.mockClear();
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).not.toHaveBeenCalled(); // an autoplay refusal is not the learner's problem
    native.speakNative.mockReset();
    native.speakNative.mockImplementation(async () => undefined);
  });
});
