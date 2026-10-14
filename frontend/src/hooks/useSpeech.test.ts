import { describe, expect, it } from 'vitest';
import { pickVoice, speak, speechSupported } from './useSpeech';

const voice = (name: string, lang: string) => ({ name, lang }) as SpeechSynthesisVoice;

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

describe('speak()', () => {
  it('returns false when the browser has no speech synthesis (jsdom)', () => {
    expect(speechSupported()).toBe(false);
    expect(speak('abandon', 'en-US')).toBe(false);
  });
});
