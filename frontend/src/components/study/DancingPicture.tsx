// DancingPicture — a dancing picture card drawn inline (API.md §9.1 `ImageMeta.dancing`; docs/releases/2026-11-dancing-cards.md).
// The server-sanitised SVG of a svg-v3 drawing is fetched and put into the page (an <img> cannot be reached into), the headword is
// printed on the picture's ground as one <text> per letter, and one tap — or the first appearance — plays: letters enter one by
// one, the word beats once, then the picture's `#actor` and the word do the motion recorded in the file (`dancingMotions.ts`).
// `mode` is the learner's dance setting: 'off' never moves, 'form_only' stops after the letters; reduced motion and a browser
// without element.animate show the same picture still. The file's own `style` attributes and tooltips are not carried over.
import { useEffect, useRef, useState } from 'react';
import type { DanceMode } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import { BEAT_MS, HIGHLIGHT_MS, LETTER_ENTER_MS, LETTER_STEP_MS, highlightIndexes, meaningStart, motionSteps, parseStage } from './dancingMotions';
import type { MotionStep, StageRecord } from './dancingMotions';

const SVG_NS = 'http://www.w3.org/2000/svg';
const FONT_SIZE = 84;
const BASELINE = 468;
const MIDDLE = 400;
const MAX_WORD_WIDTH = 700;
const INK = '#2a2f45';
const HOT = '#e8590c';

export interface DancingPictureProps {
  src: string;
  /** The headword printed on the picture's ground; null (the learner's `image_word` off) leaves the ground empty. */
  word: string | null;
  /** Doubled letters of the word (`DanceSpec.marks.double`): they jump together when the drawing names no highlight. */
  twins?: [number, number][];
  mode: DanceMode;
  alt: string;
  onLoaded?: () => void;
  /** The file could not be fetched or is not a drawing: the caller falls back to a plain <img>. */
  onFailed?: () => void;
  className?: string;
}

interface Stage {
  svg: SVGSVGElement;
  record: StageRecord;
  actor: SVGGraphicsElement | null;
  wordGroup: SVGGElement | null;
  letters: SVGTextElement[];
  lit: number[];
}

function reducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function anchor(el: SVGElement, origin: string) {
  el.style.setProperty('transform-box', 'fill-box');
  el.style.setProperty('transform-origin', origin);
}

/** Parse the fetched file; null when it is not an SVG document. */
function readDrawing(text: string): SVGSVGElement | null {
  const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
  const root = doc.documentElement;
  if (!root || root.localName !== 'svg' || doc.getElementsByTagName('parsererror').length > 0) return null;
  return document.importNode(root, true) as unknown as SVGSVGElement;
}

function printWord(svg: SVGSVGElement, word: string, lit: number[]): { group: SVGGElement; letters: SVGTextElement[] } {
  const group = document.createElementNS(SVG_NS, 'g');
  group.setAttribute('class', 'dpic__word');
  const letters = Array.from(word).map((ch, i) => {
    const t = document.createElementNS(SVG_NS, 'text');
    t.textContent = ch;
    if (lit.includes(i)) t.setAttribute('class', 'is-lit');
    group.appendChild(t);
    return t;
  });
  svg.appendChild(group);
  placeLetters(letters);
  anchor(group, '50% 100%');
  letters.forEach((t) => anchor(t, '50% 100%'));
  return { group, letters };
}

/** Letters side by side from their measured widths, centred, the whole word shrunk to fit the ground. */
function placeLetters(letters: SVGTextElement[]) {
  const measure = (t: SVGTextElement, size: number) => {
    const w = typeof t.getComputedTextLength === 'function' ? t.getComputedTextLength() : 0;
    return w > 0 ? w : size * (t.textContent === ' ' ? 0.3 : 0.56);
  };
  letters.forEach((t) => t.setAttribute('font-size', String(FONT_SIZE)));
  const natural = letters.map((t) => measure(t, FONT_SIZE));
  const scale = Math.min(1, MAX_WORD_WIDTH / Math.max(1, natural.reduce((a, b) => a + b, 0)));
  let x = MIDDLE - (natural.reduce((a, b) => a + b, 0) * scale) / 2;
  letters.forEach((t, i) => {
    t.setAttribute('font-size', (FONT_SIZE * scale).toFixed(1));
    t.setAttribute('x', x.toFixed(1));
    t.setAttribute('y', String(BASELINE));
    x += (natural[i] ?? 0) * scale;
  });
}

export function DancingPicture({ src, word, twins, mode, alt, onLoaded, onFailed, className }: DancingPictureProps) {
  const host = useRef<HTMLSpanElement>(null);
  const stage = useRef<Stage | null>(null);
  const running = useRef<Animation[]>([]);
  const [ready, setReady] = useState(false);
  const callbacks = useRef({ onLoaded, onFailed });
  callbacks.current = { onLoaded, onFailed };
  const twinKey = JSON.stringify(twins ?? []);

  const play = () => {
    const s = stage.current;
    running.current.forEach((a) => a.cancel());
    running.current = [];
    if (!s || mode === 'off' || reducedMotion() || typeof s.svg.animate !== 'function') return;
    const run = (el: Element, frames: Keyframe[], options: KeyframeAnimationOptions) => running.current.push(el.animate(frames, options));
    const step = (el: SVGElement, m: MotionStep, delay: number) => {
      anchor(el, m.origin);
      run(el, m.frames, { duration: m.duration, iterations: m.iterations ?? 1, delay });
    };
    s.letters.forEach((el, i) =>
      run(
        el,
        [
          { opacity: 0, transform: 'translateY(-46px) scale(.6)' },
          { opacity: 1, transform: 'translateY(6px) scale(1.06)', offset: 0.7 },
          { opacity: 1, transform: 'translateY(0px) scale(1)' },
        ],
        { duration: LETTER_ENTER_MS, delay: i * LETTER_STEP_MS, fill: 'backwards' },
      ),
    );
    const start = s.letters.length ? meaningStart(s.letters.length) : 0;
    if (s.wordGroup) {
      anchor(s.wordGroup, '50% 100%');
      run(
        s.wordGroup,
        [{ transform: 'translateY(0px)', easing: 'ease-out' }, { transform: 'translateY(-18px)', offset: 0.4, easing: 'ease-in' }, { transform: 'translateY(0px)' }],
        { duration: BEAT_MS, delay: start - BEAT_MS - 160 },
      );
    }
    // the letters the picture makes memorable light up at the meaning part; before it they are ink like the rest
    s.lit.forEach((i) => {
      const el = s.letters[i];
      if (!el) return;
      run(el, [{ fill: INK }, { fill: HOT }], { duration: 220, delay: start, fill: 'backwards' });
      run(
        el,
        [{ transform: 'translateY(0px)', easing: 'ease-out' }, { transform: 'translateY(-28px)', offset: 0.35, easing: 'ease-in' }, { transform: 'translateY(0px)', offset: 0.7 }, { transform: 'translateY(0px)' }],
        { duration: HIGHLIGHT_MS, delay: start },
      );
    });
    if (mode !== 'full') return;
    const steps = motionSteps(s.record.motion);
    if (!steps) return;
    if (s.actor) step(s.actor, steps.actor, start);
    if (s.wordGroup && s.lit.length === 0) step(s.wordGroup, steps.word, start);
  };
  const playRef = useRef(play);
  playRef.current = play;

  useEffect(() => {
    let live = true;
    setReady(false);
    stage.current = null;
    fetch(src, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => {
        const svg = live ? readDrawing(text) : null;
        const node = host.current;
        if (!live) return;
        if (!svg || !node) {
          callbacks.current.onFailed?.();
          return;
        }
        const record = parseStage(svg.querySelector('desc#wd-stage')?.textContent);
        svg.querySelectorAll('title').forEach((t) => t.remove());
        svg.querySelectorAll('[style]').forEach((el) => el.removeAttribute('style'));
        svg.setAttribute('class', 'dpic__svg');
        svg.setAttribute('aria-hidden', 'true');
        node.replaceChildren(svg);
        const actor = svg.querySelector<SVGGraphicsElement>('g#actor');
        let lit = word ? highlightIndexes(word, record.highlight) : [];
        if (word && lit.length === 0) lit = (JSON.parse(twinKey) as [number, number][]).flat();
        const printed = word ? printWord(svg, word, lit) : null;
        stage.current = { svg, record, actor, wordGroup: printed?.group ?? null, letters: printed?.letters ?? [], lit };
        // the lettering font may arrive after the first layout: measure again once it is there
        if (printed && document.fonts?.ready) void document.fonts.ready.then(() => live && placeLetters(printed.letters));
        setReady(true);
        callbacks.current.onLoaded?.();
        playRef.current();
      })
      .catch(() => {
        if (live) callbacks.current.onFailed?.();
      });
    return () => {
      live = false;
      running.current.forEach((a) => a.cancel());
      running.current = [];
    };
  }, [src, word, twinKey]);

  return (
    <button type="button" className={cx('dpic', ready && 'is-loaded', className)} onClick={() => play()} aria-label={alt ? `${alt} · ${zh.word.replayDance}` : zh.word.replayDance}>
      <span ref={host} className="dpic__host" />
    </button>
  );
}
