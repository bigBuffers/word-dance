// Server-side pronunciation clips (FRONTEND.md §6.4; API.md 76 `GET /media/audio?text&accent`). The fallback for a device without an
// English voice: Android's WebView has no speechSynthesis, the Android container of HarmonyOS NEXT has no TTS engine the shell's
// plugin can reach, many domestic ROMs have no English voice. The clip URL is played straight from one shared <audio> element —
// same-origin, so the session cookie goes along, the browser's HTTP cache keeps a clip for a week, the site's CSP (`default-src
// 'self'`, no `blob:`) allows it, and `play()` runs synchronously inside the tap, so autoplay policies are satisfied however long the
// server takes to synthesise. Only when the element fails is the URL fetched once more to learn why (`diagnose`: the API error →
// a `ServerAudioReason`). Two ways a clip would otherwise never settle are watched for: the user agent pausing the element by itself
// (audio focus lost to a call or another app, the headset unplugged → `paused`) and a request that hangs without an error (a
// network that went away: no `playing` within STALL_MS of `play()` → `network`). `setServerAudio` mirrors `ServerFlags.audio` (AuthContext, after /me) so a server without a provider is
// never asked; a 503 {reason:'off'} switches it off for the rest of the session as well. `ServerFlags.audio_key` (provider + voice
// fingerprint) rides on every clip URL as `v`, so a switched voice is a new URL and no browser keeps last week's voice from its cache.
// Chinese (`accent=zh-CN`, 磨耳朵 — docs/LISTEN_MODE_DESIGN.md §4.1): the same endpoint reads glosses and translations when the
// server's provider has a Chinese voice (`ServerFlags.audio_zh`); `serverAudioSpeaks(lang)` answers per language, and one Chinese
// clip the server could not make (`failed`) or would not take (`invalid` — an older server knows no `zh-CN`) switches Chinese off
// for the session (`zhOff`), so a server without the voice is asked once, not once per word. English is untouched by all of this.
import { toApiError } from '@/api/client';
import type { Accent } from '@/hooks/useSpeech';

/** What endpoint 76 can be asked to read: the learner's English accent, or Chinese. */
export type SpeechLang = Accent | 'zh-CN';

export type ServerAudioReason =
  | 'off' // no provider on the server (WD_AUDIO_PROVIDER=off) — stop asking
  | 'busy' // synthesis slot or per-user budget exhausted — try again later
  | 'failed' // the provider failed for this text
  | 'missing' // the server's read-only cache has no clip for this text (synced from the host that synthesises): use the device's voice for this one
  | 'invalid' // the server refused the text (400)
  | 'auth' // 401: the session is gone (client.ts dispatched auth:expired)
  | 'network' // the clip could not be fetched at all
  | 'blocked' // play() refused: no user gesture yet (autoplay policy)
  | 'paused' // the user agent paused the element by itself mid-clip (audio focus lost, a call, the headset unplugged): a tap plays it again
  | 'decode' // the server serves the clip but the element could not play it
  | 'interrupted'; // a later play / stop took over before this clip could report

export class ServerAudioError extends Error {
  readonly reason: ServerAudioReason;

  constructor(reason: ServerAudioReason, message?: string) {
    super(message ?? reason);
    this.name = 'ServerAudioError';
    this.reason = reason;
  }
}

export function isServerAudioError(e: unknown): e is ServerAudioError {
  return e instanceof ServerAudioError;
}

let enabled = false;
let cacheKey = '';
let zhEnabled = false; // ServerFlags.audio_zh: the provider has a Chinese voice
let zhOff = false; // a Chinese clip came back `failed` / `invalid` in this session: stop asking for Chinese

/**
 * Mirrors `ServerFlags.audio` (true when the server has a pronunciation provider; `null`/`undefined` count as false),
 * `ServerFlags.audio_key` (the provider + voice fingerprint the clip URLs carry; missing on an older server → none) and
 * `ServerFlags.audio_zh` (the provider also reads Chinese; missing on an older server → no).
 */
export function setServerAudio(on: boolean | null | undefined, key?: string | null, zh?: boolean | null): void {
  enabled = on === true;
  cacheKey = typeof key === 'string' ? key : '';
  zhEnabled = zh === true;
}

export function serverAudioEnabled(): boolean {
  return enabled;
}

/**
 * Whether the server's clips can read `lang` right now: English whenever the server has a provider; Chinese only when that
 * provider has a Chinese voice and no Chinese clip has failed in this session.
 */
export function serverAudioSpeaks(lang: SpeechLang): boolean {
  return lang === 'zh-CN' ? enabled && zhEnabled && !zhOff : enabled;
}

/** The request URL of a clip (same-origin; the cookie session authenticates it) — with the server's voice fingerprint as `v` when known. */
export function clipUrl(text: string, accent: SpeechLang): string {
  const params = new URLSearchParams({ text, accent });
  if (cacheKey) params.set('v', cacheKey); // the server ignores it; a switched provider or voice is a new URL for the browser's HTTP cache
  return `/media/audio?${params.toString()}`;
}

/**
 * Why the element could not play the clip for `text`: the URL is fetched once more and the API error read (one extra request, on
 * failure only). A 200 means the server serves the clip and the element is the problem (`decode`); a 503 {reason:'off'} also
 * switches the server route off for the session, and a Chinese clip answered `failed` / `invalid` switches Chinese off (`zhOff`).
 */
export async function diagnose(text: string, accent: SpeechLang): Promise<ServerAudioReason> {
  const reason = await explainClip(text, accent);
  if (accent === 'zh-CN' && (reason === 'failed' || reason === 'invalid')) zhOff = true; // no Chinese voice after all, or a server that knows no zh-CN
  return reason;
}

async function explainClip(text: string, accent: SpeechLang): Promise<ServerAudioReason> {
  const path = clipUrl(text, accent);
  let res: Response;
  try {
    res = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'audio/*' } });
  } catch {
    return 'network';
  }
  if (res.ok) return 'decode';
  const err = await toApiError(res, path);
  if (err.code === 'audio_unavailable') {
    const reason = err.details?.['reason'];
    if (reason === 'off') {
      enabled = false;
      return 'off';
    }
    if (reason === 'missing') return 'missing';
    return reason === 'busy' ? 'busy' : 'failed';
  }
  if (err.status === 401) return 'auth';
  if (err.status === 400) return 'invalid';
  if (err.status === 429) return 'busy';
  return err.code === 'network' ? 'network' : 'failed';
}

/** A clip that has not started playing this long after `play()` is given up as `network` (the server may hold a request 8 s for a synthesis slot, plus the synthesis). */
export const STALL_MS = 20_000;

let element: HTMLAudioElement | null = null;
let current: (() => void) | null = null; // settles the promise of the clip now loading / playing
let generation = 0; // a play / stop after this one started makes the older call give up

/**
 * Plays the clip for `text` at `rate` (the element's playbackRate, pitch preserved); resolves when it ends — or when a later
 * `playServerAudio` / `stopServerAudio` cuts it short (resolved, not rejected, like the native path). Rejects with a
 * `ServerAudioError` naming the reason when the clip could not be played (`diagnose`), `blocked` when the browser refused
 * `play()` without a user gesture, `paused` when the browser paused the clip by itself, or `network` when it never started
 * playing (STALL_MS). Synchronous up to `play()`: call it inside the tap handler.
 */
export function playServerAudio(text: string, accent: SpeechLang, rate = 1): Promise<void> {
  stopServerAudio();
  const mine = generation;
  const audio = element ?? (element = new Audio());
  audio.preload = 'auto';
  audio.src = clipUrl(text, accent);
  audio.playbackRate = rate;
  (audio as HTMLAudioElement & { preservesPitch?: boolean }).preservesPitch = true;
  return new Promise<void>((resolve, reject) => {
    let done = false;
    const cleanup = () => {
      clearTimeout(stall);
      audio.removeEventListener('ended', onEnd);
      audio.removeEventListener('error', onError);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('playing', onPlaying);
      if (current === settle) current = null;
    };
    const settle = () => {
      if (done) return;
      done = true;
      cleanup();
      resolve();
    };
    const fail = (reason: ServerAudioReason) => {
      if (done) return;
      done = true;
      cleanup();
      reject(new ServerAudioError(reason));
    };
    const explain = () => {
      // the element gave up on the source (HTTP error, no decoder): ask the server why — unless a newer call already took over
      if (done) return;
      if (mine !== generation) {
        fail('interrupted');
        return;
      }
      done = true;
      cleanup();
      diagnose(text, accent).then(
        (reason) => reject(new ServerAudioError(mine !== generation ? 'interrupted' : reason)), // a newer call took over meanwhile: its outcome matters, not this one's
        () => reject(new ServerAudioError(mine !== generation ? 'interrupted' : 'failed')),
      );
    };
    const onEnd = () => settle();
    const onError = () => explain();
    const onPause = () => {
      // not the `pause` every natural end fires just before `ended`, and not the stale one of an earlier stopServerAudio() that
      // lands when this clip is already playing (cleanup() took the listener off for the clip it belonged to)
      if (done || mine !== generation || audio.ended || !audio.paused) return;
      fail('paused');
    };
    const onPlaying = () => clearTimeout(stall);
    const stall = setTimeout(() => fail('network'), STALL_MS); // neither sound nor an error: the request hangs — a diagnosis would hang with it
    current = settle;
    audio.addEventListener('ended', onEnd);
    audio.addEventListener('error', onError);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('playing', onPlaying);
    let started: unknown;
    try {
      started = audio.play();
    } catch {
      explain();
      return;
    }
    Promise.resolve(started).catch((e: unknown) => {
      const name = (e as { name?: unknown } | null)?.name;
      if (name === 'NotAllowedError') fail('blocked');
      else if (name === 'AbortError') fail('interrupted'); // the source changed under a pending play(): a newer call owns the element
      else explain();
    });
  });
}

/** Stops the clip now loading / playing (its promise resolves). */
export function stopServerAudio(): void {
  generation += 1;
  const settle = current;
  current = null;
  if (element) {
    try {
      element.pause();
    } catch {
      /* jsdom */
    }
  }
  settle?.();
}

/** Test hook: forgets the shared element and the flags. */
export function resetServerAudio(): void {
  cacheKey = '';
  stopServerAudio();
  element = null;
  enabled = false;
  zhEnabled = false;
  zhOff = false;
}
