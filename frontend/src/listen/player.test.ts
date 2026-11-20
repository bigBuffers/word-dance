// listen/player (FRONTEND §5.9, docs/LISTEN_MODE_DESIGN.md §3.3–§3.5, §6.2): the segment lists of both modes, the options
// sanitiser, and the player driven with a fake voice and a fake clock — order and pauses, pause / resume, previous / next,
// changed options, segments nothing can read (skipped and counted), a server out of reach (parked on the word), the words
// never read (published with the finished state), the tap a browser wants first, and the end.
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ListenItem } from '@/api/types';
import type { UtterOutcome } from '@/audio/utter';
import { DEFAULT_OPTIONS, INITIAL_STATE, ListenPlayer, SEGMENT_PAUSE_MS, WORD_PAUSE_MS, sanitizeOptions, segmentsFor, timerWait, type ListenOptions, type ListenState } from './player';

const item = (id: number, over: Partial<ListenItem> = {}): ListenItem => ({
  item_id: id,
  word_id: 100 + id,
  assigned: false,
  kind: 'new',
  done: false,
  display: `w${id}`,
  phonetic: null,
  spoken_en: `w${id}`,
  meaning_zh: `n. 义${id}`,
  gloss_zh: `义${id}`,
  sentence_en: `Sentence ${id}.`,
  sentence_zh: `句子${id}。`,
  ...over,
});

const follow: ListenOptions = DEFAULT_OPTIONS;
const dictation: ListenOptions = { ...DEFAULT_OPTIONS, mode: 'dictation' };
const wordsOnly: ListenOptions = { ...DEFAULT_OPTIONS, sentence: false, zh: false };

/**
 * A player over a fake voice and clock. Every `utter` / `wait` is logged (`en:w1`, `zh:义1`, `wait:350`, `stop`); with `hold`
 * set the call in flight stays open until `release()` (or, for a wait, until its signal aborts), otherwise it resolves at once.
 */
function harness(outcomeOf: (text: string) => UtterOutcome = () => 'ended') {
  const log: string[] = [];
  const states: ListenState[] = [];
  let open: (() => void) | null = null;
  const h = {
    hold: false,
    log,
    states,
    aborted: 0,
    player: null as unknown as ListenPlayer,
    /** Lets the held call finish. */
    release() {
      const resolve = open;
      open = null;
      resolve?.();
    },
    /** Runs the chain until it is held or over. */
    drain: () => new Promise<void>((resolve) => setTimeout(resolve, 0)),
    state: () => h.player.getState(),
    spoken: () => log.filter((entry) => entry.startsWith('en:') || entry.startsWith('zh:')),
  };
  h.player = new ListenPlayer({
    utter: (text, lang) => {
      log.push(`${lang}:${text}`);
      if (!h.hold) return Promise.resolve(outcomeOf(text));
      return new Promise<UtterOutcome>((resolve) => (open = () => resolve(outcomeOf(text))));
    },
    stop: () => void log.push('stop'),
    wait: (ms, signal) => {
      log.push(`wait:${ms}`);
      if (!h.hold) return Promise.resolve();
      return new Promise<void>((resolve) => {
        open = resolve;
        signal.addEventListener('abort', () => {
          h.aborted += 1;
          resolve();
        });
      });
    },
    onChange: (state) => void states.push(state),
  });
  return h;
}

describe('segmentsFor', () => {
  it('follow: word → gloss → sentence → translation, the Chinese ones only with 中文 on, the sentence ones only with 例句 on', () => {
    const kinds = (options: ListenOptions, row = item(1)) => segmentsFor(row, options).map((s) => s.kind);
    expect(segmentsFor(item(1), follow)).toEqual([
      { kind: 'word', text: 'w1', lang: 'en', round: 1 },
      { kind: 'gloss', text: '义1', lang: 'zh', round: 1 },
      { kind: 'sentence', text: 'Sentence 1.', lang: 'en', round: 1 },
      { kind: 'sentenceZh', text: '句子1。', lang: 'zh', round: 1 },
    ]);
    expect(kinds({ ...follow, zh: false })).toEqual(['word', 'sentence']);
    expect(kinds({ ...follow, sentence: false })).toEqual(['word', 'gloss']);
    expect(kinds(wordsOnly)).toEqual(['word']); // both off: the words in a row, no writing time
  });

  it('follow: a part the playlist row lacks is left out; a headword the server would refuse still gets the rest read', () => {
    const kinds = (row: ListenItem) => segmentsFor(row, follow).map((s) => s.kind);
    expect(kinds(item(1, { gloss_zh: null }))).toEqual(['word', 'sentence', 'sentenceZh']);
    expect(kinds(item(1, { sentence_zh: null }))).toEqual(['word', 'gloss', 'sentence']);
    expect(kinds(item(1, { sentence_en: null }))).toEqual(['word', 'gloss']); // no translation without its sentence
    expect(kinds(item(1, { sentence_en: null, sentence_zh: null, gloss_zh: null }))).toEqual(['word']);
    expect(kinds(item(1, { spoken_en: null }))).toEqual(['gloss', 'sentence', 'sentenceZh']);
  });

  it('dictation: the word `repeat` times with `gapSec` of writing time after each reading — no Chinese, no sentence', () => {
    expect(segmentsFor(item(1), dictation)).toEqual([
      { kind: 'word', text: 'w1', lang: 'en', round: 1 },
      { kind: 'gap', ms: 5000, round: 1 },
      { kind: 'word', text: 'w1', lang: 'en', round: 2 },
      { kind: 'gap', ms: 5000, round: 2 },
    ]);
    expect(segmentsFor(item(1), { ...dictation, repeat: 1, gapSec: 12 })).toEqual([
      { kind: 'word', text: 'w1', lang: 'en', round: 1 },
      { kind: 'gap', ms: 12000, round: 1 },
    ]);
    expect(segmentsFor(item(1), { ...dictation, repeat: 3, gapSec: 3 })).toHaveLength(6);
    expect(segmentsFor(item(1, { spoken_en: null }), dictation)).toEqual([]); // nothing to write down: the word is skipped
  });
});

describe('sanitizeOptions', () => {
  it('defaults: follow, sentence and Chinese on, two readings, five seconds', () => {
    expect(DEFAULT_OPTIONS).toEqual({ mode: 'follow', sentence: true, zh: true, repeat: 2, gapSec: 5 });
    for (const junk of [undefined, null, 'follow', 42, [], {}]) expect(sanitizeOptions(junk)).toEqual(DEFAULT_OPTIONS);
  });

  it('keeps every valid field and replaces each invalid one by its default', () => {
    const stored = { mode: 'dictation', sentence: false, zh: false, repeat: 3, gapSec: 12 };
    expect(sanitizeOptions(stored)).toEqual(stored);
    expect(sanitizeOptions({ mode: 'dictation', extra: 1 })).toEqual({ ...DEFAULT_OPTIONS, mode: 'dictation' });
    expect(sanitizeOptions({ mode: 'karaoke', sentence: 'no', zh: 0, repeat: 4, gapSec: 7 })).toEqual(DEFAULT_OPTIONS);
    expect(sanitizeOptions({ repeat: '2', gapSec: '8' })).toEqual(DEFAULT_OPTIONS); // numbers, not their strings
    expect(sanitizeOptions({ repeat: 1, gapSec: 8 })).toEqual({ ...DEFAULT_OPTIONS, repeat: 1, gapSec: 8 });
  });
});

describe('ListenPlayer: playing through', () => {
  it('follow: every word in order, 350 ms between its segments and 900 ms before the next word, then finished', async () => {
    const h = harness();
    h.player.load([item(1), item(2)], follow);
    expect(h.state()).toEqual(INITIAL_STATE);
    h.player.play();
    await h.drain();
    expect(h.log).toEqual([
      'stop', // load
      'stop', // play: whatever spoke before is silenced first
      'en:w1',
      `wait:${SEGMENT_PAUSE_MS}`,
      'zh:义1',
      `wait:${SEGMENT_PAUSE_MS}`,
      'en:Sentence 1.',
      `wait:${SEGMENT_PAUSE_MS}`,
      'zh:句子1。',
      `wait:${WORD_PAUSE_MS}`,
      'en:w2',
      `wait:${SEGMENT_PAUSE_MS}`,
      'zh:义2',
      `wait:${SEGMENT_PAUSE_MS}`,
      'en:Sentence 2.',
      `wait:${SEGMENT_PAUSE_MS}`,
      'zh:句子2。',
    ]);
    expect(h.state()).toEqual({ status: 'finished', index: 1, segment: null, round: 1, unspoken: 0, offline: false, unread: [] });
    // what the page highlights, in order: each segment of word 1, the pause between the words, each segment of word 2
    expect(h.states.filter((s) => s.status === 'playing').map((s) => `${s.index}:${s.segment}`)).toEqual([
      '0:null', '0:word', '0:gloss', '0:sentence', '0:sentenceZh', '0:null', '1:word', '1:gloss', '1:sentence', '1:sentenceZh',
    ]);
  });

  it('follow with both switches off reads the words in a row', async () => {
    const h = harness();
    h.player.load([item(1), item(2), item(3)], wordsOnly);
    h.player.play();
    await h.drain();
    expect(h.log.slice(2)).toEqual(['en:w1', `wait:${WORD_PAUSE_MS}`, 'en:w2', `wait:${WORD_PAUSE_MS}`, 'en:w3']);
  });

  it('dictation: the word, the writing time, again — and straight on to the next word', async () => {
    const h = harness();
    h.player.load([item(1), item(2)], { ...dictation, repeat: 2, gapSec: 8 });
    h.player.play();
    await h.drain();
    expect(h.log.slice(2)).toEqual(['en:w1', 'wait:8000', 'en:w1', 'wait:8000', 'en:w2', 'wait:8000', 'en:w2', 'wait:8000']);
    expect(h.states.filter((s) => s.status === 'playing' && s.index === 0).map((s) => `${s.segment}:${s.round}`)).toEqual(['null:1', 'word:1', 'gap:1', 'word:2', 'gap:2']);
    expect(h.state().status).toBe('finished');
  });

  it('dictation skips a word whose headword cannot be spoken; follow reads the rest of it', async () => {
    const rows = [item(1), item(2, { spoken_en: null }), item(3)];
    const d = harness();
    d.player.load(rows, { ...dictation, repeat: 1 });
    d.player.play();
    await d.drain();
    expect(d.spoken()).toEqual(['en:w1', 'en:w3']);
    const f = harness();
    f.player.load(rows, follow);
    f.player.play();
    await f.drain();
    expect(f.spoken()).toEqual(['en:w1', 'zh:义1', 'en:Sentence 1.', 'zh:句子1。', 'zh:义2', 'en:Sentence 2.', 'zh:句子2。', 'en:w3', 'zh:义3', 'en:Sentence 3.', 'zh:句子3。']);
  });

  it('calls the first utter synchronously inside play() (the tap that started it covers the first clip)', () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1)], follow);
    h.player.play();
    expect(h.spoken()).toEqual(['en:w1']);
    expect(h.state()).toEqual({ status: 'playing', index: 0, segment: 'word', round: 1, unspoken: 0, offline: false, unread: [] });
  });

  it('an empty playlist never plays', async () => {
    const h = harness();
    h.player.load([], follow);
    h.player.play();
    h.player.next();
    h.player.restart();
    await h.drain();
    expect(h.spoken()).toEqual([]);
    expect(h.state()).toEqual(INITIAL_STATE);
  });
});

describe('ListenPlayer: transport', () => {
  it('pause silences the voice and parks the chain; play reads the current word again from its first segment', async () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1), item(2)], follow);
    h.player.play();
    h.release(); // w1 read
    await h.drain();
    h.release(); // the 350 ms pause
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1', 'zh:义1']);
    h.log.length = 0;
    h.player.pause();
    expect(h.log).toEqual(['stop']);
    expect(h.state()).toEqual({ status: 'paused', index: 0, segment: null, round: 1, unspoken: 0, offline: false, unread: [] });
    h.release(); // the cut clip's promise settles late: the old chain must not go on
    await h.drain();
    expect(h.spoken()).toEqual([]);
    expect(h.state().status).toBe('paused');
    h.player.play();
    expect(h.spoken()).toEqual(['en:w1']); // from the word, not from the gloss it was cut in
    expect(h.state()).toEqual({ status: 'playing', index: 0, segment: 'word', round: 1, unspoken: 0, offline: false, unread: [] });
    h.player.play(); // already playing: nothing restarts
    expect(h.spoken()).toEqual(['en:w1']);
  });

  it('pause during a writing gap aborts the wait', async () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1)], dictation);
    h.player.play();
    h.release(); // the word is read; the gap is held
    await h.drain();
    expect(h.state()).toMatchObject({ status: 'playing', segment: 'gap', round: 1 });
    h.player.pause();
    expect(h.aborted).toBe(1);
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1']); // the second reading never starts
    expect(h.state().status).toBe('paused');
  });

  it('toggle pauses while playing and plays otherwise', () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1)], follow);
    h.player.toggle();
    expect(h.state().status).toBe('playing');
    h.player.toggle();
    expect(h.state().status).toBe('paused');
    h.player.toggle();
    expect(h.state().status).toBe('playing');
  });

  it('next / prev while playing jump and read at once; the old chain stops', async () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1), item(2), item(3)], follow);
    h.player.play();
    h.player.next();
    expect(h.spoken()).toEqual(['en:w1', 'en:w2']);
    expect(h.state()).toMatchObject({ status: 'playing', index: 1, segment: 'word' });
    h.player.next();
    h.player.prev();
    h.player.prev();
    h.player.prev(); // at the first word: read it again
    expect(h.spoken()).toEqual(['en:w1', 'en:w2', 'en:w3', 'en:w2', 'en:w1', 'en:w1']);
    expect(h.state().index).toBe(0);
    h.release();
    await h.drain();
    expect(h.spoken().slice(6)).toEqual([]); // only the newest chain is alive, and it is held in its 350 ms pause
    expect(h.log[h.log.length - 1]).toBe(`wait:${SEGMENT_PAUSE_MS}`);
  });

  it('next / prev / seek while paused only move: the next play starts there', () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1), item(2), item(3)], follow);
    h.player.next();
    expect(h.state()).toEqual({ status: 'idle', index: 1, segment: null, round: 1, unspoken: 0, offline: false, unread: [] });
    h.player.seek(99); // clamped
    expect(h.state().index).toBe(2);
    h.player.seek(-5);
    expect(h.state().index).toBe(0);
    h.player.seek(1);
    expect(h.spoken()).toEqual([]);
    h.player.play();
    expect(h.spoken()).toEqual(['en:w2']);
    h.player.pause();
    h.player.prev();
    expect(h.state()).toMatchObject({ status: 'paused', index: 0 });
  });

  it('next on the last word finishes the playlist', () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1), item(2)], follow);
    h.player.play();
    h.player.next();
    h.player.next();
    expect(h.state()).toEqual({ status: 'finished', index: 1, segment: null, round: 1, unspoken: 0, offline: false, unread: [0, 1] }); // neither word was read through
    expect(h.log[h.log.length - 1]).toBe('stop');
  });

  it('after the end: next / prev / seek do nothing, play and restart begin again from the first word', async () => {
    const h = harness();
    h.player.load([item(1), item(2)], wordsOnly);
    h.player.play();
    await h.drain();
    expect(h.state().status).toBe('finished');
    h.log.length = 0;
    h.player.next();
    h.player.prev();
    h.player.seek(0);
    expect(h.state().status).toBe('finished'); // the 听写 answer sheet is not taken away by a stray key
    expect(h.log).toEqual([]);
    h.hold = true;
    h.player.play();
    expect(h.state()).toMatchObject({ status: 'playing', index: 0 });
    h.player.seek(1);
    h.player.restart();
    expect(h.spoken()).toEqual(['en:w1', 'en:w2', 'en:w1']);
    expect(h.state()).toMatchObject({ status: 'playing', index: 0 });
  });

  it('load replaces the playlist and stops what was playing', async () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1)], follow);
    h.player.play();
    h.player.load([item(7), item(8)], follow);
    expect(h.state()).toEqual(INITIAL_STATE);
    h.release();
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1']); // the old chain is dead
    h.player.play();
    expect(h.spoken()).toEqual(['en:w1', 'en:w7']);
  });

  it('dispose silences the voice for good: no state reaches onChange and play does nothing', async () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1), item(2)], follow);
    h.player.play();
    const seen = h.states.length;
    h.log.length = 0;
    h.player.dispose();
    expect(h.log).toEqual(['stop']);
    h.release();
    await h.drain();
    h.player.play();
    h.player.restart();
    expect(h.spoken()).toEqual([]);
    expect(h.states).toHaveLength(seen);
  });

  it('a player disposed while playing starts no chain from next / prev / seek or a changed option either', async () => {
    const calls: ((player: ListenPlayer) => void)[] = [
      (player) => player.next(),
      (player) => player.prev(),
      (player) => player.seek(2),
      (player) => player.setOptions({ ...follow, zh: false }),
      (player) => player.setOptions(dictation),
    ];
    for (const call of calls) {
      const h = harness();
      h.hold = true;
      h.player.load([item(1), item(2), item(3)], follow);
      h.player.play();
      h.player.dispose(); // the status it leaves behind is still `playing`
      const seen = h.states.length;
      h.log.length = 0;
      call(h.player);
      h.release();
      await h.drain();
      expect(h.spoken()).toEqual([]);
      expect(h.log.filter((entry) => entry.startsWith('wait:'))).toEqual([]);
      expect(h.states).toHaveLength(seen);
    }
  });
});

describe('ListenPlayer: options', () => {
  it('a changed option re-reads the current word from its first segment with the new segments; unchanged options do nothing', async () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1), item(2)], follow);
    h.player.play();
    h.player.next();
    h.release();
    await h.drain();
    h.release();
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1', 'en:w2', 'zh:义2']);
    h.player.setOptions({ ...follow }); // the same values: the word is not interrupted
    h.player.setOptions({ ...follow, repeat: 3, gapSec: 12 }); // nor by fields only 听写 uses
    expect(h.spoken()).toHaveLength(3);
    h.player.setOptions({ ...follow, zh: false });
    expect(h.spoken().slice(3)).toEqual(['en:w2']);
    h.release();
    await h.drain();
    h.release();
    await h.drain();
    expect(h.spoken().slice(3)).toEqual(['en:w2', 'en:Sentence 2.']); // no gloss any more
    h.player.setOptions({ ...dictation, sentence: false, zh: false, repeat: 3, gapSec: 12 }); // mode switch mid-word: the same word, now dictated with the stored 遍数 / 间隔
    expect(h.spoken().slice(5)).toEqual(['en:w2']);
    h.release();
    await h.drain();
    expect(h.state()).toMatchObject({ status: 'playing', index: 1, segment: 'gap' });
    expect(h.log[h.log.length - 1]).toBe('wait:12000');
    const aborted = h.aborted;
    h.player.setOptions({ ...dictation, sentence: true, zh: true, repeat: 3, gapSec: 12 }); // the switches mean nothing to 听写: the gap goes on
    expect(h.aborted).toBe(aborted);
    expect(h.spoken().slice(5)).toEqual(['en:w2']);
  });

  it('`reread: false` (Chinese turned out to be unreadable mid-chain): the word is not started over, its Chinese still to come is skipped, the Chinese misses are forgotten', async () => {
    const h = harness((text) => (text === '义1' || text === 'Sentence 1.' ? 'unspoken' : 'ended'));
    h.hold = true;
    h.player.load([item(1), item(2)], follow);
    h.player.play();
    h.release(); // w1
    await h.drain();
    h.release(); // the 350 ms pause; 义1 is held
    await h.drain();
    h.release(); // 义1 cannot be read: straight on to the sentence, which is held
    await h.drain();
    expect(h.state()).toMatchObject({ status: 'playing', index: 0, segment: 'sentence', unspoken: 1 });
    h.player.setOptions({ ...follow, zh: false }, { reread: false });
    expect(h.spoken()).toEqual(['en:w1', 'zh:义1', 'en:Sentence 1.']); // the sentence goes on
    expect(h.state()).toMatchObject({ status: 'playing', index: 0, segment: 'sentence', unspoken: 0 });
    h.hold = false;
    h.release(); // the sentence cannot be read either: an English miss, which stays counted
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1', 'zh:义1', 'en:Sentence 1.', 'en:w2', 'en:Sentence 2.']); // 句子1。 is not tried; word 2 has no Chinese
    expect(h.state()).toMatchObject({ status: 'finished', unspoken: 1 });
  });

  it('while paused or idle the new options wait for the next play', () => {
    const h = harness();
    h.hold = true;
    h.player.load([item(1)], follow);
    h.player.setOptions(wordsOnly);
    expect(h.spoken()).toEqual([]);
    expect(h.state()).toEqual(INITIAL_STATE);
    h.player.play();
    h.player.pause();
    h.player.setOptions(dictation);
    expect(h.state().status).toBe('paused');
    expect(h.spoken()).toEqual(['en:w1']);
  });

  it('after the end a changed mode goes back to the start without playing; other options keep the finished screen', async () => {
    const h = harness();
    h.player.load([item(1), item(2)], { ...dictation, repeat: 1 });
    h.player.play();
    await h.drain();
    expect(h.state().status).toBe('finished');
    const spoken = h.spoken().length;
    h.player.setOptions({ ...dictation, repeat: 3, gapSec: 12 });
    expect(h.state().status).toBe('finished'); // adjusting the readings does not take the answer sheet away
    h.player.setOptions({ ...follow, repeat: 3, gapSec: 12 });
    expect(h.state()).toEqual(INITIAL_STATE); // no answer sheet for a dictation that never ran, in either direction
    expect(h.spoken()).toHaveLength(spoken);
  });
});

describe('ListenPlayer: segments nothing can read', () => {
  it('follow: an unspoken segment is counted and skipped without its pause; the chain goes on', async () => {
    const h = harness((text) => (text.startsWith('义') || text === 'Sentence 2.' ? 'unspoken' : 'ended'));
    h.player.load([item(1), item(2)], follow);
    h.player.play();
    await h.drain();
    expect(h.log.slice(2)).toEqual([
      'en:w1',
      `wait:${SEGMENT_PAUSE_MS}`,
      'zh:义1', // unspoken: straight on
      'en:Sentence 1.',
      `wait:${SEGMENT_PAUSE_MS}`,
      'zh:句子1。',
      `wait:${WORD_PAUSE_MS}`,
      'en:w2',
      `wait:${SEGMENT_PAUSE_MS}`,
      'zh:义2',
      'en:Sentence 2.',
      'zh:句子2。',
    ]);
    expect(h.state()).toEqual({ status: 'finished', index: 1, segment: null, round: 1, unspoken: 3, offline: false, unread: [] });
  });

  it('a word of which nothing was heard earns no pause before the next one', async () => {
    const h = harness((text) => (text === 'w1' ? 'unspoken' : 'ended'));
    h.player.load([item(1), item(2)], wordsOnly);
    h.player.play();
    await h.drain();
    expect(h.log.slice(2)).toEqual(['en:w1', 'en:w2']);
    expect(h.state().unspoken).toBe(1);
  });

  it('dictation: a word that cannot be read is not tried again and gets no writing time', async () => {
    const h = harness((text) => (text === 'w2' ? 'unspoken' : 'ended'));
    h.player.load([item(1), item(2), item(3)], { ...dictation, repeat: 2, gapSec: 3 });
    h.player.play();
    await h.drain();
    expect(h.log.slice(2)).toEqual(['en:w1', 'wait:3000', 'en:w1', 'wait:3000', 'en:w2', 'en:w3', 'wait:3000', 'en:w3', 'wait:3000']);
    expect(h.state()).toMatchObject({ status: 'finished', unspoken: 1 });
  });

  it('counts a segment once however often its word is re-read; restart and a fresh run after the end start the count again', async () => {
    const h = harness((text) => (text === '义1' ? 'unspoken' : 'ended'));
    h.hold = true;
    h.player.load([item(1), item(2)], { ...follow, sentence: false });
    h.player.play();
    h.release(); // w1
    await h.drain();
    h.release(); // 350 ms, then 义1 is held
    await h.drain();
    h.release(); // 义1 unspoken
    await h.drain();
    expect(h.state().unspoken).toBe(1);
    h.player.pause();
    h.hold = false;
    h.player.play(); // re-reads word 1: 义1 fails again
    await h.drain();
    expect(h.state()).toMatchObject({ status: 'finished', unspoken: 1 });
    h.hold = true;
    h.player.play(); // again from the top
    expect(h.state()).toMatchObject({ status: 'playing', index: 0, unspoken: 0 });
    h.hold = false;
    h.release();
    await h.drain();
    expect(h.state().unspoken).toBe(1);
    h.hold = true;
    h.player.restart();
    expect(h.state().unspoken).toBe(0);
  });
});

describe('ListenPlayer: a server that cannot be reached', () => {
  it('parks on the current word when utter answers offline: paused, nothing counted, nothing flushed — play() reads that word again', async () => {
    let up = true;
    const h = harness((text) => (up || text.startsWith('w') ? 'ended' : 'offline'));
    h.player.load([item(1), item(2), item(3)], follow);
    h.hold = true;
    h.player.play();
    h.hold = false;
    h.player.next(); // word 2, read through
    up = false; // …but its gloss is not in the browser's cache, and the server is gone
    await h.drain();
    expect(h.log.slice(h.log.indexOf('en:w2'))).toEqual(['en:w2', `wait:${SEGMENT_PAUSE_MS}`, 'zh:义2']); // no pause, no further segment, no further word
    expect(h.state()).toEqual({ status: 'paused', index: 1, segment: null, round: 1, unspoken: 0, offline: true, unread: [] });
    h.player.next(); // moving while parked keeps the note: the server is still to be tried
    h.player.prev();
    expect(h.state()).toMatchObject({ status: 'paused', index: 1, offline: true });

    up = true;
    h.log.length = 0;
    h.player.play();
    await h.drain();
    expect(h.spoken()).toEqual(['en:w2', 'zh:义2', 'en:Sentence 2.', 'zh:句子2。', 'en:w3', 'zh:义3', 'en:Sentence 3.', 'zh:句子3。']);
    expect(h.state()).toEqual({ status: 'finished', index: 2, segment: null, round: 1, unspoken: 0, offline: false, unread: [0] });
    expect(h.states.filter((s) => s.offline).every((s) => s.status === 'paused')).toBe(true); // offline only ever while parked
  });

  it('dictation: an outage does not end on the answer sheet — the word is neither skipped nor given writing time', async () => {
    let up = true;
    const h = harness(() => (up ? 'ended' : 'offline'));
    h.hold = true;
    h.player.load([item(1), item(2), item(3)], { ...dictation, repeat: 1 });
    h.player.play();
    h.release(); // w1 read; its writing time is held
    await h.drain();
    up = false;
    h.hold = false;
    h.release();
    await h.drain();
    expect(h.log.slice(2)).toEqual(['en:w1', 'wait:5000', 'en:w2']);
    expect(h.state()).toMatchObject({ status: 'paused', index: 1, unspoken: 0, offline: true });
    h.player.next();
    h.player.next(); // the learner gives up and ends it: the sheet shows what was never read
    expect(h.state()).toEqual({ status: 'finished', index: 2, segment: null, round: 1, unspoken: 0, offline: false, unread: [1, 2] });
  });
});

describe('ListenPlayer: the words that were never read (the 听写 answer sheet marks them)', () => {
  it('finished publishes the words whose headword was not read through: unreadable, without spoken_en, or skipped with next', async () => {
    const h = harness((text) => (text === 'w2' ? 'unspoken' : 'ended'));
    h.player.load([item(1), item(2), item(3, { spoken_en: null }), item(4)], { ...dictation, repeat: 1 });
    h.player.play();
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1', 'en:w2', 'en:w4']);
    expect(h.state()).toEqual({ status: 'finished', index: 3, segment: null, round: 1, unspoken: 1, offline: false, unread: [1, 2] });
    expect(h.states.filter((s) => s.status !== 'finished').every((s) => s.unread.length === 0)).toBe(true); // nothing to mark before the end

    const skipping = harness();
    skipping.hold = true;
    skipping.player.load([item(1), item(2), item(3)], { ...dictation, repeat: 1 });
    skipping.player.play();
    skipping.player.next(); // w1 was cut before its end
    skipping.release(); // w2 is read through…
    await skipping.drain();
    skipping.player.next(); // …its writing time cut short
    skipping.player.next(); // and w3 skipped as well: past the last word
    expect(skipping.state()).toMatchObject({ status: 'finished', unread: [0, 2] });
  });

  it('a word that failed once and was heard on a later try is not marked, although its miss stays counted', async () => {
    let broken = true;
    const h = harness((text) => (text === 'w1' && broken ? 'unspoken' : 'ended'));
    h.hold = true;
    h.player.load([item(1), item(2)], { ...dictation, repeat: 1 });
    h.player.play();
    h.release(); // w1 cannot be read: on to w2
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1', 'en:w2']);
    broken = false;
    h.player.prev(); // back to w1, which is read this time
    h.hold = false;
    h.release();
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1', 'en:w2', 'en:w1', 'en:w2']);
    expect(h.state()).toMatchObject({ status: 'finished', unspoken: 1, unread: [] });
  });

  it('a new run forgets what the last one heard: restart, play after the end, a reloaded playlist and the mode reset', async () => {
    const h = harness();
    const rows = [item(1), item(2)];
    h.player.load(rows, { ...dictation, repeat: 1 });
    h.player.play();
    await h.drain();
    expect(h.state()).toMatchObject({ status: 'finished', unread: [] });
    h.hold = true;
    h.player.play(); // again from the top: the answer sheet's marks are gone with the sheet
    expect(h.state()).toMatchObject({ status: 'playing', index: 0, unread: [] });
    h.player.next();
    h.player.next();
    expect(h.state()).toMatchObject({ status: 'finished', unread: [0, 1] }); // nothing of this run was heard

    h.hold = false;
    h.player.restart();
    await h.drain();
    expect(h.state()).toMatchObject({ status: 'finished', unread: [] });
    h.player.setOptions({ ...follow, sentence: false, zh: false }); // the mode reset: back to the first word, not playing
    expect(h.state()).toEqual(INITIAL_STATE);
    h.player.seek(1);
    h.player.play(); // only w2 is read in this run
    await h.drain();
    expect(h.state()).toMatchObject({ status: 'finished', unread: [0] });

    h.player.load(rows, { ...dictation, repeat: 1 });
    h.player.next();
    h.player.next();
    expect(h.state()).toMatchObject({ status: 'finished', unread: [0, 1] });
  });
});

describe('ListenPlayer: a browser that wants a tap first', () => {
  it('parks in blocked when utter says so and starts the same word again on play()', async () => {
    let allowed = false;
    const h = harness(() => (allowed ? 'ended' : 'blocked'));
    h.player.load([item(1), item(2)], wordsOnly);
    h.player.play(); // the automatic start, outside any gesture
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1']);
    expect(h.state()).toEqual({ status: 'blocked', index: 0, segment: null, round: 1, unspoken: 0, offline: false, unread: [] });
    h.player.seek(1); // moving while blocked does not play
    h.player.seek(0);
    expect(h.spoken()).toEqual(['en:w1']);
    allowed = true;
    h.player.play(); // inside the tap
    expect(h.spoken()).toEqual(['en:w1', 'en:w1']);
    await h.drain();
    expect(h.spoken()).toEqual(['en:w1', 'en:w1', 'en:w2']);
    expect(h.state().status).toBe('finished');
  });
});

describe('timerWait', () => {
  afterEach(() => vi.useRealTimers());

  it('resolves after the time, or as soon as the signal aborts — and at once for a signal already aborted', async () => {
    vi.useFakeTimers();
    let done = 0;
    void timerWait(900, new AbortController().signal).then(() => (done += 1));
    await vi.advanceTimersByTimeAsync(899);
    expect(done).toBe(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(done).toBe(1);

    const cut = new AbortController();
    void timerWait(5000, cut.signal).then(() => (done += 1));
    await vi.advanceTimersByTimeAsync(100);
    cut.abort();
    await vi.advanceTimersByTimeAsync(0);
    expect(done).toBe(2);
    expect(vi.getTimerCount()).toBe(0); // the timer of an aborted wait is cleared

    void timerWait(5000, cut.signal).then(() => (done += 1));
    await vi.advanceTimersByTimeAsync(0);
    expect(done).toBe(3);
  });
});
