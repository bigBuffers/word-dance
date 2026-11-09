// useSpeech in a browser (FRONTEND §6.4): voice choice, the route chosen per call — the Web Speech API with an English voice (or no
// voice list yet), else the server's clips when the server has a provider, else the browser default —, the hook's `supported` flag,
// the copy per failure, and one voice at a time across routes and taps.
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const server = vi.hoisted(() => ({ enabled: false, play: vi.fn<(text: string, accent: string, rate: number) => Promise<void>>(async () => undefined), stop: vi.fn() }));
const toastApi = vi.hoisted(() => ({ toast: vi.fn(), success: vi.fn(), error: vi.fn(), dismiss: vi.fn(), dismissAll: vi.fn() }));
vi.mock('@/hooks/useToast', () => ({ useToast: () => toastApi }));
vi.mock('@/audio/serverAudio', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/audio/serverAudio')>()),
  serverAudioEnabled: () => server.enabled,
  playServerAudio: server.play,
  stopServerAudio: server.stop,
}));

import { ServerAudioError } from '@/audio/serverAudio';
import { zh } from '@/i18n/zh';
import { pickVoice, speak, speechAvailable, speechFailureCopy, speechRoute, speechSupported, useSpeech } from './useSpeech';

const voice = (name: string, lang: string) => ({ name, lang }) as SpeechSynthesisVoice;


/** A fake Web Speech API with the given voices; `remove()` restores jsdom's bare window. */
function installSpeech(voices: SpeechSynthesisVoice[]) {
  const w = window as unknown as Record<string, unknown>;
  const synth = { getVoices: vi.fn(() => voices), speak: vi.fn(), cancel: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() };
  class Utterance {
    text: string;
    lang = '';
    rate = 1;
    voice: SpeechSynthesisVoice | null = null;
    constructor(text: string) {
      this.text = text;
    }
  }
  w['speechSynthesis'] = synth as unknown as SpeechSynthesis;
  w['SpeechSynthesisUtterance'] = Utterance;
  return {
    synth,
    remove() {
      delete w['speechSynthesis'];
      delete w['SpeechSynthesisUtterance'];
    },
  };
}

async function settle() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

afterEach(() => {
  vi.clearAllMocks();
  server.enabled = false;
});

describe('pickVoice (FRONTEND §6.4)', () => {
  it('prefers an exact-lang voice from Google/Microsoft/Samantha/Daniel', () => {
    const voices = [voice('Alex', 'en-US'), voice('Google US English', 'en-US'), voice('Daniel', 'en-GB')];
    expect(pickVoice(voices, 'en-US')?.name).toBe('Google US English');
    expect(pickVoice(voices, 'en-GB')?.name).toBe('Daniel');
  });

  it('falls back to the first exact-lang voice, normalising en_GB style tags', () => {
    expect(pickVoice([voice('Alex', 'en-US'), voice('Kate', 'en_GB')], 'en-GB')?.name).toBe('Kate');
    expect(pickVoice([voice('Alex', 'en-US'), voice('Kate', 'en-GB')], 'en-US')?.name).toBe('Alex');
  });

  it('falls back to any English voice, else undefined', () => {
    expect(pickVoice([voice('Ting-Ting', 'zh-CN'), voice('Moira', 'en-IE')], 'en-US')?.name).toBe('Moira');
    expect(pickVoice([voice('Ting-Ting', 'zh-CN')], 'en-US')).toBeUndefined();
    expect(pickVoice([], 'en-GB')).toBeUndefined();
  });
});

describe('speak() without speechSynthesis (jsdom)', () => {
  it('returns false when the server has no clips either', () => {
    expect(speechSupported()).toBe(false);
    expect(speechAvailable()).toBe(false);
    expect(speechRoute('en-US')).toBeNull();
    expect(speak('abandon', 'en-US')).toBe(false);
    expect(server.play).not.toHaveBeenCalled();
  });

  it('plays the server clip when the server has a provider', async () => {
    server.enabled = true;
    expect(speechAvailable()).toBe(true);
    expect(speechRoute('en-GB')).toBe('server');
    expect(speak('abandon', 'en-GB')).toBe(true);
    await settle();
    expect(server.play).toHaveBeenCalledWith('abandon', 'en-GB', 0.92);
  });
});

describe('speechRoute with the Web Speech API present', () => {
  it('uses the browser voice when an English one is listed, the server when none is, the browser default when the server is off too', () => {
    const speech = installSpeech([voice('Samantha', 'en-US')]);
    try {
      expect(speechRoute('en-US')).toBe('synth');
      server.enabled = true;
      expect(speechRoute('en-US')).toBe('synth'); // an English voice beats the network
      speech.synth.getVoices.mockReturnValue([voice('Ting-Ting', 'zh-CN')]);
      expect(speechRoute('en-US')).toBe('server');
      speech.synth.getVoices.mockReturnValue([]); // Chrome fills the list asynchronously: no verdict yet → the browser default, not the Mac's voice
      expect(speechRoute('en-US')).toBe('synth');
      speech.synth.getVoices.mockReturnValue([voice('Ting-Ting', 'zh-CN')]);
      server.enabled = false;
      expect(speechRoute('en-US')).toBe('synth');
    } finally {
      speech.remove();
    }
  });

  it('the synth route silences a server clip still playing, the server route the browser queue', async () => {
    const speech = installSpeech([voice('Samantha', 'en-US')]);
    try {
      server.enabled = true;
      expect(speak('apple', 'en-US')).toBe(true);
      expect(server.stop).toHaveBeenCalledTimes(1);
      expect(speech.synth.cancel).toHaveBeenCalledTimes(1);
      expect(speech.synth.speak).toHaveBeenCalledTimes(1);
      speech.synth.getVoices.mockReturnValue([voice('Ting-Ting', 'zh-CN')]);
      expect(speak('pear', 'en-US')).toBe(true);
      await settle();
      expect(speech.synth.cancel).toHaveBeenCalledTimes(2);
      expect(server.play).toHaveBeenCalledWith('pear', 'en-US', 0.92);
    } finally {
      speech.remove();
    }
  });

  it('a server that turns out to be off falls back to the browser default voice, silently', async () => {
    const speech = installSpeech([voice('Ting-Ting', 'zh-CN')]);
    try {
      server.enabled = true;
      server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('off')));
      const { result } = renderHook(() => useSpeech('en-US'));
      expect(result.current.supported).toBe(true);
      act(() => {
        result.current.speak('apple');
      });
      await settle();
      expect(server.play).toHaveBeenCalledWith('apple', 'en-US', 0.92);
      expect(speech.synth.speak).toHaveBeenCalledTimes(1);
      expect(toastApi.error).not.toHaveBeenCalled();
    } finally {
      speech.remove();
    }
  });
});

describe('useSpeech hook without speechSynthesis', () => {
  it('is unsupported until the server offers clips, then speaks through them and phrases failures', async () => {
    const off = renderHook(() => useSpeech('en-US'));
    expect(off.result.current.supported).toBe(false);
    expect(off.result.current.speak('apple')).toBe(false);
    off.unmount();
    server.enabled = true;
    const { result } = renderHook(() => useSpeech('en-US'));
    expect(result.current.supported).toBe(true);
    expect(result.current.voicesReady).toBe(true);
    let finish!: () => void;
    server.play.mockImplementationOnce(() => new Promise<void>((resolve) => (finish = resolve)));
    act(() => {
      expect(result.current.speak('apple')).toBe(true);
    });
    expect(result.current.speaking).toBe(true);
    await act(async () => {
      finish();
      await Promise.resolve();
    });
    expect(result.current.speaking).toBe(false);
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('busy')));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceBusy);
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('off')));
    act(() => {
      result.current.speak('apple');
    });
    await settle();
    expect(toastApi.error).toHaveBeenLastCalledWith(zh.word.voiceMissing); // no browser voice to fall back to
    act(() => result.current.cancel());
    expect(server.stop).toHaveBeenCalled();
  });
});

describe('speechFailureCopy', () => {
  it('names the cause the learner can act on, and stays quiet where nothing can be done', () => {
    expect(speechFailureCopy(new ServerAudioError('network'))).toBe(zh.word.voiceFetchFailed);
    expect(speechFailureCopy(new ServerAudioError('busy'))).toBe(zh.word.voiceBusy);
    expect(speechFailureCopy(new ServerAudioError('failed'))).toBe(zh.word.voiceServerFailed);
    expect(speechFailureCopy(new ServerAudioError('invalid'))).toBe(zh.word.voiceTextUnsupported); // never "the server is not configured"
    expect(speechFailureCopy(new ServerAudioError('decode'))).toBe(zh.word.voicePlayFailed);
    expect(speechFailureCopy(new ServerAudioError('off'))).toBe(zh.word.voiceMissing);
    expect(speechFailureCopy(new ServerAudioError('blocked'))).toBeNull();
    expect(speechFailureCopy(new ServerAudioError('auth'))).toBeNull();
    expect(speechFailureCopy(new ServerAudioError('interrupted'))).toBeNull();
    expect(speechFailureCopy(new Error('This language is not supported.'))).toBe(zh.word.voiceMissing);
  });
});

describe('useSpeech across taps', () => {
  it('a second tap owns `speaking` and the toast: the first clip finishing or failing later changes nothing', async () => {
    server.enabled = true;
    let failFirst!: (e: unknown) => void;
    let finishSecond!: () => void;
    server.play.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => (failFirst = reject)));
    server.play.mockImplementationOnce(() => new Promise<void>((resolve) => (finishSecond = resolve)));
    const { result } = renderHook(() => useSpeech('en-US'));
    act(() => {
      result.current.speak('apple');
    });
    act(() => {
      result.current.speak('pear');
    });
    expect(result.current.speaking).toBe(true);
    await act(async () => {
      failFirst(new ServerAudioError('failed'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.speaking).toBe(true); // the second clip is still playing
    expect(toastApi.error).not.toHaveBeenCalled(); // the superseded call's failure is not the learner's concern
    await act(async () => {
      finishSecond();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.speaking).toBe(false);
  });

  it('cancel() ends the speaking state even while a clip is pending', async () => {
    server.enabled = true;
    server.play.mockImplementationOnce(() => new Promise<void>(() => undefined));
    const { result } = renderHook(() => useSpeech('en-US'));
    act(() => {
      result.current.speak('apple');
    });
    expect(result.current.speaking).toBe(true);
    act(() => result.current.cancel());
    expect(result.current.speaking).toBe(false);
    expect(server.stop).toHaveBeenCalled();
  });
});
