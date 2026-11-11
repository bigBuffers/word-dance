// ThirdPartyRow — the third-party entries under the sign-in form (FRONTEND §2 / §4; API.md §3.3, docs/AUTH_SIGNUP_DESIGN.md §5.3):
// one entry per provider the server offers (`health.wechat_enabled` / `qq_enabled` / `apple_enabled` — all false on a server
// without credentials, and then the row is not rendered at all). WeChat opens the ticket bridge (`WechatSignIn`, in the parent's
// sheet); QQ and Apple are plain `<a href>` links to the redirect endpoints 118 / 120 (`oauthStartUrl`; the provider's answer comes
// back through 119 / 121 → 122 as a full-page navigation, `?next` kept) — in `invite` registration mode they first open the invite
// step (`OauthInviteStep` in this row's sheet: the optional code becomes `invite_code` on the link; the skip link `zh.auth.skipInvite`
// leaves it out, because an existing binding signs in without one). Apple keeps the HIG wording (`zh.auth.apple`).
// Platform rule (`thirdPartyEntries`): the redirect entries exist on the web only — inside the Capacitor shell (`nativePlatform()`
// 'ios' / 'android'; `allowNavigation: []`) a top-level navigation to the provider's host opens the system browser, where the
// session would land instead of in the app — and on iOS WeChat is offered only next to Apple (App Store 4.8, design §5.3), so the
// iOS shell shows nothing until a native Apple plugin exists; the Android shell shows WeChat alone (its pairing code works there).
import { useState } from 'react';
import { oauthStartUrl, type OAuthProvider } from '@/api/endpoints';
import type { ServerFlags } from '@/api/types';
import { zh } from '@/i18n/zh';
import { nativePlatform, type NativePlatform } from '@/native/capacitor';
import { Button } from './Button';
import { cx } from './cx';
import { Field } from './Field';
import { Sheet } from './Sheet';
import './auth.css';

/** The three flags of `HealthResponse` / `ServerFlags` (API.md 1 / 5). */
export interface ThirdPartyFlags {
  wechat_enabled: boolean;
  qq_enabled: boolean;
  apple_enabled: boolean;
}

/** Which providers this platform can start a login / bind with. */
export interface ThirdPartyEntries {
  wechat: boolean;
  qq: boolean;
  apple: boolean;
}

export interface ThirdPartyRowProps {
  /** `health` (guests) or `server` (a session); null / undefined while unknown → nothing is rendered. */
  flags: ThirdPartyFlags | null | undefined;
  /** Same-origin path to land on after a QQ / Apple login (the login page's `?next`). */
  next?: string | null;
  /** `health.registration_mode`: in `invite` mode the QQ / Apple entries ask for the (optional) invite code before the redirect. */
  registrationMode?: ServerFlags['registration_mode'] | undefined;
  /** The WeChat entry: the parent opens its `WechatSignIn` sheet. */
  onWechat: () => void;
  className?: string;
}

/**
 * The entries the row shows for these flags on this platform (the platform rules live here, so the settings page and the tests
 * share them): QQ / Apple only on the web (a redirect flow cannot finish inside the shell), and on iOS WeChat only next to Apple.
 */
export function thirdPartyEntries(flags: ThirdPartyFlags | null | undefined, platform: NativePlatform = nativePlatform()): ThirdPartyEntries {
  if (!flags) return { wechat: false, qq: false, apple: false };
  // QQ / Apple are top-level navigations to the provider's host: the shell's `allowNavigation: []` opens those in the system
  // browser, where endpoint 122 would set the session — so the redirect entries stay web-only until a native plugin / return path exists
  const redirectOk = platform === 'web';
  const apple = flags.apple_enabled && redirectOk;
  // App Store 4.8: an iOS app that offers a third-party login must offer an equivalent privacy-friendly one — Apple's own
  const mainlandAllowed = platform !== 'ios' || apple;
  return { wechat: flags.wechat_enabled && mainlandAllowed, qq: flags.qq_enabled && mainlandAllowed && redirectOk, apple };
}

/**
 * The invite step of a QQ / Apple login in `invite` registration mode (API.md 118 / 120 `invite_code`): the code is optional — a
 * new account needs it, an existing binding signs in without one (the skip link). Both ways out are plain links, so the flow stays
 * in this browser (the `wd_oauth` cookie of /start is required at /finish); Enter in the field follows the continue link.
 */
export function OauthInviteStep({ provider, next }: { provider: OAuthProvider; next?: string | null }) {
  const [invite, setInvite] = useState('');
  const withCode = oauthStartUrl(provider, 'login', next, invite);
  return (
    <form
      className="auth__form oauth-invite"
      onSubmit={(e) => {
        e.preventDefault();
        window.location.assign(withCode);
      }}
      noValidate
    >
      <Field label={zh.auth.inviteForNew}>
        {(control) => <input {...control} type="text" autoComplete="off" autoCapitalize="characters" spellCheck={false} autoFocus value={invite} onChange={(e) => setInvite(e.target.value)} />}
      </Field>
      <a className="btn btn--primary btn--lg btn--block" href={withCode}>
        <span className="btn__label">{zh.auth.inviteContinue}</span>
      </a>
      <p className="auth__links">
        <a href={oauthStartUrl(provider, 'login', next)}>{zh.auth.skipInvite}</a>
      </p>
    </form>
  );
}

export function ThirdPartyRow({ flags, next, registrationMode, onWechat, className }: ThirdPartyRowProps) {
  const [inviteFor, setInviteFor] = useState<OAuthProvider | null>(null);
  const entries = thirdPartyEntries(flags);
  if (!entries.wechat && !entries.qq && !entries.apple) return null;
  const askInvite = registrationMode === 'invite';
  const redirectEntry = (provider: OAuthProvider, label: string) =>
    askInvite ? (
      <Button onClick={() => setInviteFor(provider)}>{label}</Button>
    ) : (
      <a className="btn btn--secondary btn--md" href={oauthStartUrl(provider, 'login', next)}>
        <span className="btn__label">{label}</span>
      </a>
    );
  return (
    <div className={cx('third-party', className)} role="group" aria-label={zh.auth.thirdParty}>
      <p className="third-party__label">{zh.auth.thirdParty}</p>
      <div className="third-party__buttons">
        {entries.wechat && <Button onClick={onWechat}>{zh.auth.wechat}</Button>}
        {entries.qq && redirectEntry('qq', zh.auth.qq)}
        {entries.apple && redirectEntry('apple', zh.auth.apple)}
      </div>
      <Sheet open={inviteFor !== null} onClose={() => setInviteFor(null)} title={inviteFor === 'apple' ? zh.auth.apple : zh.auth.qqTitle}>
        {inviteFor !== null && <OauthInviteStep provider={inviteFor} next={next} />}
      </Sheet>
    </div>
  );
}
