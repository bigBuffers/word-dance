// LoginPage (FRONTEND §2, API.md 3 / §3.1): the username + password entry keeps its contract (register-link rules, ?next, the
// `{username, password}` body, the inline error), the code entries appear only when the server can send on them, the code
// flow is consent → (captcha) → send → countdown → 6 digits → endpoint 81 → session, the stale-phone challenge takes a
// second factor or a dispute (endpoint 81 is posted exactly once — the sheet lives outside the form), a 429 on the send
// counts the button down, and the read-only demo renders only when `GET /api/demo` answers with items.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CodeLoginResponse, Content, DemoResponse, ImageMeta, Settings, User, WordBrief } from '@/api/types';
import { AuthProvider, RequireGuest } from '@/auth/AuthContext';
import { zh } from '@/i18n/zh';
import LoginPage from './LoginPage';

const ISO = '2026-10-14T00:00:00Z';
const WX_TICKET = 'abcdefghijklmnopqrstuvwxyz';
const wechatTicket = () => json(201, { ticket: WX_TICKET, pairing_code: '123456', expires_in_s: 180, qr_url: `/api/auth/wechat/ticket/${WX_TICKET}/qr` });
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const unauthorized = () => json(401, { error: { code: 'unauthorized', message: '' } });
const health = (over: Record<string, unknown>) => () =>
  json(200, { status: 'ok', version: '0.1.0', registration_mode: 'invite', needs_setup: false, sms_enabled: false, email_enabled: false, captcha: false, wechat_enabled: false, qq_enabled: false, apple_enabled: false, time: ISO, ...over });

const user: User = { id: 7, username: 'u_ab23cd45', display_name: '', email: null, email_verified: false, role: 'user', onboarding_state: 'pending', created_at: ISO, has_password: false, phone_masked: '138****8000', needs_profile: true, age_band: null, account_kind: 'learner', is_child: false, needs_profile_prompt: false, providers: [] };
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: true, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: false, updated_at: ISO,
};
const me = () => json(200, { user, settings, server: { version: '0.1.0', registration_mode: 'verified', email_configured: false, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', sms_enabled: true, wechat_enabled: false, qq_enabled: false, apple_enabled: false }, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: null } });
const word = (id: number, lemma: string): WordBrief => ({
  id, lemma, display: lemma, kind: 'word', phonetic: null, translation_short: `zh-${lemma}`, stages: ['xs'], stage_min: 1, cet6_star: false, frq: null, collins: null, oxford: null, difficulty: null,
  is_public: true, is_valid_english: true, my_state: null, content_state: 'ready', image_state: 'none',
});
const image = (id: number): ImageMeta => ({ id: null, url: `/media/demo/${id}.svg`, kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: null, height: null, alt_zh: null, attribution: null });
const content = (lemma: string): Content => ({
  word: lemma, valid: true, meaning_zh: `meaning-${lemma}`, meaning_en: 'x', examples: [{ en: `Look ${lemma}.`, zh: `zh-example-${lemma}` }, { en: 'second', zh: 'second' }], collocations: [], mnemonic_zh: '',
  image_keywords: [], image_alt_zh: '', difficulty: 1, version: 1, prompt_version: 'p', model: 'm', created_at: ISO,
});
const demo: DemoResponse = { items: [{ word: word(1, 'up'), content: content('up'), image: image(1), dance: null }, { word: word(2, 'jump'), content: null, image: image(2), dance: null }] };

type Handler = (init?: RequestInit) => Response;
function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const path = url.split('?')[0] ?? url;
    const handler = routes[path];
    return Promise.resolve(handler ? handler(init) : json(404, { error: { code: 'not_found', message: '' } }));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}
const bodyOf = (fetchMock: ReturnType<typeof mockFetch>, path: string) => {
  const call = fetchMock.mock.calls.find(([u]) => String(u) === path);
  return call?.[1]?.body ? (JSON.parse(String(call[1].body)) as Record<string, unknown>) : null;
};

/** The current query string, so a test can see `?error=` leave the URL while `?next=` stays. */
function SearchProbe() {
  const location = useLocation();
  return <div data-testid="search">{location.search}</div>;
}

function renderLogin(path = '/login') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route element={<RequireGuest />}>
            <Route
              path="/login"
              element={
                <>
                  <LoginPage />
                  <SearchProbe />
                </>
              }
            />
          </Route>
          <Route path="/today" element={<div>today-page</div>} />
          <Route path="/bank" element={<div>bank-page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

const phoneInput = () => screen.getByLabelText(new RegExp(`^${zh.auth.phone}`)) as HTMLInputElement;
const codeInput = () => screen.getByLabelText(new RegExp(`^${zh.auth.code}`)) as HTMLInputElement;
const sendButton = () => screen.getByRole('button', { name: zh.auth.sendCode }) as HTMLButtonElement;
const consentBox = () => screen.getByRole('checkbox') as HTMLInputElement;

describe('LoginPage', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows the first-admin notice with a register link instead of the normal hint while needs_setup is true', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ needs_setup: true, registration_mode: 'closed' }) });
    renderLogin();
    expect(await screen.findByText(zh.auth.needsSetup, { exact: false })).toBeTruthy();
    expect(screen.getByRole('link', { name: zh.auth.goRegister }).getAttribute('href')).toBe('/register');
    expect(screen.queryByText(zh.auth.noAccount, { exact: false })).toBeNull();
  });

  it('hides the register link on a closed server and keeps it otherwise, carrying ?next=', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'closed' }) });
    const first = renderLogin();
    await screen.findByRole('button', { name: zh.auth.login });
    await waitFor(() => expect(screen.queryByRole('link', { name: zh.auth.register })).toBeNull());
    first.unmount();
    vi.unstubAllGlobals();

    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'invite' }) });
    renderLogin('/login?next=%2Fbank');
    expect((await screen.findByRole('link', { name: zh.auth.register })).getAttribute('href')).toBe('/register?next=%2Fbank');
  });

  it('posts the credentials and shows the server error inline on failure', async () => {
    const fetchMock = mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({}),
      '/api/auth/login': () => json(401, { error: { code: 'invalid_credentials', message: '' } }),
    });
    renderLogin();
    const submit = await screen.findByRole('button', { name: zh.auth.login });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.identifier}`)), { target: { value: ' alice ' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password}`)), { target: { value: 'secret123' } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.invalidCredentials);
    const loginCall = fetchMock.mock.calls.find(([u]) => String(u) === '/api/auth/login');
    expect(loginCall?.[1]?.method).toBe('POST');
    expect(loginCall?.[1]?.body).toBe(JSON.stringify({ username: 'alice', password: 'secret123' }));
    expect((loginCall?.[1]?.headers as Record<string, string>)['X-WD-Request']).toBe('1');
    // no code entries while the server can send on no channel, a forgot-password link under the form, no demo (404)
    expect(screen.queryByRole('radiogroup', { name: zh.auth.loginMethod })).toBeNull();
    expect(screen.getByRole('link', { name: zh.auth.forgot }).getAttribute('href')).toBe('/forgot');
    expect(screen.queryByText(zh.auth.demoTitle)).toBeNull();
  });

  it('offers the phone entry first in verified mode with SMS on: consent gates the send, the send starts the countdown, the code signs in', async () => {
    let loginBody: Record<string, unknown> | null = null;
    const fetchMock = mockFetch({
      '/api/auth/me': () => (loginBody ? me() : unauthorized()),
      '/api/health': health({ registration_mode: 'verified', sms_enabled: true, email_enabled: true }),
      '/api/auth/code': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/code/login': (init) => {
        loginBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
        const res: CodeLoginResponse = { user, settings, created: true, challenge: null };
        return json(201, res);
      },
    });
    renderLogin('/login?next=%2Fbank');
    const entries = await screen.findByRole('radiogroup', { name: zh.auth.loginMethod });
    expect(within(entries).getAllByRole('radio').map((r) => r.textContent)).toEqual([zh.auth.methodPhone, zh.auth.methodEmail, zh.auth.methodPassword]);
    expect(within(entries).getByRole('radio', { name: zh.auth.methodPhone }).getAttribute('aria-checked')).toBe('true');
    expect(screen.queryByLabelText(new RegExp(`^${zh.auth.identifier}`))).toBeNull();

    fireEvent.change(phoneInput(), { target: { value: '138 0013 8000' } });
    expect(phoneInput().value).toBe('13800138000'); // digits only, +86 is the fixed prefix
    expect(sendButton().disabled).toBe(true); // consent first
    fireEvent.click(consentBox());
    expect(sendButton().disabled).toBe(false);
    fireEvent.click(sendButton());
    await waitFor(() => expect(bodyOf(fetchMock, '/api/auth/code')).toEqual({ channel: 'phone', target: '+8613800138000', purpose: 'login', consent: true }));
    expect(await screen.findByRole('button', { name: zh.auth.resendIn(60) })).toBeTruthy(); // countdown; the hint says 10 minutes
    expect(screen.getByText(zh.auth.codeHint)).toBeTruthy();

    const submit = screen.getByRole('button', { name: zh.auth.loginOrRegister }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(codeInput(), { target: { value: '12x3456' } });
    expect(codeInput().value).toBe('123456');
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    expect(await screen.findByText('bank-page')).toBeTruthy(); // the session is installed through applyAuth and the guard redirects to ?next
    expect(loginBody).toEqual({ channel: 'phone', target: '+8613800138000', code: '123456' });
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/auth/me')).toHaveLength(2); // bootstrap + after the sign-in
  });

  it('renders the captcha when the server asks for it and reloads it on request', async () => {
    let served = 0;
    mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({ registration_mode: 'verified', sms_enabled: true, captcha: true }),
      '/api/auth/captcha': () => {
        served += 1;
        return json(200, { id: `c${served}`, image: 'data:image/png;base64,AAAA', exp: 1_900_000_000, sig: 'sig', expires_in_s: 120 });
      },
    });
    renderLogin();
    const img = (await screen.findByAltText(zh.auth.captchaAlt)) as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('data:image/png;base64,AAAA');
    expect(screen.getByLabelText(new RegExp(`^${zh.auth.captcha}`))).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.auth.captchaRefresh }));
    await waitFor(() => expect(served).toBe(2));
  });

  it('a stale phone opens the challenge sheet: the password confirms (endpoint 83) and installs the session', async () => {
    let confirmed = false;
    const fetchMock = mockFetch({
      '/api/auth/me': () => (confirmed ? me() : unauthorized()),
      '/api/health': health({ registration_mode: 'verified', sms_enabled: true }),
      '/api/auth/code': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/code/login': () => {
        const res: CodeLoginResponse = { user: null, settings: null, created: false, challenge: { token: 'tok', display_name_masked: 'A**', since: '2025-03', can_password: true, can_email: true, email_masked: 'a***@qq.com' } };
        return json(200, res);
      },
      '/api/auth/challenge/confirm': () => {
        confirmed = true;
        return json(200, { user, settings });
      },
    });
    renderLogin();
    fireEvent.change(await screen.findByLabelText(new RegExp(`^${zh.auth.phone}`)), { target: { value: '13800138000' } });
    fireEvent.click(consentBox());
    fireEvent.click(sendButton());
    await screen.findByRole('button', { name: zh.auth.resendIn(60) });
    fireEvent.change(codeInput(), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.loginOrRegister }));
    const dialog = (await screen.findByRole('heading', { name: zh.auth.staleTitle })).closest('dialog') as HTMLDialogElement;
    expect(within(dialog).getByText(zh.auth.staleBody('A**', '2025-03'))).toBeTruthy();
    expect(within(dialog).getByRole('radio', { name: zh.auth.staleUsePassword }).getAttribute('aria-checked')).toBe('true'); // both factors → a choice, password first
    expect(document.querySelectorAll('form form')).toHaveLength(0); // the sheet's form is not nested in the sign-in form
    fireEvent.change(within(dialog).getByLabelText(new RegExp(`^${zh.auth.password}`)), { target: { value: 'secret123' } });
    fireEvent.click(within(dialog).getByRole('button', { name: zh.auth.staleYes }));
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(bodyOf(fetchMock, '/api/auth/challenge/confirm')).toEqual({ token: 'tok', password: 'secret123' });
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/auth/code/login')).toHaveLength(1); // the confirm never re-posted endpoint 81
  });

  it('a challenge without any factor shows the contact-admin text; the dispute goes through the confirmation to endpoint 84', async () => {
    let disputed = false;
    const fetchMock = mockFetch({
      '/api/auth/me': () => (disputed ? me() : unauthorized()),
      '/api/health': health({ registration_mode: 'verified', sms_enabled: true }),
      '/api/auth/code': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/code/login': () => {
        const res: CodeLoginResponse = { user: null, settings: null, created: false, challenge: { token: 'tok2', display_name_masked: 'B**', since: '2024-11', can_password: false, can_email: false, email_masked: null } };
        return json(200, res);
      },
      '/api/auth/challenge/dispute': () => {
        disputed = true;
        return json(201, { user, settings });
      },
    });
    renderLogin();
    fireEvent.change(await screen.findByLabelText(new RegExp(`^${zh.auth.phone}`)), { target: { value: '13800138000' } });
    fireEvent.click(consentBox());
    fireEvent.click(sendButton());
    await screen.findByRole('button', { name: zh.auth.resendIn(60) });
    fireEvent.change(codeInput(), { target: { value: '654321' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.loginOrRegister }));
    const dialog = (await screen.findByRole('heading', { name: zh.auth.staleTitle })).closest('dialog') as HTMLDialogElement;
    expect(within(dialog).getByText(zh.auth.staleContactAdmin)).toBeTruthy();
    expect(within(dialog).queryByRole('button', { name: zh.auth.staleYes })).toBeNull();
    expect(document.querySelectorAll('form form')).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole('button', { name: zh.auth.staleNo }));
    const confirm = await screen.findByRole('alertdialog');
    expect(within(confirm).getByText(zh.auth.staleDisputeConfirm)).toBeTruthy();
    fireEvent.click(within(confirm).getByRole('button', { name: zh.common.confirm }));
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(bodyOf(fetchMock, '/api/auth/challenge/dispute')).toEqual({ token: 'tok2' });
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/auth/code/login')).toHaveLength(1);
  });

  it('a challenge with only the e-mail factor sends the e-mail code (endpoint 82) and confirms with it (83); endpoint 81 is posted once', async () => {
    let confirmed = false;
    const fetchMock = mockFetch({
      '/api/auth/me': () => (confirmed ? me() : unauthorized()),
      '/api/health': health({ registration_mode: 'verified', sms_enabled: true }),
      '/api/auth/code': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/code/login': () => {
        const res: CodeLoginResponse = { user: null, settings: null, created: false, challenge: { token: 'tok3', display_name_masked: 'C**', since: '2025-01', can_password: false, can_email: true, email_masked: 'x***@example.com' } };
        return json(200, res);
      },
      '/api/auth/challenge/email': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/challenge/confirm': () => {
        confirmed = true;
        return json(200, { user, settings });
      },
    });
    renderLogin();
    fireEvent.change(await screen.findByLabelText(new RegExp(`^${zh.auth.phone}`)), { target: { value: '13800138000' } });
    fireEvent.click(consentBox());
    fireEvent.click(sendButton());
    await screen.findByRole('button', { name: zh.auth.resendIn(60) });
    fireEvent.change(codeInput(), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.loginOrRegister }));
    const dialog = (await screen.findByRole('heading', { name: zh.auth.staleTitle })).closest('dialog') as HTMLDialogElement;
    expect(within(dialog).queryByRole('radiogroup')).toBeNull(); // one factor → no choice
    expect(within(dialog).queryByLabelText(new RegExp(`^${zh.auth.password}`))).toBeNull();
    expect(within(dialog).getByText(zh.auth.staleEmailHint('x***@example.com'))).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: zh.auth.sendCode }));
    await waitFor(() => expect(bodyOf(fetchMock, '/api/auth/challenge/email')).toEqual({ token: 'tok3' }));
    expect(await within(dialog).findByRole('button', { name: zh.auth.resendIn(60) })).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(new RegExp(`^${zh.auth.code}`)), { target: { value: '246810' } });
    fireEvent.click(within(dialog).getByRole('button', { name: zh.auth.staleYes }));
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(bodyOf(fetchMock, '/api/auth/challenge/confirm')).toEqual({ token: 'tok3', code: '246810' });
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/auth/code/login')).toHaveLength(1);
  });

  it('invite mode: the e-mail entry requests the code without a captcha and signs in with the invite code (endpoints 80 / 81)', async () => {
    let signedIn = false;
    const fetchMock = mockFetch({
      '/api/auth/me': () => (signedIn ? me() : unauthorized()),
      '/api/health': health({ registration_mode: 'invite', sms_enabled: true, email_enabled: true }),
      '/api/auth/code': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/code/login': () => {
        signedIn = true;
        const res: CodeLoginResponse = { user, settings, created: true, challenge: null };
        return json(201, res);
      },
    });
    renderLogin();
    const entries = await screen.findByRole('radiogroup', { name: zh.auth.loginMethod });
    expect(within(entries).getByRole('radio', { name: zh.auth.methodPassword }).getAttribute('aria-checked')).toBe('true'); // not `verified` → the password entry first
    fireEvent.click(within(entries).getByRole('radio', { name: zh.auth.methodEmail }));
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.emailAddress}`)), { target: { value: 'Alice@Example.com' } });
    fireEvent.click(consentBox());
    fireEvent.click(sendButton());
    await waitFor(() => expect(bodyOf(fetchMock, '/api/auth/code')).toEqual({ channel: 'email', target: 'Alice@Example.com', purpose: 'login', consent: true }));
    expect(fetchMock.mock.calls.some(([u]) => String(u) === '/api/auth/captcha')).toBe(false); // health.captcha false → no captcha at all
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)), { target: { value: ' INV-2026 ' } });
    fireEvent.change(codeInput(), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.loginOrRegister }));
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(bodyOf(fetchMock, '/api/auth/code/login')).toEqual({ channel: 'email', target: 'Alice@Example.com', code: '123456', invite_code: 'INV-2026' });
  });

  it('with the captcha on, the code request carries the captcha token and a fresh captcha loads after the send', async () => {
    let served = 0;
    const fetchMock = mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({ registration_mode: 'verified', sms_enabled: true, captcha: true }),
      '/api/auth/captcha': () => {
        served += 1;
        return json(200, { id: `c${served}`, image: 'data:image/png;base64,AAAA', exp: 1_900_000_000, sig: `sig${served}`, expires_in_s: 120 });
      },
      '/api/auth/code': () => json(202, { sent: true, expires_in_s: 600 }),
    });
    renderLogin();
    await screen.findByAltText(zh.auth.captchaAlt);
    fireEvent.change(phoneInput(), { target: { value: '13800138000' } });
    fireEvent.click(consentBox());
    expect(sendButton().disabled).toBe(true); // the captcha digits are missing
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.captcha}`)), { target: { value: '1234' } });
    await waitFor(() => expect(sendButton().disabled).toBe(false));
    fireEvent.click(sendButton());
    await waitFor(() => expect(bodyOf(fetchMock, '/api/auth/code')).toEqual({ channel: 'phone', target: '+8613800138000', purpose: 'login', consent: true, captcha: { id: 'c1', exp: 1_900_000_000, sig: 'sig1', answer: '1234' } }));
    await waitFor(() => expect(served).toBe(2)); // a token is accepted once: a new image after the send
    expect((screen.getByLabelText(new RegExp(`^${zh.auth.captcha}`)) as HTMLInputElement).value).toBe('');
    expect(await screen.findByRole('button', { name: zh.auth.resendIn(60) })).toBeTruthy();
  });

  it('a 429 on the code request names the wait and counts the send button down for the server window; nothing was sent', async () => {
    mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({ registration_mode: 'verified', sms_enabled: true }),
      '/api/auth/code': () => json(429, { error: { code: 'rate_limited', message: '', details: { retry_after_s: 45 } } }),
    });
    renderLogin();
    fireEvent.change(await screen.findByLabelText(new RegExp(`^${zh.auth.phone}`)), { target: { value: '13800138000' } });
    fireEvent.click(consentBox());
    fireEvent.click(sendButton());
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.rateLimitedIn(45));
    const waiting = (await screen.findByRole('button', { name: zh.auth.resendIn(45) })) as HTMLButtonElement;
    expect(waiting.disabled).toBe(true);
    expect(screen.queryByText(zh.auth.codeHint)).toBeNull(); // no code went out
    fireEvent.change(codeInput(), { target: { value: '123456' } });
    expect((screen.getByRole('button', { name: zh.auth.loginOrRegister }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the password-reset notice after /forgot (?reset=1)', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({}) });
    renderLogin('/login?reset=1');
    expect(await screen.findByText(zh.auth.resetDone)).toBeTruthy();
    expect(screen.getByRole('status')).toHaveProperty('textContent', zh.auth.resetDone);
  });

  it('renders the read-only demo when /api/demo answers with items and switches words with the dots', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({}), '/api/demo': () => json(200, demo) });
    renderLogin();
    expect(await screen.findByText(zh.auth.demoTitle)).toBeTruthy();
    const headword = () => document.querySelector('.login-demo .word-head__display')?.textContent;
    expect(headword()).toBe('up');
    expect(screen.getByText('meaning-up')).toBeTruthy();
    expect(screen.getByText('zh-example-up')).toBeTruthy(); // the first example only, translation shown
    expect(screen.queryByText('second')).toBeNull();
    expect((screen.getByAltText('') as HTMLImageElement).getAttribute('src')).toBe('/media/demo/1.svg');
    fireEvent.click(screen.getByRole('button', { name: zh.auth.demoItem(2) }));
    expect(headword()).toBe('jump');
    expect(screen.getByText('zh-jump')).toBeTruthy(); // no content → the short translation
  });

  it('slice 2-A: no third-party row on a dark server, none while needs_setup; with the flags on, QQ / Apple link to 118 / 120 with ?next and WeChat opens the ticket sheet', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({}) });
    const dark = renderLogin();
    await screen.findByRole('button', { name: zh.auth.login });
    expect(screen.queryByRole('group', { name: zh.auth.thirdParty })).toBeNull();
    dark.unmount();
    vi.unstubAllGlobals();

    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ needs_setup: true, wechat_enabled: true, qq_enabled: true, apple_enabled: true }) });
    const setup = renderLogin();
    await screen.findByText(zh.auth.needsSetup, { exact: false });
    expect(screen.queryByRole('group', { name: zh.auth.thirdParty })).toBeNull(); // the first admin signs up with a password
    setup.unmount();
    vi.unstubAllGlobals();

    const fetchMock = mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'open', wechat_enabled: true, qq_enabled: true, apple_enabled: true }), '/api/auth/wechat/ticket': wechatTicket });
    renderLogin('/login?next=%2Fbank');
    const row = await screen.findByRole('group', { name: zh.auth.thirdParty });
    expect(within(row).getByRole('link', { name: zh.auth.qq }).getAttribute('href')).toBe('/api/auth/qq/start?kind=login&next=%2Fbank');
    expect(within(row).getByRole('link', { name: zh.auth.apple }).getAttribute('href')).toBe('/api/auth/apple/start?kind=login&next=%2Fbank');
    fireEvent.click(within(row).getByRole('button', { name: zh.auth.wechat }));
    const sheet = (await screen.findByRole('heading', { name: zh.auth.wechatTitle })).closest('dialog') as HTMLDialogElement;
    expect((await within(sheet).findByAltText(zh.auth.wechatQrAlt)).getAttribute('src')).toBe(`/api/auth/wechat/ticket/${WX_TICKET}/qr`);
    expect(within(sheet).getByText(zh.auth.wechatPairHint)).toBeTruthy();
    expect(bodyOf(fetchMock, '/api/auth/wechat/ticket')).toEqual({ kind: 'login' });
    expect(screen.queryByRole('alert')).toBeNull(); // no ?error= → no notice
  });

  it('slice 2-A: in invite mode the WeChat sheet asks for the invite code before the ticket', async () => {
    const fetchMock = mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'invite', wechat_enabled: true }), '/api/auth/wechat/ticket': wechatTicket });
    renderLogin();
    fireEvent.click(await screen.findByRole('button', { name: zh.auth.wechat }));
    const sheet = (await screen.findByRole('heading', { name: zh.auth.wechatTitle })).closest('dialog') as HTMLDialogElement;
    expect(bodyOf(fetchMock, '/api/auth/wechat/ticket')).toBeNull();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)), { target: { value: 'INV-2026' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.auth.showQr }));
    await within(sheet).findByAltText(zh.auth.wechatQrAlt);
    expect(bodyOf(fetchMock, '/api/auth/wechat/ticket')).toEqual({ kind: 'login', invite_code: 'INV-2026' });
  });

  it('slice 2-A: ?error=<code> from a failed QQ / Apple redirect (119 / 121 / 122) shows the mapped notice once and leaves the URL (?next kept)', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({}) });
    renderLogin('/login?error=invalid_grant&next=%2Fbank');
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.invalidGrant);
    expect(screen.queryByText('invalid_grant')).toBeNull(); // never the raw code
    await waitFor(() => expect(screen.getByTestId('search').textContent).toBe('?next=%2Fbank')); // replaced: a reload or a back navigation will not repeat it
    expect(screen.getByRole('alert').textContent).toBe(zh.errors.invalidGrant); // the notice stays while the page is open
    expect(screen.getByRole('link', { name: zh.auth.register }).getAttribute('href')).toBe('/register?next=%2Fbank'); // ?next survived the cleanup
  });

  it('slice 2-A: in invite mode QQ / Apple open the invite step instead of navigating at once; the continue link carries the code, the skip link does not', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'invite', qq_enabled: true, apple_enabled: true }) });
    renderLogin('/login?next=%2Fbank');
    const row = await screen.findByRole('group', { name: zh.auth.thirdParty });
    expect(within(row).queryByRole('link', { name: zh.auth.qq })).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: zh.auth.qq }));
    const sheet = (await screen.findByRole('heading', { name: zh.auth.qqTitle })).closest('dialog') as HTMLDialogElement;
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)), { target: { value: ' INV-2026 ' } });
    expect(within(sheet).getByRole('link', { name: zh.auth.inviteContinue }).getAttribute('href')).toBe('/api/auth/qq/start?kind=login&invite_code=INV-2026&next=%2Fbank');
    expect(within(sheet).getByRole('link', { name: zh.auth.skipInvite }).getAttribute('href')).toBe('/api/auth/qq/start?kind=login&next=%2Fbank');
  });

  it(
    'slice 2-A: a confirmed WeChat ticket installs the session through applyAuth and the guest guard redirects to ?next',
    async () => {
      let confirmed = false;
      const fetchMock = mockFetch({
        '/api/auth/me': () => (confirmed ? me() : unauthorized()),
        '/api/health': health({ registration_mode: 'verified', wechat_enabled: true }),
        '/api/auth/wechat/ticket': wechatTicket,
        [`/api/auth/wechat/ticket/${WX_TICKET}`]: () => {
          confirmed = true; // the session cookie came with this poll
          return json(201, { status: 'confirmed', user, settings, created: true });
        },
      });
      renderLogin('/login?next=%2Fbank');
      fireEvent.click(await screen.findByRole('button', { name: zh.auth.wechat }));
      await screen.findByAltText(zh.auth.wechatQrAlt);
      expect(await screen.findByText('bank-page', {}, { timeout: 4000 })).toBeTruthy(); // the first poll comes after WECHAT_POLL_MS (2 s)
      expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/auth/me')).toHaveLength(2); // bootstrap + applyAuth
    },
    8000,
  );
});
