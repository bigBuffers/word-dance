// i18n rules (FRONTEND §8, DESIGN §0.3) enforced in CI through `npm test` — the same rules as
// scripts/check-copy.mjs (`npm run lint`), applied here through Vite's raw source globs.
import { describe, expect, it } from 'vitest';
import type { ItemKind, ReportReason, Stage, UserState, WebhookFormat } from '@/api/types';
import { zh } from './zh';

// Built from code points so this file never contains the term it hunts for.
const CJK = new RegExp(`[${String.fromCharCode(0x4e00)}-${String.fromCharCode(0x9fa5)}]`);
const FORBIDDEN_TERM = String.fromCharCode(0x5355, 0x8bcd, 0x672c); // the non-glossary synonym of zh.bank.title (DESIGN §0.3)

const tsxSources = import.meta.glob('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const allSources = import.meta.glob(['/src/**/*.ts', '/src/**/*.tsx', '/src/**/*.css', '/index.html'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function offendingLines(sources: Record<string, string>, test: (line: string) => boolean, skip: (path: string) => boolean): string[] {
  const out: string[] = [];
  for (const [path, source] of Object.entries(sources)) {
    if (skip(path)) continue;
    source.split('\n').forEach((line, i) => {
      if (test(line)) out.push(`${path}:${i + 1}`);
    });
  }
  return out;
}

describe('zh.ts', () => {
  it('is the only place Chinese copy lives in *.tsx files', () => {
    expect(Object.keys(tsxSources).length).toBeGreaterThan(20);
    expect(offendingLines(tsxSources, (line) => CJK.test(line), (path) => path.startsWith('/src/i18n/'))).toEqual([]);
  });

  it('never uses the forbidden glossary term anywhere', () => {
    expect(Object.keys(allSources).length).toBeGreaterThan(40);
    expect(offendingLines(allSources, (line) => line.includes(FORBIDDEN_TERM), () => false)).toEqual([]);
  });

  it('labels every enumerated DTO value used in the UI (compile-time Record checks)', () => {
    const stages: Record<Stage, string> = zh.stages;
    const kinds: Record<ItemKind, string> = zh.study.kind;
    const states: Record<UserState, string> = zh.bank.tabs;
    const reasons: Record<ReportReason, string> = zh.word.reportReasons;
    const formats: Record<WebhookFormat, string> = zh.settings.formats;
    for (const table of [stages, kinds, states, reasons, formats]) {
      for (const label of Object.values(table)) expect(label.length).toBeGreaterThan(0);
    }
  });

  it('uses the glossary term for the personal word bank consistently', () => {
    expect(zh.nav.bank).toBe(zh.bank.title);
    expect(zh.app.name).toBe('word-Dance');
  });

  it('formats parameterised strings', () => {
    expect(zh.common.total(4722)).toContain('4722');
    expect(zh.errors.accountLocked(601)).toContain('11');
    expect(zh.study.nextDue.days(3)).toContain('3');
  });
});
