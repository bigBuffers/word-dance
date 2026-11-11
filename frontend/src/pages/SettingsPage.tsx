// SettingsPage — `/settings` me (FRONTEND §5.8): sections push settings / learning settings / account / about & sources, each field
// saved on its own (`PUT /api/settings` through AuthContext.updateSettings, inline saved), e-mail code
// flow, webhook test, export (CSV / JSON links), import (JSON reduced client-side to `{version, words}`,
// CSV posted as is → result sheet), the login-methods block (API.md §3.1: phone bind / rebind / unbind through endpoints 85–88,
// set-password for a code-created account through a `reauth` code + endpoint 7, change-password otherwise, the read-only username),
// logout, delete account (password re-entry, or a `reauth` code when the account has no password — endpoint 8).
// Slice 1-B (FRONTEND §5.8): a guardian gets the children row → /children first in the account section; a learner that is neither a
// child nor an admin gets the join-family row (`zh.settings.joinFamily` + `isChildAccount` → `ClaimDialog`, endpoints 108 / 109);
// a CHILD (`user.is_child`) sees `zh.settings.childManaged` instead of the nickname field, the login-methods block, the e-mail
// field, the password row and the delete button (export / import / logout stay). A guardian's delete answers 409 `has_children`
// with the children's names: the sheet lists them with the `deleteChildren` checkbox and retries with `delete_children: true`.
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import { exportAccountUrl, importPayloadFromJsonExport, type ImportBody, type SettingsUpdate, type WebhookTestResponse } from '@/api/endpoints';
import type { CodeChannel, DanceMode, ImportResponse, Settings, Stage, User, WebhookFormat } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { ClaimDialog } from '@/components/account/ClaimDialog';
import { Button } from '@/components/ui/Button';
import { CodeField, CODE_LENGTH } from '@/components/ui/CodeField';
import { Field } from '@/components/ui/Field';
import { PhoneField } from '@/components/ui/PhoneField';
import { Segmented } from '@/components/ui/Segmented';
import { Sheet } from '@/components/ui/Sheet';
import { Switch } from '@/components/ui/Switch';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { isNative, reminderPermission, requestReminderPermission, syncDailyReminder, type ReminderPermission } from '@/native/capacitor';
import { legalUrls, routePaths } from '@/routes';
import { isMainlandPhone, phoneToE164 } from '@/utils/auth';
import { DEFAULT_TIMEZONE, detectTimeZone, formatDateTime, isValidPushTime } from '@/utils/date';
import { parseIntInRange } from '@/utils/format';
import { AddStatusBadge } from '@/components/bank/AddWordPreviewRow';
import '@/components/ui/auth.css';
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

/**
 * Re-authentication by code for an account without a password (API.md 7 / 8 / 87): a `reauth` code of endpoint 85 goes to
 * the bound phone (while the server can send SMS) or the verified e-mail (while the server can send mail); both available →
 * the learner picks; neither → a hint instead of a code input the server could not serve.
 */
function ReauthCode({ user, smsOn, emailOn, code, onChange, disabled = false }: { user: User; smsOn: boolean; emailOn: boolean; code: string; onChange: (c: string) => void; disabled?: boolean }) {
  const toast = useToast();
  const [choice, setChoice] = useState<CodeChannel | null>(null);
  const channels: CodeChannel[] = [...(smsOn && user.phone_masked ? (['phone'] as const) : []), ...(emailOn && user.email && user.email_verified ? (['email'] as const) : [])];
  const channel: CodeChannel | null = choice !== null && channels.includes(choice) ? choice : (channels[0] ?? null);
  const targetOf = (c: CodeChannel) => (c === 'phone' ? (user.phone_masked ?? '') : (user.email ?? ''));
  const send = async () => {
    if (!channel) return;
    try {
      await endpoints.requestAccountCode({ channel, purpose: 'reauth' });
      toast.success(zh.auth.codeSent);
    } catch (e) {
      toast.error(errorMessage(e));
      throw e;
    }
  };
  if (channel === null) return <p className="settings__hint">{zh.settings.reauthUnavailable}</p>;
  return (
    <>
      <p className="settings__hint">{zh.settings.reauthHint}</p>
      {channels.length > 1 ? (
        <div className="settings__row">
          <span>{zh.settings.reauthVia}</span>
          <Segmented size="sm" aria-label={zh.settings.reauthVia} options={channels.map((c) => ({ value: c, label: targetOf(c) }))} value={channel ?? channels[0]!} onChange={setChoice} />
        </div>
      ) : (
        channel && (
          <p className="settings__hint">
            {zh.settings.reauthVia} {targetOf(channel)}
          </p>
        )
      )}
      <CodeField value={code} onChange={onChange} onSend={send} canSend={channel !== null} disabled={disabled} />
    </>
  );
}

function AccountSection({ user }: { user: User }) {
  const { server, applySession, refresh, refreshCounters, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [saved, setSaved] = useState(false);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [name, setName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email ?? '');
  const [pwOpen, setPwOpen] = useState(false);
  const [pwCurrent, setPwCurrent] = useState('');
  const [pwCode, setPwCode] = useState('');
  const [pwNew, setPwNew] = useState('');
  const [pwBusy, setPwBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importResult, setImportResult] = useState<ImportResponse | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePw, setDeletePw] = useState('');
  const [deleteCode, setDeleteCode] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteChildrenOf, setDeleteChildrenOf] = useState<{ id: number; display_name: string }[] | null>(null); // 409 has_children: the children named by the server
  const [deleteChildren, setDeleteChildren] = useState(false);
  const [claimOpen, setClaimOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  // login methods: phone bind / rebind / unbind sheets (API.md 85–88)
  const [bindOpen, setBindOpen] = useState(false);
  const [bindDigits, setBindDigits] = useState('');
  const [bindCode, setBindCode] = useState('');
  const [bindBusy, setBindBusy] = useState(false);
  const [rebindOpen, setRebindOpen] = useState(false);
  const [rebindOldCode, setRebindOldCode] = useState('');
  const [rebindDigits, setRebindDigits] = useState('');
  const [rebindNewCode, setRebindNewCode] = useState('');
  const [rebindBusy, setRebindBusy] = useState(false);
  const [unbindOpen, setUnbindOpen] = useState(false);
  const [unbindPw, setUnbindPw] = useState('');
  const [unbindCode, setUnbindCode] = useState('');
  const [unbindBusy, setUnbindBusy] = useState(false);

  const smsOn = server?.sms_enabled === true;
  const emailOn = server?.email_configured !== false; // the same flag PushSection reads (`smtpMissing`)
  const hasPassword = user.has_password;
  const isChild = user.is_child; // the guardian manages the child's nickname, login and deletion (API.md §1, the restriction list)
  const isGuardian = user.account_kind === 'guardian';
  const canClaim = !isChild && !isGuardian && user.role !== 'admin'; // the server refuses the others (108: admin / has_children)

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

  /** Sends a bind / rebind code (endpoint 85); the toast reports the outcome, the CodeField starts its countdown only on success. */
  const sendAccountCode = async (body: Parameters<typeof endpoints.requestAccountCode>[0]) => {
    try {
      await endpoints.requestAccountCode(body);
      toast.success(zh.auth.codeSent);
    } catch (e) {
      toast.error(errorMessage(e));
      throw e;
    }
  };

  const pwReady = pwNew.length >= 8 && (hasPassword ? pwCurrent.length > 0 : pwCode.length === CODE_LENGTH);
  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    if (!pwReady) return;
    setPwBusy(true);
    try {
      await endpoints.changePassword(hasPassword ? { current_password: pwCurrent, new_password: pwNew } : { code: pwCode, new_password: pwNew });
      if (!hasPassword) await refresh().catch(() => undefined); // has_password flips to true
      toast.success(zh.common.saved);
      setPwOpen(false);
      setPwCurrent('');
      setPwCode('');
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

  const deleteReady = hasPassword ? deletePw.length > 0 : deleteCode.length === CODE_LENGTH;
  const doDelete = async (e: FormEvent) => {
    e.preventDefault();
    if (!deleteReady) return;
    setDeleteBusy(true);
    try {
      await endpoints.deleteAccount({ ...(hasPassword ? { password: deletePw } : { code: deleteCode }), ...(deleteChildren ? { delete_children: true } : {}) });
      await logout().catch(() => undefined);
      navigate(routePaths.login, { replace: true });
    } catch (err) {
      if (isApiError(err) && err.code === 'has_children') {
        // a guardian with children: name them and offer the checkbox, the retry carries delete_children (API.md 8)
        const rows = err.details?.children;
        setDeleteChildrenOf(Array.isArray(rows) ? (rows as { id: number; display_name: string }[]) : []);
      }
      toast.error(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  const bindTarget = isMainlandPhone(bindDigits) ? phoneToE164(bindDigits) : null;
  const doBind = async (e: FormEvent) => {
    e.preventDefault();
    if (!bindTarget || bindCode.length !== CODE_LENGTH) return;
    setBindBusy(true);
    try {
      const res = await endpoints.bindPhone({ target: bindTarget, code: bindCode });
      applySession({ user: res.user });
      toast.success(zh.settings.phoneBound);
      setBindOpen(false);
      setBindDigits('');
      setBindCode('');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBindBusy(false);
    }
  };

  const rebindTarget = isMainlandPhone(rebindDigits) ? phoneToE164(rebindDigits) : null;
  const doRebind = async (e: FormEvent) => {
    e.preventDefault();
    if (!rebindTarget || rebindOldCode.length !== CODE_LENGTH || rebindNewCode.length !== CODE_LENGTH) return;
    setRebindBusy(true);
    try {
      const res = await endpoints.rebindPhone({ code_old: rebindOldCode, target_new: rebindTarget, code_new: rebindNewCode });
      applySession({ user: res.user });
      toast.success(zh.settings.phoneRebound);
      setRebindOpen(false);
      setRebindOldCode('');
      setRebindDigits('');
      setRebindNewCode('');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setRebindBusy(false);
    }
  };

  const unbindReady = hasPassword ? unbindPw.length > 0 : unbindCode.length === CODE_LENGTH;
  const doUnbind = async (e: FormEvent) => {
    e.preventDefault();
    if (!unbindReady) return;
    setUnbindBusy(true);
    try {
      const res = await endpoints.unbindPhone(hasPassword ? { password: unbindPw } : { code: unbindCode });
      applySession({ user: res.user });
      toast.success(zh.settings.phoneUnbound);
      setUnbindOpen(false);
      setUnbindPw('');
      setUnbindCode('');
    } catch (err) {
      toast.error(errorMessage(err)); // 409 last_login_method: the phone is the only login method
    } finally {
      setUnbindBusy(false);
    }
  };

  const emailHint = user.email ? (user.email_verified ? zh.settings.emailVerified : zh.settings.emailUnverified) : undefined;

  return (
    <Section title={zh.settings.account} saved={saved}>
      {isGuardian && (
        <div className="settings__row">
          <span>{zh.settings.myChildren}</span>
          <Link className="btn btn--secondary btn--sm" to={routePaths.children}>
            <span className="btn__label">{zh.settings.myChildren}</span>
          </Link>
        </div>
      )}
      {canClaim && (
        <div className="settings__row">
          <span>{zh.settings.joinFamily}</span>
          <Button size="sm" onClick={() => setClaimOpen(true)}>
            {zh.settings.isChildAccount}
          </Button>
        </div>
      )}
      {isChild && <p className="settings__hint">{zh.settings.childManaged}</p>}
      {!isChild && (
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
      )}

      {!isChild && <h3 className="settings__subtitle">{zh.settings.loginMethods}</h3>}
      {!isChild && smsOn && (
        <div className="settings__row">
          <span>{zh.settings.phone}</span>
          <div className="settings__inline">
            <span className="muted">{user.phone_masked ?? zh.settings.unbound}</span>
            {user.phone_masked ? (
              <>
                <Button size="sm" onClick={() => setRebindOpen(true)}>
                  {zh.settings.rebind}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setUnbindOpen(true)}>
                  {zh.settings.unbind}
                </Button>
              </>
            ) : (
              <Button size="sm" onClick={() => setBindOpen(true)}>
                {zh.settings.bind}
              </Button>
            )}
          </div>
        </div>
      )}
      {!isChild && (
        <Field label={zh.auth.email} htmlFor="acct-email" hint={emailHint}>
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
      )}
      {!isChild && (
        <div className="settings__row">
          <span>{zh.auth.password}</span>
          <div className="settings__inline">
            {!hasPassword && <span className="settings__hint">{zh.settings.noPasswordYet}</span>}
            <Button size="sm" onClick={() => setPwOpen(true)}>
              {hasPassword ? zh.settings.changePassword : zh.settings.setPassword}
            </Button>
          </div>
        </div>
      )}
      <div className="settings__row">
        <span>{zh.settings.username}</span>
        <span className="muted" lang="en">
          {user.username}
        </span>
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
      {!isChild && (
        <div className="settings__danger">
          <Button size="sm" variant="danger" onClick={() => setDeleteOpen(true)}>
            {zh.settings.deleteAccount}
          </Button>
        </div>
      )}
      <ClaimDialog open={claimOpen} onClose={() => setClaimOpen(false)} />

      <Sheet open={pwOpen} onClose={() => setPwOpen(false)} title={hasPassword ? zh.settings.changePassword : zh.settings.setPassword}>
        <form className="auth__form" onSubmit={changePassword}>
          {hasPassword ? (
            <Field label={zh.settings.currentPassword} required>
              {(c) => <input {...c} type="password" autoComplete="current-password" value={pwCurrent} onChange={(e) => setPwCurrent(e.target.value)} />}
            </Field>
          ) : (
            <ReauthCode user={user} smsOn={smsOn} emailOn={emailOn} code={pwCode} onChange={setPwCode} disabled={pwBusy} />
          )}
          <Field label={zh.settings.newPassword} hint={zh.auth.passwordHint} required>
            {(c) => <input {...c} type="password" autoComplete="new-password" minLength={8} maxLength={64} value={pwNew} onChange={(e) => setPwNew(e.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" block loading={pwBusy} disabled={!pwReady}>
            {zh.common.save}
          </Button>
        </form>
      </Sheet>

      <Sheet open={bindOpen} onClose={() => setBindOpen(false)} title={zh.settings.bindPhone}>
        <form className="auth__form" onSubmit={doBind} noValidate>
          <PhoneField value={bindDigits} onChange={setBindDigits} hint={zh.auth.phoneHint} disabled={bindBusy} autoFocus />
          <CodeField
            value={bindCode}
            onChange={setBindCode}
            onSend={() => sendAccountCode({ channel: 'phone', purpose: 'bind_phone', target: bindTarget ?? '' })}
            canSend={bindTarget !== null}
            disabled={bindBusy}
          />
          <Button type="submit" variant="primary" block loading={bindBusy} disabled={bindTarget === null || bindCode.length !== CODE_LENGTH}>
            {zh.settings.bind}
          </Button>
        </form>
      </Sheet>

      <Sheet open={rebindOpen} onClose={() => setRebindOpen(false)} title={zh.settings.rebindPhone}>
        <form className="auth__form" onSubmit={doRebind} noValidate>
          <p className="settings__hint">{zh.settings.rebindHint}</p>
          <CodeField label={zh.settings.oldPhoneCode} value={rebindOldCode} onChange={setRebindOldCode} onSend={() => sendAccountCode({ channel: 'phone', purpose: 'rebind_phone' })} disabled={rebindBusy} />
          <PhoneField label={zh.settings.newPhone} value={rebindDigits} onChange={setRebindDigits} hint={zh.auth.phoneHint} disabled={rebindBusy} />
          <CodeField
            label={zh.settings.newPhoneCode}
            value={rebindNewCode}
            onChange={setRebindNewCode}
            onSend={() => sendAccountCode({ channel: 'phone', purpose: 'bind_phone', target: rebindTarget ?? '' })}
            canSend={rebindTarget !== null}
            disabled={rebindBusy}
          />
          <Button type="submit" variant="primary" block loading={rebindBusy} disabled={rebindTarget === null || rebindOldCode.length !== CODE_LENGTH || rebindNewCode.length !== CODE_LENGTH}>
            {zh.settings.rebind}
          </Button>
        </form>
      </Sheet>

      <Sheet open={unbindOpen} onClose={() => setUnbindOpen(false)} title={zh.settings.unbindPhone}>
        <form className="auth__form" onSubmit={doUnbind} noValidate>
          <p className="settings__hint">{zh.settings.unbindHint}</p>
          {hasPassword ? (
            <Field label={zh.auth.password} required>
              {(c) => <input {...c} type="password" autoComplete="current-password" value={unbindPw} onChange={(e) => setUnbindPw(e.target.value)} />}
            </Field>
          ) : (
            <ReauthCode user={user} smsOn={smsOn} emailOn={emailOn} code={unbindCode} onChange={setUnbindCode} disabled={unbindBusy} />
          )}
          <Button type="submit" variant="danger" block loading={unbindBusy} disabled={!unbindReady}>
            {zh.settings.unbind}
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
          <p>{hasPassword ? zh.settings.deleteConfirm : zh.settings.deleteConfirmCode}</p>
          {hasPassword ? (
            <Field label={zh.auth.password} required>
              {(c) => <input {...c} type="password" autoComplete="current-password" value={deletePw} onChange={(e) => setDeletePw(e.target.value)} />}
            </Field>
          ) : (
            <ReauthCode user={user} smsOn={smsOn} emailOn={emailOn} code={deleteCode} onChange={setDeleteCode} disabled={deleteBusy} />
          )}
          {deleteChildrenOf !== null && (
            <div className="settings__children" role="group" aria-label={zh.settings.childrenOf}>
              <p className="settings__hint">
                {zh.settings.childrenOf} {deleteChildrenOf.map((c) => c.display_name).join(' · ')}
              </p>
              <label className="auth__consent">
                <input type="checkbox" checked={deleteChildren} disabled={deleteBusy} onChange={(e) => setDeleteChildren(e.target.checked)} />
                <span>{zh.settings.deleteChildren}</span>
              </label>
            </div>
          )}
          <Button type="submit" variant="danger" block loading={deleteBusy} disabled={!deleteReady || (deleteChildrenOf !== null && !deleteChildren)}>
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
        <p>
          <a href={legalUrls.privacy}>{zh.settings.privacy}</a> · <a href={legalUrls.terms}>{zh.settings.terms}</a> · <a href={legalUrls.children}>{zh.auth.childrenLink}</a>
        </p>
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
