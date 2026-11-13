// audio/utter (FRONTEND §6.4, docs/LISTEN_MODE_DESIGN.md §6.1): the awaitable voice of 磨耳朵 — the server's clip first, then the
// shell's plugin, then the Web Speech API; `busy` asked once more, a server out of reach twice more and then `offline` (not
// `unspoken`) where the device cannot read the text either, `blocked` reported at once (a clip the browser paused by itself
// too), a refused plugin not asked again, the browser route ended by its events or the watchdog, the Chinese voice pick, and
// interruption by stopUtter() / the next utter().
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const server = vi.hoisted(() => ({ en: false, zh: false, play: vi.fn<(text: string, lang: string, rate: number) => Promise<void>>(async () => undefined), stop: vi.fn() }));
const native = vi.hoisted(() => ({ on: false, speakNative: vi.fn(async (_text: string, _lang: string, _rate: number) => undefined), stopNativeSpeech: vi.fn(async () => undefined) }));
vi.mock('@/audio/serverAudio', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/audio/serverAudio')>()),
  serverAudioSpeaks: (lang: string) => (lang === 'zh-CN' ? server.zh : server.en),
  playServerAudio: server.play,
  stopServerAudio: server.stop,
}));
vi.mock('@/native/capacitor', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/capacitor')>()),
  isNative: () => native.on,
  speakNative: native.speakNative,
  stopNativeSpeech: native.stopNativeSpeech,
}));

import { ServerAudioError } from '@/audio/serverAudio';
import { BUSY_RETRY_MS, pickZhVoice, resetUtter, stopUtter, utter, utterAvailable, watchdogMs } from './utter';

const voice = (name: string, lang: string) => ({ name, lang }) as SpeechSynthesisVoice;

class FakeUtterance {
  text: string;
  lang = '';
  rate = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

/** A fake Web Speech API whose utterances the test starts / ends / fails by hand; `remove()` restores jsdom's bare window. */
function installSpeech(voices: SpeechSynthesisVoice[]) {
  const w = window as unknown as Record<string, unknown>;
  const spoken: FakeUtterance[] = [];
  const synth = { getVoices: vi.fn(() => voices), speak: vi.fn((u: FakeUtterance) => void spoken.push(u)), cancel: vi.fn() };
  w['speechSynthesis'] = synth;
  w['SpeechSynthesisUtterance'] = FakeUtterance;
  return {
    synth,
    spoken,
    last: () => spoken[spoken.length - 1]!,
    remove() {
      delete w['speechSynthesis'];
      delete w['SpeechSynthesisUtterance'];
    },
  };
}

const unavailable = () => Object.assign(new Error('Not yet initialized or not available on this device.'), { code: 'UNAVAILABLE' });
const settle = async () => {
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
};

let speech: ReturnType<typeof installSpeech> | null = null;

beforeEach(() => {
  vi.useFakeTimers();
  resetUtter();
  vi.clearAllMocks();
});

afterEach(() => {
  speech?.remove();
  speech = null;
  server.en = false;
  server.zh = false;
  native.on = false;
  server.play.mockReset(); // a persistent mockImplementation must not leak into the next test
  server.play.mockImplementation(async () => undefined);
  native.speakNative.mockReset();
  native.speakNative.mockImplementation(async () => undefined);
  vi.useRealTimers();
});

describe('utter: the route order', () => {
  it("plays the server's clip first — even where the device has a voice — and passes text, language and rate through", async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    native.on = true;
    server.en = true;
    server.zh = true;
    expect(await utter('share', 'en-GB', 0.92)).toBe('ended');
    expect(await utter('分享，共用', 'zh-CN', 1)).toBe('ended');
    expect(server.play.mock.calls).toEqual([
      ['share', 'en-GB', 0.92],
      ['分享，共用', 'zh-CN', 1],
    ]);
    expect(native.speakNative).not.toHaveBeenCalled();
    expect(speech.synth.speak).not.toHaveBeenCalled();
  });

  it('calls play() synchronously, so the gesture of the tap that started the chain covers the first clip', () => {
    server.en = true;
    void utter('share', 'en-US', 0.92);
    expect(server.play).toHaveBeenCalledTimes(1);
  });

  it('a server that cannot read the language is not asked: the shell speaks, else the browser', async () => {
    speech = installSpeech([voice('Samantha', 'en-US'), voice('Tingting', 'zh-CN')]);
    server.en = true; // English only: no Chinese voice on the server
    native.on = true;
    expect(await utter('你好', 'zh-CN', 1)).toBe('ended');
    expect(server.play).not.toHaveBeenCalled();
    expect(native.speakNative).toHaveBeenCalledWith('你好', 'zh-CN', 1);
    native.on = false;
    const pending = utter('你好', 'zh-CN', 1);
    expect(speech.last().text).toBe('你好');
    speech.last().onend?.();
    expect(await pending).toBe('ended');
  });

  it('falls from a failed clip to the plugin and from a refusing plugin to the browser voice', async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    server.en = true;
    native.on = true;
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('missing')));
    expect(await utter('zebra', 'en-US', 0.92)).toBe('ended');
    expect(native.speakNative).toHaveBeenCalledWith('zebra', 'en-US', 0.92);
    server.play.mockImplementation(() => Promise.reject(new ServerAudioError('network')));
    native.speakNative.mockImplementationOnce(() => Promise.reject(new Error('Failed to read text.')));
    const pending = utter('zebra', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(2 * BUSY_RETRY_MS); // a server that cannot be reached is asked twice more before the device
    expect(speech.last().text).toBe('zebra');
    expect(speech.last().lang).toBe('en-US');
    expect(speech.last().rate).toBe(0.92);
    expect(speech.last().voice?.name).toBe('Samantha');
    speech.last().onend?.();
    expect(await pending).toBe('ended');
  });

  it('answers unspoken when no route exists, and when every route failed', async () => {
    expect(await utter('share', 'en-US', 0.92)).toBe('unspoken'); // jsdom: no server, no shell, no speechSynthesis
    server.en = true;
    native.on = true;
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('failed')));
    native.speakNative.mockImplementationOnce(() => Promise.reject(unavailable()));
    expect(await utter('share', 'en-US', 0.92)).toBe('unspoken');
  });
});

describe('utter: the server route', () => {
  it('asks a busy server once more after 1.5 s', async () => {
    server.en = true;
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('busy')));
    const pending = utter('share', 'en-US', 0.92);
    await settle();
    expect(server.play).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS - 1);
    expect(server.play).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(server.play).toHaveBeenCalledTimes(2);
    expect(await pending).toBe('ended');
  });

  it('gives a server that is busy twice up for this segment (the device speaks, or nothing does)', async () => {
    server.en = true;
    server.play.mockImplementation(() => Promise.reject(new ServerAudioError('busy')));
    const pending = utter('share', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS);
    expect(await pending).toBe('unspoken');
    expect(server.play).toHaveBeenCalledTimes(2);
  });

  it('asks a server that cannot be reached twice more, 1.5 s apart: an ordinary restart is ridden out without a tap', async () => {
    server.en = true;
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('network')));
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('network')));
    const pending = utter('share', 'en-US', 0.92);
    await settle();
    expect(server.play).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS);
    expect(server.play).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS);
    expect(server.play).toHaveBeenCalledTimes(3); // the server is back: the clip plays
    expect(await pending).toBe('ended');
  });

  it('answers offline, not unspoken, when the server stays out of reach and the device has no voice — and ended when it has one', async () => {
    server.en = true;
    server.play.mockImplementation(() => Promise.reject(new ServerAudioError('network')));
    let pending = utter('share', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(2 * BUSY_RETRY_MS);
    expect(await pending).toBe('offline'); // the caller parks instead of skipping: every later segment would fail the same way
    expect(server.play).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(10 * BUSY_RETRY_MS);
    expect(server.play).toHaveBeenCalledTimes(3); // no retry outlives the call

    resetUtter();
    speech = installSpeech([voice('Samantha', 'en-US')]);
    pending = utter('share', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(2 * BUSY_RETRY_MS);
    speech.last().onend?.();
    expect(await pending).toBe('ended'); // the device read it: nothing to report
    server.zh = true;
    expect(await utter('你好', 'zh-CN', 1)).toBe('offline'); // …but it has no Chinese voice, and the server's Chinese is out of reach too
  });

  it('a long outage costs the retries once: until a clip plays again the server is asked once per segment', async () => {
    server.en = true;
    server.play.mockImplementation(() => Promise.reject(new ServerAudioError('network')));
    const first = utter('one', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(2 * BUSY_RETRY_MS);
    expect(await first).toBe('offline');
    expect(server.play).toHaveBeenCalledTimes(3);
    expect(await utter('two', 'en-US', 0.92)).toBe('offline'); // at once: the tap that tries again is answered without a wait
    expect(server.play).toHaveBeenCalledTimes(4);
    server.play.mockImplementationOnce(async () => undefined); // the server is back
    expect(await utter('three', 'en-US', 0.92)).toBe('ended');
    const later = utter('four', 'en-US', 0.92); // and away again: the retries are due once more
    await vi.advanceTimersByTimeAsync(2 * BUSY_RETRY_MS);
    expect(await later).toBe('offline');
    expect(server.play).toHaveBeenCalledTimes(8);
  });

  it('does not retry a request that hung (the stall watchdog of the clip answers network late), nor a lost session', async () => {
    server.en = true;
    server.play.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => setTimeout(() => reject(new ServerAudioError('network')), 20_000)));
    const hung = utter('share', 'en-US', 0.92);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(await hung).toBe('offline');
    expect(server.play).toHaveBeenCalledTimes(1);

    resetUtter();
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('auth')));
    expect(await utter('share', 'en-US', 0.92)).toBe('offline'); // 401: client.ts announces it; nothing is skipped meanwhile
    expect(server.play).toHaveBeenCalledTimes(2);
  });

  it('reports an autoplay refusal as blocked at once, without trying the device', async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    server.en = true;
    native.on = true;
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('blocked')));
    expect(await utter('share', 'en-US', 0.92)).toBe('blocked');
    expect(native.speakNative).not.toHaveBeenCalled();
    expect(speech.synth.speak).not.toHaveBeenCalled();
  });

  it('reports a clip the browser paused by itself as blocked too: a tap resumes it, the device does not take over', async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    server.en = true;
    native.on = true;
    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('paused')));
    expect(await utter('share', 'en-US', 0.92)).toBe('blocked');
    expect(native.speakNative).not.toHaveBeenCalled();
    expect(speech.synth.speak).not.toHaveBeenCalled();
  });

  it('a clip cut by stopUtter() or by the next utter() has ended; a stop during the busy pause ends the wait', async () => {
    server.en = true;
    let finishFirst!: () => void;
    server.play.mockImplementationOnce(() => new Promise<void>((resolve) => (finishFirst = resolve)));
    const first = utter('one', 'en-US', 0.92);
    const second = utter('two', 'en-US', 0.92); // silences the first…
    expect(server.stop).toHaveBeenCalled();
    finishFirst(); // …whose promise the real stopServerAudio() settles (resolved, not rejected)
    expect(await first).toBe('ended');
    expect(await second).toBe('ended');

    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('interrupted')));
    expect(await utter('three', 'en-US', 0.92)).toBe('ended'); // a SpeakButton took the element: not a failure, no fallback

    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('busy')));
    const waiting = utter('four', 'en-US', 0.92);
    await settle();
    stopUtter();
    expect(await waiting).toBe('ended');
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS * 2);
    expect(server.play).toHaveBeenCalledTimes(4); // one, two, three, four — and no retry after the stop

    server.play.mockImplementationOnce(() => Promise.reject(new ServerAudioError('network')));
    const away = utter('five', 'en-US', 0.92);
    await settle();
    stopUtter(); // the learner paused while the server was being asked again
    expect(await away).toBe('ended');
    await vi.advanceTimersByTimeAsync(BUSY_RETRY_MS * 2);
    expect(server.play).toHaveBeenCalledTimes(5);
  });
});

describe('utter: the shell plugin', () => {
  it('does not ask a plugin again for a language it refused; UNAVAILABLE (no engine) rules out both languages', async () => {
    native.on = true;
    native.speakNative.mockImplementationOnce(() => Promise.reject(new Error('This language is not supported.')));
    expect(utterAvailable('zh-CN')).toBe(true); // unknown until asked
    expect(await utter('你好', 'zh-CN', 1)).toBe('unspoken');
    expect(utterAvailable('zh-CN')).toBe(false);
    expect(utterAvailable('en-US')).toBe(true);
    expect(await utter('你好', 'zh-CN', 1)).toBe('unspoken');
    expect(native.speakNative).toHaveBeenCalledTimes(1);
    expect(await utter('share', 'en-US', 0.92)).toBe('ended'); // English still goes to the plugin
    expect(native.speakNative).toHaveBeenCalledTimes(2);

    resetUtter();
    native.speakNative.mockImplementationOnce(() => Promise.reject(unavailable()));
    expect(await utter('share', 'en-US', 0.92)).toBe('unspoken');
    expect(utterAvailable('en-GB')).toBe(false);
    expect(utterAvailable('zh-CN')).toBe(false);
  });

  it('silences the plugin before every utterance and on stopUtter()', async () => {
    native.on = true;
    await utter('share', 'en-US', 0.92);
    expect(native.stopNativeSpeech).toHaveBeenCalledTimes(1);
    stopUtter();
    expect(native.stopNativeSpeech).toHaveBeenCalledTimes(2);
  });
});

describe('utter: the Web Speech route', () => {
  it('resolves when the utterance ends, keeping the browser queue to one voice', async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    const pending = utter('share', 'en-US', 0.92);
    expect(speech.synth.cancel).toHaveBeenCalledTimes(1); // whatever spoke before is cut first
    expect(speech.synth.speak).toHaveBeenCalledTimes(1);
    let done = false;
    void pending.then(() => (done = true));
    await settle();
    expect(done).toBe(false); // not at once, unlike useSpeech's synth route
    speech.last().onstart?.();
    speech.last().onend?.();
    expect(await pending).toBe('ended');
  });

  it('maps the error event: not-allowed is blocked, a cut is ended, anything else unspoken', async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    let pending = utter('share', 'en-US', 0.92);
    speech.last().onerror?.({ error: 'not-allowed' });
    expect(await pending).toBe('blocked');
    pending = utter('share', 'en-US', 0.92);
    speech.last().onerror?.({ error: 'interrupted' });
    expect(await pending).toBe('ended');
    pending = utter('share', 'en-US', 0.92);
    speech.last().onerror?.({ error: 'synthesis-failed' });
    expect(await pending).toBe('unspoken');
  });

  it('the watchdog ends an utterance that lost its end event: heard when it had started, unspoken when it never did', async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    expect(watchdogMs('share')).toBe(4_000 + 5 * 350);
    expect(watchdogMs('x'.repeat(300))).toBe(30_000);
    let pending = utter('share', 'en-US', 0.92);
    speech.last().onstart?.();
    await vi.advanceTimersByTimeAsync(watchdogMs('share'));
    expect(await pending).toBe('ended');
    expect(speech.synth.cancel).toHaveBeenCalledTimes(2); // the silence before speaking + the watchdog's own cancel
    pending = utter('share', 'en-US', 0.92); // iOS outside a gesture: speak() is ignored without any event
    await vi.advanceTimersByTimeAsync(watchdogMs('share'));
    expect(await pending).toBe('unspoken');
  });

  it('stopUtter() and the next utter() settle the utterance in flight as ended', async () => {
    speech = installSpeech([voice('Samantha', 'en-US')]);
    const first = utter('one', 'en-US', 0.92);
    const second = utter('two', 'en-US', 0.92);
    expect(await first).toBe('ended');
    stopUtter();
    expect(await second).toBe('ended');
    expect(speech.spoken.map((u) => u.text)).toEqual(['one', 'two']);
    await vi.advanceTimersByTimeAsync(60_000); // the watchdogs of settled utterances are gone
    expect(speech.synth.cancel).toHaveBeenCalledTimes(3); // one per utter() + the stop, none from a late watchdog
  });

  it('reads Chinese with a Chinese voice, with the browser default while the list is still empty, and not at all without one', async () => {
    speech = installSpeech([voice('Samantha', 'en-US'), voice('Sin-ji', 'zh-HK'), voice('Tingting', 'zh_CN')]);
    let pending = utter('你好', 'zh-CN', 1);
    expect(speech.last().lang).toBe('zh-CN');
    expect(speech.last().voice?.name).toBe('Tingting');
    expect(speech.last().rate).toBe(1);
    speech.last().onend?.();
    expect(await pending).toBe('ended');

    speech.synth.getVoices.mockReturnValue([]); // Chrome fills the list asynchronously: the browser picks by `lang`
    pending = utter('你好', 'zh-CN', 1);
    expect(speech.last().voice).toBeNull();
    speech.last().onend?.();
    expect(await pending).toBe('ended');

    speech.synth.getVoices.mockReturnValue([voice('Samantha', 'en-US')]);
    expect(await utter('你好', 'zh-CN', 1)).toBe('unspoken'); // an English voice reads Chinese as silence
    expect(speech.synth.speak).toHaveBeenCalledTimes(2);
    pending = utter('share', 'en-US', 0.92); // English is unaffected
    speech.last().onend?.();
    expect(await pending).toBe('ended');
  });
});

describe('pickZhVoice', () => {
  it('prefers a mainland Mandarin voice (a Premium / Enhanced one first), then other Mandarin, then any zh voice', () => {
    expect(pickZhVoice([voice('Mei-Jia', 'zh-TW'), voice('Tingting', 'zh-CN'), voice('Lili (Premium)', 'zh-CN')])?.name).toBe('Lili (Premium)');
    expect(pickZhVoice([voice('Mei-Jia', 'zh-TW'), voice('Tingting', 'zh_CN')])?.name).toBe('Tingting');
    expect(pickZhVoice([voice('Google', 'cmn-Hans-CN'), voice('Mei-Jia', 'zh-TW')])?.name).toBe('Google');
    expect(pickZhVoice([voice('Sin-ji', 'zh-HK'), voice('Mei-Jia', 'zh-TW')])?.name).toBe('Mei-Jia');
    expect(pickZhVoice([voice('Sin-ji', 'zh-HK')])?.name).toBe('Sin-ji');
    expect(pickZhVoice([voice('Samantha', 'en-US'), voice('Kyoko', 'ja-JP')])).toBeUndefined();
    expect(pickZhVoice([])).toBeUndefined();
  });
});

describe('utterAvailable', () => {
  it('is true where the server, the shell or a suitable browser voice may read the language', () => {
    expect(utterAvailable('en-US')).toBe(false); // jsdom: nothing at all
    expect(utterAvailable('zh-CN')).toBe(false);
    server.en = true;
    expect(utterAvailable('en-GB')).toBe(true);
    expect(utterAvailable('zh-CN')).toBe(false); // the server has no Chinese voice
    server.zh = true;
    expect(utterAvailable('zh-CN')).toBe(true);
    server.en = false;
    server.zh = false;
    native.on = true;
    expect(utterAvailable('en-US')).toBe(true); // the plugin may have a voice: known only once asked
    native.on = false;
    speech = installSpeech([voice('Samantha', 'en-US')]);
    expect(utterAvailable('en-US')).toBe(true);
    expect(utterAvailable('zh-CN')).toBe(false); // a known list without a Chinese voice
    speech.synth.getVoices.mockReturnValue([]);
    expect(utterAvailable('zh-CN')).toBe(true); // not known yet
    speech.synth.getVoices.mockReturnValue([voice('Tingting', 'zh-CN')]);
    expect(utterAvailable('zh-CN')).toBe(true);
    expect(utterAvailable('en-US')).toBe(true); // without an English voice the browser default speaks, as in useSpeech
  });
});
