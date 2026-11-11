// WechatSignIn (FRONTEND §4, API.md 112–114): a ticket → the mini-program code image + the grouped pairing code; the poll of
// endpoint 113 runs pending → scanned → confirmed and hands the account, `created` and the settings to onDone, then stops; a broken
// image leaves the pairing code alone; expired / 404 / cancelled end the ticket with a refresh button that creates a new one; a 429
// slows the poll instead of stopping it, any other 4xx ends the ticket with the mapped error, 5xx blips are tolerated up to
// WECHAT_POLL_MAX_TRANSIENT in a row; StrictMode's doubled mount effect still creates one ticket; in `invite` mode the login
// variant asks for the (optional) invite code first.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Settings, User, WechatTicket, WechatTicketStatus } from '@/api/types';
import { zh } from '@/i18n/zh';
import { groupPairingCode, WECHAT_POLL_MAX_TRANSIENT, WechatSignIn } from './WechatSignIn';

const ISO = '2026-11-11T00:00:00Z';
const TICKET = 'abcdefghijklmnopqrstuvwxyz';
const TICKET_2 = 'zyxwvutsrqponmlkjihgfedcba';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const user: User = { id: 7, username: 'u_ab23cd45', display_name: '', email: null, email_verified: false, role: 'user', onboarding_state: 'pending', created_at: ISO, has_password: false, phone_masked: null, needs_profile: true, age_band: null, account_kind: 'learner', is_child: false, needs_profile_prompt: false, providers: ['wechat_mini'] };
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: true, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: false, updated_at: ISO,
};
const ticket = (id = TICKET, code = '123456'): WechatTicket => ({ ticket: id, pairing_code: code, expires_in_s: 180, qr_url: `/api/auth/wechat/ticket/${id}/qr` });
const status = (over: Partial<WechatTicketStatus> = {}): WechatTicketStatus => ({ status: 'pending', user: null, settings: null, created: null, ...over });
const intervals = { poll: 20, slow: 40 }; // the test seam: 2 s / 5 s in production

type Handler = (init?: RequestInit) => Response;
/** Routes by path; `polls` answers the ticket poll in order (the last answer repeats). */
function mockFetch(routes: Record<string, Handler>, polls: (() => Response)[] = []) {
  let pollIndex = 0;
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const path = url.split('?')[0] ?? url;
    if (/^\/api\/auth\/wechat\/ticket\/[a-z2-7]{26}$/.test(path)) {
      const answer = polls[Math.min(pollIndex, polls.length - 1)];
      pollIndex += 1;
      return Promise.resolve(answer ? answer() : json(200, status()));
    }
    const handler = routes[path];
    return Promise.resolve(handler ? handler(init) : json(404, { error: { code: 'not_found', message: '' } }));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}
const ticketRoute = (ids: string[] = [TICKET]) => {
  let n = 0;
  return () => json(201, ticket(ids[Math.min(n++, ids.length - 1)]));
};
const pollCalls = (fetchMock: ReturnType<typeof mockFetch>) => fetchMock.mock.calls.filter(([u]) => /\/api\/auth\/wechat\/ticket\/[a-z2-7]{26}$/.test(String(u))).length;
const ticketCalls = (fetchMock: ReturnType<typeof mockFetch>) => fetchMock.mock.calls.filter(([u]) => String(u) === '/api/auth/wechat/ticket');
const settle = (ms: number) => new Promise((r) => setTimeout(r, ms));
const qrImage = () => screen.getByAltText(zh.auth.wechatQrAlt) as HTMLImageElement;
/** The grouped digits of the pairing block (null while no live ticket is shown). */
const pairingCode = () => document.querySelector('.wechat-signin__code strong')?.textContent ?? null;

describe('WechatSignIn', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('creates a login ticket, shows the code image and the grouped pairing code, polls pending → scanned → confirmed and stops after onDone', async () => {
    const onDone = vi.fn();
    const fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() }, [() => json(200, status()), () => json(200, status({ status: 'scanned' })), () => json(201, status({ status: 'confirmed', user, settings, created: true }))]);
    render(<WechatSignIn kind="login" onDone={onDone} intervals={intervals} />);
    expect(screen.getByRole('status').textContent).toBe(zh.common.loading); // the ticket request is in flight
    await screen.findByAltText(zh.auth.wechatQrAlt);
    expect(qrImage().getAttribute('src')).toBe(`/api/auth/wechat/ticket/${TICKET}/qr`);
    expect(JSON.parse(String(ticketCalls(fetchMock)[0]?.[1]?.body))).toEqual({ kind: 'login' });
    expect(pairingCode()).toBe('123 456');
    expect(screen.getByText(zh.auth.wechatScanHint)).toBeTruthy();
    expect(screen.getByText(zh.auth.wechatPairHint)).toBeTruthy();
    expect(await screen.findByText(zh.auth.scanned)).toBeTruthy(); // the second poll
    expect(screen.getByRole('status').textContent).toBe(zh.auth.scanned);
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(user, true, settings));
    expect(onDone).toHaveBeenCalledTimes(1);
    const polled = pollCalls(fetchMock);
    expect(polled).toBe(3);
    await settle(intervals.poll * 4);
    expect(pollCalls(fetchMock)).toBe(polled); // polling stopped with the confirmation
    expect(screen.queryByRole('button', { name: zh.auth.refresh })).toBeNull();
  });

  it('a bind ticket posts kind=bind and hands the bound account to onDone (created false, no settings)', async () => {
    const onDone = vi.fn();
    const fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() }, [() => json(200, status({ status: 'confirmed', user, settings: null, created: false }))]);
    render(<WechatSignIn kind="bind" registrationMode="invite" onDone={onDone} intervals={intervals} />);
    expect(screen.queryByLabelText(new RegExp(`^${zh.auth.inviteForNew}`))).toBeNull(); // the invite step is the login variant's only
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(user, false, null));
    expect(JSON.parse(String(ticketCalls(fetchMock)[0]?.[1]?.body))).toEqual({ kind: 'bind' });
  });

  it('a broken code image hides the picture and its hint, the pairing code block stays', async () => {
    mockFetch({ '/api/auth/wechat/ticket': ticketRoute() });
    render(<WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />);
    fireEvent.error(await screen.findByAltText(zh.auth.wechatQrAlt));
    expect(screen.queryByAltText(zh.auth.wechatQrAlt)).toBeNull();
    expect(screen.queryByText(zh.auth.wechatScanHint)).toBeNull();
    expect(pairingCode()).toBe('123 456');
    expect(screen.getByText(zh.auth.wechatPairHint)).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.auth.copyPairing })).toBeTruthy();
  });

  it('an expired ticket ends with the refresh button, which creates a new ticket; a 404 from the poll counts as expired too', async () => {
    const fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute([TICKET, TICKET_2]) }, [() => json(200, status({ status: 'expired' })), () => json(404, { error: { code: 'not_found', message: '' } })]);
    render(<WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />);
    expect(await screen.findByText(zh.auth.qrExpired)).toBeTruthy();
    expect(screen.queryByAltText(zh.auth.wechatQrAlt)).toBeNull(); // a dead ticket shows neither code nor digits
    expect(pairingCode()).toBeNull();
    const polledAtExpiry = pollCalls(fetchMock);
    await settle(intervals.poll * 3);
    expect(pollCalls(fetchMock)).toBe(polledAtExpiry); // no polling of a dead ticket
    fireEvent.click(screen.getByRole('button', { name: zh.auth.refresh }));
    await waitFor(() => expect(ticketCalls(fetchMock)).toHaveLength(2));
    expect((await screen.findByAltText(zh.auth.wechatQrAlt)).getAttribute('src')).toBe(`/api/auth/wechat/ticket/${TICKET_2}/qr`);
    expect(await screen.findByText(zh.auth.qrExpired)).toBeTruthy(); // the 404
    expect(screen.getByRole('button', { name: zh.auth.refresh })).toBeTruthy();
  });

  it('a cancelled ticket says so and offers the refresh button', async () => {
    mockFetch({ '/api/auth/wechat/ticket': ticketRoute() }, [() => json(200, status({ status: 'cancelled' }))]);
    render(<WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />);
    expect(await screen.findByText(zh.auth.cancelledInWechat)).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.auth.refresh })).toBeTruthy();
  });

  it('a 429 on the poll slows down instead of stopping: the confirmation still arrives', async () => {
    const onDone = vi.fn();
    const fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() }, [
      () => json(429, { error: { code: 'rate_limited', message: '', details: { retry_after_s: 5 } } }),
      () => json(200, status()),
      () => json(201, status({ status: 'confirmed', user, settings, created: false })),
    ]);
    render(<WechatSignIn kind="login" onDone={onDone} intervals={intervals} />);
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(user, false, settings));
    expect(pollCalls(fetchMock)).toBe(3);
  });

  it('a 403 / 409 on the poll ends the ticket: polling stops, the mapped error shows with the refresh button (403 account_disabled after a confirmation)', async () => {
    const fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() }, [() => json(403, { error: { code: 'account_disabled', message: '' } })]);
    render(<WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />);
    expect(await screen.findByText(zh.errors.forbidden)).toBeTruthy(); // errorMessage(account_disabled)
    expect(screen.getByRole('button', { name: zh.auth.refresh })).toBeTruthy();
    expect(pairingCode()).toBeNull(); // a dead ticket shows neither code nor digits
    expect(pollCalls(fetchMock)).toBe(1);
    await settle(intervals.poll * 4);
    expect(pollCalls(fetchMock)).toBe(1); // no more polling of a refused ticket
  });

  it('a 5xx blip keeps polling and the confirmation still arrives; WECHAT_POLL_MAX_TRANSIENT of them in a row give the ticket up', async () => {
    const onDone = vi.fn();
    const hiccup = () => json(502, { error: { code: 'internal_error', message: '' } });
    let fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() }, [hiccup, hiccup, () => json(201, status({ status: 'confirmed', user, settings, created: false }))]);
    const first = render(<WechatSignIn kind="login" onDone={onDone} intervals={intervals} />);
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(user, false, settings));
    expect(pollCalls(fetchMock)).toBe(3);
    first.unmount();
    vi.unstubAllGlobals();

    fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() }, [hiccup]);
    render(<WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />);
    expect(await screen.findByText(zh.errors.server, {}, { timeout: 3000 })).toBeTruthy();
    expect(pollCalls(fetchMock)).toBe(WECHAT_POLL_MAX_TRANSIENT);
    expect(screen.getByRole('button', { name: zh.auth.refresh })).toBeTruthy();
    await settle(intervals.poll * 3);
    expect(pollCalls(fetchMock)).toBe(WECHAT_POLL_MAX_TRANSIENT); // given up
  });

  it('creates exactly one ticket under React StrictMode (the mount effect runs twice in development; the poll cookie is one per browser)', async () => {
    const fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() });
    render(
      <StrictMode>
        <WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />
      </StrictMode>,
    );
    await screen.findByAltText(zh.auth.wechatQrAlt);
    await settle(intervals.poll * 2);
    expect(ticketCalls(fetchMock)).toHaveLength(1);
  });

  it('a failed ticket request shows the mapped error with the refresh button (a dark server answers 409 provider_unconfigured)', async () => {
    mockFetch({ '/api/auth/wechat/ticket': () => json(409, { error: { code: 'provider_unconfigured', message: '' } }) });
    render(<WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />);
    expect(await screen.findByText(zh.errors.providerUnconfigured)).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.auth.refresh })).toBeTruthy();
    expect(pairingCode()).toBeNull();
  });

  it('invite mode asks for the invite code first and sends it with the ticket; a refused code returns to the field', async () => {
    let attempts = 0;
    const fetchMock = mockFetch({
      '/api/auth/wechat/ticket': () => {
        attempts += 1;
        return attempts === 1 ? json(403, { error: { code: 'invalid_invite', message: '' } }) : json(201, ticket());
      },
    });
    render(<WechatSignIn kind="login" registrationMode="invite" onDone={() => undefined} intervals={intervals} />);
    expect(ticketCalls(fetchMock)).toHaveLength(0); // nothing until the form is sent
    const field = screen.getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)) as HTMLInputElement;
    fireEvent.change(field, { target: { value: ' bad-code ' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.showQr }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.invalidInvite);
    expect(JSON.parse(String(ticketCalls(fetchMock)[0]?.[1]?.body))).toEqual({ kind: 'login', invite_code: 'bad-code' });
    expect((screen.getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)) as HTMLInputElement).value).toBe(' bad-code '); // the field is kept for a correction
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.inviteForNew}`)), { target: { value: 'INV-2026' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.showQr }));
    expect(await screen.findByAltText(zh.auth.wechatQrAlt)).toBeTruthy();
    expect(JSON.parse(String(ticketCalls(fetchMock)[1]?.[1]?.body))).toEqual({ kind: 'login', invite_code: 'INV-2026' });
  });

  it('invite mode without a code (an existing binding) posts the plain login ticket', async () => {
    const fetchMock = mockFetch({ '/api/auth/wechat/ticket': ticketRoute() });
    render(<WechatSignIn kind="login" registrationMode="invite" onDone={() => undefined} intervals={intervals} />);
    fireEvent.click(screen.getByRole('button', { name: zh.auth.showQr }));
    await screen.findByAltText(zh.auth.wechatQrAlt);
    expect(JSON.parse(String(ticketCalls(fetchMock)[0]?.[1]?.body))).toEqual({ kind: 'login' });
  });

  it('the copy button writes the six digits to the clipboard and confirms briefly', async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    mockFetch({ '/api/auth/wechat/ticket': ticketRoute() });
    render(<WechatSignIn kind="login" onDone={() => undefined} intervals={intervals} />);
    fireEvent.click(await screen.findByRole('button', { name: zh.auth.copyPairing }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('123456')); // the digits, not the display grouping
    expect(await screen.findByRole('button', { name: zh.auth.copied })).toBeTruthy();
  });

  it('groups the six digits in two threes', () => {
    expect(groupPairingCode('123456')).toBe('123 456');
    expect(groupPairingCode('12345')).toBe('12345');
  });
});
