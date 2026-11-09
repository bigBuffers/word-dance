// useSpeech — pronunciation through the Web Speech API (FRONTEND.md §6.4).
// Voices load asynchronously (`voiceschanged`); the first user gesture unlocks audio on iOS, which
// is naturally satisfied because `speak()` is always triggered from a click/key handler.
// Inside the native shell (mobile/, §6.6) the system TTS plugin speaks instead: Android's WebView has no speechSynthesis.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { isNative, isSpeechUnavailable, speakNative, stopNativeSpeech } from '@/native/capacitor';

export type Accent = 'en-US' | 'en-GB';

export const DEFAULT_RATE = 0.92;
const PREFERRED_VOICE = /Google|Microsoft|Samantha|Daniel/i;

export function speechSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance === 'function';
}

/** Something can pronounce: the Web Speech API, or the native shell's TTS plugin. */
export function speechAvailable(): boolean {
  return isNative() || speechSupported();
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

function buildUtterance(text: string, accent: Accent, rate: number): SpeechSynthesisUtterance {
  const voice = pickVoice(window.speechSynthesis.getVoices(), accent);
  const u = new window.SpeechSynthesisUtterance(text);
  u.lang = accent;
  if (voice) u.voice = voice;
  u.rate = rate;
  return u;
}

/** Speaks `text`; returns false when the browser has no speech synthesis. Cancels anything still speaking. */
export function speak(text: string, accent: Accent, rate = DEFAULT_RATE): boolean {
  if (isNative()) {
    void speakNative(text, accent, rate).catch(() => undefined); // no UI here (auto-pronounce); the hook reports a missing voice
    return true;
  }
  if (!speechSupported()) return false;
  const synth = window.speechSynthesis;
  const u = buildUtterance(text, accent, rate);
  synth.cancel();
  synth.speak(u);
  return true;
}

export interface Speech {
  /** `speechSynthesis` exists in this browser. */
  supported: boolean;
  /** An utterance started through this hook is currently playing. */
  speaking: boolean;
  /** `getVoices()` has returned at least one voice. */
  voicesReady: boolean;
  speak: (text: string, accent?: Accent, rate?: number) => boolean;
  cancel: () => void;
}

export function useSpeech(defaultAccent: Accent = 'en-US'): Speech {
  const toast = useToast();
  const [supported] = useState<boolean>(() => speechAvailable());
  const [speaking, setSpeaking] = useState(false);
  const [voicesReady, setVoicesReady] = useState<boolean>(() => isNative() || (speechSupported() && window.speechSynthesis.getVoices().length > 0));
  const currentRef = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    if (!speechSupported() || isNative()) return;
    const synth = window.speechSynthesis; // captured: the cleanup must not depend on the global still existing
    const onVoices = () => setVoicesReady(synth.getVoices().length > 0);
    onVoices();
    synth.addEventListener('voiceschanged', onVoices);
    return () => synth.removeEventListener('voiceschanged', onVoices);
  }, [supported]);

  const doSpeak = useCallback(
    (text: string, accent: Accent = defaultAccent, rate = DEFAULT_RATE): boolean => {
      if (!supported) return false;
      if (isNative()) {
        setSpeaking(true);
        void speakNative(text, accent, rate)
          .catch((e: unknown) => toast.error(isSpeechUnavailable(e) ? zh.word.voiceNotReady : zh.word.voiceMissing)) // engine not ready yet / no English voice (common on domestic ROMs)
          .finally(() => setSpeaking(false));
        return true;
      }
      const synth = window.speechSynthesis;
      const u = buildUtterance(text, accent, rate);
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
      synth.cancel();
      synth.speak(u);
      return true;
    },
    [supported, defaultAccent, toast],
  );

  const cancel = useCallback(() => {
    if (!supported) return;
    if (isNative()) {
      void stopNativeSpeech().catch(() => undefined);
      currentRef.current = null;
      setSpeaking(false);
      return;
    }
    window.speechSynthesis.cancel();
    currentRef.current = null;
    setSpeaking(false);
  }, [supported]);

  return { supported, speaking, voicesReady, speak: doSpeak, cancel };
}
