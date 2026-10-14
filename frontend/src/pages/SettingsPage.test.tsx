// Import reduction (API.md 11/75) and the stage toggle used by the settings page.
import { describe, expect, it } from 'vitest';
import { buildImportBody, toggleStageSetting } from './SettingsPage';

const fakeFile = (name: string, text: string) => ({ name, text: () => Promise.resolve(text) });

describe('buildImportBody', () => {
  it('drops review_logs from a JSON export and keeps only {version, words}', async () => {
    const exportJson = JSON.stringify({
      version: 1,
      exported_at: '2026-10-14T00:00:00Z',
      username: 'alice',
      words: [{ word: 'abandon', state: 'learning', ease: 2.5 }],
      review_logs: Array.from({ length: 5000 }, (_, i) => ({ created_at: '2026-10-14T00:00:00Z', word: `w${i}`, action: 'good' })),
    });
    const body = await buildImportBody(fakeFile('word-dance-export-20261014.json', exportJson));
    expect(body?.format).toBe('json');
    expect(body?.data).toBe(JSON.stringify({ version: 1, words: [{ word: 'abandon', state: 'learning', ease: 2.5 }] }));
    expect(body!.data.length).toBeLessThan(exportJson.length / 10);
  });

  it('sniffs JSON without an extension, returns null for an unparsable or non-export file, and posts CSV verbatim', async () => {
    expect((await buildImportBody(fakeFile('export', '{"version":1,"words":[]}')))?.format).toBe('json');
    expect(await buildImportBody(fakeFile('x.json', '{not json'))).toBeNull();
    expect(await buildImportBody(fakeFile('x.json', JSON.stringify({ foo: 1 })))).toBeNull();
    expect(await buildImportBody(fakeFile('empty.csv', '   '))).toBeNull();
    const csv = 'word,phonetic,translation,state\nabandon,,give up,learning\n';
    expect(await buildImportBody(fakeFile('word-dance-export-20261014.csv', csv))).toEqual({ format: 'csv', data: csv });
  });
});

describe('toggleStageSetting', () => {
  it('keeps the list non-empty and the current stage inside it, in canonical order', () => {
    expect(toggleStageSetting(['cet4', 'cet6'], 'cet4', 'gk')).toEqual({ stages: ['gk', 'cet4', 'cet6'], current_stage: 'cet4' });
    expect(toggleStageSetting(['cet4', 'cet6'], 'cet4', 'cet4')).toEqual({ stages: ['cet6'], current_stage: 'cet6' });
    expect(toggleStageSetting(['cet6'], 'cet6', 'cet6')).toEqual({ stages: ['cet6'], current_stage: 'cet6' });
    expect(toggleStageSetting(['zk'], 'zk', 'cet6')).toEqual({ stages: ['zk', 'cet6'], current_stage: 'zk' });
  });
});
