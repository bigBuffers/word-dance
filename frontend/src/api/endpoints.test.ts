// endpoints.ts covers the whole API.md §2 catalogue and uses its methods/paths.
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as endpoints from './endpoints';
import source from './endpoints.ts?raw';

describe('endpoints.ts', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('declares a numbered wrapper for every catalogue entry 1–93 exactly once (76 GET /media/audio has none; 52 / 53 / 78 are URL builders)', () => {
    const numbers = [...source.matchAll(/^\/\/ #(\d+) (GET|POST|PUT|PATCH|DELETE) (\/\S+)/gm)].map((m) => Number(m[1]));
    const expected = Array.from({ length: 93 }, (_, i) => i + 1).filter((n) => n !== 76);
    expect([...numbers].sort((a, b) => a - b)).toEqual(expected);
    expect(new Set(numbers).size).toBe(numbers.length);
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
    ]);
    expect(fetchMock.mock.calls[13]?.[1]?.body).toBe(JSON.stringify({ paused: true }));
    expect(fetchMock.mock.calls[11]?.[1]?.body).toBe(JSON.stringify({ password: 'pw' }));
    expect(fetchMock.mock.calls[20]?.[1]?.body).toBe(JSON.stringify({ code: '123456' }));
  });

  it('builds media and export URLs', () => {
    expect(endpoints.cardUrl(123)).toBe('/media/card/123.svg');
    expect(endpoints.demoCardUrl(5)).toBe('/media/demo/5.svg');
    expect(endpoints.mediaImageUrl('ab/ab12.jpg')).toBe('/media/images/ab/ab12.jpg');
    expect(endpoints.exportAccountUrl('json')).toBe('/api/account/export?format=json');
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
