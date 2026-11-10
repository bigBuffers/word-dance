// WelcomePage — `/welcome` (FRONTEND §2, DESIGN §6.2). Step 0 (first setup) only while `user.needs_profile` (an account a
// verification code created, API.md 81 / 89): required nickname, the age band (adult / guardian or student aged 14+; under-14 learners
// are pointed to the coming guardian accounts), an optional one-time username and an optional password (strength meter)
// → POST /api/account/profile → `applySession({user})` → step 1. Step 1: who am I… quick picks pre-select target stages
// (primary pupil → xs · junior-high student → xs+zk · high-school student → zk+gk · university student → gk+cet4+cet6 · professional → cet4+cet6), main stage segmented, push time,
// timezone (auto-detected) → POST /api/onboarding (state `screen`). Step 2: screening of up to 30 cards from
// GET /api/screen/next?stage=auto&count=30 with known / unfamiliar / skip / peek, 5-s undo (server `restore`),
// skip onboarding / finish → POST /api/onboarding/complete → /today. Keys 1 / 2 / S / Space go through the
// shared `useKeyboard` (drops auto-repeat, modifiers, form controls, open dialogs — FRONTEND §5.4) and the
// verdict buttons through `useTapLock`, so one held key or one double tap judges exactly one card.
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { ProfileBody } from '@/api/endpoints';
import type { ScreenVerdict, ScreenWord, Stage } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Segmented } from '@/components/ui/Segmented';
import { Skeleton } from '@/components/ui/Skeleton';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { WordHeader } from '@/components/word/WordHeader';
import { useKeyboard } from '@/hooks/useKeyboard';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useTapLock } from '@/hooks/useTapLock';
import { UNDO_LIST_MS, useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { USERNAME_RE, passwordStrength, validationFieldMessages } from '@/utils/auth';
import { DEFAULT_TIMEZONE, detectTimeZone, isValidPushTime } from '@/utils/date';
import { clientEventId } from '@/utils/format';
import '@/components/bank/bank.css';
import '@/components/ui/auth.css';
import './WelcomePage.css';

export type Role = 'xs' | 'zk' | 'gk' | 'uni' | 'pro';

/** Self-description → pre-selected stages and the main stage (DESIGN §6.2): the junior-high preset includes xs, the high-school one does not (zk ⊄ gk — PLAN P8). */
export const ROLE_PRESETS: Record<Role, { stages: Stage[]; current: Stage }> = {
  xs: { stages: ['xs'], current: 'xs' },
  zk: { stages: ['xs', 'zk'], current: 'zk' },
  gk: { stages: ['zk', 'gk'], current: 'gk' },
  uni: { stages: ['gk', 'cet4', 'cet6'], current: 'cet4' },
  pro: { stages: ['cet4', 'cet6'], current: 'cet4' },
};

export const ROLES: readonly Role[] = ['xs', 'zk', 'gk', 'uni', 'pro'];
/** Pre-selection before any role is picked — mirrors the user_settings DDL default / bank.DEFAULT_STAGES (PLAN §0, A6). */
export const DEFAULT_PRESET: { stages: Stage[]; current: Stage } = { stages: ['xs', 'zk'], current: 'xs' };
const SCREEN_BATCH = 30;
const STAGE_FULL: Record<Stage, string> = { xs: zh.stages.xsFull, zk: zh.stages.zkFull, gk: zh.stages.gkFull, cet4: zh.stages.cet4Full, cet6: zh.stages.cet6Full };

/** Toggles a stage keeping the list non-empty and `current` inside it (canonical order). */
export function toggleStage(stages: readonly Stage[], current: Stage, stage: Stage): { stages: Stage[]; current: Stage } {
  const has = stages.includes(stage);
  if (has && stages.length === 1) return { stages: [...stages], current };
  const next = STAGE_ORDER.filter((s) => (s === stage ? !has : stages.includes(s)));
  const nextCurrent = next.includes(current) ? current : (next[0] ?? current);
  return { stages: next, current: nextCurrent };
}

function StepDots({ step, withProfile = false }: { step: 0 | 1 | 2; withProfile?: boolean }) {
  return (
    <div className="welcome__steps" aria-hidden="true">
      {withProfile && <span className="welcome__step is-active" />}
      <span className={`welcome__step${step >= 1 ? ' is-active' : ''}`} />
      <span className={`welcome__step${step >= 2 ? ' is-active' : ''}`} />
    </div>
  );
}

type AgeChoice = ProfileBody['age_band'];

/** Step 0 (first setup) of a code-created account (API.md 89): nickname + age band, optional username and password. */
function ProfileStep({ onDone }: { onDone: () => void }) {
  const { applySession, refresh } = useAuth();
  const [nickname, setNickname] = useState('');
  const [ageBand, setAgeBand] = useState<AgeChoice | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = nickname.trim();
  const trimmedUser = username.trim();
  const usernameOk = trimmedUser === '' || USERNAME_RE.test(trimmedUser);
  const strength = passwordStrength(password, trimmedUser);
  const passwordOk = password === '' || strength >= 2;
  const valid = trimmedName.length > 0 && trimmedName.length <= 32 && ageBand !== null && usernameOk && passwordOk;
  const nameError = touched && !trimmedName ? zh.welcome.nicknameHint : null;
  const usernameError = touched && !usernameOk ? zh.auth.usernameHint : null;
  const passwordError = touched && !passwordOk ? zh.errors.weakPassword : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid || saving || ageBand === null) return;
    setSaving(true);
    setError(null);
    const body: ProfileBody = { display_name: trimmedName, age_band: ageBand };
    if (trimmedUser) body.username = trimmedUser;
    if (password) body.password = password;
    try {
      const res = await endpoints.saveProfile(body);
      applySession({ user: res.user });
      onDone();
    } catch (err) {
      if (isApiError(err) && err.code === 'invalid_transition') {
        // the profile is already saved (another tab): take the server's user (display_name, needs_profile false) before step 1
        await refresh().catch(() => undefined);
        onDone();
        return;
      }
      setError(validationFieldMessages(err) ?? errorMessage(err)); // 400 validation_error → the field messages (e.g. a phone-like username)
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="page page--narrow welcome">
      <StepDots step={0} withProfile />
      <h1 className="page__title">{zh.welcome.step0}</h1>
      <p className="welcome__lead">{zh.welcome.step0Lead}</p>
      <form className="auth__form" onSubmit={submit} noValidate>
        <Field label={zh.welcome.nickname} hint={nameError ? undefined : zh.welcome.nicknameHint} error={nameError} required>
          {(control) => <input {...control} type="text" autoComplete="nickname" maxLength={32} autoFocus value={nickname} onChange={(e) => setNickname(e.target.value)} />}
        </Field>
        <div className="welcome__group">
          <span className="welcome__label" id="welcome-age">
            {zh.welcome.ageBand}
          </span>
          <div className="auth__radios" role="radiogroup" aria-labelledby="welcome-age">
            <label className="auth__radio">
              <input type="radio" name="age_band" value="adult" checked={ageBand === 'adult'} onChange={() => setAgeBand('adult')} />
              <span>{zh.welcome.ageAdult}</span>
            </label>
            <label className="auth__radio">
              <input type="radio" name="age_band" value="14plus" checked={ageBand === '14plus'} onChange={() => setAgeBand('14plus')} />
              <span>{zh.welcome.age14plus}</span>
            </label>
          </div>
          <p className="settings__hint muted">{zh.welcome.under14}</p>
        </div>
        <Field label={zh.welcome.optionalUsername} hint={usernameError ? undefined : zh.auth.usernameHint} error={usernameError}>
          {(control) => <input {...control} type="text" autoComplete="username" autoCapitalize="off" autoCorrect="off" spellCheck={false} maxLength={32} value={username} onChange={(e) => setUsername(e.target.value)} />}
        </Field>
        <Field label={zh.welcome.optionalPassword} hint={passwordError ? undefined : zh.welcome.passwordWhy} error={passwordError}>
          {(control) => (
            <>
              <input {...control} type="password" autoComplete="new-password" maxLength={64} value={password} onChange={(e) => setPassword(e.target.value)} />
              <div className="auth__meter" data-level={strength} aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            </>
          )}
        </Field>
        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}
        <div className="welcome__actions">
          <Button type="submit" variant="primary" size="lg" loading={saving} disabled={!valid && touched}>
            {zh.welcome.next}
          </Button>
        </div>
      </form>
    </section>
  );
}

export default function WelcomePage() {
  usePageTitle(zh.welcome.title);
  const { user, settings, applySession } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const withProfile = user?.needs_profile === true;
  const [step, setStep] = useState<0 | 1 | 2>(withProfile ? 0 : user?.onboarding_state === 'screen' ? 2 : 1);

  // ---- step 1 ----
  const detected = useMemo(() => detectTimeZone(), []);
  const [role, setRole] = useState<Role | null>(null);
  const [stages, setStages] = useState<Stage[]>(settings?.stages.length ? settings.stages : DEFAULT_PRESET.stages);
  const [current, setCurrent] = useState<Stage>(settings?.current_stage ?? DEFAULT_PRESET.current);
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
  const tapLock = useTapLock();

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
      tapLock.arm();
      setPeek(false);
      setScreened((n) => n + 1);
      if (v !== 'skip') setRemaining((n) => Math.max(0, n - 1));
      try {
        const res = await endpoints.postScreenVerdict({ client_event_id: clientEventId(), word_id: judged.word.id, verdict: v, context: 'onboarding' });
        if (v === 'skip') return;
        const message = v === 'unfamiliar' ? (res.added_to_today ? zh.screen.addedToday : zh.screen.addedBank) : zh.screen.markedKnown(judged.word.display);
        toast.toast(message, { durationMs: UNDO_LIST_MS, action: { label: zh.common.undo, onClick: () => undo(judged) } });
      } catch (err) {
        toast.error(errorMessage(err));
      }
    },
    [card, tapLock, toast, undo],
  );

  /** Button / pointer verdicts: ignored for a moment after the previous verdict advanced the card (double tap). */
  const tapVerdict = (v: ScreenVerdict) => {
    if (tapLock.locked()) return;
    void verdict(v);
  };

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

  // keyboard: 1 known · 2 unfamiliar · S skip · Space peek (FRONTEND §5.4) — the hook reads the latest
  // handlers through a ref and ignores `event.repeat`, so a held key cannot run through the deck
  useKeyboard(
    {
      '1': () => void verdict('known'),
      '2': () => void verdict('unfamiliar'),
      s: () => void verdict('skip'),
      Space: () => setPeek(true),
    },
    { enabled: step === 2 && card !== undefined },
  );

  if (step === 0) return <ProfileStep onDone={() => setStep(1)} />;

  if (step === 1) {
    return (
      <section className="page page--narrow welcome">
        <StepDots step={1} withProfile={withProfile} />
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
      <StepDots step={2} withProfile={withProfile} />
      <h1 className="page__title">{zh.welcome.step2}</h1>
      <p className="welcome__lead">{zh.welcome.step2Hint}</p>
      <div className="welcome__progress" aria-live="polite">
        <span>{zh.screen.remaining(remaining)}</span>
        <span>{screened > 0 ? zh.screen.screenedCount(screened) : null}</span>
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
            <Button variant="primary" tone="good" size="lg" onClick={() => tapVerdict('known')}>
              {zh.study.known}
            </Button>
            <Button variant="primary" tone="again" size="lg" onClick={() => tapVerdict('unfamiliar')}>
              {zh.study.unfamiliar}
            </Button>
            <Button variant="ghost" onClick={() => tapVerdict('skip')}>
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
