// endpoints.ts covers the whole API.md §2 catalogue and uses its methods/paths.
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as endpoints from './endpoints';
import source from './endpoints.ts?raw';

describe('endpoints.ts', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('declares a numbered wrapper for every catalogue entry 1–122 exactly once (76 GET /media/audio has none; 52 / 53 / 78 are URL builders; 114 is an <img src>, 118–122 are navigation links)', () => {
    const numbers = [...source.matchAll(/^\/\/ #(\d+) (GET|POST|PUT|PATCH|DELETE) (\/\S+)/gm)].map((m) => Number(m[1]));
    const withoutWrapper = new Set([76, 114, 118, 119, 120, 121, 122]);
    const expected = Array.from({ length: 122 }, (_, i) => i + 1).filter((n) => !withoutWrapper.has(n));
    expect([...numbers].sort((a, b) => a - b)).toEqual(expected);
    expect(new Set(numbers).size).toBe(numbers.length);
    // the wrapper-less entries stay visible under `// #N —` comments so the numbering has no gaps
    for (const n of [114, 118, 119, 120, 121, 122]) expect(source).toMatch(new RegExp(`^// #${n} — (GET|POST) /`, 'm'));
  });

  it('uses the catalogue methods and paths', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', fetchMock);

    await endpoints.getHealth();
    await endpoints.getVocab({ stage: 'cet6', new_only: true, page: 2 });
    await endpoints.lookup('abandonned');
    await endpoints.getWord('ice cream');
    await endpoints.markWord(12, { action: 'restore', context: 'browse' });
    await endpoints.batchMark({ items: [{ word_id: 1, action: 'known' }] });
    await endpoints.getScreenNext('auto');
    await endpoints.patchBankEntry(7, { attention: 'retry' });
    await endpoints.acceptBankSuggestion(7);
    await endpoints.gradeItem(99, { client_event_id: 'uuid', grade: 'good' });
    await endpoints.getBatch(5);
    await endpoints.deleteAccount({ password: 'pw' });
    await endpoints.adminUpdateUser(3, { role: 'admin' });
    await endpoints.adminAiPause(true);
    await endpoints.adminAiProbe();
    await endpoints.adminAiProbe('fallback');
    await endpoints.importBank({ format: 'csv', data: 'word\nabandon' });
    await endpoints.sendCode({ channel: 'phone', target: '+8613800138000', purpose: 'login', consent: true });
    await endpoints.loginWithCode({ channel: 'phone', target: '+8613800138000', code: '123456' });
    await endpoints.requestAccountCode({ channel: 'phone', purpose: 'reauth' });
    await endpoints.unbindPhone({ code: '123456' });
    await endpoints.saveProfile({ display_name: 'Alice', age_band: 'adult' });
    await endpoints.forgotPassword({ identifier: 'alice' });
    await endpoints.adminDisputedIdentities(2);
    await endpoints.adminRestoreIdentity(9);
    // guardian and child accounts (slice 1-B, API.md §3.2)
    await endpoints.getChildren();
    await endpoints.createChild({ display_name: 'Tao', pin: '274913' });
    await endpoints.updateChild(4, { display_name: 'Tao Tao' });
    await endpoints.deleteChild(4);
    await endpoints.revokeChildSessions(4);
    await endpoints.issueChildLoginCode(4);
    await endpoints.requestChildPhoneCode(4, { target: '+8613900139000' });
    await endpoints.emancipateChild(4, { target: '+8613900139000', code: '123456', password: 'Str0ng-Passphrase!' });
    await endpoints.passGate({ pin: '274913' });
    await endpoints.setGuardianPin({ pin: '274913' });
    await endpoints.switchToChild(4);
    await endpoints.switchBack({ code: '123456' });
    await endpoints.requestSwitchCode({ channel: 'phone' });
    await endpoints.childLogin({ code: '12345678' });
    await endpoints.requestGuardianClaimCode({ target: '+8613800138000' });
    await endpoints.claimGuardian({ target: '+8613800138000', code: '123456', age_band: 'u14' });
    await endpoints.declareAccount({ account_kind: 'guardian', age_band: 'adult' });
    await endpoints.skipDeclare();
    await endpoints.deleteAccount({ code: '123456', delete_children: true });
    // third-party sign-in (slice 2-A, API.md §3.3)
    await endpoints.createWechatTicket({ kind: 'login', invite_code: 'INV-2026' });
    await endpoints.pollWechatTicket('abcdefghijklmnopqrstuvwxyz');
    await endpoints.unbindIdentity('wechat_mini', { password: 'pw' });
    await endpoints.scanWechatTicket({ js_code: 'js-code', pairing_code: '123456' }); // the mini program's calls (115 / 116), documented here, never made by the SPA
    await endpoints.confirmWechatTicket({ mp_token: 'tok', ticket: 'abcdefghijklmnopqrstuvwxyz', accept: true });

    const probeBodies = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/admin/ai/probe')).map(([, init]) => init?.body);
    expect(probeBodies).toEqual([JSON.stringify({ provider: 'claude' }), JSON.stringify({ provider: 'fallback' })]);
    const calls = fetchMock.mock.calls.map(([url, init]) => `${init?.method} ${String(url)}`);
    expect(calls).toEqual([
      'GET /api/health',
      'GET /api/vocab?stage=cet6&new_only=1&page=2',
      'GET /api/lookup?q=abandonned',
      'GET /api/words/ice%20cream',
      'POST /api/words/12/mark',
      'POST /api/words/batch-mark',
      'GET /api/screen/next?stage=auto&count=30',
      'PATCH /api/bank/7',
      'POST /api/bank/7/accept-suggestion',
      'POST /api/today/items/99/grade',
      'GET /api/batches/5',
      'DELETE /api/account',
      'POST /api/admin/users/3',
      'POST /api/admin/ai/pause',
      'POST /api/admin/ai/probe',
      'POST /api/admin/ai/probe',
      'POST /api/bank/import',
      'POST /api/auth/code',
      'POST /api/auth/code/login',
      'POST /api/account/code',
      'DELETE /api/account/identities/phone',
      'POST /api/account/profile',
      'POST /api/auth/password/forgot',
      'GET /api/admin/identities/disputed?page=2',
      'POST /api/admin/identities/9/restore',
      'GET /api/guardian/children',
      'POST /api/guardian/children',
      'PATCH /api/guardian/children/4',
      'DELETE /api/guardian/children/4',
      'POST /api/guardian/children/4/sessions/revoke',
      'POST /api/guardian/children/4/login-code',
      'POST /api/guardian/children/4/code',
      'POST /api/guardian/children/4/emancipate',
      'POST /api/guardian/gate',
      'PUT /api/guardian/pin',
      'POST /api/auth/switch/4',
      'POST /api/auth/switch/back',
      'POST /api/auth/switch/code',
      'POST /api/auth/child-login',
      'POST /api/account/guardian/code',
      'POST /api/account/guardian',
      'POST /api/account/declare',
      'POST /api/account/declare/skip',
      'DELETE /api/account',
      'POST /api/auth/wechat/ticket',
      'GET /api/auth/wechat/ticket/abcdefghijklmnopqrstuvwxyz',
      'DELETE /api/account/identities/wechat_mini',
      'POST /api/auth/wechat/scan',
      'POST /api/auth/wechat/confirm',
    ]);
    expect(fetchMock.mock.calls[13]?.[1]?.body).toBe(JSON.stringify({ paused: true }));
    expect(fetchMock.mock.calls[11]?.[1]?.body).toBe(JSON.stringify({ password: 'pw' }));
    expect(fetchMock.mock.calls[20]?.[1]?.body).toBe(JSON.stringify({ code: '123456' }));
    expect(fetchMock.mock.calls[35]?.[1]?.body).toBeUndefined(); // #104 has no body
    expect(fetchMock.mock.calls[36]?.[1]?.body).toBe(JSON.stringify({ code: '123456' })); // #105 carries the gate factor
    expect(fetchMock.mock.calls[43]?.[1]?.body).toBe(JSON.stringify({ code: '123456', delete_children: true })); // #8 with delete_children
    expect(fetchMock.mock.calls[44]?.[1]?.body).toBe(JSON.stringify({ kind: 'login', invite_code: 'INV-2026' })); // #112
    expect(fetchMock.mock.calls[45]?.[1]?.credentials).toBe('same-origin'); // #113 rides on the wd_wxt cookie like every call
    expect(fetchMock.mock.calls[46]?.[1]?.body).toBe(JSON.stringify({ password: 'pw' })); // #117 the endpoint-87 one-of
  });

  it('builds media and export URLs', () => {
    expect(endpoints.cardUrl(123)).toBe('/media/card/123.svg');
    expect(endpoints.demoCardUrl(5)).toBe('/media/demo/5.svg');
    expect(endpoints.mediaImageUrl('ab/ab12.jpg')).toBe('/media/images/ab/ab12.jpg');
    expect(endpoints.exportAccountUrl('json')).toBe('/api/account/export?format=json');
  });

  it('builds the redirect-flow links of endpoints 118 / 120 (plain <a href>, the result comes back through 119 / 121 → 122)', () => {
    expect(endpoints.oauthStartUrl('qq', 'login')).toBe('/api/auth/qq/start?kind=login');
    expect(endpoints.oauthStartUrl('qq', 'login', '/bank')).toBe('/api/auth/qq/start?kind=login&next=%2Fbank');
    expect(endpoints.oauthStartUrl('apple', 'bind', '/settings')).toBe('/api/auth/apple/start?kind=bind&next=%2Fsettings');
    expect(endpoints.oauthStartUrl('apple', 'login', null)).toBe('/api/auth/apple/start?kind=login'); // an empty next is omitted
    expect(endpoints.oauthStartUrl('qq', 'login', '/bank', ' INV-2026 ')).toBe('/api/auth/qq/start?kind=login&invite_code=INV-2026&next=%2Fbank'); // invite mode: the trimmed code
    expect(endpoints.oauthStartUrl('qq', 'login', null, '  ')).toBe('/api/auth/qq/start?kind=login'); // a blank code is omitted (an existing binding needs none)
  });

  it('importPayloadFromJsonExport keeps {version, words} and drops review_logs', () => {
    const text = JSON.stringify({
      version: 1,
      exported_at: '2026-10-14T00:00:00Z',
      username: 'alice',
      words: [{ word: 'abandon', state: 'learning' }],
      review_logs: [{ created_at: 'x', word: 'abandon', action: 'good' }],
    });
    const payload = endpoints.importPayloadFromJsonExport(text);
    expect(payload).not.toBeNull();
    expect(JSON.parse(payload!)).toEqual({ version: 1, words: [{ word: 'abandon', state: 'learning' }] });
    expect(endpoints.importPayloadFromJsonExport('not json')).toBeNull();
    expect(endpoints.importPayloadFromJsonExport('{"words": 1}')).toBeNull();
    expect(endpoints.importPayloadFromJsonExport('[]')).toBeNull();
  });
});
