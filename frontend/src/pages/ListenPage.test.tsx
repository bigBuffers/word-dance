// ListenPage render tests (FRONTEND §5.9, docs/LISTEN_MODE_DESIGN.md §3.3–§3.5), over the real player with a fake voice:
//  * the playlist starts by itself and reads word → gloss → sentence → translation with the learner's accent, the segment
//    being read highlighted; the transport buttons and the keyboard drive it;
//  * dictation never puts the word in the DOM before the answer sheet, which lists every word with its SpeakButton and
//    marks the ones that were never read;
//  * options re-read the current word and persist in localStorage['wd.listen'];
//  * a browser that wants a tap first gets the tap-to-start button; the empty, error and no-voice states; Chinese nothing
//    can read is left out and said so — also when that only shows mid-chain, without starting the word over; unspoken
//    segments are counted; a server out of reach parks the player on the word; the finished screens take a focus that fell
//    to the body; leaving the page stops the voice.
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, errorMessage } from '@/api/client';
import type { ListenItem, ListenPlaylist } from '@/api/types';
import { resetServerAudio, setServerAudio } from '@/audio/serverAudio';
import type { UtterOutcome } from '@/audio/utter';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import { SEGMENT_PAUSE_MS, WORD_PAUSE_MS } from '@/listen/player';

interface Call {
  text: string;
  lang: string;
  rate: number;
  resolve: (outcome: UtterOutcome) => void;
}
const voice = vi.hoisted(() => ({ en: true, zh: true, calls: [] as Call[], stop: vi.fn(), outcomeOf: null as ((text: string) => UtterOutcome) | null }));
const media = vi.hoisted(() => ({
  handlers: null as { play(): void; pause(): void; prev(): void; next(): void } | null,
  unbind: vi.fn(),
  describe: vi.fn<(now: { title: string; album: string; playing: boolean } | null) => void>(),
}));
const awake = vi.hoisted(() => ({ keep: vi.fn(), release: vi.fn() }));

vi.mock('@/api/endpoints', () => ({ getListenPlaylist: vi.fn() }));
vi.mock('@/auth/AuthContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/AuthContext')>();
  const fake = { user: { id: 1 }, settings: { accent: 'en-GB' } };
  return { ...actual, useAuth: () => fake, useOptionalAuth: () => fake };
});
// the fake voice: every utter() is recorded and stays open until the test ends it — or answers at once through `outcomeOf`
vi.mock('@/audio/utter', () => ({
  utter: (text: string, lang: string, rate: number) =>
    new Promise<UtterOutcome>((resolve) => {
      voice.calls.push({ text, lang, rate, resolve });
      if (voice.outcomeOf) resolve(voice.outcomeOf(text));
    }),
  stopUtter: voice.stop,
  utterAvailable: (lang: string) => (lang === 'zh-CN' ? voice.zh : voice.en),
}));
vi.mock('@/listen/mediaSession', () => ({
  bindMediaSession: (handlers: NonNullable<typeof media.handlers>) => {
    media.handlers = handlers;
    return media.unbind;
  },
  describeMediaSession: media.describe,
}));
vi.mock('@/listen/screenAwake', () => ({
  keepScreenAwake: () => {
    awake.keep();
    return awake.release;
  },
}));

import { getListenPlaylist } from '@/api/endpoints';
import ListenPage, { LISTEN_PREF_KEY } from './ListenPage';

// Latin stand-ins for the Chinese fields: copy lives in zh.ts only, and the voice is fake anyway
const item = (id: number, over: Partial<ListenItem> = {}): ListenItem => ({
  item_id: id,
  word_id: 100 + id,
  kind: 'new',
  done: false,
  display: `w${id}`,
  phonetic: `ph${id}`,
  spoken_en: `w${id}`,
  meaning_zh: `MEANING-${id}`,
  gloss_zh: `gloss-${id}`,
  sentence_en: `Sentence ${id}.`,
  sentence_zh: `TRANSLATION-${id}`,
  ...over,
});
const playlist = (items: ListenItem[]): ListenPlaylist => ({ batch_id: items.length > 0 ? 7 : null, local_date: '2026-11-12', items });

const settle = () =>
  act(async () => {
    for (let i = 0; i < 12; i += 1) await Promise.resolve();
  });
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
/** Ends the utterance in flight, then lets the pause after it pass. */
const finish = async (pauseMs = 0, outcome: UtterOutcome = 'ended') => {
  await act(async () => {
    voice.calls[voice.calls.length - 1]?.resolve(outcome);
    for (let i = 0; i < 12; i += 1) await Promise.resolve();
  });
  if (pauseMs > 0) await advance(pauseMs);
};
const last = () => voice.calls[voice.calls.length - 1]!;
const said = () => voice.calls.map((c) => c.text);
const current = (text: string) => screen.getByText(text).getAttribute('aria-current');

async function renderListen(items: ListenItem[] = [item(1), item(2)]) {
  vi.mocked(getListenPlaylist).mockResolvedValue(playlist(items));
  const view = render(
    <MemoryRouter initialEntries={['/listen']}>
      <ToastProvider>
        <ListenPage />
      </ToastProvider>
    </MemoryRouter>,
  );
  await settle();
  return view;
}

describe('ListenPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    window.localStorage.clear();
    voice.calls.length = 0;
    voice.en = true;
    voice.zh = true;
    voice.outcomeOf = null;
    media.handlers = null;
  });
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
    resetServerAudio();
  });

  it('starts by itself and reads word → gloss → sentence → translation, highlighting the segment being read', async () => {
    await renderListen();
    expect(document.title).toContain(zh.listen.title);
    expect(said()).toEqual(['w1']); // no tap needed
    expect([last().lang, last().rate]).toEqual(['en-GB', 0.92]); // the learner's accent, the pace of every other pronunciation
    expect(screen.getByRole('heading', { level: 2, name: 'w1' })).toBeTruthy();
    expect(screen.getByText('/ph1/')).toBeTruthy();
    expect(screen.getByText(zh.listen.position(1, 2))).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('1');
    expect(current('w1')).toBe('true');
    expect(current('MEANING-1')).toBeNull();

    await finish(SEGMENT_PAUSE_MS);
    expect(said()).toEqual(['w1', 'gloss-1']); // the speakable gloss is read, the dictionary-style meaning is shown
    expect([last().lang, last().rate]).toEqual(['zh-CN', 1]);
    expect(current('MEANING-1')).toBe('true');
    expect(current('w1')).toBeNull();

    await finish(SEGMENT_PAUSE_MS);
    expect(last().text).toBe('Sentence 1.');
    expect(current('Sentence 1.')).toBe('true');
    await finish(SEGMENT_PAUSE_MS);
    expect(last().text).toBe('TRANSLATION-1');
    expect(current('TRANSLATION-1')).toBe('true');

    await finish(WORD_PAUSE_MS - 1);
    expect(said()).toHaveLength(4); // the pause between two words
    await advance(1);
    expect(last().text).toBe('w2');
    expect(screen.getByRole('heading', { level: 2, name: 'w2' })).toBeTruthy();
    expect(screen.queryByText('w1')).toBeNull();
    expect(screen.getByText(zh.listen.position(2, 2))).toBeTruthy();
  });

  it('the transport buttons and the keyboard: pause / play, previous / next, restart', async () => {
    await renderListen([item(1), item(2), item(3)]);
    voice.stop.mockClear(); // loading and starting silenced the voice twice already
    fireEvent.click(screen.getByRole('button', { name: zh.listen.pause }));
    expect(voice.stop).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: zh.listen.pause })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: zh.listen.play }));
    expect(said()).toEqual(['w1', 'w1']); // resumed from the first segment of the current word
    fireEvent.click(screen.getByRole('button', { name: zh.listen.next }));
    expect(last().text).toBe('w2');
    fireEvent.click(screen.getByRole('button', { name: zh.listen.next }));
    fireEvent.click(screen.getByRole('button', { name: zh.listen.prev }));
    expect(said().slice(2)).toEqual(['w2', 'w3', 'w2']);
    expect(screen.getByText(zh.listen.position(2, 3))).toBeTruthy();

    fireEvent.keyDown(window, { key: ' ' }); // Space: pause
    expect(screen.getByRole('button', { name: zh.listen.play })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'ArrowRight' }); // moves while paused, does not speak
    expect(screen.getByRole('heading', { level: 2, name: 'w3' })).toBeTruthy();
    expect(said()).toHaveLength(5);
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    fireEvent.keyDown(window, { key: ' ' }); // Space: play
    expect(last().text).toBe('w2');
    fireEvent.click(screen.getByRole('button', { name: zh.listen.restart }));
    expect(last().text).toBe('w1');
    expect(screen.getByText(zh.listen.position(1, 3))).toBeTruthy();
  });

  it('follow mode ends on the finished screen with listen-again and go-study', async () => {
    voice.outcomeOf = () => 'ended';
    await renderListen();
    await advance(10_000);
    expect(said()).toHaveLength(8);
    expect(screen.getByText(zh.listen.finished)).toBeTruthy();
    expect(screen.getByText(zh.listen.position(2, 2))).toBeTruthy();
    expect(screen.queryByRole('button', { name: zh.listen.play })).toBeNull();
    expect(screen.getByRole('link', { name: zh.listen.goStudy }).getAttribute('href')).toBe('/study');
    fireEvent.keyDown(window, { key: ' ' }); // the keyboard is off on the finished screens
    expect(said()).toHaveLength(8);
    voice.outcomeOf = null;
    fireEvent.click(screen.getByRole('button', { name: zh.listen.again }));
    expect(last().text).toBe('w1');
    expect(screen.queryByText(zh.listen.finished)).toBeNull();
  });

  it('switching the mode on a finished screen goes back to the first word without playing, never to the other finished screen', async () => {
    voice.outcomeOf = () => 'ended';
    await renderListen();
    await advance(10_000);
    expect(screen.getByText(zh.listen.finished)).toBeTruthy();
    voice.outcomeOf = null;
    const spoken = said().length;
    fireEvent.click(screen.getByRole('radio', { name: zh.listen.modes.dictation }));
    expect(screen.queryByRole('heading', { name: zh.listen.answers })).toBeNull(); // no answer sheet for a dictation that never ran
    expect(screen.queryByText(zh.listen.finished)).toBeNull();
    expect(screen.getByText(zh.listen.dictationIndex(1))).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.listen.play })).toBeTruthy();
    expect(said()).toHaveLength(spoken);
  });

  it('dictation reads only the word, never shows it while playing, and ends on the answer sheet', async () => {
    setServerAudio(true); // so the answer sheet's SpeakButtons are enabled
    window.localStorage.setItem(LISTEN_PREF_KEY, JSON.stringify({ mode: 'dictation', repeat: 2, gapSec: 3 }));
    const { container } = await renderListen();
    expect(said()).toEqual(['w1']);
    expect(screen.getByText(zh.listen.dictationIndex(1))).toBeTruthy();
    expect(screen.getByText(zh.listen.dictationHint)).toBeTruthy();
    const hidden = () => ['w1', 'w2', 'MEANING', 'ph1', 'Sentence'].every((secret) => !container.textContent?.includes(secret));
    expect(hidden()).toBe(true);
    expect(container.querySelectorAll('.listen__round')).toHaveLength(2);

    await finish(2_999);
    expect(said()).toEqual(['w1']); // writing time
    await advance(1);
    expect(said()).toEqual(['w1', 'w1']); // the second reading
    expect(container.querySelectorAll('.listen__round.is-done')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: zh.listen.pause })); // paused: still nothing to peek at
    expect(hidden()).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: zh.listen.next }));
    fireEvent.click(screen.getByRole('button', { name: zh.listen.play }));
    expect(last().text).toBe('w2');
    expect(screen.getByText(zh.listen.dictationIndex(2))).toBeTruthy();
    expect(media.describe.mock.calls.every(([now]) => now === null || !/w\d/.test(now.title))).toBe(true); // nor on the lock screen
    expect(hidden()).toBe(true);
    await finish(3_000);
    await finish(3_000);

    expect(screen.getByRole('heading', { name: zh.listen.answers })).toBeTruthy();
    const rows = screen.getAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual(['1w1MEANING-1', '2w2MEANING-2']);
    expect(within(rows[0]!).getByRole('button', { name: zh.word.speak })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: zh.common.backToToday }).map((a) => a.getAttribute('href'))).toEqual(['/today', '/today']); // the head's exit + the sheet's own
    const before = said().length;
    fireEvent.keyDown(window, { key: ' ' }); // a stray key does not take the answers away
    act(() => media.handlers?.play());
    fireEvent.click(screen.getByRole('radio', { name: zh.listen.repeats(3) })); // nor does adjusting the readings
    expect(said()).toHaveLength(before);
    expect(screen.getByRole('heading', { name: zh.listen.answers })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: zh.listen.dictateAgain }));
    expect(last().text).toBe('w1');
    expect(screen.queryByRole('heading', { name: zh.listen.answers })).toBeNull();
    expect(hidden()).toBe(true);
  });

  it('options re-read the current word without the parts switched off and persist in localStorage', async () => {
    const { container } = await renderListen();
    await finish(SEGMENT_PAUSE_MS);
    expect(last().text).toBe('gloss-1');
    fireEvent.click(screen.getByRole('switch', { name: zh.listen.optZh }));
    expect(JSON.parse(window.localStorage.getItem(LISTEN_PREF_KEY) ?? '{}')).toMatchObject({ mode: 'follow', zh: false, sentence: true });
    expect(last().text).toBe('w1'); // the current word again, from its first segment
    await finish(SEGMENT_PAUSE_MS);
    expect(last().text).toBe('Sentence 1.'); // no gloss any more
    await finish(WORD_PAUSE_MS);
    expect(last().text).toBe('w2'); // and no translation

    fireEvent.click(screen.getByRole('switch', { name: zh.listen.optSentence }));
    expect(screen.queryByText('Sentence 2.')).toBeNull(); // what is not read is not shown
    expect(screen.getByText('MEANING-2')).toBeTruthy();

    fireEvent.click(screen.getByRole('radio', { name: zh.listen.modes.dictation }));
    expect(screen.queryByText('w2')).toBeNull();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.getByText(zh.listen.optRepeat)).toBeTruthy();
    expect(screen.getByText(zh.listen.optGap)).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: zh.listen.repeats(3) }));
    fireEvent.click(screen.getByRole('radio', { name: zh.listen.gaps(12) }));
    expect(JSON.parse(window.localStorage.getItem(LISTEN_PREF_KEY) ?? '{}')).toEqual({ mode: 'dictation', sentence: false, zh: false, repeat: 3, gapSec: 12 });
    expect(container.querySelectorAll('.listen__round')).toHaveLength(3);
    await finish(11_999);
    const before = said().length;
    await advance(1);
    expect(said()).toHaveLength(before + 1); // the 12-second gap is the one in force
  });

  it('a browser that wants a tap first: the stage offers tap-to-start and the tap starts the same word', async () => {
    voice.outcomeOf = () => 'blocked';
    await renderListen();
    expect(said()).toEqual(['w1']);
    const tap = screen.getByRole('button', { name: zh.listen.tapToStart });
    expect(screen.getByRole('button', { name: zh.listen.play })).toBeTruthy(); // not playing
    voice.outcomeOf = null;
    fireEvent.click(tap);
    expect(said()).toEqual(['w1', 'w1']);
    expect(screen.queryByRole('button', { name: zh.listen.tapToStart })).toBeNull();
    expect(screen.getByRole('button', { name: zh.listen.pause })).toBeTruthy();
  });

  it('an empty playlist shows the empty state with the way back and plays nothing', async () => {
    await renderListen([]);
    expect(screen.getByText(zh.listen.empty)).toBeTruthy();
    expect(screen.getAllByRole('link', { name: zh.common.backToToday }).map((a) => a.getAttribute('href'))).toEqual(['/today', '/today']); // the head's exit + the empty state's action
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(said()).toEqual([]);
    fireEvent.keyDown(window, { key: ' ' });
    expect(said()).toEqual([]);
  });

  it('a failed load offers a retry, which then plays', async () => {
    const failure = new ApiError('internal_error', 500, 'boom');
    vi.mocked(getListenPlaylist).mockRejectedValueOnce(failure);
    render(
      <MemoryRouter initialEntries={['/listen']}>
        <ToastProvider>
          <ListenPage />
        </ToastProvider>
      </MemoryRouter>,
    );
    await settle();
    expect(screen.getByText(errorMessage(failure))).toBeTruthy();
    expect(screen.getByRole('link', { name: zh.common.backToToday }).getAttribute('href')).toBe('/today'); // a bare route: the head is the only way out
    expect(screen.queryByRole('progressbar')).toBeNull();
    vi.mocked(getListenPlaylist).mockResolvedValue(playlist([item(1)]));
    fireEvent.click(screen.getByRole('button', { name: zh.common.retry }));
    await settle();
    expect(said()).toEqual(['w1']);
  });

  it('a device nothing can read on gets the no-voice state and a way to the cards', async () => {
    voice.en = false;
    await renderListen();
    expect(screen.getByText(zh.listen.noVoice)).toBeTruthy();
    expect(screen.getByRole('link', { name: zh.listen.goStudy }).getAttribute('href')).toBe('/study');
    expect(said()).toEqual([]);
  });

  it('Chinese nothing here can read is left out of the chain and said so; the switch keeps the preference', async () => {
    voice.zh = false;
    await renderListen();
    expect(screen.getByText(zh.listen.noZh)).toBeTruthy();
    expect(screen.getByRole('switch', { name: zh.listen.optZh }).getAttribute('aria-checked')).toBe('true');
    await finish(SEGMENT_PAUSE_MS);
    expect(said()).toEqual(['w1', 'Sentence 1.']);
    await finish(WORD_PAUSE_MS);
    expect(said()).toEqual(['w1', 'Sentence 1.', 'w2']);
    expect(voice.calls.some((c) => c.lang === 'zh-CN')).toBe(false);
    expect(window.localStorage.getItem(LISTEN_PREF_KEY)).toBeNull(); // the stored preference is not rewritten
    fireEvent.click(screen.getByRole('switch', { name: zh.listen.optZh }));
    expect(screen.queryByText(zh.listen.noZh)).toBeNull(); // nothing to explain once Chinese is switched off
  });

  it('Chinese that turns out to be unreadable mid-chain is dropped without starting the word over, and the note replaces the count', async () => {
    await renderListen();
    await finish(SEGMENT_PAUSE_MS);
    expect(said()).toEqual(['w1', 'gloss-1']); // nothing could tell beforehand: the first Chinese segment is tried
    expect(screen.queryByText(zh.listen.noZh)).toBeNull();
    voice.zh = false; // the shell's plugin refused the language, or the server's Chinese clip failed: no route is left
    await finish(0, 'unspoken');
    expect(said()).toEqual(['w1', 'gloss-1', 'Sentence 1.']); // straight on — the word is not read a second time
    expect(screen.getByText(zh.listen.noZh)).toBeTruthy();
    expect(screen.queryByText(zh.listen.skipped(1))).toBeNull(); // the note says why: no count beside it
    expect(screen.getByRole('switch', { name: zh.listen.optZh }).getAttribute('aria-checked')).toBe('true');
    await finish(SEGMENT_PAUSE_MS + WORD_PAUSE_MS);
    expect(said()).toEqual(['w1', 'gloss-1', 'Sentence 1.', 'w2']); // the translation of the word in flight is not tried either
    await finish(SEGMENT_PAUSE_MS);
    expect(last().text).toBe('Sentence 2.');
    expect(voice.calls.filter((c) => c.lang === 'zh-CN')).toHaveLength(1);
    expect(screen.queryByText(zh.listen.skipped(1))).toBeNull();
  });

  it('a server out of reach parks the player on the current word and says so; play tries that word again', async () => {
    await renderListen();
    await finish(SEGMENT_PAUSE_MS);
    await finish(0, 'offline'); // the gloss: the server is gone and nothing here reads Chinese
    expect(screen.getByText(zh.listen.offline)).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.listen.play })).toBeTruthy(); // parked, not playing
    expect(screen.queryByRole('button', { name: zh.listen.tapToStart })).toBeNull();
    expect(screen.getByText(zh.listen.position(1, 2))).toBeTruthy(); // on the word it was reading
    expect(screen.queryByText(zh.listen.skipped(1))).toBeNull(); // nothing was skipped
    expect(awake.release).toHaveBeenCalledTimes(1);
    await advance(60_000);
    expect(said()).toEqual(['w1', 'gloss-1']); // and nothing is flushed meanwhile
    fireEvent.click(screen.getByRole('button', { name: zh.listen.play }));
    expect(said()).toEqual(['w1', 'gloss-1', 'w1']);
    expect(screen.queryByText(zh.listen.offline)).toBeNull();
  });

  it('the answer sheet marks the words that were never read', async () => {
    setServerAudio(true);
    window.localStorage.setItem(LISTEN_PREF_KEY, JSON.stringify({ mode: 'dictation', repeat: 1, gapSec: 3 }));
    voice.outcomeOf = (text) => (text === 'w2' ? 'unspoken' : 'ended');
    await renderListen([item(1), item(2), item(3, { spoken_en: null }), item(4)]);
    await advance(10_000);
    expect(said()).toEqual(['w1', 'w2', 'w4']); // w2 could not be read, w3 has nothing to read
    expect(screen.getByRole('heading', { name: zh.listen.answers })).toBeTruthy();
    const rows = screen.getAllByRole('listitem');
    expect(rows.map((row) => within(row).queryByText(zh.listen.unread) !== null)).toEqual([false, true, true, false]);
    expect(rows[0]!.textContent).toBe('1w1MEANING-1');
    expect(rows[1]!.textContent).toBe(`2w2${zh.listen.unread}MEANING-2`);
  });

  it('the finished screens take the keyboard focus the unmounted transport bar dropped, and leave a focus that is still somewhere alone', async () => {
    window.localStorage.setItem(LISTEN_PREF_KEY, JSON.stringify({ mode: 'dictation', repeat: 1, gapSec: 3 }));
    const sheet = await renderListen([item(1)]);
    screen.getByRole('button', { name: zh.listen.pause }).focus();
    await finish(3_000);
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: zh.listen.answers })); // announced, and Tab goes on from the answers
    fireEvent.click(screen.getByRole('button', { name: zh.listen.dictateAgain }));
    const readings = screen.getByRole('radio', { name: zh.listen.repeats(1) });
    readings.focus();
    await finish(3_000);
    expect(screen.getByRole('heading', { name: zh.listen.answers })).toBeTruthy();
    expect(document.activeElement).toBe(readings); // the learner was on the options: not taken away
    sheet.unmount();

    window.localStorage.setItem(LISTEN_PREF_KEY, JSON.stringify({ mode: 'follow', sentence: false, zh: false }));
    await renderListen([item(1)]);
    screen.getByRole('button', { name: zh.listen.pause }).focus();
    await finish();
    expect(document.activeElement).toBe(screen.getByText(zh.listen.finished));
  });

  it('counts the segments that could not be read', async () => {
    voice.outcomeOf = (text) => (text.startsWith('gloss') ? 'unspoken' : 'ended');
    await renderListen();
    await advance(10_000);
    expect(screen.getByText(zh.listen.finished)).toBeTruthy();
    expect(screen.getByText(zh.listen.skipped(2))).toBeTruthy();
    expect(said()).toHaveLength(8); // nothing stalled
  });

  it('keeps the screen awake only while playing, serves the headset buttons, and stops the voice when the page unmounts', async () => {
    const view = await renderListen();
    expect(awake.keep).toHaveBeenCalledTimes(1);
    expect(media.describe).toHaveBeenLastCalledWith({ title: 'w1', album: zh.listen.title, playing: true });
    act(() => media.handlers?.pause());
    expect(awake.release).toHaveBeenCalledTimes(1);
    expect(media.describe).toHaveBeenLastCalledWith({ title: 'w1', album: zh.listen.title, playing: false });
    act(() => media.handlers?.next());
    act(() => media.handlers?.play());
    expect(last().text).toBe('w2');
    expect(awake.keep).toHaveBeenCalledTimes(2);
    act(() => media.handlers?.prev());
    expect(last().text).toBe('w1');

    voice.stop.mockClear();
    view.unmount();
    expect(voice.stop).toHaveBeenCalled();
    expect(media.unbind).toHaveBeenCalledTimes(1);
    expect(awake.release).toHaveBeenCalledTimes(2);
    const spoken = said().length;
    await finish(10_000); // the clip that was cut settles late: the chain is dead
    expect(said()).toHaveLength(spoken);
  });
});
