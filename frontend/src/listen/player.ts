// listen/player — the 磨耳朵 playlist as a pure state machine (FRONTEND.md §5.9; docs/LISTEN_MODE_DESIGN.md §3.3–§3.5, §6.2).
// No React, no audio, no timers of its own: the page injects `utter` (audio/utter.ts with the learner's accent and the rates),
// `stop`, `wait` and `onChange`, and vitest drives the same class with fakes.
//
// A word is a list of segments (`segmentsFor`): 跟着听 reads the headword, its Chinese gloss, one example sentence and the
// sentence's translation — gloss and translation only with 中文 on, sentence and translation only with 例句 on, each only when the
// playlist row has it; 听写 reads the headword `repeat` times with `gapSec` seconds of writing time after each reading. A row
// whose headword endpoint 76 would refuse (`spoken_en: null`) has no `word` segment: 跟着听 still reads the rest, 听写 skips the word.
//
// One chain runs at a time. Every transport call (pause, seek, a changed option, restart, dispose) bumps the generation, aborts the
// wait in flight and stops the voice; the old chain's awaits then come back to a generation that is no longer theirs and return
// without touching the state. `utter` answering `blocked` (the browser wants a tap before any sound) parks the player in `blocked`
// until `play()` is called from that tap; `unspoken` (no route could read the segment) is counted and the chain moves on —
// playback never stalls on a segment; `offline` (the server is out of reach and the device cannot read the segment either) parks
// the player on the current word, paused with `offline` set and nothing counted — skipping would run through the rest of the
// playlist in a moment — until `play()` tries that word again. Resuming after a pause re-reads the current word from its first
// segment, and so does a changed option. The first `utter` of a chain is called synchronously inside `play()`, so the tap's
// gesture covers it.
import type { ListenItem } from '@/api/types';
import type { UtterOutcome } from '@/audio/utter';

export type ListenMode = 'follow' | 'dictation';
export type ListenRepeat = 1 | 2 | 3;
export type ListenGap = 3 | 5 | 8 | 12;

export interface ListenOptions {
  mode: ListenMode;
  /** 跟着听: read the example sentence. */
  sentence: boolean;
  /** 跟着听: read the Chinese gloss (and, with `sentence`, the sentence's translation). */
  zh: boolean;
  /** 听写: readings per word. */
  repeat: ListenRepeat;
  /** 听写: seconds of writing time after each reading. */
  gapSec: ListenGap;
}

export const LISTEN_REPEATS: readonly ListenRepeat[] = [1, 2, 3];
export const LISTEN_GAPS: readonly ListenGap[] = [3, 5, 8, 12];
export const DEFAULT_OPTIONS: ListenOptions = { mode: 'follow', sentence: true, zh: true, repeat: 2, gapSec: 5 };

/** Pause between two spoken segments of a word, and between two words (跟着听; 听写 has its own gaps). */
export const SEGMENT_PAUSE_MS = 350;
export const WORD_PAUSE_MS = 900;

/** Whatever localStorage['wd.listen'] holds → valid options: every field that is missing or out of range takes its default. */
export function sanitizeOptions(raw: unknown): ListenOptions {
  const o = raw !== null && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const mode = o['mode'];
  const sentence = o['sentence'];
  const zh = o['zh'];
  return {
    mode: mode === 'follow' || mode === 'dictation' ? mode : DEFAULT_OPTIONS.mode,
    sentence: typeof sentence === 'boolean' ? sentence : DEFAULT_OPTIONS.sentence,
    zh: typeof zh === 'boolean' ? zh : DEFAULT_OPTIONS.zh,
    repeat: LISTEN_REPEATS.find((n) => n === o['repeat']) ?? DEFAULT_OPTIONS.repeat,
    gapSec: LISTEN_GAPS.find((n) => n === o['gapSec']) ?? DEFAULT_OPTIONS.gapSec,
  };
}

/** Both option sets read a word the same way: the same mode and the same values of the fields that mode uses. */
function sameReading(a: ListenOptions, b: ListenOptions): boolean {
  if (a.mode !== b.mode) return false;
  return a.mode === 'dictation' ? a.repeat === b.repeat && a.gapSec === b.gapSec : a.sentence === b.sentence && a.zh === b.zh;
}

export type SegmentKind = 'word' | 'gloss' | 'sentence' | 'sentenceZh' | 'gap';
/** The language of a spoken segment; the page maps `en` to the learner's accent and `zh` to zh-CN. */
export type SegmentLang = 'en' | 'zh';
export type Segment =
  | { kind: Exclude<SegmentKind, 'gap'>; text: string; lang: SegmentLang; round: number }
  | { kind: 'gap'; ms: number; round: number };

/** What is read for one word, in order (`round`: which reading of the word in 听写, 1 in 跟着听). */
export function segmentsFor(item: ListenItem, options: ListenOptions): Segment[] {
  const out: Segment[] = [];
  if (options.mode === 'dictation') {
    if (!item.spoken_en) return out; // nothing to write down without the word
    for (let round = 1; round <= options.repeat; round += 1) {
      out.push({ kind: 'word', text: item.spoken_en, lang: 'en', round }, { kind: 'gap', ms: options.gapSec * 1000, round });
    }
    return out;
  }
  if (item.spoken_en) out.push({ kind: 'word', text: item.spoken_en, lang: 'en', round: 1 });
  if (options.zh && item.gloss_zh) out.push({ kind: 'gloss', text: item.gloss_zh, lang: 'zh', round: 1 });
  if (options.sentence && item.sentence_en) {
    out.push({ kind: 'sentence', text: item.sentence_en, lang: 'en', round: 1 });
    if (options.zh && item.sentence_zh) out.push({ kind: 'sentenceZh', text: item.sentence_zh, lang: 'zh', round: 1 });
  }
  return out;
}

export type ListenStatus = 'idle' | 'playing' | 'paused' | 'blocked' | 'finished';

export interface ListenState {
  /** idle = loaded, not started; blocked = the browser wants a tap before it plays (then `play()`). */
  status: ListenStatus;
  /** The word being read (0-based); the last word once finished. */
  index: number;
  /** The segment being read (`gap` = the writing time of 听写); null between words and while not playing. */
  segment: SegmentKind | null;
  /** 听写: which reading of the word (1-based); 1 in 跟着听. */
  round: number;
  /** Distinct segments no route could read since the playlist was (re)started. */
  unspoken: number;
  /** Paused by the player itself: `utter` answered `offline` for the current word. False again once it plays or the playlist ends. */
  offline: boolean;
  /**
   * Once finished: the words (0-based, ascending) whose headword was never read through in this run — nothing could read it, the
   * row has no `spoken_en`, or the learner moved on before it ended. The 听写 answer sheet marks them. Empty until then.
   */
  unread: readonly number[];
}

export const INITIAL_STATE: ListenState = { status: 'idle', index: 0, segment: null, round: 1, unspoken: 0, offline: false, unread: [] };

export interface ListenPlayerDeps {
  /** Reads `text` and resolves when it has been read, could not be read, must wait for a tap, or the server is out of reach (audio/utter.ts). */
  utter(text: string, lang: SegmentLang): Promise<UtterOutcome>;
  /** Silences whatever `utter` is reading. */
  stop(): void;
  /** Resolves after `ms`, or as soon as `signal` aborts. */
  wait(ms: number, signal: AbortSignal): Promise<void>;
  onChange(state: ListenState): void;
}

/** The real `wait`: a timer the signal ends early (resolved either way — the player's generation decides what happens next). */
export function timerWait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal.addEventListener('abort', done);
  });
}

export class ListenPlayer {
  private readonly deps: ListenPlayerDeps;
  private items: readonly ListenItem[] = [];
  private options: ListenOptions = DEFAULT_OPTIONS;
  private state: ListenState = INITIAL_STATE;
  private generation = 0; // the running chain's number; a chain that wakes up to another number stops
  private waiting: AbortController | null = null;
  private readonly missed = new Set<string>(); // `index:kind:round` of every unspoken segment — a re-read word is not counted twice
  private readonly heard = new Set<number>(); // the words whose headword was read through at least once in this run (→ `unread`)
  private disposed = false;

  constructor(deps: ListenPlayerDeps) {
    this.deps = deps;
  }

  getState(): ListenState {
    return this.state;
  }

  /** Replaces the playlist: stopped, at the first word, nothing counted. Does not start playing. */
  load(items: readonly ListenItem[], options: ListenOptions): void {
    this.halt();
    this.items = items;
    this.options = options;
    this.missed.clear();
    this.heard.clear();
    this.set(INITIAL_STATE);
  }

  /** Starts the current word from its first segment (from the first word after `finished`). Call it inside the tap when `blocked`. */
  play(): void {
    if (this.disposed || this.items.length === 0 || this.state.status === 'playing') return;
    if (this.state.status === 'finished') this.restart();
    else this.start(this.state.index);
  }

  pause(): void {
    if (this.state.status !== 'playing') return;
    this.halt();
    this.set({ status: 'paused', segment: null, round: 1 });
  }

  toggle(): void {
    if (this.state.status === 'playing') this.pause();
    else this.play();
  }

  /** The next word; past the last one the playlist is finished. */
  next(): void {
    if (this.items.length === 0 || this.state.status === 'finished') return;
    if (this.state.index < this.items.length - 1) {
      this.seek(this.state.index + 1);
      return;
    }
    this.halt();
    this.set({ status: 'finished', segment: null, round: 1, offline: false, unread: this.unread() });
  }

  /** The previous word (the first word again at the start). */
  prev(): void {
    this.seek(this.state.index - 1);
  }

  /** Moves to word `index` (clamped): read at once while playing, otherwise where the next `play()` starts. Not after `finished`. */
  seek(index: number): void {
    if (this.items.length === 0 || this.state.status === 'finished') return;
    const target = Math.max(0, Math.min(this.items.length - 1, Math.trunc(index)));
    if (this.state.status === 'playing') this.start(target);
    else this.set({ index: target, segment: null, round: 1 });
  }

  /** From the first word, playing, with the unspoken count back at zero and nothing heard yet. */
  restart(): void {
    if (this.disposed || this.items.length === 0) return;
    this.missed.clear();
    this.heard.clear();
    this.set({ unspoken: 0, unread: [] });
    this.start(0);
  }

  /**
   * New options: while playing the current word is read again from its first segment — unless the change does not alter what
   * is read (a field the other mode uses); a finished playlist goes back to the start (not playing) when the mode changed — the
   * 听写 answer sheet must not appear for a dictation that never ran — and otherwise stays finished, so adjusting 遍数 / 间隔
   * does not take the answers away.
   * `reread: false` is for Chinese that turned out to be unreadable while the chain runs (the page learns it from the first
   * Chinese segment the shell's plugin refuses or the server fails): not the learner's doing, so the word being read is not
   * started over — its Chinese segments still to come are skipped (`run`) — and the Chinese segments already counted as
   * unspoken are forgotten: the page's note about Chinese says it once.
   */
  setOptions(options: ListenOptions, { reread = true }: { reread?: boolean } = {}): void {
    const previous = this.options;
    this.options = options;
    if (!reread && previous.zh && !options.zh) {
      for (const key of this.missed) if (key.includes(':gloss:') || key.includes(':sentenceZh:')) this.missed.delete(key);
      this.set({ unspoken: this.missed.size });
    }
    if (this.state.status === 'playing') {
      if (reread && !sameReading(previous, options)) this.start(this.state.index);
    } else if (this.state.status === 'finished' && options.mode !== previous.mode) {
      this.missed.clear();
      this.heard.clear();
      this.set(INITIAL_STATE);
    }
  }

  /** Stops for good (the page unmounted): silence, and no state reaches `onChange` any more. */
  dispose(): void {
    this.halt();
    this.disposed = true;
  }

  /** Ends the chain now running: its awaits come back to a generation that is no longer theirs. */
  private halt(): void {
    this.generation += 1;
    this.waiting?.abort();
    this.waiting = null;
    this.deps.stop();
  }

  private set(patch: Partial<ListenState>): void {
    const next = { ...this.state, ...patch };
    const s = this.state;
    const sameUnread = next.unread.length === s.unread.length && next.unread.every((index, i) => index === s.unread[i]);
    if (next.status === s.status && next.index === s.index && next.segment === s.segment && next.round === s.round && next.unspoken === s.unspoken && next.offline === s.offline && sameUnread) return;
    this.state = next;
    if (!this.disposed) this.deps.onChange(next);
  }

  /** The words not in `heard`, for the finished state. */
  private unread(): number[] {
    return this.items.map((_, index) => index).filter((index) => !this.heard.has(index));
  }

  /** The one place a chain starts — never on a disposed player, whose status may still say `playing`. */
  private start(index: number): void {
    if (this.disposed) return;
    this.halt();
    void this.run(index, this.generation);
  }

  private async run(from: number, mine: number): Promise<void> {
    const waiting = new AbortController();
    this.waiting = waiting;
    const last = this.items.length - 1;
    this.set({ status: 'playing', index: from, segment: null, round: 1, offline: false });
    for (let index = from; index <= last; index += 1) {
      const item = this.items[index];
      if (!item) break;
      const segments = segmentsFor(item, this.options);
      let spoke = false; // something of this word was heard: the pause before the next word is earned
      for (let s = 0; s < segments.length; s += 1) {
        const segment = segments[s];
        if (!segment) break;
        if (segment.kind !== 'gap' && segment.lang === 'zh' && !this.options.zh) continue; // Chinese went off while this word was being read (`setOptions`, `reread: false`): not tried, not counted
        this.set({ index, segment: segment.kind, round: segment.round });
        if (segment.kind === 'gap') {
          await this.deps.wait(segment.ms, waiting.signal);
          if (mine !== this.generation) return;
          continue;
        }
        const outcome = await this.deps.utter(segment.text, segment.lang);
        if (mine !== this.generation) return;
        if (outcome === 'blocked') {
          this.waiting = null;
          this.set({ status: 'blocked', segment: null, round: 1 });
          return;
        }
        if (outcome === 'offline') {
          this.waiting = null;
          this.set({ status: 'paused', segment: null, round: 1, offline: true });
          return;
        }
        if (outcome === 'unspoken') {
          this.missed.add(`${index}:${segment.kind}:${segment.round}`);
          this.set({ unspoken: this.missed.size });
          if (this.options.mode === 'dictation') break; // a word nothing can read is not tried again, and gets no writing time
          continue;
        }
        spoke = true;
        if (segment.kind === 'word') this.heard.add(index);
        const following = segments[s + 1];
        if (following && following.kind !== 'gap') {
          await this.deps.wait(SEGMENT_PAUSE_MS, waiting.signal);
          if (mine !== this.generation) return;
        }
      }
      if (spoke && index < last && segments[segments.length - 1]?.kind !== 'gap') {
        this.set({ segment: null });
        await this.deps.wait(WORD_PAUSE_MS, waiting.signal);
        if (mine !== this.generation) return;
      }
    }
    this.waiting = null;
    this.set({ status: 'finished', index: Math.max(0, last), segment: null, round: 1, unread: this.unread() });
  }
}
