// SettingsPage — `/settings` me (FRONTEND §5.8): sections push settings / learning settings / account / about & sources, each field
// saved on its own (`PUT /api/settings` through AuthContext.updateSettings, inline saved), e-mail code
// flow, webhook test, export (CSV / JSON links), import (JSON reduced client-side to `{version, words}`,
// CSV posted as is → result sheet), change password, logout, delete account (password re-entry).
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import { exportAccountUrl, importPayloadFromJsonExport, type ImportBody, type SettingsUpdate, type WebhookTestResponse } from '@/api/endpoints';
import type { DanceMode, ImportResponse, Settings, Stage, User, WebhookFormat } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Segmented } from '@/components/ui/Segmented';
import { Sheet } from '@/components/ui/Sheet';
import { Switch } from '@/components/ui/Switch';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { isNative, reminderPermission, requestReminderPermission, syncDailyReminder, type ReminderPermission } from '@/native/capacitor';
import { routePaths } from '@/routes';
import { DEFAULT_TIMEZONE, detectTimeZone, formatDateTime, isValidPushTime } from '@/utils/date';
import { parseIntInRange } from '@/utils/format';
import { AddStatusBadge } from '@/components/bank/AddWordPreviewRow';
import './SettingsPage.css';

const FORMATS: readonly WebhookFormat[] = ['generic', 'wecom', 'feishu', 'serverchan', 'bark'];
const DANCE_MODES: readonly DanceMode[] = ['full', 'form_only', 'off']; // the three levels of the word dance (WORD_DANCE_DESIGN §6.3), in display order
const SAVED_FLASH_MS = 2000;

/**
 * Turns a previous export file into the `POST /api/bank/import` body (API.md 11/75): a JSON export is reduced
 * to `{version, words}` (the `review_logs` array is dropped client-side; an unparsable file yields null and no
 * request is made), a CSV is posted verbatim. The format is taken from the extension, else sniffed.
 */
export async function buildImportBody(file: { name: string; text(): Promise<string> }): Promise<ImportBody | null> {
  const text = await file.text();
  const name = file.name.toLowerCase();
  const isJson = name.endsWith('.json') || (!name.endsWith('.csv') && text.trimStart().startsWith('{'));
  if (isJson) {
    const data = importPayloadFromJsonExport(text);
    return data ? { format: 'json', data } : null;
  }
  return text.trim() ? { format: 'csv', data: text } : null;
}

/**
 * zh cause + action for a failed webhook test (DESIGN §0.3: no raw transport text for non-admins). The server's
 * closed-set `reason` (API.md 17) picks the copy; its `error` string is an English diagnostic ("request failed:
 * ConnectError: …", "rejected: …", "HTTP 404") kept for the admin job ledger and never rendered. Without a usable
 * reason (an older server, or `http_error` without a status) the HTTP status decides, else the connection advice.
 */
export function webhookFailureReason(res: Pick<WebhookTestResponse, 'http_status' | 'error'> & Partial<Pick<WebhookTestResponse, 'reason'>>): string {
  switch (res.reason) {
    case 'dns_failed':
      return zh.settings.webhookFailDns;
    case 'host_not_public':
      return zh.settings.webhookFailPrivate;
    case 'connect_failed':
      return zh.settings.webhookFailConnect;
    case 'timeout':
      return zh.settings.webhookFailTimeout;
    case 'tls_failed':
      return zh.settings.webhookFailTls;
    case 'invalid_url':
      return zh.settings.webhookFailInvalidUrl;
    default:
      return typeof res.http_status === 'number' ? zh.settings.webhookFailHttp(res.http_status) : zh.settings.webhookFailConnect;
  }
}

/** Toggles a stage keeping the list non-empty and `current_stage` inside it (canonical order). */
export function toggleStageSetting(stages: readonly Stage[], current: Stage, stage: Stage): { stages: Stage[]; current_stage: Stage } {
  const has = stages.includes(stage);
  if (has && stages.length === 1) return { stages: [...stages], current_stage: current };
  const next = STAGE_ORDER.filter((s) => (s === stage ? !has : stages.includes(s)));
  return { stages: next, current_stage: next.includes(current) ? current : (next[0] ?? current) };
}

function useSectionSaver() {
  const { updateSettings } = useAuth();
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const save = useCallback(
    async (partial: SettingsUpdate): Promise<boolean> => {
      setSaving(true);
      try {
        await updateSettings(partial);
        setSaved(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setSaved(false), SAVED_FLASH_MS);
        return true;
      } catch (e) {
        toast.error(errorMessage(e));
        return false;
      } finally {
        setSaving(false);
      }
    },
    [updateSettings, toast],
  );
  return { save, saving, saved };
}

function Section({ title, saved, children }: { title: string; saved?: boolean; children: ReactNode }) {
  return (
    <section className="settings__section card">
      <h2>
        {title}
        {saved && (
          <span className="settings__saved" role="status">
            {zh.common.saved}
          </span>
        )}
      </h2>
      {children}
    </section>
  );
}

function NumberRow({ label, value, min, max, onSave }: { label: string; value: number; min: number; max: number; onSave: (n: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => {
    const n = parseIntInRange(draft, min, max);
    if (n === null) {
      setDraft(String(value));
      return;
    }
    setDraft(String(n));
    if (n !== value) onSave(n);
  };
  const id = `num-${label}`;
  return (
    <div className="settings__row">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
// push settings
// ---------------------------------------------------------------------------------------------------

function PushSection({ settings, user }: { settings: Settings; user: User }) {
  const { save, saved } = useSectionSaver();
  const { server, applySession, refresh } = useAuth();
  const toast = useToast();
  const detected = useMemo(() => detectTimeZone(), []);
  const [zones, setZones] = useState<string[]>([]);
  const [pushDraft, setPushDraft] = useState(settings.push_time);
  const [webhookDraft, setWebhookDraft] = useState(settings.webhook_url ?? '');
  const [codeMode, setCodeMode] = useState(false);
  const [code, setCode] = useState('');
  const [emailBusy, setEmailBusy] = useState(false);
  const [testingWebhook, setTestingWebhook] = useState(false);

  useEffect(() => setPushDraft(settings.push_time), [settings.push_time]);
  useEffect(() => setWebhookDraft(settings.webhook_url ?? ''), [settings.webhook_url]);
  useEffect(() => {
    let cancelled = false;
    endpoints
      .getTimezones(false)
      .then((res) => {
        if (!cancelled) setZones(res.items);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  const zoneOptions = useMemo(() => [...new Set<string>([settings.timezone, detected, DEFAULT_TIMEZONE, ...zones])], [zones, settings.timezone, detected]);

  const commitPushTime = () => {
    if (!isValidPushTime(pushDraft)) {
      setPushDraft(settings.push_time);
      return;
    }
    if (pushDraft !== settings.push_time) void save({ push_time: pushDraft });
  };

  const onStage = (stage: Stage) => {
    const next = toggleStageSetting(settings.stages, settings.current_stage, stage);
    if (next.stages.length !== settings.stages.length || next.current_stage !== settings.current_stage) void save(next);
  };

  const requestCode = async () => {
    setEmailBusy(true);
    try {
      await endpoints.requestEmailCode();
      toast.success(zh.settings.emailSent);
      setCodeMode(true);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setEmailBusy(false);
    }
  };
  const verify = async (e: FormEvent) => {
    e.preventDefault();
    if (!/^\d{6}$/.test(code)) return;
    setEmailBusy(true);
    try {
      const res = await endpoints.verifyEmail(code);
      applySession({ user: res.user });
      await refresh().catch(() => undefined);
      toast.success(zh.settings.emailVerified);
      setCodeMode(false);
      setCode('');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setEmailBusy(false);
    }
  };
  const sendTestEmail = async () => {
    try {
      await endpoints.testEmail(); // 202 {queued}: the SMTP send happens later on the io worker (API.md 18)
      toast.success(zh.settings.emailTestQueued);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const onWebhookEnabled = (on: boolean) => {
    if (on && !webhookDraft.trim()) {
      toast.error(zh.errors.webhookUnconfigured);
      return;
    }
    void save(on ? { webhook_enabled: true, webhook_url: webhookDraft.trim() } : { webhook_enabled: false });
  };
  const commitWebhookUrl = () => {
    const value = webhookDraft.trim();
    if (value !== (settings.webhook_url ?? '')) void save({ webhook_url: value || null });
  };
  const sendTestWebhook = async () => {
    setTestingWebhook(true);
    try {
      const res = await endpoints.testWebhook();
      if (res.ok) toast.success(zh.settings.webhookOk);
      else toast.error(zh.settings.webhookFail(webhookFailureReason(res)));
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setTestingWebhook(false);
    }
  };

  const smtpMissing = server?.email_configured === false;
  const canEnableEmail = settings.email_verified && !smtpMissing;
  // in the native shell the daily reminder is a local notification: ask for permission inside this gesture, then save either way
  const enablePush = async (v: boolean) => {
    if (v && isNative()) {
      const granted = await requestReminderPermission().catch(() => false); // a failed permission call counts as not granted; still save
      setReminderPerm(granted ? 'granted' : 'denied');
      if (!granted) toast.error(zh.settings.reminderDenied);
    }
    await save({ push_enabled: v });
  };
  // a learner whose push was already on before installing the app never went through the toggle: show the state and a button
  const [reminderPerm, setReminderPerm] = useState<ReminderPermission | null>(null);
  useEffect(() => {
    if (!isNative() || !settings.push_enabled) return;
    let cancelled = false;
    const refresh = () => {
      if (document.visibilityState === 'hidden') return;
      void reminderPermission().then((p) => {
        if (!cancelled) setReminderPerm(p);
      });
    };
    refresh();
    document.addEventListener('visibilitychange', refresh); // the learner may grant it in the system settings and come back
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [settings.push_enabled]);
  const allowReminder = async () => {
    const granted = await requestReminderPermission().catch(() => false); // inside the gesture: the OS may prompt
    setReminderPerm(granted ? 'granted' : 'denied');
    if (granted) await syncDailyReminder(settings);
    else toast.error(zh.settings.reminderDenied);
  };

  return (
    <Section title={zh.settings.push} saved={saved}>
      <div className="settings__row">
        <Switch label={zh.settings.pushEnabled} checked={settings.push_enabled} onChange={(v) => void enablePush(v)} />
      </div>
      <div className="settings__row">
        <label htmlFor="push-time">{zh.settings.pushTime}</label>
        <input id="push-time" type="time" step={60} value={pushDraft} onChange={(e) => setPushDraft(e.target.value)} onBlur={commitPushTime} />
      </div>
      <div className="settings__row">
        <label htmlFor="push-tz">{zh.settings.timezone}</label>
        <div className="settings__inline">
          <select id="push-tz" value={settings.timezone} onChange={(e) => void save({ timezone: e.target.value })}>
            {zoneOptions.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
          <Button size="sm" disabled={settings.timezone === detected} onClick={() => void save({ timezone: detected })}>
            {zh.settings.detect}
          </Button>
        </div>
      </div>
      {settings.next_push_at && <p className="settings__hint">{zh.settings.nextPush(formatDateTime(settings.next_push_at, settings.timezone))}</p>}
      {isNative() && <p className="settings__hint">{zh.settings.nativeReminderHint}</p>}
      {isNative() && settings.push_enabled && reminderPerm !== null && reminderPerm !== 'granted' && (
        <div className="settings__row">
          <span className="settings__hint">{zh.settings.reminderDenied}</span>
          <Button size="sm" onClick={() => void allowReminder()}>
            {zh.settings.allowNotifications}
          </Button>
        </div>
      )}
      <NumberRow label={zh.settings.dailyNew} value={settings.daily_new_count} min={0} max={50} onSave={(n) => void save({ daily_new_count: n })} />
      <NumberRow label={zh.settings.dailyScreen} value={settings.daily_screen_count} min={0} max={50} onSave={(n) => void save({ daily_screen_count: n })} />
      <NumberRow label={zh.settings.maxReviews} value={settings.max_reviews} min={0} max={300} onSave={(n) => void save({ max_reviews: n })} />
      <div className="settings__row">
        <span id="settings-stages">{zh.settings.stages}</span>
        <div className="settings__stages" role="group" aria-labelledby="settings-stages">
          {STAGE_ORDER.map((s) => (
            <button key={s} type="button" className="chip-btn" aria-pressed={settings.stages.includes(s)} onClick={() => onStage(s)}>
              {zh.stages[s]}
            </button>
          ))}
        </div>
      </div>
      <div className="settings__row">
        <span id="settings-current">{zh.settings.currentStage}</span>
        <Segmented
          size="sm"
          aria-labelledby="settings-current"
          options={STAGE_ORDER.filter((s) => settings.stages.includes(s)).map((s) => ({ value: s, label: zh.stages[s] }))}
          value={settings.current_stage}
          onChange={(s) => void save({ current_stage: s })}
        />
      </div>

      <div className="settings__row">
        <Switch label={zh.settings.email} checked={settings.email_enabled} disabled={!canEnableEmail} onChange={(v) => void save({ email_enabled: v })} />
      </div>
      {smtpMissing && <p className="settings__hint">{zh.errors.smtpUnconfigured}</p>}
      {!settings.email_verified && !smtpMissing && (
        <>
          <p className="settings__hint">{zh.errors.emailNotVerified}</p>
          {user.email &&
            (codeMode ? (
              <form className="settings__inline" onSubmit={verify}>
                <input
                  className="settings__code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  aria-label={zh.settings.emailCode}
                  placeholder={zh.settings.emailCode}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                />
                <Button type="submit" variant="primary" size="sm" loading={emailBusy} disabled={code.length !== 6}>
                  {zh.common.confirm}
                </Button>
                <Button size="sm" variant="ghost" disabled={emailBusy} onClick={() => void requestCode()}>
                  {zh.common.retry}
                </Button>
              </form>
            ) : (
              <div className="settings__buttons">
                <Button size="sm" loading={emailBusy} onClick={() => void requestCode()}>
                  {zh.settings.emailVerify}
                </Button>
              </div>
            ))}
        </>
      )}
      {settings.email_verified && settings.email_enabled && (
        <div className="settings__buttons">
          <Button size="sm" onClick={() => void sendTestEmail()}>
            {zh.settings.emailTest}
          </Button>
        </div>
      )}

      <div className="settings__row">
        <Switch label={zh.settings.webhook} checked={settings.webhook_enabled} onChange={onWebhookEnabled} />
      </div>
      <Field label={zh.settings.webhookUrl} htmlFor="webhook-url">
        <input
          id="webhook-url"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://"
          value={webhookDraft}
          onChange={(e) => setWebhookDraft(e.target.value)}
          onBlur={commitWebhookUrl}
        />
      </Field>
      <div className="settings__row">
        <label htmlFor="webhook-format">{zh.settings.webhookFormat}</label>
        <select id="webhook-format" value={settings.webhook_format} onChange={(e) => void save({ webhook_format: e.target.value as WebhookFormat })}>
          {FORMATS.map((f) => (
            <option key={f} value={f}>
              {zh.settings.formats[f]}
            </option>
          ))}
        </select>
      </div>
      <div className="settings__buttons">
        {/* the server test requires the switch on AND a saved URL (routers/settings.py); mirror both, like the e-mail test above */}
        <Button size="sm" loading={testingWebhook} disabled={!settings.webhook_enabled || !settings.webhook_url} onClick={() => void sendTestWebhook()}>
          {zh.settings.webhookTest}
        </Button>
        {!settings.webhook_enabled && settings.webhook_url && <span className="settings__hint">{zh.settings.webhookEnableFirst}</span>}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------------------
// learning settings
// ---------------------------------------------------------------------------------------------------

function LearnSection({ settings }: { settings: Settings }) {
  const { save, saved } = useSectionSaver();
  return (
    <Section title={zh.settings.learn} saved={saved}>
      <div className="settings__row">
        <Switch label={zh.settings.showImages} checked={settings.show_images} onChange={(v) => void save({ show_images: v })} />
      </div>
      <div className="settings__row">
        <span id="settings-zh">{zh.settings.zhExamples}</span>
        <Segmented
          size="sm"
          aria-labelledby="settings-zh"
          options={[
            { value: 'tap', label: zh.settings.zhModes.tap },
            { value: 'always', label: zh.settings.zhModes.always },
          ]}
          value={settings.zh_examples}
          onChange={(v) => void save({ zh_examples: v })}
        />
      </div>
      <div className="settings__row">
        <Switch label={zh.settings.autoPronounce} checked={settings.auto_pronounce} onChange={(v) => void save({ auto_pronounce: v })} />
      </div>
      <div className="settings__row settings__row--wrap">
        <span id="settings-dance">{zh.settings.dance}</span>
        {/* three levels: full = spelling + stress + the meaning motion at the reveal, form_only = no meaning motion, off = plain headword */}
        <Segmented
          size="sm"
          aria-labelledby="settings-dance"
          aria-describedby="settings-dance-hint"
          options={DANCE_MODES.map((mode) => ({ value: mode, label: zh.settings.danceModes[mode] }))}
          value={settings.dance_mode}
          onChange={(v) => void save({ dance_mode: v })}
        />
        <span id="settings-dance-hint" className="settings__hint settings__hint--row">{zh.settings.danceHint}</span>
      </div>
      <div className="settings__row">
        <span id="settings-accent">{zh.settings.accent}</span>
        <Segmented
          size="sm"
          aria-labelledby="settings-accent"
          options={[
            { value: 'en-US', label: zh.settings.accents['en-US'] },
            { value: 'en-GB', label: zh.settings.accents['en-GB'] },
          ]}
          value={settings.accent}
          onChange={(v) => void save({ accent: v })}
        />
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------------------
// account
// ---------------------------------------------------------------------------------------------------

function AccountSection({ user }: { user: User }) {
  const { applySession, refresh, refreshCounters, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [saved, setSaved] = useState(false);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [name, setName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email ?? '');
  const [pwOpen, setPwOpen] = useState(false);
  const [pwCurrent, setPwCurrent] = useState('');
  const [pwNew, setPwNew] = useState('');
  const [pwBusy, setPwBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importResult, setImportResult] = useState<ImportResponse | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePw, setDeletePw] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => setName(user.display_name), [user.display_name]);
  useEffect(() => setEmail(user.email ?? ''), [user.email]);
  useEffect(
    () => () => {
      if (flashTimer.current) clearTimeout(flashTimer.current);
    },
    [],
  );

  const flashSaved = () => {
    setSaved(true);
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setSaved(false), SAVED_FLASH_MS);
  };

  const saveAccount = async (body: { display_name?: string | null; email?: string | null }) => {
    try {
      const res = await endpoints.updateAccount(body);
      applySession({ user: res.user });
      await refresh().catch(() => undefined); // e-mail changes reset email_verified / email_enabled (API.md 6)
      flashSaved();
    } catch (e) {
      toast.error(errorMessage(e));
      setName(user.display_name);
      setEmail(user.email ?? '');
    }
  };

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    if (!pwCurrent || pwNew.length < 8) return;
    setPwBusy(true);
    try {
      await endpoints.changePassword({ current_password: pwCurrent, new_password: pwNew });
      toast.success(zh.common.saved);
      setPwOpen(false);
      setPwCurrent('');
      setPwNew('');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setPwBusy(false);
    }
  };

  const onImportFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setImportBusy(true);
    try {
      const body = await buildImportBody(file);
      if (!body) {
        toast.error(zh.errors.importTooLarge);
        return;
      }
      const res = await endpoints.importBank(body);
      setImportResult(res);
      void refreshCounters();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setImportBusy(false);
    }
  };

  const doLogout = async () => {
    setLoggingOut(true);
    await logout().catch(() => undefined);
    navigate(routePaths.login, { replace: true });
  };

  const doDelete = async (e: FormEvent) => {
    e.preventDefault();
    if (!deletePw) return;
    setDeleteBusy(true);
    try {
      await endpoints.deleteAccount(deletePw);
      await logout().catch(() => undefined);
      navigate(routePaths.login, { replace: true });
    } catch (err) {
      toast.error(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <Section title={zh.settings.account} saved={saved}>
      <Field label={zh.settings.displayName} htmlFor="acct-name">
        <input
          id="acct-name"
          type="text"
          value={name}
          maxLength={32}
          autoComplete="nickname"
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            const v = name.trim();
            if (v && v !== user.display_name) void saveAccount({ display_name: v });
            else setName(user.display_name);
          }}
        />
      </Field>
      <Field label={zh.auth.email} htmlFor="acct-email" hint={user.email && user.email_verified ? zh.settings.emailVerified : undefined}>
        <input
          id="acct-email"
          type="email"
          inputMode="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onBlur={() => {
            const v = email.trim();
            if (v !== (user.email ?? '')) void saveAccount({ email: v || null });
          }}
        />
      </Field>
      <div className="settings__buttons">
        <Button size="sm" onClick={() => setPwOpen(true)}>
          {zh.settings.changePassword}
        </Button>
      </div>

      {!isNative() && (
        <div className="settings__row">
          <span>{zh.settings.export}</span>
          <div className="settings__inline">
            <a className="btn btn--secondary btn--sm" href={exportAccountUrl('csv')} download>
              <span className="btn__label">{zh.settings.exportCsv}</span>
            </a>
            <a className="btn btn--secondary btn--sm" href={exportAccountUrl('json')} download>
              <span className="btn__label">{zh.settings.exportJson}</span>
            </a>
          </div>
        </div>
      )}
      <div className="settings__row">
        <span>{zh.settings.import}</span>
        <label className={`btn btn--secondary btn--sm${importBusy ? ' is-loading' : ''}`} aria-busy={importBusy || undefined}>
          <span className="btn__label">{zh.settings.import}</span>
          <input className="file-input" type="file" accept=".csv,.json,text/csv,application/json" disabled={importBusy} onChange={(e) => void onImportFile(e)} />
        </label>
      </div>
      <p className="settings__hint">{zh.settings.importHint}</p>

      <div className="settings__buttons">
        <Button size="sm" loading={loggingOut} onClick={() => void doLogout()}>
          {zh.auth.logout}
        </Button>
      </div>
      <div className="settings__danger">
        <Button size="sm" variant="danger" onClick={() => setDeleteOpen(true)}>
          {zh.settings.deleteAccount}
        </Button>
      </div>

      <Sheet open={pwOpen} onClose={() => setPwOpen(false)} title={zh.settings.changePassword}>
        <form className="auth__form" onSubmit={changePassword}>
          <Field label={zh.settings.currentPassword} required>
            {(c) => <input {...c} type="password" autoComplete="current-password" value={pwCurrent} onChange={(e) => setPwCurrent(e.target.value)} />}
          </Field>
          <Field label={zh.settings.newPassword} hint={zh.auth.passwordHint} required>
            {(c) => <input {...c} type="password" autoComplete="new-password" minLength={8} maxLength={64} value={pwNew} onChange={(e) => setPwNew(e.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" block loading={pwBusy} disabled={!pwCurrent || pwNew.length < 8}>
            {zh.common.save}
          </Button>
        </form>
      </Sheet>

      <Sheet open={importResult !== null} onClose={() => setImportResult(null)} title={zh.settings.import}>
        {importResult && (
          <>
            <p>{zh.settings.importDone(Math.max(0, importResult.rows - importResult.skipped), importResult.skipped)}</p>
            <ul className="import-results">
              {importResult.results.map((r, i) => (
                <li key={`${r.input}-${i}`}>
                  <span lang="en">{r.word?.display ?? r.input}</span>
                  <AddStatusBadge status={r.status} />
                </li>
              ))}
            </ul>
          </>
        )}
      </Sheet>

      <Sheet
        open={deleteOpen}
        onClose={() => {
          if (!deleteBusy) setDeleteOpen(false);
        }}
        title={zh.settings.deleteAccount}
      >
        <form className="auth__form" onSubmit={doDelete}>
          <p>{zh.settings.deleteConfirm}</p>
          <Field label={zh.auth.password} required>
            {(c) => <input {...c} type="password" autoComplete="current-password" value={deletePw} onChange={(e) => setDeletePw(e.target.value)} />}
          </Field>
          <Button type="submit" variant="danger" block loading={deleteBusy} disabled={!deletePw}>
            {zh.settings.deleteAccount}
          </Button>
        </form>
      </Sheet>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------------------
// about & sources
// ---------------------------------------------------------------------------------------------------

function AboutSection() {
  const { server } = useAuth();
  return (
    <Section title={zh.settings.about}>
      <div className="settings__about">
        {server?.version && <p>{zh.settings.version(server.version)}</p>}
        <p>{zh.settings.sources.dict}</p>
        <p>{zh.settings.sources.lists}</p>
        <p>{zh.settings.sources.images}</p>
        <p>{zh.settings.sources.ai}</p>
      </div>
    </Section>
  );
}

export default function SettingsPage() {
  usePageTitle(zh.settings.title);
  const { user, settings } = useAuth();
  if (!user || !settings) {
    return (
      <div className="loading-screen" role="status" aria-busy="true">
        {zh.common.loading}
      </div>
    );
  }
  return (
    <section className="page page--narrow settings">
      <h1 className="page__title">{zh.settings.title}</h1>
      <PushSection settings={settings} user={user} />
      <LearnSection settings={settings} />
      <AccountSection user={user} />
      <AboutSection />
    </section>
  );
}
