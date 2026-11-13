// utter — "read this aloud and tell me when you are done", the awaitable primitive 磨耳朵 chains (FRONTEND.md §6.4;
// docs/LISTEN_MODE_DESIGN.md §6.1). `useSpeech` cannot be chained: its browser route returns at once and it prefers the device's
// voice. A playlist wants the opposite order and an ending, so `utter(text, lang, rate)` tries, per call:
//   server  the clip of `GET /media/audio` whenever the server reads this language (`serverAudioSpeaks`: English with a provider,
//           Chinese with `ServerFlags.audio_zh`) — one <audio> element chained clip after clip, the same voice on every device, and
//           the only Chinese the HarmonyOS tablet has. `busy` (the synthesis slots, the per-minute budget) is asked once more after
//           1.5 s, a server that cannot be reached (`network`) twice more — an ordinary restart of the service is over by then;
//           `blocked` (no user gesture yet) is reported at once — no other route would be allowed to speak either — and so is a
//           clip the browser paused by itself (`paused`: audio focus lost, a call), which a tap plays again;
//   native  the shell's TTS plugin, until it has refused the language (no engine at all: code UNAVAILABLE, for good);
//   synth   the Web Speech API, ended by the utterance's own events plus a watchdog (Chrome loses `onend` on long remote-voice
//           utterances; iOS ignores a speak() outside a gesture without any event) — English with `pickVoice`, Chinese with a
//           `zh` voice, and not at all when the list is known and holds none (an English voice reads Chinese as silence).
// The outcome is `ended` (spoken, or cut short by `stopUtter()` / the next `utter()` — the caller's own generation number tells
// which), `unspoken` (no route could read it: the caller skips the segment), `blocked` (the browser wants a tap first) or
// `offline` (the server could not be reached — `network`, or the session is gone: `auth` — and the device could not read the text
// either: the next segment would fail the same way, so the caller parks instead of skipping its way through the playlist).
// Synchronous up to `play()` / the plugin call / `speak()`, so a tap handler's gesture covers the first clip.
import { isServerAudioError, playServerAudio, serverAudioSpeaks, stopServerAudio, type SpeechLang } from '@/audio/serverAudio';
import { BETTER_VOICE, pickVoice, speechSupported } from '@/hooks/useSpeech';
import { isNative, speakNative, stopNativeSpeech } from '@/native/capacitor';

export type UtterOutcome = 'ended' | 'unspoken' | 'blocked' | 'offline';

/** A `busy` server (two synthesis slots, 60 misses a minute) is asked once more after this long. */
export const BUSY_RETRY_MS = 1_500;
/**
 * A server that cannot be reached is asked again, BUSY_RETRY_MS apart, while the segment is younger than this: two more tries,
 * which an ordinary restart of the service (2–3 s of refused connections) does not outlast. A request that hung until the clip's
 * stall watchdog gave it up is older than this by then and is not asked again.
 */
const NETWORK_RETRY_WINDOW_MS = 2 * BUSY_RETRY_MS;
const WATCHDOG_BASE_MS = 4_000;
const WATCHDOG_PER_CHAR_MS = 350;
const WATCHDOG_MAX_MS = 30_000;

/** How long a Web Speech utterance may take before it is given up: 4 s + 0.35 s per character, at most 30 s. */
export function watchdogMs(text: string): number {
  return Math.min(WATCHDOG_MAX_MS, WATCHDOG_BASE_MS + WATCHDOG_PER_CHAR_MS * text.length);
}

const ZH_VOICE = /^(zh|cmn)(-|$)/;
const MAINLAND_VOICE = /^(zh-cn|zh-hans|cmn)/;
const CANTONESE_VOICE = /^zh-hk/;
const voiceLang = (v: SpeechSynthesisVoice) => v.lang.replace(/_/g, '-').toLowerCase();

/**
 * The voice for Chinese: a mainland Mandarin one (`zh-CN`, `zh-Hans…`, `cmn…`; a Premium / Enhanced voice first), else any other
 * `zh` voice (Mandarin before Cantonese), else undefined — the caller then does not speak when the list is known.
 */
export function pickZhVoice(voices: readonly SpeechSynthesisVoice[]): SpeechSynthesisVoice | undefined {
  const zh = voices.filter((v) => ZH_VOICE.test(voiceLang(v)));
  const mainland = zh.filter((v) => MAINLAND_VOICE.test(voiceLang(v)));
  return mainland.find((v) => BETTER_VOICE.test(v.name)) ?? mainland[0] ?? zh.find((v) => !CANTONESE_VOICE.test(voiceLang(v))) ?? zh[0];
}

type Family = 'en' | 'zh';
const familyOf = (lang: SpeechLang): Family => (lang === 'zh-CN' ? 'zh' : 'en');

let generation = 0; // a later utter() / stopUtter() makes the older call give up
let cut: (() => void) | null = null; // settles what the current call is waiting on (the busy pause, the Web Speech utterance)
let held: SpeechSynthesisUtterance | null = null; // a reference keeps the utterance from being collected before its `onend`
const nativeRefused = new Set<Family>(); // the plugin rejected this language in this session: not asked again
let unreachable = false; // the last clip stayed out of reach through its retries: until one plays again `network` is final at once — a long outage costs the wait once, not on every segment

/** One voice at a time: whatever an earlier utter() started is cut on every route (its promise settles `ended`). */
function silence(): void {
  generation += 1;
  const settle = cut;
  cut = null;
  settle?.();
  stopServerAudio();
  if (isNative()) void stopNativeSpeech().catch(() => undefined);
  if (speechSupported()) window.speechSynthesis.cancel();
}

/** A pause the next utter() / stopUtter() ends early. */
function pause(ms: number): Promise<void> {
  return new Promise<void>((resolve) => {
    const done = () => {
      clearTimeout(timer);
      if (cut === done) cut = null;
      resolve();
    };
    const timer = setTimeout(done, ms);
    cut = done;
  });
}

/**
 * The server route. The device should try when it answers null (the server could not read this text) or `offline` (the server
 * could not be reached at all: what the call as a whole answers when the device cannot read the text either).
 */
async function serverUtter(text: string, lang: SpeechLang, rate: number, mine: number): Promise<UtterOutcome | null> {
  const asked = Date.now();
  for (let attempt = 0; ; attempt += 1) {
    try {
      await playServerAudio(text, lang, rate);
      if (mine === generation) unreachable = false;
      return 'ended';
    } catch (e) {
      const reason = isServerAudioError(e) ? e.reason : 'failed';
      if (reason === 'blocked' || reason === 'paused') return 'blocked'; // `paused`: the browser stopped the clip by itself — a tap plays it again, as after an autoplay refusal
      if (reason === 'interrupted' || mine !== generation) return 'ended';
      const again = reason === 'busy' ? attempt === 0 : reason === 'network' && !unreachable && Date.now() - asked < NETWORK_RETRY_WINDOW_MS;
      if (!again) {
        if (reason === 'network') unreachable = true;
        return reason === 'network' || reason === 'auth' ? 'offline' : null; // off / failed / missing / invalid / decode / busy twice: the device's voice, if it has one
      }
      await pause(BUSY_RETRY_MS);
      if (mine !== generation) return 'ended';
    }
  }
}

function synthUtter(text: string, lang: SpeechLang, rate: number): Promise<UtterOutcome> {
  const synth = window.speechSynthesis;
  const voices = synth.getVoices();
  const voice = lang === 'zh-CN' ? pickZhVoice(voices) : pickVoice(voices, lang);
  if (lang === 'zh-CN' && voices.length > 0 && !voice) return Promise.resolve('unspoken'); // the list is known and has no Chinese voice
  const u = new window.SpeechSynthesisUtterance(text);
  u.lang = lang;
  if (voice) u.voice = voice;
  u.rate = rate;
  return new Promise<UtterOutcome>((resolve) => {
    let started = false;
    let done = false;
    const finish = (outcome: UtterOutcome) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      u.onstart = null;
      u.onend = null;
      u.onerror = null;
      if (held === u) held = null;
      if (cut === onCut) cut = null;
      resolve(outcome);
    };
    const onCut = () => finish('ended');
    const timer = setTimeout(() => {
      // no `onend` in time: a started utterance has been heard (Chrome drops the event on long ones); one that never started was
      // never spoken (iOS outside a gesture, an engine that is stuck)
      synth.cancel();
      finish(started ? 'ended' : 'unspoken');
    }, watchdogMs(text));
    u.onstart = () => {
      started = true;
    };
    u.onend = () => finish('ended');
    u.onerror = (event) => {
      const error = (event as { error?: unknown } | null)?.error;
      if (error === 'not-allowed') finish('blocked'); // Chrome: speak() before any user activation
      else finish(error === 'interrupted' || error === 'canceled' ? 'ended' : 'unspoken');
    };
    held = u;
    cut = onCut;
    try {
      synth.speak(u);
    } catch {
      finish('unspoken');
    }
  });
}

/**
 * Reads `text` in `lang` at `rate` and resolves when it has been read (`ended`), when nothing here can read it (`unspoken`), when
 * the browser refuses to play before a tap (`blocked`) or when the server is out of reach and the device cannot read it either
 * (`offline`). Never rejects. A later `utter()` / `stopUtter()` cuts it: `ended`.
 */
export async function utter(text: string, lang: SpeechLang, rate: number): Promise<UtterOutcome> {
  silence();
  const mine = generation;
  let unread: UtterOutcome = 'unspoken'; // what the call answers when no route below reads the text
  if (serverAudioSpeaks(lang)) {
    const outcome = await serverUtter(text, lang, rate, mine);
    if (outcome === 'offline') unread = 'offline';
    else if (outcome !== null) return outcome;
  }
  const family = familyOf(lang);
  if (isNative() && !nativeRefused.has(family)) {
    try {
      await speakNative(text, lang, rate);
      return 'ended';
    } catch (e) {
      // no engine (code UNAVAILABLE: the plugin initialises once at launch and never retries — both languages are gone), no
      // voice for this language, or an engine error: the plugin is not asked for it again in this session
      nativeRefused.add(family);
      if ((e as { code?: unknown } | null)?.code === 'UNAVAILABLE') nativeRefused.add(family === 'zh' ? 'en' : 'zh');
      if (mine !== generation) return 'ended';
    }
  }
  if (!speechSupported()) return unread;
  const outcome = await synthUtter(text, lang, rate);
  return outcome === 'unspoken' ? unread : outcome;
}

/** Silences whatever `utter()` is reading; its promise resolves `ended`. */
export function stopUtter(): void {
  silence();
}

/**
 * Whether some route may read `lang` right now — optimistic where the device cannot tell beforehand: the shell's plugin counts
 * until it has refused the language, a voice list that is still empty (Chrome fills it asynchronously) counts as "maybe".
 * English in a browser always counts (without an English voice the browser default speaks, as in `useSpeech`).
 */
export function utterAvailable(lang: SpeechLang): boolean {
  if (serverAudioSpeaks(lang)) return true;
  if (isNative() && !nativeRefused.has(familyOf(lang))) return true;
  if (!speechSupported()) return false;
  if (lang !== 'zh-CN') return true;
  const voices = window.speechSynthesis.getVoices();
  return voices.length === 0 || pickZhVoice(voices) !== undefined;
}

/** Test hook: forgets what the plugin refused, the outage and whatever was pending. */
export function resetUtter(): void {
  silence();
  nativeRefused.clear();
  unreachable = false;
}
