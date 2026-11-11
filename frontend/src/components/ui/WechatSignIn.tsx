// WechatSignIn — the SPA side of the WeChat ticket bridge (FRONTEND §4; API.md 112–114, docs/AUTH_SIGNUP_DESIGN.md §5.3): one
// ticket (endpoint 112) shown as the mini-program code (`<img src={qr_url}>`, endpoint 114 — a broken image hides the picture and
// leaves the pairing code block alone) plus the 6-digit pairing code in `123 456` groups with a copy button and the hint for the
// mobile path (search the mini program, type the code); endpoint 113 is polled every 2 s while mounted (a 429 backs off to 5 s)
// until the ticket is `scanned` (`zh.auth.scanned`), `confirmed` (→ `onDone(user, created, settings)` — for `kind='login'` the
// session cookie came with that very poll, so the parent installs it through `applyAuth`; for `kind='bind'` the identity is
// already written and `user.providers` carries it), `cancelled` (`zh.auth.cancelledInWechat` + the refresh button) or `expired` /
// gone (a 404; `zh.auth.qrExpired` + refresh — every refresh is a new ticket). Any other 4xx of the poll (403 `account_disabled`,
// 409 …) ends the ticket too: the poll stops and the mapped `errorMessage` shows with the refresh button; a network failure or a
// 5xx is a blip and keeps polling, until `WECHAT_POLL_MAX_TRANSIENT` of them in a row end the ticket the same way. The first ticket
// is created once per mount (a ref guards React StrictMode's doubled effects — the poll cookie `wd_wxt` is one per browser, so a
// second ticket would orphan the one on screen). In `invite` registration mode the login variant first asks for the invite code,
// optional because an existing binding signs in without one (the server validates it at the ticket and consumes it at the
// confirmation). The ticket lives in component state only — nothing is written to storage.
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { errorMessage, isAbortError, isApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { ServerFlags, Settings, User, WechatTicket } from '@/api/types';
import { usePolling } from '@/hooks/usePolling';
import { zh } from '@/i18n/zh';
import { Button } from './Button';
import { cx } from './cx';
import { Field } from './Field';
import './auth.css';

/** Poll interval of endpoint 113 (API.md: every 2 s) and the back-off after a 429 `rate_limited`. */
export const WECHAT_POLL_MS = 2000;
export const WECHAT_POLL_SLOW_MS = 5000;
/** Consecutive network / 5xx failures of the poll tolerated before the ticket is given up (≈ 10 s at the normal interval). */
export const WECHAT_POLL_MAX_TRANSIENT = 5;
const COPIED_FLASH_MS = 2000;

/** Where the bridge stands: the invite step, a ticket being created, the live ticket (pending / scanned), or one of the ends. */
export type WechatPhase = 'invite' | 'creating' | 'pending' | 'scanned' | 'confirmed' | 'cancelled' | 'expired' | 'failed';

export interface WechatSignInProps {
  kind: 'login' | 'bind';
  /** `health.registration_mode`: `invite` asks a login ticket for the (optional) invite code first. */
  registrationMode?: ServerFlags['registration_mode'] | undefined;
  /** The confirmed ticket: the signed-in / bound account, whether the confirmation created it, and — login tickets — its settings. */
  onDone: (user: User, created: boolean, settings: Settings | null) => void | Promise<void>;
  /** Test seam only: the poll intervals (default 2 s, 5 s after a 429). */
  intervals?: { poll: number; slow: number };
  className?: string;
}

/** `123456` → `123 456` (the digits are typed into the mini program, so they are shown in two groups). */
export function groupPairingCode(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}

export function WechatSignIn({ kind, registrationMode, onDone, intervals, className }: WechatSignInProps) {
  const pollMs = intervals?.poll ?? WECHAT_POLL_MS;
  const slowMs = intervals?.slow ?? WECHAT_POLL_SLOW_MS;
  const askInvite = kind === 'login' && registrationMode === 'invite';
  const [invite, setInvite] = useState('');
  const [phase, setPhase] = useState<WechatPhase>(askInvite ? 'invite' : 'creating');
  const [ticket, setTicket] = useState<WechatTicket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [imgBroken, setImgBroken] = useState(false);
  const [slow, setSlow] = useState(false);
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const started = useRef(false); // the first ticket was requested (StrictMode runs the mount effect twice)
  const createSeq = useRef(0); // the latest ticket request; an older response (a double refresh) is dropped so state and cookie agree
  const transientFailures = useRef(0); // consecutive network / 5xx poll failures
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (copiedTimer.current) clearTimeout(copiedTimer.current);
    };
  }, []);

  /** A new ticket (the first one, or a refresh after expiry / cancellation / a failure). */
  const create = useCallback(async () => {
    setPhase('creating');
    setError(null);
    setTicket(null);
    setImgBroken(false);
    setSlow(false);
    setCopied(false);
    transientFailures.current = 0;
    const seq = ++createSeq.current;
    const code = invite.trim();
    try {
      const res = await endpoints.createWechatTicket({ kind, ...(askInvite && code ? { invite_code: code } : {}) });
      if (!mounted.current || seq !== createSeq.current) return;
      setTicket(res);
      setPhase('pending');
    } catch (e) {
      if (!mounted.current || seq !== createSeq.current) return;
      setError(errorMessage(e));
      setPhase(askInvite ? 'invite' : 'failed'); // an invalid invite code goes back to the field, everything else offers the refresh button
    }
  }, [kind, invite, askInvite]);

  // the first ticket as soon as the bridge mounts — once, even under StrictMode's doubled effects; the invite variant waits for its form
  const createRef = useRef(create);
  createRef.current = create;
  useEffect(() => {
    if (askInvite || started.current) return;
    started.current = true;
    void createRef.current();
  }, [askInvite]);

  const live = phase === 'pending' || phase === 'scanned';
  usePolling(
    async (signal) => {
      if (!ticket) return false;
      try {
        const res = await endpoints.pollWechatTicket(ticket.ticket, signal);
        if (!mounted.current) return false;
        transientFailures.current = 0;
        switch (res.status) {
          case 'pending':
            return undefined;
          case 'scanned':
            setPhase('scanned');
            return undefined;
          case 'confirmed':
            if (!res.user) {
              setError(zh.errors.server); // the contract promises the account with a confirmed ticket
              setPhase('failed');
              return false;
            }
            setPhase('confirmed');
            await onDoneRef.current(res.user, res.created === true, res.settings);
            return false;
          case 'cancelled':
            setPhase('cancelled');
            return false;
          case 'expired':
            setPhase('expired');
            return false;
        }
      } catch (e) {
        if (isAbortError(e)) throw e;
        if (!mounted.current) return false;
        if (isApiError(e) && e.status === 404) {
          setPhase('expired'); // unknown / consumed ticket, or the poll cookie is gone: the same as expired for the learner
          return false;
        }
        if (isApiError(e) && e.status === 429) {
          setSlow(true); // the per-IP poll window: slow down instead of giving up
          return undefined;
        }
        const transient = !isApiError(e) || e.status === 0 || e.status >= 500; // a network blip or a server hiccup, not a verdict on the ticket
        if (transient && ++transientFailures.current < WECHAT_POLL_MAX_TRANSIENT) return undefined; // keep polling for a while
        // 403 account_disabled, 409 … (or blips that will not stop): the ticket is dead for this learner — say why, offer a new one
        setError(errorMessage(e));
        setPhase('failed');
        return false;
      }
      return undefined;
    },
    slow ? slowMs : pollMs,
    { enabled: live && ticket !== null },
  );

  const copy = async () => {
    if (!ticket) return;
    try {
      await navigator.clipboard.writeText(ticket.pairing_code);
      setCopied(true);
      if (copiedTimer.current) clearTimeout(copiedTimer.current);
      copiedTimer.current = setTimeout(() => setCopied(false), COPIED_FLASH_MS);
    } catch {
      /* no clipboard (insecure context, permission denied): the code stays readable on screen */
    }
  };

  if (phase === 'invite') {
    const submit = (e: FormEvent) => {
      e.preventDefault();
      void create();
    };
    return (
      <form className={cx('auth__form wechat-signin', className)} onSubmit={submit} noValidate>
        <Field label={zh.auth.inviteForNew}>
          {(control) => <input {...control} type="text" autoComplete="off" autoCapitalize="characters" spellCheck={false} autoFocus value={invite} onChange={(e) => setInvite(e.target.value)} />}
        </Field>
        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" block>
          {zh.auth.showQr}
        </Button>
      </form>
    );
  }

  const ended = phase === 'expired' || phase === 'cancelled' || phase === 'failed';
  const status = phase === 'creating' ? zh.common.loading : phase === 'scanned' ? zh.auth.scanned : phase === 'expired' ? zh.auth.qrExpired : phase === 'cancelled' ? zh.auth.cancelledInWechat : phase === 'failed' ? error : null;
  return (
    <div className={cx('wechat-signin', className)} aria-busy={phase === 'creating' || undefined}>
      {live && ticket && (
        <>
          {!imgBroken && <img className="wechat-signin__qr" src={ticket.qr_url} alt={zh.auth.wechatQrAlt} width={200} height={200} decoding="async" onError={() => setImgBroken(true)} />}
          {!imgBroken && <p className="wechat-signin__hint">{zh.auth.wechatScanHint}</p>}
          <div className="wechat-signin__pair">
            <p className="wechat-signin__hint">{zh.auth.wechatPairHint}</p>
            <p className="wechat-signin__code">
              {zh.auth.pairingCode}
              <strong lang="en">{groupPairingCode(ticket.pairing_code)}</strong>
            </p>
            <Button size="sm" onClick={() => void copy()}>
              {copied ? zh.auth.copied : zh.auth.copyPairing}
            </Button>
          </div>
        </>
      )}
      <p className={cx('wechat-signin__status', phase === 'failed' && 'wechat-signin__status--error')} role="status" aria-live="polite">
        {status}
      </p>
      {ended && <Button onClick={() => void create()}>{zh.auth.refresh}</Button>}
    </div>
  );
}
