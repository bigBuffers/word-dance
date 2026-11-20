// ListenPage — today's words by ear (`zh.listen.title`; FRONTEND §5.9; docs/LISTEN_MODE_DESIGN.md §3; API.md 123). `/listen` loads
// `GET /api/today/playlist` (review / new / extra words in batch order, one row per word) and plays it hands-free through
// listen/player.ts. `follow` mode reads word → Chinese gloss → example sentence → its translation (switches `optSentence` /
// `optZh`) and shows the word with the segment being read highlighted; `dictation` mode reads only the word (`optRepeat` 1–3
// readings, `optGap` 3 / 5 / 8 / 12 s of writing time after each), shows the position and never the word, and ends on the
// answer sheet (`zh.listen.answers`). Nothing is graded and nothing is recorded: the page only reads.
//
// Playback starts by itself once the playlist is there. Where the browser refuses sound before a tap (iOS Safari) the player
// parks in `blocked` and the stage offers `zh.listen.tapToStart`; inside the app shell no tap is needed. The voice is audio/utter.ts —
// the server's clips first (one <audio> element, the same voice on every device, Chinese included), then the device's own.
// Chinese the server cannot read and the device has no voice for is left out (`zh.listen.noZh`) — up front where that is known,
// else from the first Chinese segment that fails, without starting the word over; a segment nothing could read is skipped and
// counted (`zh.listen.skipped`); a server out of reach parks the player on the current word (`zh.listen.offline`) instead of
// skipping through the playlist. The options live in localStorage['wd.listen'] (per device, FRONTEND §3). The
// player stops when the page unmounts, not when it is hidden; while it plays the screen is asked to stay on and the headset /
// lock-screen controls are bound (listen/screenAwake.ts, listen/mediaSession.ts — both no-ops where the browser lacks the API).
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router';
import { errorMessage } from '@/api/client';
import { getListenPlaylist } from '@/api/endpoints';
import type { ListenItem, ListenPlaylist } from '@/api/types';
import { stopUtter, utter, utterAvailable } from '@/audio/utter';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { EmptyState } from '@/components/ui/EmptyState';
import { NextIcon, PauseIcon, PlayIcon, PrevIcon } from '@/components/ui/icons';
import { Segmented } from '@/components/ui/Segmented';
import { Skeleton } from '@/components/ui/Skeleton';
import { Switch } from '@/components/ui/Switch';
import { SpeakButton } from '@/components/word/SpeakButton';
import { useApi } from '@/hooks/useApi';
import { useBottomBarOffset } from '@/hooks/useBottomBarOffset';
import { useKeyboard } from '@/hooks/useKeyboard';
import { useLocalPref } from '@/hooks/useLocalPref';
import { usePageTitle } from '@/hooks/usePageTitle';
import { DEFAULT_RATE } from '@/hooks/useSpeech';
import { zh } from '@/i18n/zh';
import { bindMediaSession, describeMediaSession } from '@/listen/mediaSession';
import { DEFAULT_OPTIONS, INITIAL_STATE, LISTEN_GAPS, LISTEN_REPEATS, ListenPlayer, sanitizeOptions, timerWait, type ListenMode, type ListenOptions, type ListenState, type SegmentKind } from '@/listen/player';
import { keepScreenAwake } from '@/listen/screenAwake';
import { routePaths } from '@/routes';
import './ListenPage.css';

/** localStorage key of the options (FRONTEND §3): mode, sentence, Chinese, readings, gap — per device, never synced. */
export const LISTEN_PREF_KEY = 'wd.listen';
/** Chinese is read at the voice's own pace; English at the pace of every other pronunciation (design §3.6). */
const ZH_RATE = 1;

const SCOPE_OPTIONS: { value: 'all' | 'assigned'; label: string }[] = [
  { value: 'all', label: zh.listen.scopes.all },
  { value: 'assigned', label: zh.listen.scopes.assigned },
];
const MODE_OPTIONS: { value: ListenMode; label: string }[] = [
  { value: 'follow', label: zh.listen.modes.follow },
  { value: 'dictation', label: zh.listen.modes.dictation },
];
const REPEAT_OPTIONS = LISTEN_REPEATS.map((n) => ({ value: String(n), label: zh.listen.repeats(n) }));
const GAP_OPTIONS = LISTEN_GAPS.map((n) => ({ value: String(n), label: zh.listen.gaps(n) }));

/** Chinese nothing here can read is left out of the chain instead of being tried — and counted as unspoken — word after word. */
function readable(options: ListenOptions, zhAvailable: boolean): ListenOptions {
  return options.zh && !zhAvailable ? { ...options, zh: false } : options;
}

/** One line of the follow-mode stage; the line being read carries `is-active` (and `aria-current`). */
function line(base: string, segment: SegmentKind | null, kind: SegmentKind) {
  const active = segment === kind;
  return { className: cx('listen__line', base, active && 'is-active'), 'aria-current': active ? ('true' as const) : undefined };
}

export default function ListenPage() {
  usePageTitle(zh.listen.title);
  const { settings } = useAuth();
  const accent = settings?.accent ?? 'en-US';
  const repeatLabel = useId();
  const gapLabel = useId();
  const barRef = useBottomBarOffset<HTMLDivElement>();

  const { data, error, loading, reload } = useApi<ListenPlaylist>((signal) => getListenPlaylist(signal), []);
  // assignments (API.md 124–129): when only some of today's words were assigned the listener may narrow the playlist to them
  const [scope, setScope] = useState<'all' | 'assigned'>('all');
  const everything = data?.items ?? null;
  const mixed = !!everything && everything.some((it) => it.assigned) && everything.some((it) => !it.assigned);
  const items: ListenItem[] | null = useMemo(() => (everything && mixed && scope === 'assigned' ? everything.filter((it) => it.assigned) : everything), [everything, mixed, scope]);
  const total = items?.length ?? 0;

  const [stored, setStored] = useLocalPref<unknown>(LISTEN_PREF_KEY, DEFAULT_OPTIONS);
  const options = useMemo(() => sanitizeOptions(stored), [stored]);

  // What can read here is asked on every render (the player's state changes re-render the page): the server flags are module
  // state, a voice list fills in late, and the shell's plugin is only known to lack a language once it has refused it.
  const canSpeak = utterAvailable(accent);
  const zhAvailable = utterAvailable('zh-CN');
  const effective = useMemo(() => readable(options, zhAvailable), [options, zhAvailable]);

  const [state, setState] = useState<ListenState>(INITIAL_STATE);
  const playerRef = useRef<ListenPlayer | null>(null);
  // The player hears of a change in the same batch as the stored options, so one render shows both: a mode switch on a finished
  // screen never paints the other mode's finished screen (the answer sheet of a dictation that never ran) in between.
  const setOption = (patch: Partial<ListenOptions>) => {
    const next = { ...options, ...patch };
    setStored(next);
    playerRef.current?.setOptions(readable(next, zhAvailable));
  };
  const accentRef = useRef(accent);
  const effectiveRef = useRef(effective);
  const answersRef = useRef(false);
  useEffect(() => {
    accentRef.current = accent;
    effectiveRef.current = effective;
  });

  // ---- the player lives as long as the page; leaving the page stops the voice ----------------------
  useEffect(() => {
    const player = new ListenPlayer({
      utter: (text, lang) => (lang === 'zh' ? utter(text, 'zh-CN', ZH_RATE) : utter(text, accentRef.current, DEFAULT_RATE)),
      stop: stopUtter,
      wait: timerWait,
      onChange: setState,
    });
    playerRef.current = player;
    return () => {
      player.dispose();
      playerRef.current = null;
    };
  }, []);

  // ---- a playlist arrived: load it and start by itself (a browser that wants a tap first answers `blocked`) ----
  useEffect(() => {
    const player = playerRef.current;
    if (!player || !items) return;
    player.load(items, effectiveRef.current);
    if (utterAvailable(accentRef.current)) player.play();
  }, [items]);

  // ---- options that changed without a tap here. Another tab's change re-reads the current word when it alters what is read.
  //      Chinese that turned out to be unreadable mid-chain (the shell's plugin refused it, a server clip failed) is not the
  //      learner's doing: the player drops the Chinese still to come, and its count, and the word being read goes on ----
  const zhWas = useRef(zhAvailable);
  useEffect(() => {
    const lostZh = zhWas.current && !zhAvailable;
    zhWas.current = zhAvailable;
    playerRef.current?.setOptions(effective, { reread: !lostZh });
  }, [effective, zhAvailable]);

  const playing = state.status === 'playing';
  const finished = state.status === 'finished';
  const current = items?.[state.index] ?? null;
  const dictation = options.mode === 'dictation';
  const position = total === 0 ? 0 : finished ? total : state.index + 1;
  const ready = total > 0 && canSpeak;
  useEffect(() => {
    answersRef.current = finished && dictation;
  });

  // ---- the finished screens replace the transport bar: a keyboard focus that sat on it falls to <body>, and the screen's
  //      heading takes it — announced, and Tab goes on from there. A focus that is still on a control (the options) stays ----
  const sheetTitleRef = useRef<HTMLHeadingElement>(null);
  const finishedTitleRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (finished && document.activeElement === document.body) (sheetTitleRef.current ?? finishedTitleRef.current)?.focus();
  }, [finished]);

  // ---- screen on while playing; re-requested by the helper when the page returns to the foreground --
  useEffect(() => {
    if (!playing) return;
    return keepScreenAwake();
  }, [playing]);

  // ---- headset buttons / lock-screen controls. Dictation never names the word; the answer sheet is not restarted by a stray key ----
  useEffect(
    () =>
      bindMediaSession({
        play: () => {
          if (!answersRef.current) playerRef.current?.play();
        },
        pause: () => playerRef.current?.pause(),
        prev: () => playerRef.current?.prev(),
        next: () => playerRef.current?.next(),
      }),
    [],
  );
  const nowPlaying = !ready || !current ? null : dictation ? zh.listen.dictationIndex(state.index + 1) : current.display;
  useEffect(() => {
    describeMediaSession(nowPlaying === null ? null : { title: nowPlaying, album: zh.listen.title, playing });
  }, [nowPlaying, playing]);

  // ---- keyboard (design §3.5): Space play / pause, ← / → previous / next; off on the finished screens ----
  useKeyboard(
    {
      Space: () => playerRef.current?.toggle(),
      ArrowLeft: () => playerRef.current?.prev(),
      ArrowRight: () => playerRef.current?.next(),
    },
    { enabled: ready && !finished },
  );

  // ---- render ----------------------------------------------------------------------------------------
  const head = (
    <header className="listen__head">
      <Link to={routePaths.today} className="listen__exit">
        {zh.common.backToToday}
      </Link>
      <h1 className="listen__title">{zh.listen.title}</h1>
      <span className="listen__progress muted">{total > 0 ? zh.listen.position(position, total) : null}</span>
    </header>
  );

  if (loading && !data) {
    return (
      <section className="page listen" aria-busy="true">
        <Skeleton height={28} width="40%" />
        <Skeleton height={160} className="listen__skeleton" />
        <Skeleton lines={3} />
      </section>
    );
  }

  if (error && !data) {
    // the route is bare (no nav): the head's exit is the way out while the retry keeps failing
    return (
      <section className="page listen">
        {head}
        <EmptyState title={errorMessage(error)} action={{ label: zh.common.retry, onClick: () => void reload() }} />
      </section>
    );
  }

  if (!items || total === 0) {
    return (
      <section className="page listen">
        {head}
        <EmptyState title={zh.listen.empty} action={{ label: zh.common.backToToday, to: routePaths.today }} />
      </section>
    );
  }

  if (!canSpeak) {
    return (
      <section className="page listen">
        {head}
        <EmptyState title={zh.listen.noVoice} action={{ label: zh.listen.goStudy, to: routePaths.study }} />
      </section>
    );
  }

  const skipped = state.unspoken > 0 && (
    <p className="listen__note" role="status">
      {zh.listen.skipped(state.unspoken)}
    </p>
  );

  return (
    <section className="page listen">
      {head}
      <div className="listen__meter" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={position} aria-label={zh.listen.title}>
        <span className="listen__meter-fill" style={{ width: `${(position / total) * 100}%` }} />
      </div>

      <div className="listen__options">
        {mixed && <Segmented block size="sm" options={SCOPE_OPTIONS} value={scope} onChange={setScope} aria-label={zh.listen.scope} />}
        <Segmented block options={MODE_OPTIONS} value={options.mode} onChange={(mode) => setOption({ mode })} aria-label={zh.listen.title} />
        {dictation ? (
          <div className="listen__picks">
            <div className="listen__pick">
              <span id={repeatLabel} className="listen__pick-label">
                {zh.listen.optRepeat}
              </span>
              <Segmented
                size="sm"
                options={REPEAT_OPTIONS}
                value={String(options.repeat)}
                onChange={(v) => setOption({ repeat: LISTEN_REPEATS.find((n) => String(n) === v) ?? options.repeat })}
                aria-labelledby={repeatLabel}
              />
            </div>
            <div className="listen__pick">
              <span id={gapLabel} className="listen__pick-label">
                {zh.listen.optGap}
              </span>
              <Segmented
                size="sm"
                options={GAP_OPTIONS}
                value={String(options.gapSec)}
                onChange={(v) => setOption({ gapSec: LISTEN_GAPS.find((n) => String(n) === v) ?? options.gapSec })}
                aria-labelledby={gapLabel}
              />
            </div>
          </div>
        ) : (
          <div className="listen__switches">
            <Switch checked={options.sentence} onChange={(sentence) => setOption({ sentence })} label={zh.listen.optSentence} />
            <Switch checked={options.zh} onChange={(on) => setOption({ zh: on })} label={zh.listen.optZh} />
          </div>
        )}
        {!dictation && options.zh && !zhAvailable && (
          <p className="listen__note" role="status">
            {zh.listen.noZh}
          </p>
        )}
      </div>

      {finished && dictation ? (
        // the answer sheet: only now are the words shown — a word that was never read through (nothing could read it, the learner
        // skipped it) carries a tag, so the paper can be checked against the right row; the speaker is the ordinary SpeakButton
        // (the device's voice first, as everywhere else)
        <div className="listen__answers">
          <h2 className="listen__answers-title" tabIndex={-1} ref={sheetTitleRef}>
            {zh.listen.answers}
          </h2>
          {skipped}
          <ol className="listen__answer-list">
            {items.map((item, i) => (
              <li key={item.item_id} className="listen__answer">
                <span className="listen__answer-no">{i + 1}</span>
                <span className="listen__answer-head">
                  <span className="listen__answer-word" lang="en">
                    {item.display}
                  </span>
                  {state.unread.includes(i) && <span className="badge">{zh.listen.unread}</span>}
                </span>
                <SpeakButton text={item.spoken_en ?? item.display} lang={accent} size="sm" />
                {item.meaning_zh && <span className="listen__answer-meaning">{item.meaning_zh}</span>}
              </li>
            ))}
          </ol>
          <div className="listen__actions">
            <Button variant="primary" size="lg" onClick={() => playerRef.current?.restart()}>
              {zh.listen.dictateAgain}
            </Button>
            <Link className="btn btn--secondary btn--lg" to={routePaths.today}>
              <span className="btn__label">{zh.common.backToToday}</span>
            </Link>
          </div>
        </div>
      ) : finished ? (
        <div className="listen__finished">
          <p className="listen__finished-title" role="status" tabIndex={-1} ref={finishedTitleRef}>
            {zh.listen.finished}
          </p>
          {skipped}
          <div className="listen__actions">
            <Button variant="primary" size="lg" onClick={() => playerRef.current?.restart()}>
              {zh.listen.again}
            </Button>
            <Link className="btn btn--secondary btn--lg" to={routePaths.study}>
              <span className="btn__label">{zh.listen.goStudy}</span>
            </Link>
          </div>
        </div>
      ) : (
        <>
          <div className="listen__stage">
            {dictation ? (
              // dictation: the position only — the word is not in the DOM until the answer sheet
              <>
                <p className="listen__index">{zh.listen.dictationIndex(state.index + 1)}</p>
                <ol className="listen__rounds" aria-hidden="true">
                  {LISTEN_REPEATS.slice(0, options.repeat).map((n) => (
                    <li key={n} className={cx('listen__round', playing && n <= state.round && 'is-done')} />
                  ))}
                </ol>
                <p className="listen__hint muted">{zh.listen.dictationHint}</p>
              </>
            ) : (
              current && (
                <>
                  <h2 {...line('listen__word', state.segment, 'word')} lang="en">
                    {current.display}
                  </h2>
                  {current.phonetic && (
                    <p className="listen__phonetic" lang="en">
                      /{current.phonetic}/
                    </p>
                  )}
                  {current.meaning_zh && <p {...line('listen__meaning', state.segment, 'gloss')}>{current.meaning_zh}</p>}
                  {options.sentence && current.sentence_en && (
                    <div className="listen__sentence">
                      <p {...line('listen__en', state.segment, 'sentence')} lang="en">
                        {current.sentence_en}
                      </p>
                      {current.sentence_zh && <p {...line('listen__zh', state.segment, 'sentenceZh')}>{current.sentence_zh}</p>}
                    </div>
                  )}
                </>
              )
            )}
            {state.status === 'blocked' && (
              <Button variant="primary" size="lg" className="listen__tap" onClick={() => playerRef.current?.play()}>
                {zh.listen.tapToStart}
              </Button>
            )}
            {state.offline && (
              <p className="listen__note" role="status">
                {zh.listen.offline}
              </p>
            )}
            {skipped}
          </div>

          <div className="listen-bar" ref={barRef}>
            <Button variant="ghost" size="sm" className="listen-bar__restart" onClick={() => playerRef.current?.restart()}>
              {zh.listen.restart}
            </Button>
            <div className="listen-bar__transport">
              <Button variant="secondary" iconOnly size="lg" aria-label={zh.listen.prev} title={zh.listen.prev} onClick={() => playerRef.current?.prev()}>
                <PrevIcon />
              </Button>
              <Button
                variant="primary"
                iconOnly
                size="lg"
                className="listen-bar__play"
                aria-label={playing ? zh.listen.pause : zh.listen.play}
                title={playing ? zh.listen.pause : zh.listen.play}
                onClick={() => playerRef.current?.toggle()}
              >
                {playing ? <PauseIcon /> : <PlayIcon />}
              </Button>
              <Button variant="secondary" iconOnly size="lg" aria-label={zh.listen.next} title={zh.listen.next} onClick={() => playerRef.current?.next()}>
                <NextIcon />
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
