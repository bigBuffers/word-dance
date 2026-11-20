import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ImageMeta } from '@/api/types';
import { DancingPicture } from './DancingPicture';
import { DANCING_MOTIONS, highlightIndexes, meaningStart, motionSteps, parseStage } from './dancingMotions';
import { WordImage } from './WordImage';

const SRC = '/media/images/ab/0123.svg';
const stageOf = (motion: string, highlight = '') => `<desc id="wd-stage">${JSON.stringify({ v: 1, motion, highlight }).replace(/"/g, '&quot;')}</desc>`;
const drawing = (stage: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><desc id="aigc-label">AI</desc>${stage}<title>tip</title><rect width="800" height="500" fill="#fff" style="fill:red"/><g id="actor"><circle cx="400" cy="200" r="80"/></g></svg>`;
const answer = (body: string, ok = true) => vi.fn(() => Promise.resolve({ ok, status: ok ? 200 : 404, text: () => Promise.resolve(body) }));
const image: ImageMeta = {
  id: 7, url: SRC, kind: 'svg', provider: 'claude_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: 'ALT', attribution: null,
  dancing: true, word_layer: false, hook_zh: 'HOOK', note_zh: null,
};

afterEach(() => vi.unstubAllGlobals());

describe('dancingMotions', () => {
  it('knows every motion of the closed list and nothing else', () => {
    expect(DANCING_MOTIONS).toEqual(['none', 'hop', 'rise', 'fall', 'shiver', 'sway', 'spin', 'pulse', 'grow', 'shrink', 'dash', 'float']);
    for (const m of DANCING_MOTIONS) {
      const steps = motionSteps(m);
      if (m === 'none') expect(steps).toBeNull();
      else {
        expect(steps!.actor.frames.length).toBeGreaterThan(1);
        expect(steps!.word.frames.length).toBeGreaterThan(1);
        // letters + beat + meaning stay within the dance budget for a five-letter word
        expect(meaningStart(5) + Math.max(steps!.actor.duration * (steps!.actor.iterations ?? 1), steps!.word.duration * (steps!.word.iterations ?? 1))).toBeLessThanOrEqual(3000);
      }
    }
  });

  it('reads the stage record and treats anything else as a still picture', () => {
    expect(parseStage('{"v":1,"motion":"hop","highlight":"ear"}')).toEqual({ motion: 'hop', highlight: 'ear' });
    expect(parseStage('{"v":1,"motion":"explode","highlight":3}')).toEqual({ motion: 'none', highlight: '' });
    expect(parseStage('not json')).toEqual({ motion: 'none', highlight: '' });
    expect(parseStage(undefined)).toEqual({ motion: 'none', highlight: '' });
    expect(highlightIndexes('Hear', 'ear')).toEqual([1, 2, 3]);
    expect(highlightIndexes('hear', 'eye')).toEqual([]);
    expect(highlightIndexes('hear', '')).toEqual([]);
  });
});

describe('DancingPicture', () => {
  it('draws the file inline, prints the word letter by letter and lights the highlight', async () => {
    vi.stubGlobal('fetch', answer(drawing(stageOf('hop', 'ear'))));
    const onLoaded = vi.fn();
    const { container } = render(<DancingPicture src={SRC} word="hear" mode="full" alt="ALT" onLoaded={onLoaded} />);
    await waitFor(() => expect(onLoaded).toHaveBeenCalled());
    expect(container.querySelector('svg g#actor')).not.toBeNull();
    expect(container.querySelector('svg title')).toBeNull();
    expect(container.querySelector('svg rect[style]')).toBeNull(); // the file's own inline CSS is not carried over
    const letters = [...container.querySelectorAll('.dpic__word text')];
    expect(letters.map((t) => t.textContent)).toEqual(['h', 'e', 'a', 'r']);
    expect(letters.map((t) => t.getAttribute('class'))).toEqual([null, 'is-lit', 'is-lit', 'is-lit']);
    expect(screen.getByRole('button').getAttribute('aria-label')).toContain('ALT');
  });

  it('leaves the ground empty without a word, and lights doubled letters when the drawing names no highlight', async () => {
    vi.stubGlobal('fetch', answer(drawing(stageOf('none'))));
    const first = render(<DancingPicture src={SRC} word={null} mode="full" alt="" />);
    await waitFor(() => expect(first.container.querySelector('svg')).not.toBeNull());
    expect(first.container.querySelector('.dpic__word')).toBeNull();
    first.unmount();
    const second = render(<DancingPicture src={SRC} word="book" twins={[[1, 2]]} mode="full" alt="" />);
    await waitFor(() => expect(second.container.querySelectorAll('.dpic__word text.is-lit').length).toBe(2));
  });

  it('plays letters, beat and the motion on the actor and the word; a tap replays; off and form_only hold back', async () => {
    vi.stubGlobal('fetch', answer(drawing(stageOf('hop'))));
    const calls: Element[] = [];
    const animate = vi.fn(function (this: Element) {
      calls.push(this);
      return { cancel: vi.fn() };
    });
    Object.defineProperty(Element.prototype, 'animate', { configurable: true, writable: true, value: animate });
    try {
      const onLoaded = vi.fn();
      const full = render(<DancingPicture src={SRC} word="jump" mode="full" alt="" onLoaded={onLoaded} />);
      await waitFor(() => expect(onLoaded).toHaveBeenCalled());
      // 4 letters + the beat + the actor + the word
      expect(calls.length).toBe(7);
      expect(calls.some((el) => el.id === 'actor')).toBe(true);
      fireEvent.click(screen.getByRole('button'));
      expect(calls.length).toBe(14);
      full.unmount();
      calls.length = 0;
      const form = render(<DancingPicture src={SRC} word="jump" mode="form_only" alt="" onLoaded={onLoaded} />);
      await waitFor(() => expect(form.container.querySelector('svg')).not.toBeNull());
      expect(calls.length).toBe(5);
      expect(calls.some((el) => el.id === 'actor')).toBe(false);
      form.unmount();
      calls.length = 0;
      const off = render(<DancingPicture src={SRC} word="jump" mode="off" alt="" />);
      await waitFor(() => expect(off.container.querySelector('svg')).not.toBeNull());
      expect(calls.length).toBe(0);
    } finally {
      delete (Element.prototype as { animate?: unknown }).animate;
    }
  });

  it('reports a file that cannot be fetched or is not a drawing', async () => {
    const onFailed = vi.fn();
    vi.stubGlobal('fetch', answer('', false));
    render(<DancingPicture src={SRC} word="jump" mode="full" alt="" onFailed={onFailed} />);
    await waitFor(() => expect(onFailed).toHaveBeenCalledTimes(1));
    vi.stubGlobal('fetch', answer('<html><body>no</body></html>'));
    render(<DancingPicture src={`${SRC}?x`} word="jump" mode="full" alt="" onFailed={onFailed} />);
    await waitFor(() => expect(onFailed).toHaveBeenCalledTimes(2));
  });
});

describe('WordImage with a dancing card', () => {
  it('draws it inline with the word; image_word off leaves the word out; an unreadable file falls back to the plain picture', async () => {
    vi.stubGlobal('fetch', answer(drawing(stageOf('hop'))));
    const shown = render(<WordImage image={image} showImages imageWord word="jump" danceMode="full" />);
    await waitFor(() => expect(shown.container.querySelectorAll('.dpic__word text').length).toBe(4));
    expect(shown.container.querySelector('img')).toBeNull();
    shown.unmount();
    const wordless = render(<WordImage image={image} showImages imageWord={false} word="jump" danceMode="full" />);
    await waitFor(() => expect(wordless.container.querySelector('svg')).not.toBeNull());
    expect(wordless.container.querySelector('.dpic__word')).toBeNull();
    wordless.unmount();
    vi.stubGlobal('fetch', answer('', false));
    const broken = render(<WordImage image={image} showImages imageWord word="jump" danceMode="full" />);
    await waitFor(() => expect(broken.container.querySelector('img')).not.toBeNull());
    expect(broken.container.querySelector('img')!.getAttribute('src')).toBe(SRC);
  });

  it('shows a dancing card as a plain picture where no word is given, and every other image as before', () => {
    const fetched = vi.fn();
    vi.stubGlobal('fetch', fetched);
    const { container } = render(<WordImage image={image} showImages imageWord />);
    expect(container.querySelector('img')!.getAttribute('src')).toBe(SRC);
    render(<WordImage image={{ ...image, dancing: false }} showImages imageWord word="jump" danceMode="full" />);
    expect(fetched).not.toHaveBeenCalled();
  });
});
