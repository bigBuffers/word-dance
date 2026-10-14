// WelcomePage — `/welcome` (FRONTEND §2, DESIGN §6.2). Step 1: who am I… quick picks pre-select target stages
// (junior-high student → zk · high-school student → zk+gk · university student → gk+cet4+cet6 · professional → cet4+cet6), main stage segmented, push time,
// timezone (auto-detected) → POST /api/onboarding (state `screen`). Step 2: screening of up to 30 cards from
// GET /api/screen/next?stage=auto&count=30 with known / unfamiliar / skip / peek, 5-s undo (server `restore`),
// skip onboarding / finish → POST /api/onboarding/complete → /today.
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { ScreenVerdict, ScreenWord, Stage } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { Segmented } from '@/components/ui/Segmented';
import { Skeleton } from '@/components/ui/Skeleton';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { WordHeader } from '@/components/word/WordHeader';
import { usePageTitle } from '@/hooks/usePageTitle';
import { UNDO_LIST_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { DEFAULT_TIMEZONE, detectTimeZone, isValidPushTime } from '@/utils/date';
import { clientEventId } from '@/utils/format';
import '@/components/bank/bank.css';
import './WelcomePage.css';

export type Role = 'zk' | 'gk' | 'uni' | 'pro';

/** Self-description → pre-selected stages and the main stage (DESIGN §6.2). */
export const ROLE_PRESETS: Record<Role, { stages: Stage[]; current: Stage }> = {
  zk: { stages: ['zk'], current: 'zk' },
  gk: { stages: ['zk', 'gk'], current: 'gk' },
  uni: { stages: ['gk', 'cet4', 'cet6'], current: 'cet4' },
  pro: { stages: ['cet4', 'cet6'], current: 'cet4' },
};

const ROLES: readonly Role[] = ['zk', 'gk', 'uni', 'pro'];
const SCREEN_BATCH = 30;
const STAGE_FULL: Record<Stage, string> = { zk: zh.stages.zkFull, gk: zh.stages.gkFull, cet4: zh.stages.cet4Full, cet6: zh.stages.cet6Full };

/** Toggles a stage keeping the list non-empty and `current` inside it (canonical order). */
export function toggleStage(stages: readonly Stage[], current: Stage, stage: Stage): { stages: Stage[]; current: Stage } {
  const has = stages.includes(stage);
  if (has && stages.length === 1) return { stages: [...stages], current };
  const next = STAGE_ORDER.filter((s) => (s === stage ? !has : stages.includes(s)));
  const nextCurrent = next.includes(current) ? current : (next[0] ?? current);
  return { stages: next, current: nextCurrent };
}

function StepDots({ step }: { step: 1 | 2 }) {
  return (
    <div className="welcome__steps" aria-hidden="true">
      <span className={`welcome__step${step >= 1 ? ' is-active' : ''}`} />
      <span className={`welcome__step${step >= 2 ? ' is-active' : ''}`} />
    </div>
  );
}

export default function WelcomePage() {
  usePageTitle(zh.welcome.title);
  const { user, settings, applySession } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [step, setStep] = useState<1 | 2>(user?.onboarding_state === 'screen' ? 2 : 1);

  // ---- step 1 ----
  const detected = useMemo(() => detectTimeZone(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [stages, setStages] = useState<Stage[]>(settings?.stages.length ? settings.stages : ROLE_PRESETS.pro.stages);
  const [current, setCurrent] = useState<Stage>(settings?.current_stage ?? ROLE_PRESETS.pro.current);
  const [pushTime, setPushTime] = useState(settings?.push_time ?? '08:00');
  const [timezone, setTimezone] = useState(user?.onboarding_state === 'screen' && settings?.timezone ? settings.timezone : detected);
  const [zones, setZones] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    endpoints
      .getTimezones(false)
      .then((res) => {
        if (!cancelled) setZones(res.items);
      })
      .catch(() => {
        if (!cancelled) setZones([DEFAULT_TIMEZONE]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const zoneOptions = useMemo(() => [...new Set<string>([timezone, detected, DEFAULT_TIMEZONE, ...zones])], [zones, timezone, detected]);

  const pickRole = (r: Role) => {
    setRole(r);
    setStages(ROLE_PRESETS[r].stages);
    setCurrent(ROLE_PRESETS[r].current);
  };

  const onToggleStage = (stage: Stage) => {
    const next = toggleStage(stages, current, stage);
    setStages(next.stages);
    setCurrent(next.current);
    setRole(null);
  };

  const saveStep1 = async (e: FormEvent) => {
    e.preventDefault();
    if (saving || !isValidPushTime(pushTime) || !stages.includes(current)) return;
    setSaving(true);
    setError(null);
    try {
      const res = await endpoints.saveOnboarding({ stages, current_stage: current, timezone, push_time: pushTime });
      applySession({ settings: res.settings, ...(user ? { user: { ...user, onboarding_state: res.onboarding_state } } : {}) });
      setStep(2);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  // ---- step 2 ----
  const [cards, setCards] = useState<ScreenWord[]>([]);
  const [remaining, setRemaining] = useState(0);
  const [loadingCards, setLoadingCards] = useState(false);
  const [peek, setPeek] = useState(false);
  const [screened, setScreened] = useState(0);
  const [finishing, setFinishing] = useState(false);

  const loadCards = useCallback(async () => {
    setLoadingCards(true);
    try {
      const res = await endpoints.getScreenNext('auto', SCREEN_BATCH);
      setCards(res.items);
      setRemaining(res.remaining);
      setPeek(false);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoadingCards(false);
    }
  }, [toast]);

  useEffect(() => {
    if (step === 2) void loadCards();
  }, [step, loadCards]);

  const card = cards[0];

  const undo = useCallback(
    async (undone: ScreenWord) => {
      try {
        await endpoints.markWord(undone.word.id, { action: 'restore', context: 'screen_page' });
        setCards((prev) => [undone, ...prev]);
        setScreened((n) => Math.max(0, n - 1));
        setRemaining((n) => n + 1);
        setPeek(false);
        toast.toast(zh.common.undone);
      } catch (err) {
        toast.error(errorMessage(err));
      }
    },
    [toast],
  );

  const verdict = useCallback(
    async (v: ScreenVerdict) => {
      if (!card) return;
      const judged = card;
      setCards((prev) => prev.slice(1));
      setPeek(false);
      setScreened((n) => n + 1);
      if (v !== 'skip') setRemaining((n) => Math.max(0, n - 1));
      try {
        const res = await endpoints.postScreenVerdict({ client_event_id: clientEventId(), word_id: judged.word.id, verdict: v, context: 'onboarding' });
        if (v === 'skip') return;
        const message = v === 'unfamiliar' ? (res.added_to_today ? zh.screen.addedToday : zh.screen.addedBank) : zh.vocab.status.known;
        toast.toast(message, { durationMs: UNDO_LIST_MS, action: { label: zh.common.undo, onClick: () => undo(judged) } });
      } catch (err) {
        toast.error(errorMessage(err));
      }
    },
    [card, toast, undo],
  );

  const finish = useCallback(async () => {
    if (finishing) return;
    setFinishing(true);
    try {
      const res = await endpoints.completeOnboarding();
      if (user) applySession({ user: { ...user, onboarding_state: res.onboarding_state } });
      navigate(routePaths.today, { replace: true });
    } catch (err) {
      toast.error(errorMessage(err));
      if (isApiError(err) && err.code === 'invalid_transition') setStep(1);
      setFinishing(false);
    }
  }, [finishing, user, applySession, navigate, toast]);

  // keyboard: 1 known · 2 unfamiliar · S skip · Space peek (FRONTEND §5.4)
  useEffect(() => {
    if (step !== 2) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey || !card) return;
      if (e.key === '1') {
        e.preventDefault();
        void verdict('known');
      } else if (e.key === '2') {
        e.preventDefault();
        void verdict('unfamiliar');
      } else if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        void verdict('skip');
      } else if (e.key === ' ') {
        e.preventDefault();
        setPeek(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [step, card, verdict]);

  if (step === 1) {
    return (
      <section className="page page--narrow welcome">
        <StepDots step={1} />
        <h1 className="page__title">{zh.welcome.title}</h1>
        <p className="welcome__lead">{zh.welcome.step1}</p>
        <form onSubmit={saveStep1} noValidate>
          <div className="welcome__group">
            <span className="welcome__label" id="welcome-role">
              {zh.welcome.whoAreYou}
            </span>
            <div className="welcome__chips" role="group" aria-labelledby="welcome-role">
              {ROLES.map((r) => (
                <button key={r} type="button" className="chip-btn" aria-pressed={role === r} onClick={() => pickRole(r)}>
                  {zh.welcome.roles[r]}
                </button>
              ))}
            </div>
          </div>
          <div className="welcome__group">
            <span className="welcome__label" id="welcome-stages">
              {zh.welcome.stages}
            </span>
            <div className="welcome__chips" role="group" aria-labelledby="welcome-stages">
              {STAGE_ORDER.map((s) => (
                <button key={s} type="button" className="chip-btn" aria-pressed={stages.includes(s)} onClick={() => onToggleStage(s)}>
                  {STAGE_FULL[s]}
                </button>
              ))}
            </div>
          </div>
          <div className="welcome__group">
            <span className="welcome__label" id="welcome-current">
              {zh.welcome.currentStage}
            </span>
            <Segmented
              aria-labelledby="welcome-current"
              block
              options={STAGE_ORDER.filter((s) => stages.includes(s)).map((s) => ({ value: s, label: zh.stages[s] }))}
              value={current}
              onChange={setCurrent}
            />
          </div>
          <div className="welcome__group">
            <label className="welcome__label" htmlFor="welcome-push">
              {zh.welcome.pushTime}
            </label>
            <input id="welcome-push" type="time" step={60} value={pushTime} required onChange={(e) => setPushTime(e.target.value)} />
          </div>
          <div className="welcome__group">
            <label className="welcome__label" htmlFor="welcome-tz">
              {zh.welcome.timezone}
            </label>
            <div className="welcome__tz">
              <select id="welcome-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                {zoneOptions.map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </select>
              <Button type="button" variant="secondary" onClick={() => setTimezone(detected)} disabled={timezone === detected}>
                {zh.welcome.detectTz}
              </Button>
            </div>
          </div>
          {error && (
            <p className="auth__error" role="alert">
              {error}
            </p>
          )}
          <div className="welcome__actions">
            <Button type="submit" variant="primary" size="lg" loading={saving} disabled={!isValidPushTime(pushTime) || stages.length === 0}>
              {zh.welcome.next}
            </Button>
          </div>
        </form>
      </section>
    );
  }

  const exhausted = !loadingCards && cards.length === 0;
  return (
    <section className="page page--narrow welcome">
      <StepDots step={2} />
      <h1 className="page__title">{zh.welcome.step2}</h1>
      <p className="welcome__lead">{zh.welcome.step2Hint}</p>
      <div className="welcome__progress" aria-live="polite">
        <span>{zh.screen.remaining(remaining)}</span>
        <span>{screened > 0 ? zh.bank.counts(screened) : null}</span>
      </div>
      {loadingCards && cards.length === 0 ? (
        <div className="welcome-card" aria-busy="true">
          <Skeleton width="60%" height={40} />
          <Skeleton width="40%" height="1em" />
        </div>
      ) : card ? (
        <>
          <div className="welcome-card" role="group" aria-live="polite">
            <WordHeader word={card.word} size="lg" as="h2" />
            <div className="welcome-card__peek">
              {peek ? (
                <strong>{card.word.translation_short}</strong>
              ) : (
                <Button variant="ghost" size="sm" onClick={() => setPeek(true)}>
                  {zh.screen.peek}
                </Button>
              )}
            </div>
          </div>
          <div className="welcome__verdicts">
            <Button variant="primary" tone="good" size="lg" onClick={() => void verdict('known')}>
              {zh.study.known}
            </Button>
            <Button variant="primary" tone="again" size="lg" onClick={() => void verdict('unfamiliar')}>
              {zh.study.unfamiliar}
            </Button>
            <Button variant="ghost" onClick={() => void verdict('skip')}>
              {zh.study.skip}
            </Button>
          </div>
          <p className="welcome__keys" aria-hidden="true">
            <kbd>1</kbd> {zh.study.known} · <kbd>2</kbd> {zh.study.unfamiliar} · <kbd>S</kbd> {zh.study.skip}
          </p>
        </>
      ) : (
        <div className="welcome__done" role="status">
          <p>{remaining > 0 ? zh.screen.subtitle : zh.screen.allDone}</p>
          {remaining > 0 && (
            <Button variant="secondary" onClick={() => void loadCards()}>
              {zh.screen.another}
            </Button>
          )}
        </div>
      )}
      <div className="welcome__actions">
        <Button variant="primary" size="lg" loading={finishing} onClick={() => void finish()}>
          {zh.welcome.finish}
        </Button>
        {!exhausted && (
          <Button variant="ghost" disabled={finishing} onClick={() => void finish()}>
            {zh.welcome.skip}
          </Button>
        )}
      </div>
    </section>
  );
}
