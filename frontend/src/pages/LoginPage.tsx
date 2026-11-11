// LoginPage — `/login` (guest; FRONTEND §2, API.md 3 / §3.1, docs/AUTH_SIGNUP_DESIGN.md §5.2): three entries behind a
// Segmented — phone (while `health.sms_enabled`), e-mail (while `health.email_enabled`) and username + password (always; the
// identifier field takes a username, a phone number or an e-mail, body `{username, password}`). The default entry is
// phone in `verified` mode with SMS on, else username + password. The code entries are the shared `CodeSignIn` (consent → captcha →
// send → 6 digits → endpoint 81, stale-phone sheet). Kept from before: the first-admin notice while `needs_setup`, the
// register link (hidden when registration is closed unless `needs_setup`), `?next` propagation. New: forgot password → /forgot,
// the legal links, the password-reset notice after /forgot (`?reset=1`), and the read-only demo (D9, `zh.auth.demoTitle`) below the form —
// `GET /api/demo` through `useApi`, hidden on any error or an empty list so a server without the endpoint shows nothing.
// Slice 1-B: under the form the link `zh.auth.haveChildCode` → /child-login (a child's device signs in with the guardian's
// 8-digit code, API.md 107), hidden while `needs_setup`.
// Slice 2-A (API.md §3.3): under the form the `ThirdPartyRow` — WeChat opens the `WechatSignIn` sheet, whose confirmed poll
// carries the session (→ `applyAuth`); QQ / Apple are links to the redirect endpoints 118 / 120 with `?next` (in `invite` mode
// behind the row's invite step, which adds `invite_code`) —, hidden while `needs_setup` or while no provider flag is on (and the
// row's platform rule hides QQ / Apple in the native shell); `?error=<code>` from the QQ / Apple redirects (119 / 121 / 122) shows
// an `auth__notice` through `errorMessageForCode` once — the code is kept in state and the param leaves the URL (`replace`), like
// the settings page does, so a reload or a back navigation does not repeat a stale error.
// A successful sign-in sets the session in AuthContext and <RequireGuest/> redirects to `?next=` (or /today).
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router';
import { errorMessage, errorMessageForCode } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { CodeChannel } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { ExampleList } from '@/components/study/ExampleList';
import { WordImage } from '@/components/study/WordImage';
import { Button } from '@/components/ui/Button';
import { CodeSignIn } from '@/components/ui/CodeSignIn';
import { Field } from '@/components/ui/Field';
import { Segmented } from '@/components/ui/Segmented';
import { Sheet } from '@/components/ui/Sheet';
import { ThirdPartyRow } from '@/components/ui/ThirdPartyRow';
import { WechatSignIn } from '@/components/ui/WechatSignIn';
import { WordHeader } from '@/components/word/WordHeader';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { legalUrls, routePaths } from '@/routes';
import '@/components/ui/auth.css';
import './LoginPage.css';

type Entry = CodeChannel | 'password';

/** The read-only demo (D9): three public words with their card, meaning, first example and dance; nothing is recorded. */
function LoginDemo() {
  const demo = useApi((signal) => endpoints.getDemo(signal), []);
  const [index, setIndex] = useState(0);
  const [token, setToken] = useState(0);
  const items = demo.data?.items ?? [];
  const item = items[index] ?? items[0];
  if (demo.error || !item) return null;
  const examples = item.content?.examples.slice(0, 1) ?? [];
  return (
    <section className="login-demo" aria-labelledby="login-demo-title">
      <h3 id="login-demo-title" className="login-demo__title">
        {zh.auth.demoTitle}
      </h3>
      <p className="login-demo__hint muted">{zh.auth.demoHint}</p>
      <div className="login-demo__card card">
        <WordHeader word={item.word} size="lg" as="div" showStages={false} dance={item.dance} playToken={token} autoplay="form" replay="full" />
        <WordImage image={item.image} showImages alt={item.content?.image_alt_zh ?? null} />
        <p className="login-demo__meaning" lang="zh-CN">
          {item.content?.meaning_zh || item.word.translation_short}
        </p>
        {examples.length > 0 && <ExampleList examples={examples} lemma={item.word.lemma} forms={[]} zhMode="always" />}
      </div>
      {items.length > 1 && (
        <div className="login-demo__dots" role="group" aria-label={zh.auth.demoTitle}>
          {items.map((it, i) => (
            <button
              key={it.word.id}
              type="button"
              className="login-demo__dot"
              aria-label={zh.auth.demoItem(i + 1)}
              aria-pressed={i === index}
              onClick={() => {
                setIndex(i);
                setToken((t) => t + 1); // the new word dances in
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export default function LoginPage() {
  usePageTitle(zh.auth.login);
  const { login, health, refreshHealth, applyAuth, refresh } = useAuth();
  const [params, setParams] = useSearchParams();
  const [entryChoice, setEntryChoice] = useState<Entry | null>(null);
  const [wechatOpen, setWechatOpen] = useState(false);
  const [oauthError, setOauthError] = useState<string | null>(null); // the code of a failed QQ / Apple redirect flow, shown once
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!health) void refreshHealth();
  }, [health, refreshHealth]);

  // a failed QQ / Apple redirect flow (API.md 119 / 121 / 122) lands here with `?error=<code>`: keep the code, drop the param
  useEffect(() => {
    const code = params.get('error');
    if (code === null) return;
    setOauthError(code);
    const rest = new URLSearchParams(params);
    rest.delete('error');
    setParams(rest, { replace: true });
  }, [params, setParams]);

  const needsSetup = health?.needs_setup === true;
  const registrationVisible = needsSetup || health?.registration_mode !== 'closed';
  const next = params.get('next');
  const registerTo = next ? `${routePaths.register}?next=${encodeURIComponent(next)}` : routePaths.register;
  const resetDone = params.get('reset') === '1';

  // sign-in entries offered by the server; the first admin is created with a username and password, so the code entries wait
  const channels: CodeChannel[] = needsSetup ? [] : [...(health?.sms_enabled ? (['phone'] as const) : []), ...(health?.email_enabled ? (['email'] as const) : [])];
  const entries: Entry[] = [...channels, 'password'];
  const defaultEntry: Entry = health?.registration_mode === 'verified' && channels.includes('phone') ? 'phone' : 'password';
  const entry: Entry = entryChoice !== null && entries.includes(entryChoice) ? entryChoice : defaultEntry;
  const entryLabel = (e: Entry) => (e === 'phone' ? zh.auth.methodPhone : e === 'email' ? zh.auth.methodEmail : zh.auth.methodPassword);

  const canSubmit = username.trim().length > 0 && password.length > 0 && !busy;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <section className="page page--narrow auth">
      <header className="auth__brand">
        <h1 className="auth__name">{zh.app.name}</h1>
        <p className="auth__tagline">{zh.app.tagline}</p>
      </header>
      <h2 className="auth__title">{zh.auth.login}</h2>
      {resetDone && (
        <div className="auth__notice" role="status">
          {zh.auth.resetDone}
        </div>
      )}
      {oauthError && (
        <div className="auth__notice" role="alert">
          {errorMessageForCode(oauthError)}
        </div>
      )}
      {needsSetup && (
        <div className="auth__notice" role="status">
          {zh.auth.needsSetup}
          <Link to={registerTo}>{zh.auth.goRegister}</Link>
        </div>
      )}
      {entries.length > 1 && (
        <Segmented className="auth__entries" block aria-label={zh.auth.loginMethod} options={entries.map((e) => ({ value: e, label: entryLabel(e) }))} value={entry} onChange={setEntryChoice} />
      )}
      {entry === 'password' ? (
        <>
          <form className="auth__form" onSubmit={submit} noValidate>
            <Field label={zh.auth.identifier} required>
              {(control) => (
                <input
                  {...control}
                  type="text"
                  value={username}
                  autoComplete="username"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  autoFocus
                  maxLength={254}
                  onChange={(e) => setUsername(e.target.value)}
                />
              )}
            </Field>
            <Field label={zh.auth.password} required>
              {(control) => <input {...control} type="password" value={password} autoComplete="current-password" maxLength={64} onChange={(e) => setPassword(e.target.value)} />}
            </Field>
            {error && (
              <p className="auth__error" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!canSubmit}>
              {zh.auth.login}
            </Button>
          </form>
          <p className="auth__links">
            <Link to={routePaths.forgot}>{zh.auth.forgot}</Link>
          </p>
        </>
      ) : (
        <CodeSignIn key={entry} channels={[entry]} captcha={health?.captcha === true} registrationMode={health?.registration_mode} submitLabel={registrationVisible ? zh.auth.loginOrRegister : zh.auth.login} />
      )}
      {/* slice 2-A: the providers the server offers (nothing on a server without credentials); the first admin signs up with a password, so the row waits like the code entries */}
      {!needsSetup && <ThirdPartyRow flags={health} next={next} registrationMode={health?.registration_mode} onWechat={() => setWechatOpen(true)} />}
      {!needsSetup && registrationVisible && (
        <p className="auth__hint muted">
          {zh.auth.noAccount} <Link to={registerTo}>{zh.auth.register}</Link>
        </p>
      )}
      {!needsSetup && (
        <p className="auth__hint muted">
          <Link to={routePaths.childLogin}>{zh.auth.haveChildCode}</Link>
        </p>
      )}
      <LoginDemo />
      <p className="auth__links">
        <a href={legalUrls.terms}>{zh.auth.termsLink}</a>
        <a href={legalUrls.privacy}>{zh.auth.privacyLink}</a>
        <a href={legalUrls.children}>{zh.auth.childrenLink}</a>
      </p>
      <Sheet open={wechatOpen} onClose={() => setWechatOpen(false)} title={zh.auth.wechatTitle}>
        {wechatOpen && (
          <WechatSignIn
            kind="login"
            registrationMode={health?.registration_mode}
            onDone={async (user, _created, settings) => {
              // the session cookie came with the confirmed poll: install it like every sign-in and let the guest guard redirect to ?next
              // (an account the confirmation created has needs_profile and reaches /welcome step 0 through the onboarding guard)
              if (settings) await applyAuth({ user, settings });
              else await refresh().catch(() => undefined);
            }}
          />
        )}
      </Sheet>
    </section>
  );
}
