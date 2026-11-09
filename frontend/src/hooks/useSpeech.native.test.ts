// useSpeech inside the native shell (FRONTEND §6.4 / §6.6): the TTS plugin speaks, the hook reports supported + voicesReady without
// speechSynthesis (Android's WebView has none), and `speaking` follows the plugin promise.
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const native = vi.hoisted(() => ({ speakNative: vi.fn(async (_text: string, _lang: string, _rate: number) => undefined), stopNativeSpeech: vi.fn(async () => undefined) }));
const toastApi = vi.hoisted(() => ({ toast: vi.fn(), success: vi.fn(), error: vi.fn(), dismiss: vi.fn(), dismissAll: vi.fn() }));
vi.mock('@/hooks/useToast', () => ({ useToast: () => toastApi }));
vi.mock('@/native/capacitor', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/native/capacitor')>()), isNative: () => true, ...native }));

import { zh } from '@/i18n/zh';
import { speak, speechAvailable, speechSupported, useSpeech } from './useSpeech';

describe('useSpeech in the native shell', () => {
  it('speak() goes to the plugin and reports success although the WebView has no speechSynthesis', () => {
    expect(speechSupported()).toBe(false);
    expect(speechAvailable()).toBe(true);
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
  });

  it('reports a missing voice (the plugin rejected) instead of staying silently mute', async () => {
    native.speakNative.mockImplementationOnce(() => Promise.reject(new Error('This language is not supported.')));
    const { result } = renderHook(() => useSpeech('en-US'));
    await act(async () => {
      result.current.speak('apple');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(toastApi.error).toHaveBeenCalledWith(zh.word.voiceMissing);
    expect(result.current.speaking).toBe(false);
  });

  it('tells the learner to try again when the engine is merely not initialised yet (code UNAVAILABLE)', async () => {
    native.speakNative.mockImplementationOnce(() => Promise.reject(Object.assign(new Error('Not yet initialized'), { code: 'UNAVAILABLE' })));
    const { result } = renderHook(() => useSpeech('en-US'));
    await act(async () => {
      result.current.speak('apple');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceNotReady);
  });
});
