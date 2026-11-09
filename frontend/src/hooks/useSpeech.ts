// useSpeech — pronunciation (FRONTEND.md §6.4). Three routes, chosen per call by `speechRoute`:
//   native  the system TTS plugin inside the Capacitor shell (§6.6; Android's WebView has no speechSynthesis),
//   synth   the Web Speech API with an English voice (voices load asynchronously — `voiceschanged`; while the list is still
//           empty the browser default speaks, as before clips existed; the first user gesture unlocks audio on iOS, naturally
//           satisfied because speak() is always triggered from a click/key handler),
//   server  a clip from `GET /media/audio` (audio/serverAudio.ts) when the server has a provider (`ServerFlags.audio`) and the
//           device lists no English voice — and the fallback when the native plugin rejects (no TTS engine, no English voice).
// One voice at a time: every call silences the other routes first. The hook reports a failure through the toast (unless a later
// call superseded the failing one); the module-level speak() (auto-pronounce, key P) stays silent.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useOptionalAuth } from '@/auth/AuthContext';
import { isServerAudioError, playServerAudio, serverAudioEnabled, stopServerAudio } from '@/audio/serverAudio';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { isNative, speakNative, stopNativeSpeech } from '@/native/capacitor';

export type Accent = 'en-US' | 'en-GB';
export type SpeechRoute = 'native' | 'synth' | 'server';

export const DEFAULT_RATE = 0.92;
const PREFERRED_VOICE = /Google|Microsoft|Samantha|Daniel/i;

export function speechSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance === 'function';
}

/** Something can pronounce: the Web Speech API, the native shell's TTS plugin, or the server's clips (`ServerFlags.audio`). */
export function speechAvailable(): boolean {
  return isNative() || speechSupported() || serverAudioEnabled();
}

const normLang = (lang: string) => lang.replace('_', '-').toLowerCase();

/**
 * Exact lang match first (preferring voices whose name contains Google/Microsoft/Samantha/Daniel),
 * else any English voice, else undefined (the browser default is used).
 */
export function pickVoice(voices: readonly SpeechSynthesisVoice[], accent: Accent): SpeechSynthesisVoice | undefined {
  const wanted = accent.toLowerCase();
  const exact = voices.filter((v) => normLang(v.lang) === wanted);
  return exact.find((v) => PREFERRED_VOICE.test(v.name)) ?? exact[0] ?? voices.find((v) => normLang(v.lang).startsWith('en'));
}

/**
 * The route that pronounces right now: the shell's plugin; the Web Speech API when it lists an English voice — or no voice yet
 * (Chrome fills the list asynchronously; the browser default speaks meanwhile, as before clips existed); the server's clips when
 * the list has no English voice and the server has a provider; else the Web Speech API with the browser default; null when
 * nothing can speak (the SpeakButton is disabled).
 */
export function speechRoute(accent: Accent): SpeechRoute | null {
  if (isNative()) return 'native';
  const synth = speechSupported();
  if (synth) {
    const voices = window.speechSynthesis.getVoices();
    if (voices.length === 0 || pickVoice(voices, accent)) return 'synth';
  }
  if (serverAudioEnabled()) return 'server';
  return synth ? 'synth' : null;
}

function buildUtterance(text: string, accent: Accent, rate: number): SpeechSynthesisUtterance {
  const voice = pickVoice(window.speechSynthesis.getVoices(), accent);
  const u = new window.SpeechSynthesisUtterance(text);
  u.lang = accent;
  if (voice) u.voice = voice;
  u.rate = rate;
  return u;
}

/** Silences the other routes before one speaks: a server clip still playing, the browser's queue (the plugin flushes itself). */
function hush(): void {
  stopServerAudio();
  if (speechSupported()) window.speechSynthesis.cancel();
}

function synthSpeak(text: string, accent: Accent, rate: number): SpeechSynthesisUtterance {
  hush();
  const u = buildUtterance(text, accent, rate);
  window.speechSynthesis.speak(u);
  return u;
}

/**
 * Pronounces through `route` and resolves when the utterance / clip has finished (the synth route resolves at once — the Web
 * Speech API reports through the utterance's events, which the hook wires itself). Rejects with the plugin's error (native, no
 * server to fall back to) or a `ServerAudioError`. Synchronous up to the plugin call / `play()`, so a tap handler's gesture covers it.
 */
async function pronounce(text: string, accent: Accent, rate: number, route: SpeechRoute): Promise<void> {
  if (route === 'native') {
    hush();
    try {
      await speakNative(text, accent, rate);
    } catch (e) {
      // no TTS engine (HarmonyOS NEXT's Android container, code UNAVAILABLE), no English voice, or an engine that failed: the
      // server's clip speaks instead when there is one; otherwise the hook tells the learner what is missing
      if (!serverAudioEnabled()) throw e;
      await playServerAudio(text, accent, rate);
    }
    return;
  }
  if (route === 'server') {
    if (speechSupported()) window.speechSynthesis.cancel();
    try {
      await playServerAudio(text, accent, rate);
    } catch (e) {
      if (isServerAudioError(e) && e.reason === 'off' && speechSupported()) {
        synthSpeak(text, accent, rate); // the browser default voice, as before clips existed
        return;
      }
      throw e;
    }
    return;
  }
  synthSpeak(text, accent, rate);
}

/** What the toast says about a failed pronunciation, or null when there is nothing useful to tell (autoplay blocked, session gone, superseded). */
export function speechFailureCopy(e: unknown): string | null {
  if (isServerAudioError(e)) {
    switch (e.reason) {
      case 'network':
        return zh.word.voiceFetchFailed;
      case 'busy':
        return zh.word.voiceBusy;
      case 'failed':
        return zh.word.voiceServerFailed;
      case 'invalid':
        return zh.word.voiceTextUnsupported;
      case 'decode':
        return zh.word.voicePlayFailed;
      case 'off':
        return zh.word.voiceMissing;
      default:
        return null;
    }
  }
  return zh.word.voiceMissing; // the native plugin rejected (no engine / no English voice) and no server could help
}

/** Speaks `text`; returns false when nothing can pronounce here. Cancels anything still speaking. Failures stay silent. */
export function speak(text: string, accent: Accent, rate = DEFAULT_RATE): boolean {
  const route = speechRoute(accent);
  if (route === null) return false;
  void pronounce(text, accent, rate, route).catch(() => undefined); // no UI here (auto-pronounce / key P); the hook reports
  return true;
}

export interface Speech {
  /** Something can pronounce: speechSynthesis, the shell's plugin or the server's clips. */
  supported: boolean;
  /** An utterance started through this hook is currently playing. */
  speaking: boolean;
  /** Voices are known (`getVoices()` returned some), or a route that needs none is available. */
  voicesReady: boolean;
  speak: (text: string, accent?: Accent, rate?: number) => boolean;
  cancel: () => void;
}

export function useSpeech(defaultAccent: Accent = 'en-US'): Speech {
  const toast = useToast();
  useOptionalAuth(); // re-renders when /me lands: AuthContext.loadMe sets the server-audio flag before it updates the context
  const serverAudio = serverAudioEnabled(); // the module flag alone, so a 503 {reason:'off'} disables the button on the next render
  const supported = isNative() || speechSupported() || serverAudio;
  const [speaking, setSpeaking] = useState(false);
  const [voices, setVoices] = useState<boolean>(() => speechSupported() && window.speechSynthesis.getVoices().length > 0);
  const voicesReady = isNative() || serverAudio || voices;
  const currentRef = useRef<SpeechSynthesisUtterance | null>(null);
  const callRef = useRef(0); // the latest call owns `speaking` and the toast; an older one that finishes or fails later stays quiet

  useEffect(() => {
    if (!speechSupported() || isNative()) return;
    const synth = window.speechSynthesis; // captured: the cleanup must not depend on the global still existing
    const onVoices = () => setVoices(synth.getVoices().length > 0);
    onVoices();
    synth.addEventListener('voiceschanged', onVoices);
    return () => synth.removeEventListener('voiceschanged', onVoices);
  }, []);

  const doSpeak = useCallback(
    (text: string, accent: Accent = defaultAccent, rate = DEFAULT_RATE): boolean => {
      const route = speechRoute(accent);
      if (route === null) return false;
      const call = (callRef.current += 1);
      if (route === 'synth') {
        const u = synthSpeak(text, accent, rate);
        const done = () => {
          if (currentRef.current === u) {
            currentRef.current = null;
            setSpeaking(false);
          }
        };
        u.onstart = () => setSpeaking(true);
        u.onend = done;
        u.onerror = done;
        currentRef.current = u;
        return true;
      }
      currentRef.current = null;
      setSpeaking(true);
      void pronounce(text, accent, rate, route)
        .catch((e: unknown) => {
          if (callRef.current !== call) return; // superseded by a later tap: its outcome is the one that matters
          const copy = speechFailureCopy(e);
          if (copy) toast.error(copy);
        })
        .finally(() => {
          if (callRef.current === call) setSpeaking(false);
        });
      return true;
    },
    [defaultAccent, toast],
  );

  const cancel = useCallback(() => {
    callRef.current += 1;
    if (isNative()) void stopNativeSpeech().catch(() => undefined);
    hush();
    currentRef.current = null;
    setSpeaking(false);
  }, []);

  return { supported, speaking, voicesReady, speak: doSpeak, cancel };
}
