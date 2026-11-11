// ChildrenPage — `/children`, the guardian's children page (FRONTEND §2 / §5.8; API.md 94–104; docs/AUTH_SIGNUP_DESIGN.md §5.2,
// guardian + child). `GET /api/guardian/children` lists the children with their progress and signed-in devices, the PIN state,
// the two-factor readiness (`ready` / `missing` → the readiness banner; the actions that need readiness — add, login code,
// switch, set free — are disabled; while the phone is missing and the server has SMS off the banner explains instead of linking
// to settings, and set free — it sends an SMS — is disabled with a hint) and the gate state. The guardian gate: a G+gate action is
// attempted while a stamp is known (`gateUntil` non-null — `ChildrenResponse.gate_until` or endpoint 102's answer; the server's
// clock decides whether it is still valid, never the device's) and a 403 `guardian_gate_required` opens `GateDialog` in gate mode
// and retries once after `onPassed`; with no stamp the dialog opens first and the action follows the pass. The caller's promise
// settles only when the action finished or the gate was dismissed, so a sheet stays busy across the gate. Card actions: switch
// (endpoint 104 → `applyAuth` → /today; no gate — one tap to the child, the gate guards the way back), login code (99 → the eight
// digits grouped `1234 5678`, regenerate), manage (96 nickname / simple login — a password change signs the child's devices out —,
// 98 sign out every device, set free = 100 + 101, 97 delete). Add child (95; the first child also sets the 6-digit PIN) and the
// PIN row (103; always through the gate — a guardian without a PIN passes with the password or a code, which is also how a
// forgotten PIN is replaced). Non-guardians and switched child sessions are sent to /settings.
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { ChildCreateBody, ChildEmancipateBody, ChildUpdateBody } from '@/api/endpoints';
import type { ChildAccount, ChildrenResponse } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { GateDialog, PIN_LENGTH, PIN_RE } from '@/components/account/GateDialog';
import { Button } from '@/components/ui/Button';
import { CodeField, CODE_LENGTH } from '@/components/ui/CodeField';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Field } from '@/components/ui/Field';
import { PhoneField } from '@/components/ui/PhoneField';
import { Sheet } from '@/components/ui/Sheet';
import { Skeleton } from '@/components/ui/Skeleton';
import { Switch } from '@/components/ui/Switch';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast, type ToastApi } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { USERNAME_RE, isMainlandPhone, passwordStrength, phoneToE164, validationFieldMessages } from '@/utils/auth';
import { formatDateTime } from '@/utils/date';
import '@/components/ui/auth.css';
import './ChildrenPage.css';

/** `12345678` → `1234 5678` (the login code as the guardian reads it out). */
export function groupDigits(code: string): string {
  return code.replace(/(\d{4})(?=\d)/g, '$1 ');
}

/** The readiness banner's list of what the guardian account still lacks. */
export function missingLabels(missing: ChildrenResponse['missing']): string {
  return missing.map((m) => (m === 'phone' ? zh.children.missingPhone : zh.children.missingSecondFactor)).join(' / ');
}

type Action = () => Promise<void>;
/** An action waiting behind the gate, with the resolver of the promise its caller (a busy sheet) is awaiting. */
type Pending = { action: Action; resolve: (ok: boolean) => void };

/**
 * The gate state of this page: `gateUntil` is the server's stamp (`ChildrenResponse.gate_until`, derived from the list data —
 * no effect to race a click) until this page learns better — endpoint 102's answer after a pass, or `null` after a 403.
 * `run(action)` attempts a G+gate action while a stamp is known (the server judges its age — a device clock that runs ahead
 * must not prompt the gate before every action) and opens the dialog first when none is; a 403 `guardian_gate_required` from
 * the action opens the dialog and the action runs once more after the pass. The returned promise settles only when the action
 * finished (true) or the gate was dismissed (false), so a sheet keeps its busy state across the gate and cannot double-submit.
 * Other failures are toasts (`validation_error` with its field text) and resolve false.
 */
function useGuardianGate(serverGateUntil: string | null, toast: ToastApi) {
  const [override, setOverride] = useState<string | null | undefined>(undefined); // undefined = trust the server's stamp
  const gateUntil = override === undefined ? serverGateUntil : override;
  const [open, setOpen] = useState(false);
  const pending = useRef<Pending | null>(null);

  // parks the action behind the dialog; an action parked earlier (cannot happen through the modal sheet, but) is released
  const park = useCallback(
    (action: Action) =>
      new Promise<boolean>((resolve) => {
        pending.current?.resolve(false);
        pending.current = { action, resolve };
        setOpen(true);
      }),
    [],
  );

  const execute = useCallback(
    async (action: Action): Promise<boolean> => {
      try {
        await action();
        return true;
      } catch (e) {
        if (isApiError(e) && e.code === 'guardian_gate_required') {
          setOverride(null);
          return park(action);
        }
        toast.error(validationFieldMessages(e) ?? errorMessage(e));
        return false;
      }
    },
    [toast, park],
  );

  const run = useCallback((action: Action): Promise<boolean> => (gateUntil === null ? park(action) : execute(action)), [gateUntil, execute, park]);

  const onPassed = useCallback(
    (until: string) => {
      const p = pending.current;
      pending.current = null;
      setOverride(until);
      setOpen(false);
      if (p) void execute(p.action).then(p.resolve);
    },
    [execute],
  );

  const close = useCallback(() => {
    const p = pending.current;
    pending.current = null;
    setOpen(false);
    p?.resolve(false);
  }, []);

  return { gateUntil, open, run, onPassed, close };
}

// ---------------------------------------------------------------------------------------------------
// cards and sheets
// ---------------------------------------------------------------------------------------------------

function PasswordInput({ value, onChange, strength, disabled, label, hint, error }: { value: string; onChange: (v: string) => void; strength: 0 | 1 | 2 | 3; disabled: boolean; label: string; hint?: string; error?: string | undefined }) {
  return (
    <Field label={label} hint={error ? undefined : hint} error={error}>
      {(control) => (
        <>
          <input {...control} type="password" autoComplete="new-password" maxLength={64} disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)} />
          <div className="auth__meter" data-level={strength} aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        </>
      )}
    </Field>
  );
}

function PinInput({ value, onChange, disabled, error, autoFocus = false }: { value: string; onChange: (v: string) => void; disabled: boolean; error?: string | undefined; autoFocus?: boolean }) {
  return (
    <Field label={zh.children.pin} hint={error ? zh.children.pinHint : `${zh.children.pinDigits}。${zh.children.pinHint}`} error={error} required>
      {(control) => (
        <input
          {...control}
          type="password"
          inputMode="numeric"
          autoComplete="off"
          pattern="[0-9]{6}"
          maxLength={PIN_LENGTH}
          autoFocus={autoFocus}
          disabled={disabled}
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, PIN_LENGTH))}
        />
      )}
    </Field>
  );
}

function ChildCard({ child, tz, ready, switching, onSwitch, onCode, onManage }: { child: ChildAccount; tz: string | undefined; ready: boolean; switching: boolean; onSwitch: () => void; onCode: () => void; onManage: () => void }) {
  const band = child.age_band === 'u14' ? zh.children.u14 : child.age_band ? zh.children.plus14 : null;
  const lastLogin = child.last_login_at ? zh.children.lastLogin(formatDateTime(child.last_login_at, tz)) : zh.children.neverLoggedIn;
  return (
    <li className="child-card card" aria-label={child.display_name}>
      <div className="child-card__head">
        <span className="child-card__name">{child.display_name}</span>
        {band && <span className="child-card__chip">{band}</span>}
        {child.username && (
          <span className="child-card__user muted" lang="en">
            {child.username}
          </span>
        )}
      </div>
      <p className="child-card__meta muted">
        {zh.children.progress(child.bank_size, child.streak_days)} · {lastLogin}
      </p>
      <p className="child-card__meta muted">{zh.children.devices(child.sessions)}</p>
      <div className="child-card__actions">
        <Button variant="primary" size="sm" loading={switching} disabled={!ready} onClick={onSwitch}>
          {zh.children.switchTo}
        </Button>
        <Button size="sm" disabled={!ready} onClick={onCode}>
          {zh.children.loginCode}
        </Button>
        <Button size="sm" variant="ghost" onClick={onManage}>
          {zh.children.manage}
        </Button>
      </div>
    </li>
  );
}

/** Endpoint 95: nickname, the PIN while the guardian has none, optionally a simple username + password. */
function AddChildSheet({ pinSet, onClose, onSubmit }: { pinSet: boolean; onClose: () => void; onSubmit: (body: ChildCreateBody) => Promise<boolean> }) {
  const [name, setName] = useState('');
  const [pin, setPin] = useState('');
  const [withLogin, setWithLogin] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);

  const trimmedName = name.trim();
  const trimmedUser = username.trim();
  const pinOk = pinSet || PIN_RE.test(pin);
  const usernameOk = !withLogin || USERNAME_RE.test(trimmedUser);
  const strength = passwordStrength(password, trimmedUser);
  const passwordOk = !withLogin || strength >= 2;
  const valid = trimmedName.length > 0 && trimmedName.length <= 32 && pinOk && usernameOk && passwordOk;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid || busy) return;
    const body: ChildCreateBody = { display_name: trimmedName };
    if (!pinSet) body.pin = pin;
    if (withLogin) {
      body.username = trimmedUser;
      body.password = password;
    }
    setBusy(true);
    await onSubmit(body); // the page closes the sheet once the child exists (also after a gate pass)
    setBusy(false);
  };

  return (
    <Sheet open onClose={() => !busy && onClose()} title={zh.children.add} dismissible={!busy}>
      <form className="auth__form" onSubmit={submit} noValidate>
        <Field label={zh.settings.displayName} hint={zh.welcome.nicknameHint} error={touched && !trimmedName ? zh.welcome.nicknameHint : undefined} required>
          {(control) => <input {...control} type="text" autoComplete="off" maxLength={32} autoFocus disabled={busy} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        {!pinSet && <PinInput value={pin} onChange={setPin} disabled={busy} error={touched && !pinOk ? zh.children.pinDigits : undefined} />}
        <div className="children__toggle">
          <Switch label={zh.children.withLogin} description={zh.children.simpleLoginHint} checked={withLogin} disabled={busy} onChange={setWithLogin} />
        </div>
        {withLogin && (
          <>
            <Field label={zh.auth.username} hint={touched && !usernameOk ? undefined : zh.auth.usernameHint} error={touched && !usernameOk ? zh.auth.usernameHint : undefined} required>
              {(control) => (
                <input {...control} type="text" autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} maxLength={32} disabled={busy} value={username} onChange={(e) => setUsername(e.target.value)} />
              )}
            </Field>
            <PasswordInput label={zh.auth.password} hint={zh.auth.passwordHint} value={password} onChange={setPassword} strength={strength} disabled={busy} error={touched && !passwordOk ? zh.errors.weakPassword : undefined} />
          </>
        )}
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={touched && !valid}>
          {zh.children.add}
        </Button>
      </form>
    </Sheet>
  );
}

/** Endpoint 103: set or change the 6-digit PIN. */
function PinSheet({ pinSet, onClose, onSubmit }: { pinSet: boolean; onClose: () => void; onSubmit: (pin: string) => Promise<boolean> }) {
  const [pin, setPin] = useState('');
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const valid = PIN_RE.test(pin);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid || busy) return;
    setBusy(true);
    await onSubmit(pin);
    setBusy(false);
  };
  return (
    <Sheet open onClose={() => !busy && onClose()} title={zh.children.pin} dismissible={!busy}>
      <form className="auth__form" onSubmit={submit} noValidate>
        <PinInput value={pin} onChange={setPin} disabled={busy} error={touched && !valid ? zh.children.pinDigits : undefined} autoFocus />
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={touched && !valid}>
          {pinSet ? zh.children.pinChange : zh.children.pinSet}
        </Button>
      </form>
    </Sheet>
  );
}

/** Endpoint 99's answer: the eight digits grouped, the validity hint and a regenerate button. */
function LoginCodeSheet({ child, code, onClose, onRegenerate }: { child: ChildAccount; code: string; onClose: () => void; onRegenerate: () => Promise<boolean> }) {
  const [busy, setBusy] = useState(false);
  return (
    <Sheet open onClose={onClose} title={zh.children.codeTitle}>
      <p className="auth__lead">{child.display_name}</p>
      <p className="login-code" lang="en" aria-live="polite">
        {groupDigits(code)}
      </p>
      <p className="login-code__hint">{zh.children.codeHint}</p>
      <Button
        block
        loading={busy}
        onClick={async () => {
          setBusy(true);
          await onRegenerate();
          setBusy(false);
        }}
      >
        {zh.children.regenerate}
      </Button>
    </Sheet>
  );
}

/** Set free (endpoints 100 + 101): the child's own phone, its code, a new password — irreversible. */
function EmancipateSheet({ child, onClose, onSendCode, onSubmit }: { child: ChildAccount; onClose: () => void; onSendCode: (target: string) => Promise<boolean>; onSubmit: (body: ChildEmancipateBody) => Promise<boolean> }) {
  const [digits, setDigits] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const target = isMainlandPhone(digits) ? phoneToE164(digits) : null;
  const strength = passwordStrength(password, child.username ?? '');
  const ready = target !== null && code.length === CODE_LENGTH && strength >= 2 && !busy;

  const send = async () => {
    if (!target) return;
    const sent = await onSendCode(target); // settles only once the code went out — after a gate pass, if one was needed
    if (!sent) throw new Error('not sent'); // the gate was dismissed or the send failed: the CodeField keeps its button
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || target === null) return;
    setBusy(true);
    await onSubmit({ target, code, password });
    setBusy(false);
  };

  return (
    <Sheet open onClose={() => !busy && onClose()} title={zh.children.emancipate} dismissible={!busy}>
      <form className="auth__form" onSubmit={submit} noValidate>
        <p className="auth__lead">{zh.children.emancipateLead}</p>
        <PhoneField label={zh.children.childPhone} value={digits} onChange={setDigits} hint={zh.auth.phoneHint} disabled={busy} autoFocus />
        <CodeField key={target ?? ''} value={code} onChange={setCode} onSend={send} canSend={target !== null} disabled={busy} />
        <PasswordInput label={zh.settings.newPassword} hint={zh.auth.passwordHint} value={password} onChange={setPassword} strength={strength} disabled={busy} error={password && strength < 2 ? zh.errors.weakPassword : undefined} />
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!ready}>
          {zh.children.emancipate}
        </Button>
      </form>
    </Sheet>
  );
}

interface ManageHandlers {
  onUpdate: (body: ChildUpdateBody) => Promise<boolean>;
  onRevoke: () => Promise<boolean>;
  onDelete: () => Promise<boolean>;
  onSendPhoneCode: (target: string) => Promise<boolean>;
  onEmancipate: (body: ChildEmancipateBody) => Promise<boolean>;
}

/**
 * Manage a child: nickname / simple login (96), sign out every device (98), set free (100 + 101), delete (97). `emancipateHint`
 * (SMS off on the server, or the guardian account not ready) disables set free and says why.
 */
function ManageSheet({ child, emancipateHint, onClose, handlers }: { child: ChildAccount; emancipateHint: string | null; onClose: () => void; handlers: ManageHandlers }) {
  const [name, setName] = useState(child.display_name);
  const [username, setUsername] = useState(child.username ?? '');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [emancipateOpen, setEmancipateOpen] = useState(false);
  const [touched, setTouched] = useState(false);

  const trimmedName = name.trim();
  const trimmedUser = username.trim();
  const finalUsername = trimmedUser || child.username || '';
  const usernameOk = trimmedUser === '' || USERNAME_RE.test(trimmedUser);
  const strength = passwordStrength(password, finalUsername);
  const passwordNeedsUsername = password !== '' && finalUsername === '';
  const passwordOk = password === '' || strength >= 2;
  const body: ChildUpdateBody = {};
  if (trimmedName && trimmedName !== child.display_name) body.display_name = trimmedName;
  if (trimmedUser && trimmedUser !== (child.username ?? '')) body.username = trimmedUser;
  if (password) body.password = password;
  const changed = Object.keys(body).length > 0;
  const valid = changed && trimmedName.length > 0 && trimmedName.length <= 32 && usernameOk && passwordOk && !passwordNeedsUsername;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid || busy) return;
    setBusy(true);
    const ok = await handlers.onUpdate(body);
    setBusy(false);
    if (ok) setPassword('');
  };

  const confirmThen = async (action: () => Promise<boolean>, closeConfirm: () => void) => {
    setBusy(true);
    const ok = await action();
    setBusy(false);
    if (ok) closeConfirm();
  };

  return (
    <Sheet open onClose={() => !busy && onClose()} title={`${zh.children.manage} · ${child.display_name}`} dismissible={!busy}>
      <form className="auth__form" onSubmit={save} noValidate>
        <Field label={zh.settings.displayName} error={touched && !trimmedName ? zh.welcome.nicknameHint : undefined} required>
          {(control) => <input {...control} type="text" autoComplete="off" maxLength={32} disabled={busy} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <h3 className="children__section">{zh.children.simpleLogin}</h3>
        <p className="auth__lead">{zh.children.simpleLoginHint}</p>
        <Field label={zh.auth.username} hint={touched && (!usernameOk || passwordNeedsUsername) ? undefined : zh.auth.usernameHint} error={touched && (!usernameOk || passwordNeedsUsername) ? zh.auth.usernameHint : undefined}>
          {(control) => (
            <input {...control} type="text" autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} maxLength={32} disabled={busy} value={username} onChange={(e) => setUsername(e.target.value)} />
          )}
        </Field>
        <PasswordInput label={child.has_password ? zh.settings.newPassword : zh.auth.password} hint={zh.auth.passwordHint} value={password} onChange={setPassword} strength={strength} disabled={busy} error={touched && !passwordOk ? zh.errors.weakPassword : undefined} />
        <Button type="submit" variant="primary" block loading={busy} disabled={!changed}>
          {zh.common.save}
        </Button>
      </form>
      <div className="children__danger">
        <Button size="sm" disabled={busy} onClick={() => setRevokeOpen(true)}>
          {zh.children.revokeSessions}
        </Button>
        <Button size="sm" disabled={busy || emancipateHint !== null} onClick={() => setEmancipateOpen(true)}>
          {zh.children.emancipate}
        </Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={() => setDeleteOpen(true)}>
          {zh.children.deleteChild}
        </Button>
      </div>
      {emancipateHint && (
        <p className="children__danger-hint muted" role="note">
          {emancipateHint}
        </p>
      )}
      <ConfirmDialog open={revokeOpen} title={zh.children.revokeSessions} message={zh.children.revokeConfirm} busy={busy} onConfirm={() => confirmThen(handlers.onRevoke, () => setRevokeOpen(false))} onCancel={() => setRevokeOpen(false)} />
      <ConfirmDialog open={deleteOpen} title={zh.children.deleteChild} message={zh.children.deleteConfirm} danger busy={busy} onConfirm={() => confirmThen(handlers.onDelete, () => setDeleteOpen(false))} onCancel={() => setDeleteOpen(false)} />
      {emancipateOpen && <EmancipateSheet child={child} onClose={() => setEmancipateOpen(false)} onSendCode={handlers.onSendPhoneCode} onSubmit={handlers.onEmancipate} />}
    </Sheet>
  );
}

// ---------------------------------------------------------------------------------------------------
// page
// ---------------------------------------------------------------------------------------------------

export default function ChildrenPage() {
  usePageTitle(zh.children.title);
  const { user, session, settings, server, applyAuth } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const isGuardianSelf = user?.account_kind === 'guardian' && !session?.guardian;
  const forbidden = user !== null && !isGuardianSelf;

  const [switching, setSwitching] = useState<number | null>(null);

  // a learner, a child, or a guardian's device switched into a child: the page is not theirs (except while this very page is
  // switching the device — the child user lands in the context before `switchTo` navigates to /today)
  useEffect(() => {
    if (!forbidden || switching !== null) return;
    toast.error(zh.errors.forbidden, { id: 'forbidden' });
    navigate(routePaths.settings, { replace: true });
  }, [forbidden, switching, navigate, toast]);

  const list = useApi((signal) => endpoints.getChildren(signal), [], { enabled: isGuardianSelf });
  const gate = useGuardianGate(list.data?.gate_until ?? null, toast);

  const [addOpen, setAddOpen] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [manageId, setManageId] = useState<number | null>(null);
  const [codeFor, setCodeFor] = useState<{ childId: number; code: string } | null>(null);

  const data = list.data;
  const ready = data?.ready ?? false;
  const pinSet = data?.pin_set ?? false;
  const smsOn = server?.sms_enabled === true;
  // readiness needs a live phone and a phone is bound only through SMS: with SMS off the banner explains instead of linking
  const phoneBlocked = (data?.missing.includes('phone') ?? false) && !smsOn;
  // set free sends an SMS to the child's phone (100) and needs readiness (API.md 100 / 101)
  const emancipateHint = !smsOn ? zh.children.emancipateSmsOff : data && !data.ready ? `${zh.children.notReady}${missingLabels(data.missing)}` : null;
  const managed = manageId !== null ? (data?.items.find((c) => c.id === manageId) ?? null) : null;
  const codeChild = codeFor !== null ? (data?.items.find((c) => c.id === codeFor.childId) ?? null) : null;

  // the list refresh after a mutation is fire-and-forget: the action's outcome (toast, closing the sheet) must not wait for it
  const reload = () => void list.reload();

  const openAdd = () => void gate.run(async () => setAddOpen(true));
  const createChild = (body: ChildCreateBody) =>
    gate.run(async () => {
      await endpoints.createChild(body);
      reload();
      toast.success(zh.common.saved);
      setAddOpen(false);
    });

  const openPin = () => void gate.run(async () => setPinOpen(true)); // 103 is always gated; without a PIN the gate offers the password / a code
  const savePin = (pin: string) =>
    gate.run(async () => {
      await endpoints.setGuardianPin({ pin });
      reload();
      toast.success(zh.children.pinSaved);
      setPinOpen(false);
    });

  const switchTo = async (child: ChildAccount) => {
    setSwitching(child.id);
    try {
      const res = await endpoints.switchToChild(child.id);
      await applyAuth(res); // this device is the child's now; <RequireOnboarded/> sends a fresh child to /welcome
      navigate(routePaths.today, { replace: true });
    } catch (e) {
      toast.error(errorMessage(e));
      setSwitching(null);
    }
  };

  const issueCode = (child: ChildAccount) =>
    gate.run(async () => {
      const res = await endpoints.issueChildLoginCode(child.id);
      setCodeFor({ childId: child.id, code: res.code });
    });

  const handlersFor = (child: ChildAccount): ManageHandlers => ({
    onUpdate: (body) =>
      gate.run(async () => {
        await endpoints.updateChild(child.id, body);
        reload();
        toast.success(body.password ? zh.children.passwordChanged : zh.common.saved);
      }),
    onRevoke: () =>
      gate.run(async () => {
        await endpoints.revokeChildSessions(child.id);
        reload();
        toast.success(zh.children.revoked);
      }),
    onDelete: () =>
      gate.run(async () => {
        await endpoints.deleteChild(child.id);
        setManageId(null);
        reload();
        toast.success(zh.children.deleted);
      }),
    onSendPhoneCode: (target) =>
      gate.run(async () => {
        await endpoints.requestChildPhoneCode(child.id, { target });
        toast.success(zh.auth.codeSent);
      }),
    onEmancipate: (body) =>
      gate.run(async () => {
        await endpoints.emancipateChild(child.id, body);
        setManageId(null);
        reload();
        toast.success(zh.children.emancipated);
      }),
  });

  if (!user || forbidden) return null;

  return (
    <section className="page page--narrow children">
      <h1 className="page__title">{zh.children.title}</h1>
      <p className="children__hint muted">{zh.children.hint}</p>
      {list.error && (
        <div className="children__error" role="alert">
          <span>{errorMessage(list.error)}</span>
          <Button size="sm" onClick={reload}>
            {zh.common.retry}
          </Button>
        </div>
      )}
      {data && !data.ready && (
        <div className="children__banner" role="status">
          <div className="children__banner-body">
            <span>
              {zh.children.notReady}
              {missingLabels(data.missing)}
            </span>
            {phoneBlocked && <span className="children__banner-hint">{zh.children.smsOffHint}</span>}
          </div>
          {!phoneBlocked && <Link to={routePaths.settings}>{zh.children.goSettings}</Link>}
        </div>
      )}
      {list.loading && !data && <Skeleton lines={3} />}
      {data && data.items.length === 0 && <EmptyState title={zh.children.empty} {...(ready ? { action: { label: zh.children.add, onClick: openAdd } } : {})} />}
      {data && data.items.length > 0 && (
        <>
          <ul className="children__list">
            {data.items.map((child) => (
              <ChildCard key={child.id} child={child} tz={settings?.timezone} ready={ready} switching={switching === child.id} onSwitch={() => void switchTo(child)} onCode={() => void issueCode(child)} onManage={() => setManageId(child.id)} />
            ))}
          </ul>
          <div className="children__actions">
            <Button variant="primary" disabled={!ready} onClick={openAdd}>
              {zh.children.add}
            </Button>
          </div>
        </>
      )}
      {data && (
        <div className="children__row card">
          <span>{zh.children.pin}</span>
          <Button size="sm" onClick={openPin}>
            {pinSet ? zh.children.pinChange : zh.children.pinSet}
          </Button>
        </div>
      )}
      {addOpen && <AddChildSheet pinSet={pinSet} onClose={() => setAddOpen(false)} onSubmit={createChild} />}
      {pinOpen && <PinSheet pinSet={pinSet} onClose={() => setPinOpen(false)} onSubmit={savePin} />}
      {managed && <ManageSheet key={managed.id} child={managed} emancipateHint={emancipateHint} onClose={() => setManageId(null)} handlers={handlersFor(managed)} />}
      {codeFor && codeChild && <LoginCodeSheet child={codeChild} code={codeFor.code} onClose={() => setCodeFor(null)} onRegenerate={() => issueCode(codeChild)} />}
      <GateDialog open={gate.open} mode="gate" pinSet={pinSet} hasPassword={user.has_password} onClose={gate.close} onPassed={gate.onPassed} />
    </section>
  );
}
