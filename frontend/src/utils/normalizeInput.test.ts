// normalizeInput mirrors the DESIGN §5.1 table (the backend's test_words_normalise.py covers the same cases).
import { describe, expect, it } from 'vitest';
import { analyseInput, cleanInput, normalizeInput, splitInput, type InvalidReason, type NormalizedKind } from './normalizeInput';

type Accepted = { input: string; lemma: string; display?: string; kind?: NormalizedKind; tokens?: number };
type Rejected = { input: string; reason: InvalidReason };

const accepted: Accepted[] = [
  { input: ' Abandoned ', lemma: 'abandoned', display: 'Abandoned', kind: 'word' },
  { input: 'abandon', lemma: 'abandon', display: 'abandon', kind: 'word' },
  { input: 'a.m.', lemma: 'a.m.', display: 'a.m.', kind: 'abbreviation' },
  { input: 'e.g.', lemma: 'e.g.', display: 'e.g.', kind: 'abbreviation' },
  { input: 'etc.', lemma: 'etc.', display: 'etc.', kind: 'abbreviation' },
  { input: 'U.S.A.', lemma: 'u.s.a.', kind: 'abbreviation' },
  { input: 'ice cream', lemma: 'ice cream', display: 'ice cream', kind: 'phrase', tokens: 2 },
  { input: 'ought to', lemma: 'ought to', kind: 'phrase', tokens: 2 },
  { input: 'take off', lemma: 'take off', kind: 'phrase', tokens: 2 },
  { input: 'as a matter of', lemma: 'as a matter of', kind: 'phrase', tokens: 4 },
  { input: 'CPU', lemma: 'cpu', display: 'CPU', kind: 'abbreviation' },
  { input: 'GDP', lemma: 'gdp', display: 'GDP', kind: 'abbreviation' },
  { input: 'NASA', lemma: 'nasa', display: 'NASA', kind: 'abbreviation' },
  { input: 'TV', lemma: 'tv', display: 'TV', kind: 'abbreviation' },
  { input: 'UNESCO', lemma: 'unesco', display: 'UNESCO', kind: 'abbreviation' },
  { input: 'ABCDEFG', lemma: 'abcdefg', display: 'abcdefg', kind: 'word' },
  { input: 'Kubernetes', lemma: 'kubernetes', display: 'Kubernetes', kind: 'word' },
  { input: 'China', lemma: 'china', display: 'China' },
  { input: 'ICE CREAM', lemma: 'ice cream', display: 'ice cream', kind: 'phrase' },
  { input: 'don’t', lemma: "don't", display: "don't" },
  { input: 'rockʼn', lemma: "rock'n", display: "rock'n" },
  { input: 'rock–solid', lemma: 'rock-solid', display: 'rock-solid' },
  { input: 'well—known', lemma: 'well-known', display: 'well-known' },
  { input: 'ａｂａｎｄｏｎ', lemma: 'abandon', display: 'abandon' },
  { input: 'ｉｃｅ　ｃｒｅａｍ', lemma: 'ice cream', kind: 'phrase' },
  { input: '(abandon)', lemma: 'abandon' },
  { input: '"abandon"', lemma: 'abandon' },
  { input: 'abandon!', lemma: 'abandon' },
  { input: 'abandon?', lemma: 'abandon' },
  { input: '[abandon]', lemma: 'abandon' },
  { input: '<abandon>', lemma: 'abandon' },
  { input: 'abandon,', lemma: 'abandon' },
  { input: 'abandon;', lemma: 'abandon' },
  { input: 'abandon:', lemma: 'abandon' },
  { input: '{abandon}', lemma: 'abandon' },
  { input: "rock 'n' roll", lemma: "rock 'n' roll", kind: 'phrase', tokens: 3 },
  { input: 'mother-in-law', lemma: 'mother-in-law', kind: 'word', tokens: 1 },
  { input: "o'clock", lemma: "o'clock" },
  { input: 'abandon   ship', lemma: 'abandon ship', tokens: 2 },
  { input: 'abandon\tship', lemma: 'abandon ship', tokens: 2 },
  { input: 'a'.repeat(48), lemma: 'a'.repeat(48) },
  { input: 'Mr.', lemma: 'mr.', display: 'Mr.', kind: 'abbreviation' },
  { input: 'Dr.', lemma: 'dr.', display: 'Dr.', kind: 'abbreviation' },
];

const rejected: Rejected[] = [
  { input: '', reason: 'empty' },
  { input: '   ', reason: 'empty' },
  { input: '()', reason: 'empty' },
  { input: 'a'.repeat(49), reason: 'too_long' },
  { input: 'this is a long sentence', reason: 'too_many_tokens' },
  { input: 'one two three four five', reason: 'too_many_tokens' },
  { input: '放弃', reason: 'charset' },
  { input: 'abandon 放弃', reason: 'charset' },
  { input: 'abc123', reason: 'charset' },
  { input: 'e-mail@example', reason: 'charset' },
  { input: 'abandon_ship', reason: 'charset' },
  { input: 'naïve', reason: 'charset' },
  { input: 'hello/world', reason: 'charset' },
  { input: '-abandon', reason: 'leading_punct' },
  { input: "'abandon", reason: 'leading_punct' },
  { input: '‘quoted’', reason: 'leading_punct' }, // curly single quotes map to ' (DESIGN §5.1 step 1) → leading apostrophe
  { input: '“abandon”', reason: 'charset' }, // curly double quotes are neither mapped nor stripped
  { input: 'example.com', reason: 'dot_in_long_token' },
  { input: 'word.press', reason: 'dot_in_long_token' },
  { input: 'abandon.', reason: 'dot_in_long_token' }, // a trailing period is not stripped (DESIGN §5.1 keeps `.`)
  { input: 'abandon -', reason: 'bad_token' },
  { input: "abandon ' ship", reason: 'bad_token' },
  { input: 'abandon ... ship', reason: 'bad_token' },
  { input: 'ice . cream', reason: 'bad_token' },
];

describe('normalizeInput', () => {
  it.each(accepted)('accepts %j', (c) => {
    const r = normalizeInput(c.input);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.lemma).toBe(c.lemma);
    if (c.display !== undefined) expect(r.display).toBe(c.display);
    if (c.kind !== undefined) expect(r.kind).toBe(c.kind);
    if (c.tokens !== undefined) expect(r.tokens).toHaveLength(c.tokens);
    expect(r.lemma).toBe(r.lemma.toLowerCase());
  });

  it.each(rejected)('rejects %j', (c) => {
    expect(normalizeInput(c.input)).toEqual({ ok: false, reason: c.reason });
  });

  it('has at least 60 table rows', () => {
    expect(accepted.length + rejected.length).toBeGreaterThanOrEqual(60);
  });

  it('cleanInput applies NFKC, quote/dash mapping and edge stripping only', () => {
    expect(cleanInput('  "Don’t"  ')).toBe("Don't");
    expect(cleanInput('“Don’t”')).toBe("“Don't”"); // double curly quotes stay (server rejects them as charset)
    expect(cleanInput('a.m.')).toBe('a.m.');
    expect(cleanInput('—')).toBe('-');
  });
});

describe('splitInput / analyseInput', () => {
  it('splits on newlines, commas, semicolons (ASCII and full-width) and tabs, never on spaces', () => {
    expect(splitInput('abandoned, children\nubiquitous；bases\tabc123，ice cream; take off')).toEqual([
      'abandoned',
      'children',
      'ubiquitous',
      'bases',
      'abc123',
      'ice cream',
      'take off',
    ]);
    expect(splitInput('\n\n , ;')).toEqual([]);
  });

  it('marks lemma duplicates within one paste and keeps invalid lines', () => {
    const lines = analyseInput('Abandon\nabandon, ABANDON\nabc123\nGDP');
    expect(lines.map((l) => l.raw)).toEqual(['Abandon', 'abandon', 'ABANDON', 'abc123', 'GDP']);
    expect(lines.map((l) => l.duplicate)).toEqual([false, true, true, false, false]);
    expect(lines[3]?.result.ok).toBe(false);
    expect(lines[4]?.result).toMatchObject({ ok: true, kind: 'abbreviation', display: 'GDP' });
    expect(lines.map((l) => l.index)).toEqual([0, 1, 2, 3, 4]);
  });
});
