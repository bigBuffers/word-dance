import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { zh } from '@/i18n/zh';
import { SpeakButton } from './SpeakButton';
import { WordHeader } from './WordHeader';

class FakeUtterance {
  text: string;
  lang = '';
  rate = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

function installSpeech() {
  const synth = {
    speak: vi.fn(),
    cancel: vi.fn(),
    getVoices: vi.fn(() => [] as SpeechSynthesisVoice[]),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal('speechSynthesis', synth);
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance);
  // vitest's jsdom env aliases window to globalThis; define explicitly in case it does not
  const w = window as unknown as Record<string, unknown>;
  const had = 'speechSynthesis' in window;
  if (!had) {
    Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true, writable: true });
    Object.defineProperty(window, 'SpeechSynthesisUtterance', { value: FakeUtterance, configurable: true, writable: true });
  }
  return {
    synth,
    restore() {
      if (!had) {
        delete w['speechSynthesis'];
        delete w['SpeechSynthesisUtterance'];
      }
    },
  };
}

describe('SpeakButton', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('is disabled with the unsupported tooltip when speechSynthesis is absent (jsdom)', () => {
    render(<SpeakButton text="abandon" />);
    const button = screen.getByRole('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBe(zh.word.speechUnsupported);
    expect(button.getAttribute('aria-label')).toBe(zh.word.speechUnsupported);
  });

  it('speaks the text with the requested accent and does not bubble the click', () => {
    const speech = installSpeech();
    try {
      const outer = vi.fn();
      render(
        <div onClick={outer}>
          <SpeakButton text="abandon" lang="en-GB" />
        </div>,
      );
      const button = screen.getByRole('button') as HTMLButtonElement;
      expect(button.disabled).toBe(false);
      expect(button.getAttribute('aria-label')).toBe(zh.word.speak);
      fireEvent.click(button);
      expect(speech.synth.cancel).toHaveBeenCalledTimes(1);
      expect(speech.synth.speak).toHaveBeenCalledTimes(1);
      const utterance = speech.synth.speak.mock.calls[0]![0] as FakeUtterance;
      expect(utterance.text).toBe('abandon');
      expect(utterance.lang).toBe('en-GB');
      expect(utterance.rate).toBeCloseTo(0.92);
      expect(outer).not.toHaveBeenCalled();
    } finally {
      speech.restore();
    }
  });
});

describe('WordHeader', () => {
  it('renders display, phonetic, stage chips (with ★) and the kind badge', () => {
    render(
      <WordHeader
        word={{ display: 'abandon', phonetic: 'əˈbændən', stages: ['cet6', 'gk', 'cet4'], stage_min: 2, cet6_star: true }}
        kind="review"
        as="h1"
        size="lg"
      />,
    );
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('abandon');
    expect(screen.getByText('/əˈbændən/')).toBeTruthy();
    const chips = screen.getAllByRole('listitem').map((li) => li.textContent);
    expect(chips).toEqual([zh.stages.gk, zh.stages.cet4, `${zh.stages.cet6}★`]);
    expect(screen.getByText(zh.study.kind.review)).toBeTruthy();
    expect(screen.getByRole('img', { name: zh.stages.star })).toBeTruthy();
  });
});
